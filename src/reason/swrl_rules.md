# SWRL Rules — F1 Knowledge Graph

Rules are applied via OWLReady2 in `src/reason/apply_rules.py`.
Input: `kg_artifacts/expanded_kb.ttl`
Output: `kg_artifacts/reasoned_kb.ttl` + inferred triple count logged to stdout.

---

## Rule 1 — Champion inference

**Natural language:** A driver who has a DriverStanding with position 1 for a given season is the Champion of that season.

```
DriverStanding(?s) ∧ forDriver(?s, ?d) ∧ forSeason(?s, ?season)
∧ standingPosition(?s, 1)
→ isChampionOf(?d, ?season)
```

**Why:** The championship result is latent in the standings data. Making it explicit creates a direct triple that query consumers (SPARQL, RAG) can use without multi-hop arithmetic.

---

## Rule 2 — Teammate symmetry

**Natural language:** If driver A is the teammate of driver B, then driver B is the teammate of driver A.

```
teammateOf(?a, ?b) → teammateOf(?b, ?a)
```

**Why:** `ex:teammateOf` is declared `owl:SymmetricProperty` in the ontology, but OWL reasoners need this rule applied explicitly in OWLReady2's SWRL engine to materialise the inverse triples.

---

## Rule 3 — Driver won a race

**Natural language:** If a RaceResult has finishPosition = 1, the driver for that result hasWon that Grand Prix.

```
RaceResult(?r) ∧ forDriver(?r, ?d) ∧ forGrandPrix(?r, ?gp)
∧ finishPosition(?r, 1)
→ hasWon(?d, ?gp)
```

**Why:** Materialises race wins as direct Driver→GrandPrix triples, enabling simple queries like "list all wins for driver X" without joining through RaceResult.

---

## Rule 4 — Driver competes in season via race

**Natural language:** If a driver participated in a Grand Prix that is part of a Season, then that driver competes in that Season.

```
Driver(?d) ∧ participatedIn(?d, ?gp) ∧ GrandPrix(?gp)
∧ partOfSeason(?gp, ?season)
→ competesInSeason(?d, ?season)
```

**Why:** Provides an alternative derivation path for `competesInSeason` triples; catches any drivers whose season link was inferred from race participation rather than standings.

---

## Implementation notes

- OWLReady2 does not support the full SWRL spec; numeric comparisons (e.g., `standingPosition(?s, 1)`) require Python-level filtering.
- Rules 1 and 3 are therefore implemented as Python loops over the RDF graph (`rdflib`), not as native OWL SWRL axioms.
- Rules 2 and 4 are applied via OWLReady2's `sync_reasoner_pellet()` (when Pellet is available) or via Python materialisation loops as a fallback.
- See `apply_rules.py` for the concrete implementation.
