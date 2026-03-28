# Reasoning Notes

## Architecture

Reasoning is handled by `apply_rules.py` in two complementary layers:

**Layer 1 — OWLReady2 / Pellet (optional)**
If `owlready2` is installed, the expanded KB is loaded as an OWL ontology and
Pellet's description-logic reasoner runs. This infers class subsumptions,
property characteristics (functional, symmetric, transitive), and domain/range
violations. Install with: `pip install owlready2`

**Layer 2 — rdflib materialisation (always runs)**
Four SWRL-style rules are applied as Python loops over the rdflib Graph.
These target F1-specific entailments that OWL DL cannot express natively
(e.g., `standingPosition = 1 → isChampionOf`).

## Rule summary

| # | Name | Pattern | New predicate |
|---|---|---|---|
| 1 | Champion inference | DriverStanding(pos=1) | `isChampionOf` |
| 2 | Teammate symmetry  | `A teammateOf B`      | `B teammateOf A` |
| 3 | Race win           | RaceResult(pos=1)     | `hasWon` |
| 4 | Season via race    | `participatedIn` + `partOfSeason` | `competesInSeason` |

See `swrl_rules.md` for full formal rule notation and rationale.

## Running

```bash
python src/reason/apply_rules.py
```

Expected output:
```
SWRL MATERIALISATION — F1 Knowledge Graph
[0] Loading expanded_kb.ttl …     (≈51,000 triples)
[1] OWLReady2 / Pellet pass …
[2] Applying SWRL-style materialisation rules …
    Rule 1 (Champion inference)    : +N triples
    Rule 2 (Teammate symmetry)     : +N triples
    Rule 3 (Race win)              : +N triples
    Rule 4 (Season via race)       : +N triples
[3] Validation queries …
    Champions (isChampionOf)       : N entries
    Top-5 race winners (hasWon)
    Symmetric teammateOf triples   : N
REASONING COMPLETE
```

Output file: `kg_artifacts/reasoned_kb.ttl`

## Design decisions

- **Numeric comparisons** (`standingPosition = 1`, `finishPosition = 1`) cannot be
  expressed in OWL SWRL because SWRL's built-in `swrlb:equal` operates on
  individuals, not data values. Python loops are the portable solution.
- **Symmetry rule** is listed separately from the OWL property declaration
  (`ex:teammateOf a owl:SymmetricProperty`) because OWLReady2's Pellet bridge
  does not always materialise symmetric triples into the graph — the explicit
  rule ensures they appear in the serialised TTL file.
- **Rule 4** (season via race) intentionally creates duplicate `competesInSeason`
  triples relative to the crawled data. The `add_triple` guard (`if (s,p,o) not
  in g`) ensures no duplicates appear in the output.
