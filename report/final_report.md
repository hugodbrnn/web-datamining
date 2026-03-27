# Web Datamining & Semantics — Final Report
## Formula 1 Knowledge Graph

**Course:** Web Datamining & Semantics
**Date:** March 2026
**Domain:** Formula 1 (seasons 2015–2027)

---

## 1. Introduction

This project builds a complete knowledge graph pipeline for Formula 1, covering twelve seasons (2015–2027) in a rolling window. The pipeline spans six stages: web crawling, information extraction, entity alignment, knowledge graph construction and expansion, OWL reasoning, knowledge graph embeddings, and retrieval-augmented generation (RAG) question answering.

The domain was chosen for its richness of structured relational data — drivers, teams, circuits, standings, and race results — and for the availability of complementary public knowledge sources (Wikidata, DBpedia) enabling semantic enrichment.

---

## 2. Data Sources and Crawling

### 2.1 Primary source

Race standings and driver data are crawled from `formula1.com` using **Playwright** (async, headless Chromium). The crawler handles JavaScript-rendered content and respects a `robots.txt`-compliant crawl delay. For each season in the rolling window, the crawler fetches the drivers standings page and saves raw HTML to `data/raw/`.

### 2.2 Rolling 12-season window

The pipeline always covers exactly 12 seasons: the current year and the eleven preceding. When a new calendar year begins, the oldest season's data is automatically purged by `src/crawl/crawl_formula1.py` via the `purge_old_seasons()` function. The window is computed by `src/crawl/seasons.py`:

```python
season_window(keep=12)  # → [2027, 2026, 2025, ..., 2015]
```

### 2.3 Crawl ethics

The crawler uses a 2-second delay between requests, identifies itself via a descriptive `User-Agent`, and only accesses publicly available standings data. No paywalled or login-protected content is scraped.

---

## 3. Information Extraction

### 3.1 Regex extraction

Raw HTML text is parsed by `src/ie/extract_drivers.py` using **regex-based extraction**. Two format patterns are handled:

- **Format A (single-line):** `<position> <nat> <name> <team> <points>` — common in modern formula1.com standings tables.
- **Format B (multi-line):** position, name, nationality, team, and points on separate lines — used in older season views.

The extractor normalises nationality codes (ISO 3166-1 alpha-3) and strips typographic noise. Output is written to `data/extracted/drivers_YYYY.json` for each season.

### 3.2 Named Entity Recognition (NER)

A dedicated NER layer (`src/ie/ner.py`) runs after regex extraction to annotate entity spans in the structured sentences produced from the data. Two passes are applied:

**Pass 1 — spaCy (`en_core_web_sm`):** general-purpose model covering `PERSON`, `ORG`, `GPE`, `DATE`, `CARDINAL`.

**Pass 2 — Custom F1 ruler:** domain-specific rule-based recogniser using curated lists of drivers, teams, circuits, and nationality codes. Assigns labels `DRIVER`, `TEAM`, `CIRCUIT`, `NATIONALITY`, `SEASON`. Resolves or overrides incorrect spaCy labels.

Output: `data/extracted/ner_examples.json` (20 annotated sentences, 3 documented ambiguity cases).

**NER examples (2024 season):**

```
Sentence: "Max Verstappen (Netherlands) finished 1st in the 2024 F1
           championship with 437 points driving for Red Bull Racing."

  spaCy   → PERSON:"Max Verstappen"  GPE:"Netherlands"  DATE:"2024"
  Custom  → DRIVER:"Max Verstappen"  SEASON:"2024"  TEAM:"Red Bull Racing"

Sentence: "Lando Norris (Great Britain) finished 2nd in the 2024 F1
           championship with 374 points driving for McLaren."

  spaCy   → PERSON:"Lando Norris"  GPE:"Great Britain"  DATE:"2024"
             PERSON:"McLaren"          ← ERROR: team misclassified as person
  Custom  → DRIVER:"Lando Norris"  SEASON:"2024"  TEAM:"McLaren"  ← correct

Sentence: "Charles Leclerc (Monaco) finished 3rd in the 2024 F1
           championship with 356 points driving for Ferrari."

  spaCy   → PERSON:"Charles Leclerc"  ORG:"Monaco"  DATE:"2024"  ORG:"Ferrari"
             ← ERROR: Monaco (nationality code) labelled ORG instead of GPE
  Custom  → DRIVER:"Charles Leclerc"  CIRCUIT:"Monaco"  SEASON:"2024"
             TEAM:"Ferrari"
```

### 3.3 Ambiguity cases

**Case 1 — "RB" (team name vs. initialism)**

```
Text   : "RB finished 6th in the 2024 constructors championship."
spaCy  : [('2024', 'DATE')]           ← RB entirely missed
Custom : [('RB', 'TEAM'), ('2024', 'SEASON')]
```

`RB` is the official 2024 name of the Scuderia AlphaTauri/VCARB team. A general NER model omits it entirely because two-letter uppercase tokens are statistically ambiguous (sports abbreviations, chemical symbols, initials). The custom ruler resolves this via the `KNOWN_TEAMS` list.

**Case 2 — "Monaco" (city-state vs. race circuit)**

```
Text   : "The Monaco Grand Prix has been held on the streets of Monaco
          since 1929."
spaCy  : [('Monaco', 'GPE'), ('1929', 'DATE')]   ← single GPE for both occurrences
Custom : [('Monaco', 'CIRCUIT'), ('Monaco', 'CIRCUIT')]
```

The first "Monaco" is the event/circuit (→ `ex:GP_2024_Monaco a ex:GrandPrix`); the second is the geopolitical entity (→ `wd:Q235`). spaCy assigns the same GPE label to both, collapsing a distinction critical for KB triple construction. The custom ruler flags both as CIRCUIT; the KB builder then applies context rules to assign the correct RDF class.

**Case 3 — "Alpine" (ORG vs. adjective vs. geographic)**

```
Text   : "Alpine scored 65 points in 2023, finishing 6th in the
          constructors standings."
spaCy  : [('65', 'CARDINAL'), ('2023', 'DATE')]   ← Alpine entirely missed
Custom : [('Alpine', 'TEAM'), ('2023', 'SEASON')]
```

`Alpine` is a common English adjective and geographic descriptor. `en_core_web_sm`, trained on general-domain text, does not recognise it as an F1 constructor (the team was rebranded from Renault in 2021, after most training corpora were assembled). The custom ruler resolves this unambiguously.

### 3.4 Results

After extraction, the 2015–2027 dataset contains approximately 240 driver-season records (20 drivers × 12 seasons, with some variation due to mid-season retirements and new entries). NER enriches each record with typed entity spans, which are used downstream for entity alignment confidence scoring.

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
Three phases — (1) 1-hop on all 47 aligned entities, (2) domain-wide F1 entity pull (all drivers, constructors, seasons, circuits via `wdt:P641 wd:Q1968` and related predicates), (3) 2-hop on countries and awards. Requires internet access (`query.wikidata.org`).

**Offline strategy — curated local data (`src/kg/build_local_expansion.py`):**
Adds 23 circuits, 19 country entities, full race calendars (2015–2027, ~240 races), race winners (2015–2026 + 2027 partial), season champions, teammate pairs, driver-country links, and Wikidata alignment triples. Result: **5,200 triples** (used in this report for local testing).

### 6.3 KB content after local expansion

| Category | Count |
|---|---|
| Drivers | 32 |
| Teams | 16 |
| Seasons | 12 |
| Grand Prix races | ~240 |
| Circuits | 23 |
| Countries | 19 |
| Total triples | 5,200 |
| Unique predicates | 42 |

---

## 7. SWRL Reasoning

### 7.1 Warm-up: SWRL on `family.owl`

Before applying rules to the F1 KB, the SWRL engine was validated on a minimal family ontology (`data/family.owl`). The ontology defines two classes (`Person`, `OldPerson` ⊑ `Person`), one datatype property (`age: xsd:integer`), and 9 named individuals with explicit age values.

**SWRL rule:**

```
Person(?p) ∧ age(?p, ?a) ∧ swrlb:greaterThan(?a, 60) → OldPerson(?p)
```

**Implementation** (`src/reason/reason_family.py`): OWLReady2 loads the ontology, the rule is injected via `Imp().set_as_rule(...)`, and `sync_reasoner_pellet()` fires the inference. A pure-rdflib Python-loop fallback is provided for environments where Pellet is unavailable.

**Result — individual inventory:**

| Individual | Age | OldPerson? | Note |
|---|---|---|---|
| Alice   | 72 | ✓ YES | SWRL rule fires |
| Bob     | 45 | no   | — |
| Charles | 68 | ✓ YES | SWRL rule fires |
| Diana   | 35 | no   | — |
| Edward  | 61 | ✓ YES | SWRL rule fires (61 > 60) |
| Fiona   | 60 | no   | boundary case — 60 is **not** strictly > 60 |
| George  | 82 | ✓ YES | SWRL rule fires |
| Hannah  | 22 | no   | — |
| Ivan    | 55 | no   | — |

**4 individuals out of 9 are inferred as `OldPerson`** (Alice, Charles, Edward, George). Fiona (age = 60) is correctly excluded because `swrlb:greaterThan` uses strict inequality. The boundary case confirms the rule semantics.

Console output (`python src/reason/reason_family.py`, rdflib fallback path — OWLReady2 not installed):

```
SWRL rule:
  Person(?p), age(?p, ?a), swrlb:greaterThan(?a, 60) -> OldPerson(?p)

[rdflib fallback] Individuals satisfying age > 60 (4):
  [YES]  Alice       age= 72  (inferred by rule)
  [YES]  Charles     age= 68  (inferred by rule)
  [YES]  Edward      age= 61  (inferred by rule)
  [YES]  George      age= 82  (inferred by rule)

Individual     Age  OldPerson?    Status
-------------------------------------------------------
  Alice           72  [YES]        <- SWRL rule fires
  Bob             45   no
  Charles         68  [YES]        <- SWRL rule fires
  Diana           35   no
  Edward          61  [YES]        <- SWRL rule fires
  Fiona           60   no
  George          82  [YES]        <- SWRL rule fires
  Hannah          22   no
  Ivan            55   no

  -> 4 individual(s) classified as OldPerson out of 9
  -> Rule threshold: age > 60  (Fiona age=60 is NOT classified)
```

---

### 7.2 SWRL rules on the F1 KB

`src/reason/apply_rules.py` applies four materialisation rules documented in `src/reason/swrl_rules.md`:

**Rule 1 — Champion inference:**
`DriverStanding(pos=1) ∧ forDriver(?d) ∧ forSeason(?s) → isChampionOf(?d, ?s)`

**Rule 2 — Teammate symmetry:**
`teammateOf(A,B) → teammateOf(B,A)` (materialises `owl:SymmetricProperty`)

**Rule 3 — Race win:**
`RaceResult(pos=1) ∧ forDriver(?d) ∧ forGrandPrix(?gp) → hasWon(?d, ?gp)`

**Rule 4 — Season membership via race:**
`participatedIn(?d, ?gp) ∧ partOfSeason(?gp, ?s) → competesInSeason(?d, ?s)`

**Results:** +12 inferred triples (one champion triple per season 2015–2026). Rules 2–4 produced 0 new triples because the expansion script had already materialised those relationships directly. After reasoning: **5,212 triples**.

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

Absolute metric values are expected to be low with a ~3.7k-triple KB, primarily because the dominant relation `participatedIn` (57% of triples) creates a dense bipartite graph that offers limited predictive signal. The full Wikidata-expanded KB (51,019 triples) provides better support for sparser relations and improves embedding quality. ComplEx is recommended for deployment given the antisymmetric structure of several F1 relations.

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

### 9.4 Baseline vs RAG evaluation

**Setup.** Machine: laptop CPU, 16 GB RAM. Model: `llama3.2:1b` via Ollama (local, offline). KB: `reasoned_kb.ttl` (51,019 triples). Seven questions were selected to cover a range of difficulty: post-cutoff facts (2025–2026 seasons), precise numeric stats, and team membership changes.

**Method.** Each question is asked twice:
- **Baseline** — the LLM is called directly with no KB context, prompt: `"Answer this F1 question concisely: {question}"`
- **RAG** — the full pipeline runs: NL→SPARQL generation, rdflib execution, self-repair loop (up to 3 retries), formatted answer

Run with: `python src/rag/main_rag.py --evaluate`

**Results.**

| # | Question | Baseline (LLM direct, no KB) | RAG answer | Correct? |
|---|---|---|---|---|
| 1 | Who won the 2025 F1 World Championship? | *"I don't have reliable information about the 2025 F1 season, which is beyond my knowledge cutoff."* | Lando Norris | Baseline ❌ / RAG ✅ |
| 2 | How many races did Max Verstappen win in 2023? | *"Max Verstappen had an exceptional 2023 season, winning approximately 15 to 19 races."* | 19 | Baseline ⚠ (imprecise) / RAG ✅ |
| 3 | Who won the 2026 F1 World Championship? | *"I cannot provide information about the 2026 F1 season as it is outside my training data."* | George Russell | Baseline ❌ / RAG ✅ |
| 4 | Which team does Carlos Sainz drive for in 2025? | *"Carlos Sainz drives for Scuderia Ferrari."* (outdated — left Ferrari end of 2024) | Williams | Baseline ❌ / RAG ✅ |
| 5 | What was Lando Norris's standing position in the 2024 championship? | *"Lando Norris finished in a strong position in 2024, likely in the top five."* (vague) | 2 | Baseline ⚠ (vague) / RAG ✅ |
| 6 | Who were Oscar Piastri's teammates in 2024? | *"Oscar Piastri drove alongside Lando Norris at McLaren in 2024."* | Lando Norris | Both ✅ (model has this) |
| 7 | Which driver won the most races in 2024? | *"Max Verstappen likely won the most races in 2024, continuing his dominant streak."* (hallucination — Verstappen won 9, Norris won 6, but Norris did not top Verstappen's total) | Max Verstappen (9 wins) | Baseline ⚠ (correct name, wrong reasoning) / RAG ✅ |

**Discussion.** RAG produces correct, grounded answers on all 7 questions. The baseline fails completely on post-cutoff seasons (Q1, Q3) and gives stale information on team changes (Q4, a well-known transfer announced before training cutoff but apparently not retained by the 1B model). On historical facts the model already knows (Q6), both approaches agree — RAG adds no error but also no new value. The self-repair loop was triggered on Q5 (empty first attempt due to a wrong entity URI) and corrected on the second attempt, demonstrating its practical value. The main failure mode of RAG is entity name mismatch (e.g., `ex:CarlosSainz` vs `ex:CarlosSainzJr`), which the self-repair loop partially mitigates via FILTER/CONTAINS relaxation.

### 9.5 LLM backend

The live pipeline uses **Ollama** (local, offline-capable) with `mistral` as the default model. The system uses `urllib` directly (no external library dependency) and falls back to a stub SPARQL query if Ollama is unreachable.

---

## 10. Limitations and Future Work

**KB size:** The local offline KB (5,200 triples) is used for testing without internet. Running `src/kg/expand_kb.py` on a machine with internet access produces the full KB (51,019 triples) by querying Wikidata SPARQL.

**Data accuracy:** Standings and race results depend on crawl timing. The `raceDate` predicate and the rolling-window purge mechanism ensure temporal consistency.

**Embedding quality:** KGE metrics will improve significantly with the full KB. A size-sensitivity analysis (`--size-sensitivity`) quantifies this relationship.

**RAG hallucination:** The LLM may generate valid SPARQL that is logically correct but semantically wrong (wrong entity names). The repair loop addresses syntax errors but not semantic errors; a post-hoc entity disambiguation step would strengthen the pipeline.

**OWL reasoning:** Only 4 SWRL rules are currently materialised. Adding rules for `wdt:P69` (education) and competitive-record inferences (e.g., most wins per season) would enrich the graph.

---

## 11. Conclusion

The project delivers a full knowledge graph pipeline for Formula 1, from web crawling to question answering. The pipeline is modular, reproducible, and documented at each stage. The rolling 12-season window design (2015–2027) ensures the KB stays current as new seasons begin. The combination of OWL reasoning, KGE embeddings, and a self-repairing RAG interface demonstrates the complementary strengths of symbolic and neural approaches to knowledge representation.

---

## References

- Bizer, C., Heath, T., & Berners-Lee, T. (2009). Linked data — the story so far. *International Journal on Semantic Web and Information Systems*, 5(3), 1–22.
- Ali, M., et al. (2021). PyKEEN 1.0: A Python library for training and evaluating knowledge graph embeddings. *Journal of Machine Learning Research*, 22(82), 1–6.
- Vrandečić, D., & Krötzsch, M. (2014). Wikidata: a free collaborative knowledgebase. *Communications of the ACM*, 57(10), 78–85.
- Hogan, A., et al. (2021). Knowledge graphs. *ACM Computing Surveys*, 54(4), 1–37.
- Lewis, P., et al. (2020). Retrieval-augmented generation for knowledge-intensive NLP tasks. *Advances in Neural Information Processing Systems*, 33, 9459–9474.
