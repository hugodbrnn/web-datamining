"""
schema_summary.py — Build a compact schema summary for LLM prompting
=====================================================================
Introspects the reasoned KB (reasoned_kb.ttl) to produce:
  1. A human-readable schema string (injected into the LLM system prompt)
  2. A list of example SPARQL queries that demonstrate the KB vocabulary

The summary is intentionally compact (< 1000 tokens) so it fits inside
Ollama context windows.

Usage (standalone)
------------------
    python src/rag/schema_summary.py
    # prints the schema summary to stdout

Usage (as module)
-----------------
    from src.rag.schema_summary import get_schema_summary, EXAMPLE_QUERIES
"""

from pathlib import Path
from rdflib import Graph, Namespace
from rdflib.namespace import RDF

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_KB   = PROJECT_ROOT / "kg_artifacts" / "reasoned_kb.ttl"

EX = Namespace("http://example.org/f1#")

# ─────────────────────────────────────────────────────────────────────────────
# Static schema description (classes + properties)
# This is written manually to be concise and pedagogical for the LLM.
# ─────────────────────────────────────────────────────────────────────────────

STATIC_SCHEMA = """
PREFIX ex: <http://example.org/f1#>

## Classes
- ex:Driver        : A Formula 1 racing driver
- ex:Team          : A F1 constructor / team
- ex:Season        : A championship season (2022-2026)
- ex:GrandPrix     : A single race weekend
- ex:Circuit       : A racing circuit
- ex:RaceResult    : One driver's result in one race
- ex:DriverStanding: A driver's season-end championship standing
- ex:TeamStanding  : A team's season-end constructor standing

## Object properties
- ex:drivesFor       : Driver → Team          (current team)
- ex:competesInSeason: Driver → Season
- ex:teammateOf      : Driver ↔ Driver        (symmetric)
- ex:hasStanding     : Driver → DriverStanding
- ex:forDriver       : DriverStanding/RaceResult → Driver
- ex:forTeam         : TeamStanding → Team
- ex:forSeason       : DriverStanding/TeamStanding → Season
- ex:hasRace         : Season → GrandPrix
- ex:heldAtCircuit   : GrandPrix → Circuit
- ex:hasResult       : GrandPrix → RaceResult
- ex:forGrandPrix    : RaceResult → GrandPrix
- ex:participatedIn  : Driver → GrandPrix
- ex:partOfSeason    : GrandPrix → Season
- ex:isChampionOf    : Driver → Season        (inferred: standing pos=1)
- ex:hasWon          : Driver → GrandPrix     (inferred: finish pos=1)
- ex:winner          : GrandPrix → Driver
- ex:winningTeam     : GrandPrix → Team
- ex:fromCountry     : Driver → Country
- ex:locatedIn       : Circuit → Country

## Datatype properties
- ex:name            : rdfs:label (string)
- ex:nationality     : Driver nationality code (string, e.g. "GBR")
- ex:seasonYear      : Season → xsd:int
- ex:standingPosition: DriverStanding → xsd:int
- ex:standingPoints  : DriverStanding → xsd:decimal
- ex:finishPosition  : RaceResult → xsd:int
- ex:points          : RaceResult → xsd:decimal
- ex:raceDate        : GrandPrix → xsd:date
- ex:trackLength     : Circuit → xsd:decimal  (km)
""".strip()

# ─────────────────────────────────────────────────────────────────────────────
# Example SPARQL queries (few-shot examples for the LLM)
# ─────────────────────────────────────────────────────────────────────────────

EXAMPLE_QUERIES = [
    {
        "question": "Who won the 2024 F1 championship?",
        "sparql": """PREFIX ex: <http://example.org/f1#>
SELECT ?driverName WHERE {
    ?driver ex:isChampionOf ex:Season2024 ;
            ex:name ?driverName .
}""",
    },
    {
        "question": "Which team does Lando Norris drive for?",
        "sparql": """PREFIX ex: <http://example.org/f1#>
SELECT ?teamName WHERE {
    ?driver ex:name "Lando Norris" ;
            ex:drivesFor ?team .
    ?team ex:name ?teamName .
}""",
    },
    {
        "question": "How many races did Max Verstappen win in 2023?",
        "sparql": """PREFIX ex: <http://example.org/f1#>
SELECT (COUNT(?gp) AS ?wins) WHERE {
    ?driver ex:name "Max Verstappen" ;
            ex:hasWon ?gp .
    ?gp ex:partOfSeason ex:Season2023 .
}""",
    },
    {
        "question": "Who were the teammates of Lewis Hamilton in 2024?",
        "sparql": """PREFIX ex: <http://example.org/f1#>
SELECT ?mateName WHERE {
    ?hamilton ex:name "Lewis Hamilton" ;
              ex:teammateOf ?mate .
    ?mate ex:name ?mateName .
    ?hamilton ex:competesInSeason ex:Season2024 .
    ?mate     ex:competesInSeason ex:Season2024 .
}""",
    },
    {
        "question": "List all circuits in the 2025 season with their country.",
        "sparql": """PREFIX ex: <http://example.org/f1#>
SELECT DISTINCT ?circuitName ?country WHERE {
    ex:Season2025 ex:hasRace ?gp .
    ?gp ex:heldAtCircuit ?circuit .
    ?circuit ex:name ?circuitName .
    OPTIONAL { ?circuit ex:locatedIn ?c . ?c ex:name ?country . }
}
ORDER BY ?circuitName""",
    },
    {
        "question": "What are the standings for the 2022 season?",
        "sparql": """PREFIX ex: <http://example.org/f1#>
SELECT ?driverName ?position ?points WHERE {
    ?standing a ex:DriverStanding ;
              ex:forSeason ex:Season2022 ;
              ex:forDriver ?driver ;
              ex:standingPosition ?position ;
              ex:standingPoints ?points .
    ?driver ex:name ?driverName .
}
ORDER BY ?position""",
    },
]


# ─────────────────────────────────────────────────────────────────────────────
# Dynamic stats (read from KB at runtime)
# ─────────────────────────────────────────────────────────────────────────────

def get_kb_stats(kb_path: Path = DEFAULT_KB) -> dict:
    """Return basic KB statistics (triple count, entity count, etc.)."""
    if not kb_path.exists():
        return {}
    g = Graph()
    g.parse(kb_path, format="turtle")
    drivers  = set(g.subjects(RDF.type, EX.Driver))
    teams    = set(g.subjects(RDF.type, EX.Team))
    gps      = set(g.subjects(RDF.type, EX.GrandPrix))
    seasons  = set(g.subjects(RDF.type, EX.Season))
    circuits = set(g.subjects(RDF.type, EX.Circuit))
    return {
        "total_triples": len(g),
        "drivers":       len(drivers),
        "teams":         len(teams),
        "grand_prix":    len(gps),
        "seasons":       len(seasons),
        "circuits":      len(circuits),
    }


def get_schema_summary(kb_path: Path = DEFAULT_KB, include_examples: bool = True) -> str:
    """Return the full schema summary string for LLM injection."""
    stats = get_kb_stats(kb_path)

    header = "# F1 Knowledge Graph — Schema Summary\n"
    if stats:
        header += (
            f"\nKB contains {stats['total_triples']:,} triples | "
            f"{stats['drivers']} drivers | {stats['teams']} teams | "
            f"{stats['grand_prix']} races | {stats['seasons']} seasons | "
            f"{stats['circuits']} circuits\n"
        )

    summary = header + "\n" + STATIC_SCHEMA

    if include_examples:
        summary += "\n\n## Example SPARQL queries\n"
        for ex in EXAMPLE_QUERIES[:3]:  # keep prompt short — 3 examples
            summary += f"\n### {ex['question']}\n```sparql\n{ex['sparql']}\n```\n"

    return summary


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print(get_schema_summary())
