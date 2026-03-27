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
- ex:drivesFor       : Driver → Team          (use DIRECTLY on the driver — NEVER go through ex:teammateOf to find a driver's team)
- ex:competesInSeason: Driver → Season
- ex:teammateOf      : Driver ↔ Driver        (symmetric, across all seasons)
- ex:hasStanding     : Driver → DriverStanding
- ex:forDriver       : DriverStanding/RaceResult → Driver
- ex:forTeam         : DriverStanding/TeamStanding/RaceResult → Team
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

## URI naming conventions (IMPORTANT — use these exact formats)
- Seasons  : ex:Season2022, ex:Season2023, ex:Season2024, ex:Season2025
- Races    : ex:GP_YYYY_Country  e.g. ex:GP_2023_Italy, ex:GP_2024_Monaco, ex:GP_2023_GreatBritain, ex:GP_2024_Bahrain
- Drivers  : ex:FirstnameLastname  e.g. ex:MaxVerstappen, ex:LewisHamilton, ex:LandoNorris
- Teams    : ex:TeamName  e.g. ex:RedBullRacing, ex:Mercedes, ex:Ferrari, ex:McLaren

## CRITICAL — GrandPrix season property: ALWAYS use ex:inSeason (NEVER ex:partOfSeason on GP objects)
    # GrandPrix objects use ex:inSeason to link to a season.
    # ex:partOfSeason does NOT exist on local GP objects — using it returns nothing.
    # CORRECT:   ?gp ex:inSeason ex:Season2023 ;  ex:winner ?driver .
    # WRONG:     ?gp ex:partOfSeason ex:Season2023 .   ← returns nothing
    # DriverStanding objects use ex:forSeason (not ex:inSeason).

## CRITICAL — Race winner direction: ex:winner is on the GP (GP → Driver), not on the driver
    # CORRECT:   ?gp ex:winner ex:MaxVerstappen ; ex:inSeason ex:Season2023 .
    # WRONG:     ex:MaxVerstappen ex:hasWon ?gp .   ← do not use ex:hasWon
    # ALWAYS use:  ?gp ex:winner ex:DriverName ; ex:inSeason ex:SeasonYYYY .

## CRITICAL — GP names always include the year prefix
    # STORED AS: "2023 Italian Grand Prix", "2024 Monaco Grand Prix"
    # ALWAYS use a variable + FILTER:
    ?gp ex:inSeason ex:Season2023 ;
        ex:name ?gpName ;
        ex:winner ?driver .
    ?driver ex:name ?driverName .
    FILTER(CONTAINS(LCASE(?gpName), "italian"))
    # Keywords: italian, monaco, british, belgian, dutch, japanese, bahrain, spanish, canadian...

## CRITICAL — if the question contains a 4-digit year, the query MUST use it
    # For GrandPrix:    ?gp ex:inSeason ex:SeasonYYYY .
    # For Standings:    ?standing ex:forSeason ex:SeasonYYYY .
    # If the question includes a year and your query does not mention that year, the query is wrong.

## To find season-specific teammates: use DriverStanding with forTeam
    ?s1 a ex:DriverStanding ; ex:forSeason ex:Season2024 ; ex:forDriver ?driver1 ; ex:forTeam ?team .
    ?s2 a ex:DriverStanding ; ex:forSeason ex:Season2024 ; ex:forDriver ?driver2 ; ex:forTeam ?team .
    FILTER(?driver1 != ?driver2)
""".strip()

# ─────────────────────────────────────────────────────────────────────────────
# Example SPARQL queries (few-shot examples for the LLM)
# ─────────────────────────────────────────────────────────────────────────────

EXAMPLE_QUERIES = [
    {
        "question": "Who won the 2023 F1 championship?",
        "sparql": """PREFIX ex: <http://example.org/f1#>
SELECT ?driverName WHERE {
    ?driver ex:isChampionOf ex:Season2023 ;
            ex:name ?driverName .
}""",
    },
    {
        "question": "Who won the Monaco Grand Prix in 2024?",
        "sparql": """PREFIX ex: <http://example.org/f1#>
SELECT ?driverName WHERE {
    ?gp ex:inSeason ex:Season2024 ;
        ex:name ?gpName ;
        ex:winner ?driver .
    ?driver ex:name ?driverName .
    FILTER(CONTAINS(LCASE(?gpName), "monaco"))
}""",
    },
    {
        "question": "How many races did Max Verstappen win in 2023?",
        "sparql": """PREFIX ex: <http://example.org/f1#>
SELECT (COUNT(?gp) AS ?wins) WHERE {
    ?gp ex:winner ex:MaxVerstappen ;
        ex:inSeason ex:Season2023 .
}""",
    },
    {
        "question": "Who were the teammates of Lewis Hamilton in 2024?",
        "sparql": """PREFIX ex: <http://example.org/f1#>
SELECT DISTINCT ?mateName WHERE {
    ?s1 a ex:DriverStanding ; ex:forSeason ex:Season2024 ;
        ex:forDriver ex:LewisHamilton ; ex:forTeam ?team .
    ?s2 a ex:DriverStanding ; ex:forSeason ex:Season2024 ;
        ex:forDriver ?mate ; ex:forTeam ?team .
    ?mate ex:name ?mateName .
    FILTER(ex:LewisHamilton != ?mate)
}""",
    },
    {
        "question": "Which team does Pierre Gasly drive for?",
        "sparql": """PREFIX ex: <http://example.org/f1#>
SELECT DISTINCT ?teamName WHERE {
    ?driver ex:name "Pierre Gasly" ;
            ex:drivesFor ?team .
    ?team ex:name ?teamName .
}""",
    },
    {
        "question": "What are the driver standings in 2022?",
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
    {
        "question": "Did Lewis Hamilton win a race in 2024?",
        "sparql": """PREFIX ex: <http://example.org/f1#>
SELECT ?gpName WHERE {
    ?gp ex:winner ex:LewisHamilton ;
        ex:inSeason ex:Season2024 ;
        ex:name ?gpName .
}""",
    },
    {
        "question": "Who won the 2022 F1 World Championship?",
        "sparql": """PREFIX ex: <http://example.org/f1#>
SELECT ?driverName WHERE {
    ?driver ex:isChampionOf ex:Season2022 ;
            ex:name ?driverName .
}""",
    },
    {
        "question": "From which country does Esteban Ocon come from?",
        "sparql": """PREFIX ex: <http://example.org/f1#>
SELECT ?countryName WHERE {
    ex:EstebanOcon ex:fromCountry ?country .
    ?country ex:name ?countryName .
}""",
    },
    {
        "question": "Which team does Carlos Sainz drive for in 2025?",
        "sparql": """PREFIX ex: <http://example.org/f1#>
SELECT DISTINCT ?teamName WHERE {
    ?standing a ex:DriverStanding ;
              ex:forSeason ex:Season2025 ;
              ex:forDriver ex:CarlosSainz ;
              ex:forTeam ?team .
    ?team ex:name ?teamName .
}""",
    },
    {
        "question": "What was Lando Norris's standing position in the 2024 championship?",
        "sparql": """PREFIX ex: <http://example.org/f1#>
SELECT ?position ?points WHERE {
    ?standing a ex:DriverStanding ;
              ex:forSeason ex:Season2024 ;
              ex:forDriver ex:LandoNorris ;
              ex:standingPosition ?position ;
              ex:standingPoints ?points .
}""",
    },
    {
        "question": "Which driver won the most races in 2023?",
        "sparql": """PREFIX ex: <http://example.org/f1#>
SELECT ?driverName (COUNT(?gp) AS ?wins) WHERE {
    ?gp ex:winner ?driver ;
        ex:inSeason ex:Season2023 .
    ?driver ex:name ?driverName .
} GROUP BY ?driverName ORDER BY DESC(?wins) LIMIT 1""",
    },
    {
        "question": "Who finished 3rd in the 2022 championship?",
        "sparql": """PREFIX ex: <http://example.org/f1#>
SELECT ?driverName ?points WHERE {
    ?standing a ex:DriverStanding ;
              ex:forSeason ex:Season2022 ;
              ex:forDriver ?driver ;
              ex:standingPosition ?pos ;
              ex:standingPoints ?points .
    ?driver ex:name ?driverName .
    FILTER(?pos = 3)
}""",
    },
    {
        "question": "Which races were held in 2024?",
        "sparql": """PREFIX ex: <http://example.org/f1#>
SELECT ?gpName ?raceDate WHERE {
    ex:Season2024 ex:hasRace ?gp .
    ?gp ex:name ?gpName .
    OPTIONAL { ?gp ex:raceDate ?raceDate . }
} ORDER BY ?raceDate""",
    },
    {
        "question": "What is Max Verstappen's nationality?",
        "sparql": """PREFIX ex: <http://example.org/f1#>
SELECT ?nationality WHERE {
    ex:MaxVerstappen ex:nationality ?nationality .
}""",
    },
    {
        "question": "Which team does Lando Norris drive for in 2024?",
        "sparql": """PREFIX ex: <http://example.org/f1#>
SELECT DISTINCT ?teamName WHERE {
    ?standing a ex:DriverStanding ;
              ex:forSeason ex:Season2024 ;
              ex:forDriver ex:LandoNorris ;
              ex:forTeam ?team .
    ?team ex:name ?teamName .
}""",
    },
    {
        "question": "Who won the British Grand Prix in 2024?",
        "sparql": """PREFIX ex: <http://example.org/f1#>
SELECT ?driverName WHERE {
    ?gp ex:inSeason ex:Season2024 ;
        ex:name ?gpName ;
        ex:winner ?driver .
    ?driver ex:name ?driverName .
    FILTER(CONTAINS(LCASE(?gpName), "british"))
}""",
    },
    {
        "question": "How many races did Lewis Hamilton win in 2019?",
        "sparql": """PREFIX ex: <http://example.org/f1#>
SELECT (COUNT(?gp) AS ?wins) WHERE {
    ?gp ex:winner ex:LewisHamilton ;
        ex:inSeason ex:Season2019 .
}""",
    },
    {
        "question": "Who were the teammates of Charles Leclerc in 2023?",
        "sparql": """PREFIX ex: <http://example.org/f1#>
SELECT DISTINCT ?mateName WHERE {
    ?s1 a ex:DriverStanding ; ex:forSeason ex:Season2023 ;
        ex:forDriver ex:CharlesLeclerc ; ex:forTeam ?team .
    ?s2 a ex:DriverStanding ; ex:forSeason ex:Season2023 ;
        ex:forDriver ?mate ; ex:forTeam ?team .
    ?mate ex:name ?mateName .
    FILTER(ex:CharlesLeclerc != ?mate)
}""",
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
