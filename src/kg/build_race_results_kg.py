"""
build_race_results_kg.py — Add race result triples to the KB
=============================================================
Reads data/interim/race_results_{year}.json (from extract_race_results.py)
and adds RaceResult entities to kg_artifacts/expanded_kb.ttl.

URI convention
--------------
Race entities use the SAME convention as build_local_expansion.py:
  ex:GP_{year}_{CamelCaseName}   (e.g. ex:GP_2024_Bahrain, ex:GP_2024_SaudiArabia)

This ensures the two scripts share a single race node — no duplicate race
entities in the ex: namespace.

The slug→canonical mapping converts URL slugs (from formula1.com result URLs)
to the CamelCase names used in the CALENDAR dict:
  "bahrain"       → "Bahrain"
  "saudi-arabia"  → "SaudiArabia"
  "mexico-city"   → "Mexico"   ← display name on formula1.com is just "Mexico"
  etc.

Each race result adds triples:
  ex:RaceResult_{year}_{race}_{pos}  rdf:type          ex:RaceResult
  ex:RaceResult_{year}_{race}_{pos}  ex:forDriver       ex:DriverURI
  ex:RaceResult_{year}_{race}_{pos}  ex:forRace         ex:GP_{year}_{Name}
  ex:RaceResult_{year}_{race}_{pos}  ex:forTeam         ex:TeamURI
  ex:RaceResult_{year}_{race}_{pos}  ex:finishPosition  xsd:int
  ex:RaceResult_{year}_{race}_{pos}  ex:pointsScored    xsd:decimal
  ex:RaceResult_{year}_{race}_{pos}  ex:lapsCompleted   xsd:int
  ex:GP_{year}_{Name}                rdf:type           ex:GrandPrix   (idempotent)
  ex:GP_{year}_{Name}                ex:inSeason        ex:Season{year}

Usage:
  python src/kg/build_race_results_kg.py

Reads:  data/interim/race_results_*.json
        kg_artifacts/expanded_kb.ttl  (input, may not exist yet)
Writes: kg_artifacts/expanded_kb.ttl  (updated in-place)
        kg_artifacts/expanded_kb.nt
"""

import json
import re
from pathlib import Path
from rdflib import Graph, Namespace, URIRef, Literal
from rdflib.namespace import RDF, XSD

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
INTERIM_DIR  = PROJECT_ROOT / "data" / "interim"
KG_FILE      = PROJECT_ROOT / "kg_artifacts" / "expanded_kb.ttl"

EX = Namespace("http://example.org/f1#")

# ── Slug → canonical name mapping ─────────────────────────────────────────────
# formula1.com URL slugs differ from the display names used in build_local_expansion.py.
# General rule: capitalize each hyphen-separated word.
# Exceptions: where the display name on formula1.com differs from the slug.
_SLUG_EXCEPTIONS: dict[str, str] = {
    "mexico-city": "Mexico",        # page says "Mexico", not "Mexico City"
    "great-britain": "GreatBritain",
    "emilia-romagna": "EmiliaRomagna",
    "abu-dhabi": "AbuDhabi",
    "las-vegas": "LasVegas",
    "saudi-arabia": "SaudiArabia",
    "united-states": "UnitedStates",
}


def slug_to_canonical(slug: str) -> str:
    """
    Convert a formula1.com URL slug to the CamelCase name used in
    build_local_expansion.py's CALENDAR dict.
    """
    if slug in _SLUG_EXCEPTIONS:
        return _SLUG_EXCEPTIONS[slug]
    return "".join(word.capitalize() for word in slug.split("-"))


# ── URI helpers (ex: namespace, consistent with build_local_expansion.py) ─────

def clean_uri(text: str) -> str:
    """Remove punctuation/spaces — same convention as build_kb.py."""
    return re.sub(r"[^A-Za-z0-9_]", "", text.replace(" ", ""))


def driver_uri(name: str) -> URIRef:
    return EX[clean_uri(name)]


def team_uri(name: str) -> URIRef:
    return EX[clean_uri(name)]


def race_uri(year: int, slug: str) -> URIRef:
    """Return ex:GP_{year}_{CamelCaseName} — same convention as build_local_expansion."""
    canonical = slug_to_canonical(slug)
    return EX[f"GP_{year}_{canonical}"]


def season_uri(year: int) -> URIRef:
    return EX[f"Season{year}"]


def result_uri(year: int, slug: str, pos: int) -> URIRef:
    canonical = slug_to_canonical(slug)
    return EX[f"RaceResult_{year}_{canonical}_{pos}"]


# ── Triple builder ────────────────────────────────────────────────────────────

def add(g: Graph, s, p, o) -> bool:
    t = (s, p, o)
    if t not in g:
        g.add(t)
        return True
    return False


def build_race_result_triples(g: Graph, records: list[dict]) -> int:
    """
    Insert RaceResult triples for all records from one season.
    Returns number of new triples added.
    """
    added = 0

    for rec in records:
        year = rec["season"]
        slug = rec["race"]
        pos  = rec["position"]
        drv  = rec["driver"]
        team = rec["team"]
        laps = rec.get("laps", 0)
        pts  = rec.get("points", 0)

        r_uri  = result_uri(year, slug, pos)
        rc_uri = race_uri(year, slug)
        s_uri  = season_uri(year)
        d_uri  = driver_uri(drv)
        t_uri  = team_uri(team)

        # Race entity (idempotent — already in KB from local expansion)
        added += add(g, rc_uri, RDF.type,    EX.GrandPrix)
        added += add(g, rc_uri, EX.inSeason, s_uri)

        # Driver entity (idempotent)
        added += add(g, d_uri, RDF.type, EX.Driver)
        added += add(g, d_uri, EX.name,  Literal(drv))

        # Team entity (idempotent)
        added += add(g, t_uri, RDF.type, EX.Team)
        added += add(g, t_uri, EX.name,  Literal(team))

        # RaceResult node — the main payload
        added += add(g, r_uri, RDF.type,         EX.RaceResult)
        added += add(g, r_uri, EX.forDriver,      d_uri)
        added += add(g, r_uri, EX.forRace,        rc_uri)
        added += add(g, r_uri, EX.forTeam,        t_uri)
        added += add(g, r_uri, EX.finishPosition,
                     Literal(pos, datatype=XSD.int))
        if laps:
            added += add(g, r_uri, EX.lapsCompleted,
                         Literal(laps, datatype=XSD.int))
        added += add(g, r_uri, EX.pointsScored,
                     Literal(float(pts), datatype=XSD.decimal))

        # Convenience inverse: driver participatedIn race
        added += add(g, d_uri, EX.participatedIn, rc_uri)

        # Winner shortcut
        if pos == 1:
            added += add(g, rc_uri, EX.winner, d_uri)
            added += add(g, d_uri,  EX.hasWon, rc_uri)

    return added


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    # Load existing KB (or start fresh if it doesn't exist)
    g = Graph()
    g.bind("ex", EX)
    if KG_FILE.exists():
        print(f"Loading existing KB from {KG_FILE} …")
        g.parse(KG_FILE, format="turtle")
        print(f"  Initial triples: {len(g):,}")
    else:
        print("No existing KB found — starting fresh.")
        KG_FILE.parent.mkdir(parents=True, exist_ok=True)

    interim_files = sorted(INTERIM_DIR.glob("race_results_*.json"))
    if not interim_files:
        print("\nNo race_results_*.json files found in data/interim/.")
        print("Run these first:")
        print("  python src/crawl/crawl_race_results.py")
        print("  python src/ie/extract_race_results.py")
        return

    total_added = 0
    for f in interim_files:
        records = json.loads(f.read_text(encoding="utf-8"))
        seasons = {r["season"] for r in records}
        year    = min(seasons) if seasons else "?"
        print(f"\n[{year}] {f.name}: {len(records)} records …")
        added = build_race_result_triples(g, records)
        total_added += added
        print(f"  +{added:,} new triples  |  KB total: {len(g):,}")

    print(f"\nSaving {KG_FILE} …")
    g.serialize(destination=str(KG_FILE), format="turtle")

    nt_file = KG_FILE.with_suffix(".nt")
    g.serialize(destination=str(nt_file), format="ntriples")

    subjects   = {str(s) for s, _, _ in g if str(s).startswith("http")}
    predicates = {str(p) for _, p, _ in g}
    print("\n" + "=" * 55)
    print("RACE RESULTS KB UPDATE COMPLETE")
    print(f"  New triples added : {total_added:,}")
    print(f"  Total triples     : {len(g):,}")
    print(f"  Entities          : {len(subjects):,}")
    print(f"  Predicates        : {len(predicates):,}")
    print(f"  TTL → {KG_FILE}")
    print(f"  NT  → {nt_file}")
    print("=" * 55)


if __name__ == "__main__":
    main()
