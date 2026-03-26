# F1 Knowledge Graph — Web Datamining & Semantics

Formula 1 knowledge graph pipeline: web crawling → information extraction → RDF KB construction → OWL reasoning → Knowledge Graph Embeddings → RAG Q&A interface.

**Domain:** Formula 1 seasons 2022–2026 | **Namespace:** `ex: <http://example.org/f1#>`

---

## Quick Start

### 1. Install dependencies

```bash
pip install -r requirements.txt
pip install torch --index-url https://download.pytorch.org/whl/cpu
playwright install chromium
```

### 2. Build the Knowledge Base

```bash
# Crawl formula1.com (drivers, teams, races — 5 seasons)
python src/crawl/crawl_formula1.py

# Extract structured data from raw HTML
python src/ie/extract_drivers.py
python src/ie/extract_teams.py

# Build RDF graph + expand + apply SWRL reasoning
python src/kg/build_kb.py
python src/kg/build_local_expansion.py
python src/reason/apply_rules.py
```

### 3. Train Knowledge Graph Embeddings

```bash
python src/kge/prepare_splits.py
python src/kge/train_kge.py --epochs 100 --dim 64
python src/kge/evaluate_kge.py
```

### 4. Launch the RAG demo

```bash
# Install Ollama: https://ollama.com
ollama pull llama3.2:1b

python src/rag/app.py
# Open http://localhost:5000
```

> **No Ollama?** The **Demo tab** runs 5 pre-built queries directly against the KB — no LLM needed.

---

## Project Structure

```
src/
├── crawl/      crawl_formula1.py   — Playwright crawler (formula1.com)
├── ie/         extract_drivers.py  — Regex-based information extraction
├── kg/         build_kb.py         — RDF KB assembly
│               build_local_expansion.py — KB enrichment (circuits, GP winners…)
├── reason/     apply_rules.py      — SWRL materialisation (4 rules)
├── kge/        train_kge.py        — TransE + ComplEx (PyKEEN)
└── rag/        app.py              — Flask web demo (http://localhost:5000)

kg_artifacts/
├── auto_kg.ttl        — Private KB (~1,300 triples)
├── expanded_kb.ttl    — Expanded KB (~5,200 triples)
├── reasoned_kb.ttl    — Reasoned KB (SWRL inferences applied)
└── kge/               — Train/valid/test splits + evaluation report

ontology/
└── f1_ontology.ttl    — OWL ontology (8 classes, 25+ properties)
```

---

## Hardware

- CPU only, no GPU required
- ~2 GB RAM for KGE training
- Ollama + llama3.2:1b: ~2 GB disk, ~1.5 GB RAM
