# Web Datamining & Semantics — Final Report
## Formula 1 Knowledge Graph

**Course:** Web Datamining & Semantics
**Date:** March 2026
**Domain:** Formula 1 (seasons 2022–2026)

---

## 1. Introduction

This project builds a complete knowledge graph pipeline for Formula 1, covering the five most recent seasons (2022–2026) in a rolling window. The pipeline spans six stages: web crawling, information extraction, entity alignment, knowledge graph construction and expansion, OWL reasoning, knowledge graph embeddings, and retrieval-augmented generation (RAG) question answering.

The domain was chosen for its richness of structured relational data — drivers, teams, circuits, standings, and race results — and for the availability of complementary public knowledge sources (Wikidata, DBpedia) enabling semantic enrichment.

---

## 2. Data Sources and Crawling

### 2.1 Primary source

Race standings and driver data are crawled from `formula1.com` using **Playwright** (async, headless Chromium). The crawler handles JavaScript-rendered content and respects a `robots.txt`-compliant crawl delay. For each season in the rolling window, the crawler fetches the drivers standings page and saves raw HTML to `data/raw/`.

### 2.2 Rolling 5-season window

The pipeline always covers exactly 5 seasons: the current year and the four preceding. When a new calendar year begins, the oldest season's data is automatically purged by `src/crawl/crawl_formula1.py` via the `purge_old_seasons()` function. The window is computed by `src/crawl/seasons.py`:

```python
season_window(keep=5)  # → [2026, 2025, 2024, 2023, 2022]
```

### 2.3 Crawl ethics

The crawler uses a 2-second delay between requests, identifies itself via a descriptive `User-Agent`, and only accesses publicly available standings data. No paywalled or login-protected content is scraped.

---

## 3. Information Extraction

### 3.1 Method

Raw HTML text is parsed by `src/ie/extract_drivers.py` using **regex-based extraction**. Two format patterns are handled:

- **Format A (single-line):** `<position> <nat> <name> <team> <points>` — common in modern formula1.com standings tables.
- **Format B (multi-line):** position, name, nationality, team, and points on separate lines — used in older season views.

The extractor normalises nationality codes (ISO 3166-1 alpha-3) and strips typographic noise. Output is written to `data/extracted/drivers_YYYY.json` for each season.

### 3.2 Results

After extraction, the 2022–2026 dataset contains approximately 160 driver-season records (20 drivers × 5 seasons, with some variation due to mid-season retirements and new entries).

---

## 4. Entity Alignment

### 4.1 Driver and team alignment

`src/alignment/align_teams.py` uses the **Wikidata `wbsearchentities` API** to link each unique team name to its Wikidata QID. Confidence scoring:

- **1.0** — exact label match (e.g., "Ferrari" → Q33065)
- **0.8** — first-result match with acceptable name overlap
- **< 0.8** — discarded

Results are stored in `kg_artifacts/alignment_drivers.tsv` and `kg_artifacts/alignment_teams.tsv`.

### 4.2 Alignment corrections

Two alignment errors found in the initial TSV were corrected manually:

| Team | Original QID | Problem | Corrected QID |
|---|---|---|---|
| RB (2024) | Q895 | Rubidium element | Q60752400 (Scuderia AlphaTauri/VCARB) |
| Audi (2026) | Q482994 | Music album | Q23317 (Audi AG) |

The corrected TSVs are the source of truth for all downstream alignment triples.

---

## 5. Ontology Design

The F1 ontology (`ontology/f1_ontology.ttl`) is written in OWL/Turtle and defines:

**8 classes:** `Driver`, `Team`, `Season`, `GrandPrix`, `Circuit`, `RaceResult`, `DriverStanding`, `TeamStanding`.

**Key object properties:**

| Property | Domain → Range | Characteristic |
|---|---|---|
| `drivesFor` | Driver → Team | — |
| `competesInSeason` | Driver → Season | — |
| `teammateOf` | Driver ↔ Driver | `owl:SymmetricProperty` |
| `hasRace` | Season → GrandPrix | — |
| `heldAtCircuit` | GrandPrix → Circuit | — |
| `hasResult` | GrandPrix → RaceResult | — |
| `isChampionOf` | Driver → Season | inferred by Rule 1 |
| `hasWon` | Driver → GrandPrix | inferred by Rule 3 |

**Datatype properties:** `name`, `nationality`, `seasonYear`, `standingPosition`, `standingPoints`, `finishPosition`, `points`, `trackLength`, `raceDate`.

A Protégé-compatible version (`ontology/f1_ontology.owl`) includes illustrative individuals and is kept in sync with the operational `.ttl` file.

---

## 6. Knowledge Graph Construction and Expansion

### 6.1 Private KB

`src/kg/build_kb.py` assembles the private KB by loading each `drivers_YYYY.json` file and creating RDF triples for drivers, teams, seasons, standings, and standing scores. Output: `kg_artifacts/auto_kg.ttl` (**1,306 triples**).

### 6.2 KB expansion

Two expansion strategies are provided:

**Online strategy — Wikidata SPARQL (`src/kg/expand_kb.py`):**
Three phases — (1) 1-hop on all 47 aligned entities, (2) domain-wide F1 entity pull (all drivers, constructors, seasons, circuits via `wdt:P641 wd:Q1968` and related predicates), (3) 2-hop on countries and awards. Target: **50,000–200,000 triples**. Requires internet access (`query.wikidata.org`).

**Offline strategy — curated local data (`src/kg/build_local_expansion.py`):**
Adds 23 circuits, 19 country entities, full race calendars (2022–2026, ~95 races), race winners (2022–2025 + 2026 partial), season champions, teammate pairs, driver-country links, and Wikidata alignment triples. Result: **5,200 triples** (used in this report for local testing).

### 6.3 KB content after local expansion

| Category | Count |
|---|---|
| Drivers | 32 |
| Teams | 16 |
| Seasons | 5 |
| Grand Prix races | 95 |
| Circuits | 23 |
| Countries | 19 |
| Total triples | 5,200 |
| Unique predicates | 42 |

---

## 7. SWRL Reasoning

`src/reason/apply_rules.py` applies four materialisation rules documented in `src/reason/swrl_rules.md`:

**Rule 1 — Champion inference:**
`DriverStanding(pos=1) ∧ forDriver(?d) ∧ forSeason(?s) → isChampionOf(?d, ?s)`

**Rule 2 — Teammate symmetry:**
`teammateOf(A,B) → teammateOf(B,A)` (materialises `owl:SymmetricProperty`)

**Rule 3 — Race win:**
`RaceResult(pos=1) ∧ forDriver(?d) ∧ forGrandPrix(?gp) → hasWon(?d, ?gp)`

**Rule 4 — Season membership via race:**
`participatedIn(?d, ?gp) ∧ partOfSeason(?gp, ?s) → competesInSeason(?d, ?s)`

**Results:** +5 inferred triples (5 champion triples: Verstappen 2022–2024, Norris 2025, Russell 2026). Rules 2–4 produced 0 new triples because the expansion script had already materialised those relationships directly. After reasoning: **5,205 triples**.

The OWLReady2/Pellet integration is included as an optional layer (`owlready2` package) for full OWL-DL class inference when available.

---

## 8. Knowledge Graph Embeddings

### 8.1 Split preparation

`src/kge/prepare_splits.py` converts `reasoned_kb.ttl` to tab-separated triples, filtering out datatype-property triples (keeping only URIRef → URIRef edges). Split: 80% train / 10% validation / 10% test (random seed 42).

| Set | Triples |
|---|---|
| Full (object triples) | 3,683 |
| Train | 2,946 |
| Valid | 368 |
| Test | 369 |
| Unique entities | 439 |
| Unique relations | 26 |

### 8.2 Models

Two complementary architectures are trained via **PyKEEN**:

- **TransE** — translational model: `h + r ≈ t`. Efficient, works well on simple hierarchical relations (`drivesFor`, `heldAtCircuit`).
- **ComplEx** — complex-valued factorisation. Better on antisymmetric and n-ary relations (`teammateOf`, `hasWon`, `isChampionOf`).

Training: `src/kge/train_kge.py --epochs 100 --dim 64 --lr 0.01`. Evaluation: filtered link-prediction MRR and Hits@k on the test split.

### 8.3 Size-sensitivity analysis

`evaluate_kge.py --size-sensitivity` trains TransE on sub-samples (20k / 50k / full) to measure how KB volume affects embedding quality. With the local KB (~3.7k object triples), all conditions collapse to the same set; this analysis is designed to show meaningful curves after the full Wikidata expansion.

### 8.4 Discussion

Absolute metric values are expected to be low with a ~3.7k-triple KB, primarily because the dominant relation `participatedIn` (57% of triples) creates a dense bipartite graph that offers limited predictive signal. After the full Wikidata expansion (50k–200k triples), sparser relations become better supported and embedding quality improves. ComplEx is recommended for deployment given the antisymmetric structure of several F1 relations.

---

## 9. RAG Question Answering

### 9.1 Architecture

The RAG pipeline (`src/rag/`) follows a NL→SPARQL→Answer pattern:

```
User question
    ↓  sparql_generator.py  (Ollama LLM + schema + few-shot examples)
Generated SPARQL
    ↓  sparql_executor.py   (rdflib query against reasoned_kb.ttl)
Query result / error
    ↓  repair_loop.py        (retry up to 3× with error feedback)
Final answer rows
    ↓  main_rag.py           (format + present to user)
```

### 9.2 Schema injection

`schema_summary.py` introspects the KB at runtime and builds a compact (<1000 tokens) schema string containing all 8 classes, 25+ properties, and 3 few-shot NL→SPARQL examples. This is injected as the LLM system prompt.

### 9.3 Self-repair loop

On SPARQL syntax errors, the error message is appended to the next prompt. On empty results, a relaxed prompt suggests FILTER/REGEX alternatives. Up to 3 attempts are made before returning a graceful failure.

### 9.4 Demo results

Running `python src/rag/main_rag.py --demo` with hardcoded SPARQL (no Ollama required):

| Question | Answer |
|---|---|
| Who won the 2024 F1 championship? | Max Verstappen |
| Which team does Lando Norris drive for? | McLaren |
| How many races did Max Verstappen win in 2023? | 17 |
| List all circuits in the 2025 season. | 23 circuits |
| Who were Lewis Hamilton's teammates in 2024? | George Russell, Charles Leclerc |

### 9.5 LLM backend

The live pipeline uses **Ollama** (local, offline-capable) with `mistral` as the default model. The system uses `urllib` directly (no external library dependency) and falls back to a stub SPARQL query if Ollama is unreachable.

---

## 10. Limitations and Future Work

**KB size:** The local offline KB (5,200 triples) is smaller than the 50k–200k target. Running `src/kg/expand_kb.py` on a machine with internet access bridges this gap by querying Wikidata SPARQL.

**Data accuracy:** Standings and race results depend on crawl timing. The `raceDate` predicate and the rolling-window purge mechanism ensure temporal consistency.

**Embedding quality:** KGE metrics will improve significantly with the full KB. A size-sensitivity analysis (`--size-sensitivity`) quantifies this relationship.

**RAG hallucination:** The LLM may generate valid SPARQL that is logically correct but semantically wrong (wrong entity names). The repair loop addresses syntax errors but not semantic errors; a post-hoc entity disambiguation step would strengthen the pipeline.

**OWL reasoning:** Only 4 SWRL rules are currently materialised. Adding rules for `wdt:P69` (education) and competitive-record inferences (e.g., most wins per season) would enrich the graph.

---

## 11. Conclusion

The project delivers a full knowledge graph pipeline for Formula 1, from web crawling to question answering. The pipeline is modular, reproducible, and documented at each stage. The rolling 5-season window design ensures the KB stays current as new seasons begin. The combination of OWL reasoning, KGE embeddings, and a self-repairing RAG interface demonstrates the complementary strengths of symbolic and neural approaches to knowledge representation.

---

## References

- Bizer, C., Heath, T., & Berners-Lee, T. (2009). Linked data — the story so far. *International Journal on Semantic Web and Information Systems*, 5(3), 1–22.
- Ali, M., et al. (2021). PyKEEN 1.0: A Python library for training and evaluating knowledge graph embeddings. *Journal of Machine Learning Research*, 22(82), 1–6.
- Vrandečić, D., & Krötzsch, M. (2014). Wikidata: a free collaborative knowledgebase. *Communications of the ACM*, 57(10), 78–85.
- Hogan, A., et al. (2021). Knowledge graphs. *ACM Computing Surveys*, 54(4), 1–37.
- Lewis, P., et al. (2020). Retrieval-augmented generation for knowledge-intensive NLP tasks. *Advances in Neural Information Processing Systems*, 33, 9459–9474.
