# Knowledge Base Statistics

## Overview

| Metric | Value |
|---|---|
| Total triples | 5,368 |
| Unique subjects (entities) | 470 |
| Unique predicates (relations) | 46 |

## Top-20 predicates by frequency

| Predicate | Count |
|---|---|
| `participatedIn` | 2,114 |
| `type` | 426 |
| `forDriver` | 205 |
| `forTeam` | 205 |
| `name` | 186 |
| `hasStanding` | 111 |
| `competesInSeason` | 111 |
| `standingPoints` | 111 |
| `standingPosition` | 111 |
| `forSeason` | 111 |
| `hasRace` | 95 |
| `raceDate` | 95 |
| `partOfSeason` | 95 |
| `heldAtCircuit` | 95 |
| `forGrandPrix` | 94 |
| `hasWon` | 94 |
| `finishPosition` | 94 |
| `points` | 94 |
| `winner` | 94 |
| `winningTeam` | 94 |

## Expansion strategy (local)

This `expanded_kb.ttl` was generated locally from curated F1 data.
For the full Wikidata SPARQL expansion (target: 50,000 – 200,000 triples), run:
```
python src/kg/expand_kb.py
```
(Requires internet access to query.wikidata.org)

### Local expansion phases
1. Initial private KB (Formula1.com standings 2022-2026)
2. F1 circuits — 23 circuits with country, city, length
3. Country entities — 19 nationalities with continent + owl:sameAs
4. Race calendars — all races 2022-2026 linked to circuits + seasons
5. Race winners — 2022-2025 winners + 2026 races so far
6. Season champions — WDC + WCC 2022-2024
7. Teammate relationships — symmetric pairs per team per season
8. Driver–country links — nationality + fromCountry
9. Wikidata alignment — owl:sameAs + labels from TSV files
10. Season participation — driver ↔ GP participation links
11. Team season participation — team ↔ season links

## Source files

| File | Description |
|---|---|
| `auto_kg.ttl` | Private KB (Formula1.com) + ontology + Wikidata alignments |
| `expanded_kb.ttl` | This expanded KB (local expansion) |
| `alignment_drivers.tsv` | Driver alignment to Wikidata |
| `alignment_teams.tsv` | Team alignment to Wikidata |
