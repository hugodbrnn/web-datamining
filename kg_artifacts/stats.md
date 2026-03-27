# Knowledge Base Statistics

## Overview

| Metric | Value |
|---|---|
| Total triples | 51,030 |
| Unique subjects (entities) | 6,462 |
| Unique predicates (relations) | 52 |

## Top-20 predicates by frequency

| Predicate | Count |
|---|---|
| `type` | 6,293 |
| `participatedIn` | 4,700 |
| `forDriver` | 4,091 |
| `forTeam` | 4,091 |
| `finishPosition` | 3,849 |
| `pointsScored` | 3,849 |
| `forRace` | 3,849 |
| `lapsCompleted` | 3,849 |
| `hasWon` | 2,330 |
| `winner` | 2,330 |
| `name` | 2,048 |
| `heldAtCircuit` | 2,044 |
| `circuitName` | 1,908 |
| `raceDate` | 1,170 |
| `partOfSeason` | 1,165 |
| `nationality` | 281 |
| `hasStanding` | 242 |
| `standingPoints` | 242 |
| `competesInSeason` | 242 |
| `standingPosition` | 242 |

## Expansion strategy (15 phases — Wikidata)

| Phase | Content | Key predicate |
|---|---|---|
| 1  | F1 races: name, date, season, circuit label | `ex:partOfSeason` |
| 2  | F1 seasons: name, year, WDC | `ex:isChampionOf` |
| 3  | F1 drivers: name, nationality, birth year | `ex:nationality` |
| 4  | F1 constructors: name, country | `rdf:type ex:Team` |
| 5  | Race winners via wdt:P1346 | `ex:winner` / `ex:hasWon` |
| 6  | Podium 2nd & 3rd via qualified stmts | `ex:secondPlace` / `ex:thirdPlace` |
| 7  | Race participation — direct wdt:P710 + F1 driver filter | `ex:participatedIn` |
| 7b | Race participation — driver-centric wdt:P1344 | `ex:participatedIn` |
| 8  | Driver career team memberships | `ex:drivesFor` |
| 9  | Season standings: position + points | `ex:standingPosition` |
| 10 | F1 circuits: name, country, city | `ex:city` |
| 11 | Race → circuit URI links | `ex:heldAtCircuit` |
| 12 | Pole positions per race (wdt:P1347) | `ex:polePosition` / `ex:hasPole` |
| 13 | Fastest lap holders per race (wdt:P1351) | `ex:fastestLapBy` / `ex:hasFastestLap` |
| 14 | Driver career stats: wins, poles, FL, titles | `ex:careerWins` |
| 15 | Constructor championship winners per season | `ex:constructorsChampion` |

## Source files

| File | Description |
|---|---|
| `auto_kg.ttl` | Private KB (Formula1.com scraped data) |
| `expanded_kb.ttl` | Full expanded KB (this file, Turtle) |
| `expanded_kb.nt` | Full expanded KB (N-Triples, for KGE) |
| `alignment_drivers.tsv` | Driver → Wikidata alignment |
| `alignment_teams.tsv` | Team → Wikidata alignment |
