# Web Datamining & Semantics — F1 Knowledge Graph

A complete pipeline that crawls Formula 1 data, builds and expands a Knowledge Graph,
applies OWL reasoning, trains Knowledge Graph Embeddings, and exposes a
Retrieval-Augmented Generation (RAG) question-answering interface.

**Domain:** Formula 1 (seasons 2022 – 2026, rolling 5-season window)

---

## Project Structure

```
web-datamining/
├── data/
│   ├── raw/                  # Raw HTML from Playwright crawler (gitignored)
│   ├── extracted/            # Cleaned JSON — drivers_YYYY.json
│   └── data_sources.md       # Source documentation & crawl ethics
│
├── ontology/
│   ├── f1_ontology.ttl       # Operational OWL ontology (loaded by scripts)
│   ├── f1_ontology.owl       # Protégé-compatible version (same schema + examples)
│   └── protege_notes.md      # Class/property reference + Protégé guide
│
├── kg_artifacts/
│   ├── auto_kg.ttl           # Private KB (crawled standings + ontology)
│   ├── expanded_kb.ttl       # KB after local expansion (circuits, races, etc.)
│   ├── reasoned_kb.ttl       # KB after SWRL materialisation
│   ├── alignment_drivers.tsv # Driver → Wikidata QID alignments
│   ├── alignment_teams.tsv   # Team → Wikidata QID alignments
│   └── kge/                  # KGE split files + evaluation report
│       ├── triples.tsv / train.tsv / valid.tsv / test.tsv
│       ├── splits_stats.md
│       └── evaluation_report.md
│
├── src/
│   ├── crawl/
│   │   ├── crawl_formula1.py     # Playwright async crawler (rolling window)
│   │   └── seasons.py            # season_window(keep=5) helper
│   ├── ie/
│   │   └── extract_drivers.py    # Regex-based information extraction
│   ├── alignment/
│   │   └── align_teams.py        # Wikidata entity alignment (wbsearchentities)
│   ├── kg/
│   │   ├── build_kb.py           # Assemble private KB from extracted JSON
│   │   ├── expand_kb.py          # SPARQL-based Wikidata expansion (online)
│   │   └── build_local_expansion.py  # Offline expansion (curated F1 data)
│   ├── reason/
│   │   ├── apply_rules.py        # SWRL-style materialisation (4 rules)
│   │   ├── swrl_rules.md         # Rule documentation
│   │   └── reasoning_notes.md    # Design rationale
│   ├── kge/
│   │   ├── prepare_splits.py     # TTL → train/valid/test TSV
│   │   ├── train_kge.py          # Train TransE + ComplEx (PyKEEN)
│   │   └── evaluate_kge.py       # MRR / Hits@k + size-sensitivity
│   └── rag/
│       ├── schema_summary.py     # KB schema → LLM prompt string
│       ├── sparql_generator.py   # NL → SPARQL (Ollama)
│       ├── sparql_executor.py    # SPARQL → results (rdflib)
│       ├── repair_loop.py        # Self-repair retry loop (up to 3×)
│       └── main_rag.py           # Entry point (REPL / single Q / demo)
│
├── report/
│   └── final_report.md       # Written project report (6–10 pages)
│
├── requirements.txt
└── README.md
```

---

## Setup

```bash
# 1. Clone and enter the project
git clone <repo-url>
cd web-datamining

# 2. Create a virtual environment (recommended)
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Install PyTorch (CPU build — no GPU required)
pip install torch --index-url https://download.pytorch.org/whl/cpu

# 5. Install Playwright browsers (for crawling)
playwright install chromium
```

---

## Pipeline — Step by Step

### Step 1 — Crawl (web data collection)

```bash
python src/crawl/crawl_formula1.py
```

Crawls `formula1.com` for all 5 seasons in the rolling window (2022–2026).
Saves raw HTML to `data/raw/` and triggers information extraction automatically.

### Step 2 — Build the private KB

```bash
python src/kg/build_kb.py
```

Converts `data/extracted/drivers_*.json` into an RDF Knowledge Graph.
Output: `kg_artifacts/auto_kg.ttl` (~1,300 triples).

### Step 3 — Expand the KB

**Option A — Full Wikidata expansion (requires internet, ~50k–200k triples):**
```bash
python src/kg/expand_kb.py
```

**Option B — Offline expansion (curated F1 data, ~5,200 triples):**
```bash
python src/kg/build_local_expansion.py
```

Output: `kg_artifacts/expanded_kb.ttl`

### Step 4 — Apply SWRL reasoning

```bash
python src/reason/apply_rules.py
```

Materialises 4 inference rules (champion detection, teammate symmetry, race wins, season membership).
Output: `kg_artifacts/reasoned_kb.ttl` (5,205 triples after local expansion).

### Step 5 — Knowledge Graph Embeddings

```bash
# Prepare 80/10/10 splits
python src/kge/prepare_splits.py

# Train TransE and ComplEx
python src/kge/train_kge.py --epochs 100 --dim 64

# Evaluate (MRR, Hits@1/3/10)
python src/kge/evaluate_kge.py
python src/kge/evaluate_kge.py --size-sensitivity  # size-sensitivity analysis
```

Models saved to `models/transe/` and `models/complex/`.

### Step 6 — RAG Question Answering

```bash
# Demo mode (no Ollama required)
python src/rag/main_rag.py --demo

# Interactive REPL (requires Ollama + mistral)
ollama pull mistral
python src/rag/main_rag.py

# Single question
python src/rag/main_rag.py -q "Who won the 2024 F1 championship?"
python src/rag/main_rag.py -q "Who won the 2024 F1 championship?" --verbose
```

---

## Ontology

The F1 ontology defines 8 classes and 25+ properties:

| Class | Description |
|---|---|
| `ex:Driver` | A Formula 1 racing driver |
| `ex:Team` | A constructor / team |
| `ex:Season` | A championship season |
| `ex:GrandPrix` | A single race weekend |
| `ex:Circuit` | A racing circuit |
| `ex:RaceResult` | One driver's result in one race |
| `ex:DriverStanding` | A driver's season-end standing |
| `ex:TeamStanding` | A team's season-end standing |

Namespace: `ex:` → `http://example.org/f1#`

---

## Reasoning Rules

| # | Rule | Infers |
|---|---|---|
| 1 | DriverStanding(pos=1) | `ex:isChampionOf(driver, season)` |
| 2 | Teammate symmetry | `ex:teammateOf(B, A)` from `ex:teammateOf(A, B)` |
| 3 | RaceResult(pos=1) | `ex:hasWon(driver, gp)` |
| 4 | participatedIn + partOfSeason | `ex:competesInSeason(driver, season)` |

---

## Rolling 5-Season Window

The pipeline always operates on the 5 most recent seasons. When the calendar
year advances, the oldest season is purged from raw data and the KB is rebuilt.

```python
from src.crawl.seasons import season_window
print(season_window(keep=5))  # [2026, 2025, 2024, 2023, 2022]
```

---

## External Tools

| Tool | Purpose | Required? |
|---|---|---|
| Playwright / Chromium | Web crawling | Yes (Step 1) |
| Wikidata SPARQL endpoint | KB expansion | Optional (internet) |
| PyKEEN + PyTorch | KGE training | Yes (Step 5) |
| Ollama + Mistral/LLaMA3 | RAG generation | Yes (Step 6 live mode) |
| Protégé | Ontology editing | Optional |
| OWLReady2 + Pellet | OWL DL reasoning | Optional |
