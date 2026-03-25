# Ontology Notes

## Two Files, One Schema

| File | Purpose |
|---|---|
| `f1_ontology.ttl` | **Operational reference** — loaded by `src/kg/build_kb.py`. Contains the full class/property schema. No hardcoded individuals (those come from the data pipeline). |
| `f1_ontology.owl` | **Protégé-compatible version** — same schema, plus a small set of illustrative individuals for exploration in Protégé. Not loaded by scripts. |

Both files share the same schema. If you edit the schema, update both.

## Namespace

All entities use prefix `ex:` → `http://example.org/f1#`
Wikidata alignments use `wd:` → `http://www.wikidata.org/entity/`

## Classes

| Class | Description |
|---|---|
| `ex:Driver` | A Formula 1 racing driver |
| `ex:Team` | A Formula 1 constructor / team |
| `ex:Season` | A championship season (rolling 5-season window) |
| `ex:GrandPrix` | A single race weekend |
| `ex:Circuit` | A racing circuit |
| `ex:RaceResult` | One driver's result in one race |
| `ex:DriverStanding` | A driver's season-end championship standing |
| `ex:TeamStanding` | A team's season-end constructor standing |

## Key Object Properties

| Property | Domain → Range | Notes |
|---|---|---|
| `ex:drivesFor` | Driver → Team | Most recent team |
| `ex:competesInSeason` | Driver → Season | One triple per season |
| `ex:teammateOf` | Driver ↔ Driver | Symmetric |
| `ex:hasStanding` | Driver → DriverStanding | |
| `ex:forDriver` | DriverStanding / RaceResult → Driver | |
| `ex:forTeam` | TeamStanding → Team | |
| `ex:forSeason` | DriverStanding / TeamStanding → Season | |
| `ex:hasRace` | Season → GrandPrix | |
| `ex:heldAtCircuit` | GrandPrix → Circuit | |
| `ex:hasResult` | GrandPrix → RaceResult | |

## SWRL Rules (see `src/reason/`)

Rules are applied with OWLReady2. See `src/reason/swrl_rules.md` for documentation.
