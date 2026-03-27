"""
expand_kb.py — F1 KB expansion via Wikidata SPARQL
====================================================
Expands the private KB with F1 historical data from 1950 to present.

Scope
-----
  1. Races          : name, date, season, circuit name
  2. Seasons        : name, year, WDC champion
  3. Drivers        : name, nationality, birth year
  4. Constructors   : name, country
  5. Race winners   : winner / hasWon (direct wdt:P1346)
  6. Race podiums   : 2nd and 3rd place via qualified statements
  7. Participation  : driver→race via direct wdt:P710 (fast)
  7b. Participation : driver-centric via wdt:P1344 (fallback, high coverage)
  8. Driver careers : team memberships
  9. Standings      : driver championship positions + points
  10. Circuits       : name, country, city

Out of scope: lap times, tyre data, circuit technical specs, images,
              coordinates, social media, biographies.

Data model
----------
Wikidata entities use wd: URIs.
Private entities use ex: URIs (bridged via owl:sameAs from alignments).
All predicates map to the existing ex: vocabulary for consistent SPARQL.

Usage
-----
  python src/kg/expand_kb.py
  (requires internet — queries query.wikidata.org, ~10-30 min)

Output
------
  kg_artifacts/expanded_kb.ttl   — Turtle (human-readable)
  kg_artifacts/expanded_kb.nt    — N-Triples (for KGE pipelines)
  kg_artifacts/stats.md          — Statistics report
"""

import csv
import time
from pathlib import Path
from rdflib import Graph, Namespace, URIRef, Literal
from rdflib.namespace import RDF, OWL, XSD
import requests

# ── Paths ──────────────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
KG_FILE      = PROJECT_ROOT / "kg_artifacts" / "expanded_kb.ttl"
DRIVERS_TSV  = PROJECT_ROOT / "kg_artifacts" / "alignment_drivers.tsv"
TEAMS_TSV    = PROJECT_ROOT / "kg_artifacts" / "alignment_teams.tsv"
OUTPUT_TTL   = PROJECT_ROOT / "kg_artifacts" / "expanded_kb.ttl"
OUTPUT_NT    = PROJECT_ROOT / "kg_artifacts" / "expanded_kb.nt"
STATS_FILE   = PROJECT_ROOT / "kg_artifacts" / "stats.md"

# ── Namespaces ─────────────────────────────────────────────────────────────────
EX = Namespace("http://example.org/f1#")
WD = Namespace("http://www.wikidata.org/entity/")

# ── Wikidata SPARQL endpoint ───────────────────────────────────────────────────
WIKIDATA_SPARQL = "https://query.wikidata.org/sparql"
HEADERS = {
    "User-Agent": "f1-kg-project/3.0 (student educational project; contact via github)",
    "Accept":     "application/sparql-results+json",
}


# ── SPARQL helpers ─────────────────────────────────────────────────────────────

def sparql_query(query: str, retries: int = 4) -> list[dict]:
    """Execute a SPARQL SELECT against Wikidata. Returns bindings list."""
    for attempt in range(retries):
        try:
            resp = requests.get(
                WIKIDATA_SPARQL,
                params={"query": query, "format": "json"},
                headers=HEADERS,
                timeout=120,
            )
            if resp.status_code == 429:
                wait = int(resp.headers.get("Retry-After", 60))
                print(f"    [Rate limit] sleeping {wait}s …")
                time.sleep(wait)
                continue
            if resp.status_code in (500, 503):
                print(f"    [SPARQL {resp.status_code}] endpoint busy — skipping block")
                return []
            resp.raise_for_status()
            return resp.json().get("results", {}).get("bindings", [])
        except requests.Timeout:
            print(f"    [Timeout] attempt {attempt + 1}/{retries}")
            time.sleep(15 * (attempt + 1))
        except Exception as exc:
            print(f"    [ERROR] attempt {attempt + 1}/{retries}: {exc}")
            time.sleep(8 * (attempt + 1))
    return []


def _paginated(query_tpl: str, page: int = 5000, max_pages: int = 30,
               label: str = "") -> list[dict]:
    """
    Run a paginated SPARQL query.
    The template must contain __LIMIT__ and __OFFSET__ as literal strings.
    """
    all_rows, offset = [], 0
    for page_n in range(1, max_pages + 1):
        q = query_tpl.replace("__LIMIT__", str(page)).replace("__OFFSET__", str(offset))
        rows = sparql_query(q)
        all_rows.extend(rows)
        print(f"    {label} page {page_n}: +{len(rows):,}  (total={len(all_rows):,})")
        if len(rows) < page:
            break
        offset += page
        time.sleep(1.5)
    return all_rows


def _val(binding: dict, key: str) -> str | None:
    b = binding.get(key)
    return b["value"] if b else None


# ── Alignment loader ───────────────────────────────────────────────────────────

def load_alignments(tsv_path: Path, min_conf: float = 0.8) -> dict[str, str]:
    """Returns {wikidata_id → local_entity_name} for confident alignments."""
    mapping = {}
    if not tsv_path.exists():
        return mapping
    with open(tsv_path, encoding="utf-8") as f:
        for row in csv.DictReader(f, delimiter="\t"):
            if row.get("status") != "auto":
                continue
            try:
                if float(row["confidence"]) < min_conf:
                    continue
            except ValueError:
                continue
            wid  = row["candidate_wikidata_id"].strip()
            name = row["local_entity"].strip()
            if wid and name:
                mapping[wid] = name
    return mapping


def add_sameas(g: Graph, driver_align: dict, team_align: dict) -> None:
    """Add owl:sameAs links: ex:LocalName  owl:sameAs  wd:QID"""
    for wid, local in driver_align.items():
        g.add((EX[local], OWL.sameAs, WD[wid]))
    for wid, local in team_align.items():
        g.add((EX[local], OWL.sameAs, WD[wid]))


# ── Triple helper ──────────────────────────────────────────────────────────────

def add(g: Graph, s, p, o) -> bool:
    t = (s, p, o)
    if t not in g:
        g.add(t)
        return True
    return False


def wd_uri(uri_str: str) -> URIRef:
    return URIRef(uri_str)


def extract_qid(uri_str: str) -> str | None:
    if "wikidata.org/entity/Q" in uri_str:
        return uri_str.rsplit("/", 1)[-1]
    return None


# ── Phase 1 — F1 races ────────────────────────────────────────────────────────

RACES_QUERY = """
SELECT ?race ?label ?date ?season ?circuitLabel WHERE {
  ?season wdt:P31 wd:Q27020041 ;
          wdt:P3450 wd:Q1968 .
  ?race wdt:P361 ?season ;
        rdfs:label ?label .
  FILTER(lang(?label) = "en")
  OPTIONAL { ?race wdt:P585 ?date . }
  OPTIONAL {
    ?race wdt:P276 ?circuit .
    ?circuit rdfs:label ?circuitLabel .
    FILTER(lang(?circuitLabel) = "en")
  }
}
LIMIT __LIMIT__ OFFSET __OFFSET__
"""


def phase_races(g: Graph) -> int:
    rows = _paginated(RACES_QUERY, page=5000, max_pages=5, label="races")
    added = 0
    for row in rows:
        race_uri    = wd_uri(_val(row, "race"))
        label       = _val(row, "label")
        date_v      = _val(row, "date")
        season_uri  = _val(row, "season")
        circuit_lbl = _val(row, "circuitLabel")

        added += add(g, race_uri, RDF.type, EX.GrandPrix)
        if label:
            added += add(g, race_uri, EX.name, Literal(label, lang="en"))
        if date_v:
            try:
                added += add(g, race_uri, EX.raceDate,
                             Literal(date_v[:10], datatype=XSD.date))
            except Exception:
                pass
        if season_uri:
            added += add(g, race_uri, EX.partOfSeason, wd_uri(season_uri))
        if circuit_lbl:
            added += add(g, race_uri, EX.circuitName,
                         Literal(circuit_lbl, lang="en"))
    return added


# ── Phase 2 — F1 seasons ──────────────────────────────────────────────────────

SEASONS_QUERY = """
SELECT ?season ?label ?year ?wdc WHERE {
  ?season wdt:P31 wd:Q27020041 ;
          wdt:P3450 wd:Q1968 ;
          rdfs:label ?label .
  FILTER(lang(?label) = "en")
  OPTIONAL { ?season wdt:P585 ?year . }
  OPTIONAL { ?season wdt:P1346 ?wdc . }
}
LIMIT __LIMIT__ OFFSET __OFFSET__
"""


def phase_seasons(g: Graph) -> int:
    rows = _paginated(SEASONS_QUERY, page=500, max_pages=3, label="seasons")
    added = 0
    for row in rows:
        season_uri = wd_uri(_val(row, "season"))
        label      = _val(row, "label")
        year_v     = _val(row, "year")
        wdc        = _val(row, "wdc")

        added += add(g, season_uri, RDF.type, EX.Season)
        if label:
            added += add(g, season_uri, EX.name, Literal(label, lang="en"))
        if year_v:
            try:
                added += add(g, season_uri, EX.seasonYear,
                             Literal(int(year_v[:4]), datatype=XSD.int))
            except ValueError:
                pass
        if wdc:
            added += add(g, wd_uri(wdc), EX.isChampionOf, season_uri)
    return added


# ── Phase 3 — F1 drivers ──────────────────────────────────────────────────────

DRIVERS_QUERY = """
SELECT DISTINCT ?driver ?label ?natLabel ?birth WHERE {
  ?driver wdt:P641 wd:Q1968 .
  ?driver rdfs:label ?label . FILTER(lang(?label) = "en")
  OPTIONAL {
    ?driver wdt:P27 ?nat .
    ?nat rdfs:label ?natLabel . FILTER(lang(?natLabel) = "en")
  }
  OPTIONAL { ?driver wdt:P569 ?birth . }
}
LIMIT __LIMIT__ OFFSET __OFFSET__
"""


def phase_drivers(g: Graph) -> int:
    rows = _paginated(DRIVERS_QUERY, page=5000, max_pages=3, label="drivers")
    added = 0
    for row in rows:
        drv       = wd_uri(_val(row, "driver"))
        label     = _val(row, "label")
        nat_label = _val(row, "natLabel")
        birth     = _val(row, "birth")

        added += add(g, drv, RDF.type, EX.Driver)
        if label:
            added += add(g, drv, EX.name, Literal(label, lang="en"))
        if nat_label:
            added += add(g, drv, EX.nationality, Literal(nat_label, lang="en"))
        if birth:
            try:
                added += add(g, drv, EX.birthYear,
                             Literal(int(birth[:4]), datatype=XSD.int))
            except ValueError:
                pass
    return added


# ── Phase 4 — F1 constructors ─────────────────────────────────────────────────

TEAMS_QUERY = """
SELECT DISTINCT ?team ?label ?countryLabel WHERE {
  ?team wdt:P31 wd:Q161764 .
  ?team rdfs:label ?label . FILTER(lang(?label) = "en")
  OPTIONAL {
    ?team wdt:P17 ?country .
    ?country rdfs:label ?countryLabel . FILTER(lang(?countryLabel) = "en")
  }
}
LIMIT __LIMIT__ OFFSET __OFFSET__
"""


def phase_teams(g: Graph) -> int:
    rows = _paginated(TEAMS_QUERY, page=1000, max_pages=3, label="constructors")
    added = 0
    for row in rows:
        team          = wd_uri(_val(row, "team"))
        label         = _val(row, "label")
        country_label = _val(row, "countryLabel")

        added += add(g, team, RDF.type, EX.Team)
        if label:
            added += add(g, team, EX.name, Literal(label, lang="en"))
        if country_label:
            added += add(g, team, EX.nationality,
                         Literal(country_label, lang="en"))
    return added


# ── Phase 5 — Race winners ────────────────────────────────────────────────────
# Scope via seasons (P31/Q27020041 = ~75 items) instead of races (P31/Q10853037 = 1000+)
# to avoid Wikidata's 60s query timeout.

WINNERS_QUERY = """
SELECT ?race ?winner WHERE {
  ?season wdt:P31 wd:Q27020041 ;
          wdt:P3450 wd:Q1968 .
  ?race wdt:P361 ?season ;
        wdt:P1346 ?winner .
}
LIMIT __LIMIT__ OFFSET __OFFSET__
"""


def phase_winners(g: Graph) -> int:
    rows = _paginated(WINNERS_QUERY, page=5000, max_pages=3, label="winners")
    added = 0
    for row in rows:
        race   = wd_uri(_val(row, "race"))
        winner = wd_uri(_val(row, "winner"))
        added += add(g, race,   EX.winner, winner)
        added += add(g, winner, EX.hasWon, race)
    return added


# ── Phase 6 — Podiums (2nd and 3rd place via qualified statements) ─────────────

PODIUM_QUERY = """
SELECT ?race ?driver ?pos WHERE {
  ?season wdt:P31 wd:Q27020041 ;
          wdt:P3450 wd:Q1968 .
  ?race wdt:P361 ?season ;
        p:P710 ?stmt .
  ?stmt ps:P710 ?driver ;
        pq:P1352 ?pos .
  FILTER(xsd:integer(?pos) >= 2 && xsd:integer(?pos) <= 3)
  ?driver wdt:P641 wd:Q1968 .
}
LIMIT __LIMIT__ OFFSET __OFFSET__
"""


def phase_podiums(g: Graph) -> int:
    rows = _paginated(PODIUM_QUERY, page=5000, max_pages=5, label="podiums")
    added = 0
    pos_pred = {"2": EX.secondPlace, "3": EX.thirdPlace}
    for row in rows:
        race   = wd_uri(_val(row, "race"))
        driver = wd_uri(_val(row, "driver"))
        pos    = _val(row, "pos")
        if pos in pos_pred:
            added += add(g, race, pos_pred[pos], driver)
    return added


# ── Phase 7 — Race participation via direct wdt:P710 ─────────────────────────
# Strategy: wdt:P710 (direct) is populated for many more F1 races than the
# qualified p:P710 / ps:P710 approach used previously.
# We filter to F1 drivers (wdt:P641 = wd:Q1968) to exclude marshals, officials.

PARTICIPATION_DIRECT_QUERY = """
SELECT ?race ?driver WHERE {
  ?season wdt:P31 wd:Q27020041 ;
          wdt:P3450 wd:Q1968 .
  ?race wdt:P361 ?season ;
        wdt:P710 ?driver .
  ?driver wdt:P641 wd:Q1968 .
}
LIMIT __LIMIT__ OFFSET __OFFSET__
"""


def phase_participation_direct(g: Graph) -> int:
    """Race participation via direct wdt:P710 on race entities."""
    rows = _paginated(PARTICIPATION_DIRECT_QUERY, page=5000, max_pages=10,
                      label="participation(direct)")
    added = 0
    for row in rows:
        driver = wd_uri(_val(row, "driver"))
        race   = wd_uri(_val(row, "race"))
        added += add(g, driver, EX.participatedIn, race)
    return added


# ── Phase 7b — Participation via driver-centric wdt:P1344 ─────────────────────
# Many F1 drivers list "participant in" (P1344) events pointing to F1 GPs.
# This complements Phase 7 by catching drivers not covered there.

PARTICIPATION_DRIVER_QUERY = """
SELECT DISTINCT ?driver ?race WHERE {
  ?season wdt:P31 wd:Q27020041 ;
          wdt:P3450 wd:Q1968 .
  ?race wdt:P361 ?season .
  ?driver wdt:P641 wd:Q1968 ;
          wdt:P1344 ?race .
}
LIMIT __LIMIT__ OFFSET __OFFSET__
"""


def phase_participation_driver(g: Graph) -> int:
    """Race participation queried from the driver side (wdt:P1344)."""
    rows = _paginated(PARTICIPATION_DRIVER_QUERY, page=5000, max_pages=10,
                      label="participation(driver-centric)")
    added = 0
    for row in rows:
        driver = wd_uri(_val(row, "driver"))
        race   = wd_uri(_val(row, "race"))
        added += add(g, driver, EX.participatedIn, race)
    return added


# ── Phase 8 — Driver career (team memberships) ────────────────────────────────

CAREER_QUERY = """
SELECT DISTINCT ?driver ?team WHERE {
  ?driver wdt:P641 wd:Q1968 ;
          wdt:P54  ?team .
  FILTER EXISTS { ?team wdt:P641 wd:Q1968 }
}
LIMIT __LIMIT__ OFFSET __OFFSET__
"""


def phase_career(g: Graph) -> int:
    rows = _paginated(CAREER_QUERY, page=5000, max_pages=4, label="careers")
    added = 0
    for row in rows:
        driver = wd_uri(_val(row, "driver"))
        team   = wd_uri(_val(row, "team"))
        added += add(g, driver, EX.drivesFor, team)
    return added


# ── Phase 9 — Season standings ────────────────────────────────────────────────

STANDINGS_QUERY = """
SELECT ?season ?driver ?rank ?pts WHERE {
  ?season wdt:P31 wd:Q22979761 .
  ?season p:P1344 ?stmt .
  ?stmt ps:P1344 ?driver .
  ?stmt pq:P1352 ?rank .
  OPTIONAL { ?stmt pq:P1410 ?pts . }
  ?driver wdt:P641 wd:Q1968 .
}
LIMIT __LIMIT__ OFFSET __OFFSET__
"""


def phase_standings(g: Graph) -> int:
    rows = _paginated(STANDINGS_QUERY, page=5000, max_pages=6,
                      label="standings")
    added = 0
    for row in rows:
        season_v = _val(row, "season")
        driver_v = _val(row, "driver")
        rank_v   = _val(row, "rank")
        pts_v    = _val(row, "pts")

        if not (season_v and driver_v and rank_v):
            continue

        season = wd_uri(season_v)
        driver = wd_uri(driver_v)

        s_qid = extract_qid(season_v) or season_v.rsplit("/", 1)[-1]
        d_qid = extract_qid(driver_v) or driver_v.rsplit("/", 1)[-1]
        standing = EX[f"Standing_{s_qid}_{d_qid}"]

        added += add(g, standing, RDF.type,           EX.DriverStanding)
        added += add(g, standing, EX.forSeason,       season)
        added += add(g, standing, EX.forDriver,       driver)
        try:
            pos = int(rank_v)
            added += add(g, standing, EX.standingPosition,
                         Literal(pos, datatype=XSD.int))
            if pos == 1:
                added += add(g, driver, EX.isChampionOf, season)
        except ValueError:
            pass
        if pts_v:
            try:
                added += add(g, standing, EX.standingPoints,
                             Literal(float(pts_v), datatype=XSD.decimal))
            except ValueError:
                pass
    return added


# ── Phase 10 — F1 circuits ────────────────────────────────────────────────────
# Get all circuits actually used in an F1 Grand Prix race, with name, country,
# and city. Anchored on races so we only get F1-relevant circuits.

CIRCUITS_QUERY = """
SELECT DISTINCT ?circuit ?label ?countryLabel ?cityLabel WHERE {
  ?season wdt:P31 wd:Q27020041 ;
          wdt:P3450 wd:Q1968 .
  ?race wdt:P361 ?season ;
        wdt:P276 ?circuit .
  ?circuit rdfs:label ?label . FILTER(lang(?label) = "en")
  OPTIONAL {
    ?circuit wdt:P17 ?country .
    ?country rdfs:label ?countryLabel . FILTER(lang(?countryLabel) = "en")
  }
  OPTIONAL {
    ?circuit wdt:P131 ?city .
    ?city rdfs:label ?cityLabel . FILTER(lang(?cityLabel) = "en")
  }
}
LIMIT __LIMIT__ OFFSET __OFFSET__
"""


def phase_circuits(g: Graph) -> int:
    """All F1 circuits with name, country, and city."""
    rows = _paginated(CIRCUITS_QUERY, page=500, max_pages=3, label="circuits")
    added = 0
    for row in rows:
        circuit      = wd_uri(_val(row, "circuit"))
        label        = _val(row, "label")
        country_lbl  = _val(row, "countryLabel")
        city_lbl     = _val(row, "cityLabel")

        added += add(g, circuit, RDF.type, EX.Circuit)
        if label:
            added += add(g, circuit, EX.name, Literal(label, lang="en"))
        if country_lbl:
            added += add(g, circuit, EX.nationality, Literal(country_lbl, lang="en"))
        if city_lbl:
            added += add(g, circuit, EX.city, Literal(city_lbl, lang="en"))
    return added


# ── Phase 11 — Bind races to circuits (URI-level, not just string) ─────────────

RACE_CIRCUIT_QUERY = """
SELECT ?race ?circuit WHERE {
  ?season wdt:P31 wd:Q27020041 ;
          wdt:P3450 wd:Q1968 .
  ?race wdt:P361 ?season ;
        wdt:P276 ?circuit .
}
LIMIT __LIMIT__ OFFSET __OFFSET__
"""


def phase_race_circuit_links(g: Graph) -> int:
    """Link each race to its circuit URI (ex:heldAtCircuit)."""
    rows = _paginated(RACE_CIRCUIT_QUERY, page=5000, max_pages=5,
                      label="race→circuit links")
    added = 0
    for row in rows:
        race    = wd_uri(_val(row, "race"))
        circuit = wd_uri(_val(row, "circuit"))
        added += add(g, race, EX.heldAtCircuit, circuit)
    return added


# ── Phase 12 — Pole positions per race ───────────────────────────────────────

POLE_QUERY = """
SELECT ?race ?driver WHERE {
  ?season wdt:P31 wd:Q27020041 ;
          wdt:P3450 wd:Q1968 .
  ?race wdt:P361 ?season ;
        wdt:P1347 ?driver .
}
LIMIT __LIMIT__ OFFSET __OFFSET__
"""


def phase_poles(g: Graph) -> int:
    """Pole position holder per race (wdt:P1347)."""
    rows = _paginated(POLE_QUERY, page=5000, max_pages=3, label="pole positions")
    added = 0
    for row in rows:
        race   = wd_uri(_val(row, "race"))
        driver = wd_uri(_val(row, "driver"))
        added += add(g, race,   EX.polePosition, driver)
        added += add(g, driver, EX.hasPole,      race)
    return added


# ── Phase 13 — Fastest lap holders per race ───────────────────────────────────

FASTEST_LAP_QUERY = """
SELECT ?race ?driver WHERE {
  ?season wdt:P31 wd:Q27020041 ;
          wdt:P3450 wd:Q1968 .
  ?race wdt:P361 ?season ;
        wdt:P1351 ?driver .
}
LIMIT __LIMIT__ OFFSET __OFFSET__
"""


def phase_fastest_laps(g: Graph) -> int:
    """Fastest lap holder per race (wdt:P1351)."""
    rows = _paginated(FASTEST_LAP_QUERY, page=5000, max_pages=3, label="fastest laps")
    added = 0
    for row in rows:
        race   = wd_uri(_val(row, "race"))
        driver = wd_uri(_val(row, "driver"))
        added += add(g, race,   EX.fastestLapBy,  driver)
        added += add(g, driver, EX.hasFastestLap, race)
    return added


# ── Phase 14 — Driver career statistics ──────────────────────────────────────

DRIVER_STATS_QUERY = """
SELECT ?driver ?wins ?poles ?fastestLaps ?championships WHERE {
  ?driver wdt:P641 wd:Q1968 .
  OPTIONAL { ?driver wdt:P1350 ?wins . }
  OPTIONAL { ?driver wdt:P1352 ?poles . }
  OPTIONAL { ?driver wdt:P1353 ?fastestLaps . }
  OPTIONAL { ?driver wdt:P1081 ?championships . }
}
LIMIT __LIMIT__ OFFSET __OFFSET__
"""


def phase_driver_stats(g: Graph) -> int:
    """Career totals per driver: wins, poles, fastest laps, championships."""
    rows = _paginated(DRIVER_STATS_QUERY, page=5000, max_pages=3, label="driver stats")
    added = 0
    for row in rows:
        drv = wd_uri(_val(row, "driver"))
        for key, pred, dtype in [
            ("wins",         EX.careerWins,         XSD.int),
            ("poles",        EX.careerPoles,        XSD.int),
            ("fastestLaps",  EX.careerFastestLaps,  XSD.int),
            ("championships",EX.careerChampionships, XSD.int),
        ]:
            val = _val(row, key)
            if val:
                try:
                    added += add(g, drv, pred, Literal(int(float(val)), datatype=dtype))
                except (ValueError, TypeError):
                    pass
    return added


# ── Phase 15 — Constructor championship winner per season ─────────────────────

CONSTRUCTOR_CHAMP_QUERY = """
SELECT ?season ?team ?year WHERE {
  ?season wdt:P31 wd:Q27020041 ;
          wdt:P3450 wd:Q1968 ;
          wdt:P2522 ?team .
  OPTIONAL { ?season wdt:P585 ?year . }
}
LIMIT __LIMIT__ OFFSET __OFFSET__
"""


def phase_constructor_champs(g: Graph) -> int:
    """Constructors' championship winner per season (wdt:P2522)."""
    rows = _paginated(CONSTRUCTOR_CHAMP_QUERY, page=500, max_pages=3,
                      label="constructor champions")
    added = 0
    for row in rows:
        season = wd_uri(_val(row, "season"))
        team   = wd_uri(_val(row, "team"))
        year_v = _val(row, "year")
        added += add(g, season, EX.constructorsChampion, team)
        added += add(g, team,   EX.wonConstructorsTitleIn, season)
        if year_v:
            try:
                added += add(g, season, EX.seasonYear,
                             Literal(int(year_v[:4]), datatype=XSD.int))
            except (ValueError, TypeError):
                pass
    return added


# ── Stats ──────────────────────────────────────────────────────────────────────

def write_stats(g: Graph, path: Path) -> None:
    subjects   = {str(s) for s, _, _ in g if str(s).startswith("http")}
    predicates = {str(p) for _, p, _ in g}

    pred_counts: dict[str, int] = {}
    for _, p, _ in g:
        pred_counts[str(p)] = pred_counts.get(str(p), 0) + 1
    top20 = sorted(pred_counts.items(), key=lambda x: x[1], reverse=True)[:20]

    lines = [
        "# Knowledge Base Statistics\n",
        "## Overview\n",
        "| Metric | Value |",
        "|---|---|",
        f"| Total triples | {len(g):,} |",
        f"| Unique subjects (entities) | {len(subjects):,} |",
        f"| Unique predicates (relations) | {len(predicates):,} |",
        "",
        "## Top-20 predicates by frequency\n",
        "| Predicate | Count |",
        "|---|---|",
    ]
    for pred_uri, cnt in top20:
        short = pred_uri.split("/")[-1].split("#")[-1]
        lines.append(f"| `{short}` | {cnt:,} |")

    lines += [
        "",
        "## Expansion strategy (15 phases — Wikidata)",
        "",
        "| Phase | Content | Key predicate |",
        "|---|---|---|",
        "| 1  | F1 races: name, date, season, circuit label | `ex:partOfSeason` |",
        "| 2  | F1 seasons: name, year, WDC | `ex:isChampionOf` |",
        "| 3  | F1 drivers: name, nationality, birth year | `ex:nationality` |",
        "| 4  | F1 constructors: name, country | `rdf:type ex:Team` |",
        "| 5  | Race winners via wdt:P1346 | `ex:winner` / `ex:hasWon` |",
        "| 6  | Podium 2nd & 3rd via qualified stmts | `ex:secondPlace` / `ex:thirdPlace` |",
        "| 7  | Race participation — direct wdt:P710 + F1 driver filter | `ex:participatedIn` |",
        "| 7b | Race participation — driver-centric wdt:P1344 | `ex:participatedIn` |",
        "| 8  | Driver career team memberships | `ex:drivesFor` |",
        "| 9  | Season standings: position + points | `ex:standingPosition` |",
        "| 10 | F1 circuits: name, country, city | `ex:city` |",
        "| 11 | Race → circuit URI links | `ex:heldAtCircuit` |",
        "| 12 | Pole positions per race (wdt:P1347) | `ex:polePosition` / `ex:hasPole` |",
        "| 13 | Fastest lap holders per race (wdt:P1351) | `ex:fastestLapBy` / `ex:hasFastestLap` |",
        "| 14 | Driver career stats: wins, poles, FL, titles | `ex:careerWins` |",
        "| 15 | Constructor championship winners per season | `ex:constructorsChampion` |",
        "",
        "## Source files",
        "",
        "| File | Description |",
        "|---|---|",
        "| `auto_kg.ttl` | Private KB (Formula1.com scraped data) |",
        "| `expanded_kb.ttl` | Full expanded KB (this file, Turtle) |",
        "| `expanded_kb.nt` | Full expanded KB (N-Triples, for KGE) |",
        "| `alignment_drivers.tsv` | Driver → Wikidata alignment |",
        "| `alignment_teams.tsv` | Team → Wikidata alignment |",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Stats written → {path}")


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    print("=" * 65)
    print("KB EXPANSION — Wikidata (11 phases)")
    print("=" * 65)

    print("\n[0] Loading initial KB …")
    g = Graph()
    g.parse(KG_FILE, format="turtle")
    g.bind("ex", EX)
    g.bind("wd", WD)
    print(f"    Initial KB: {len(g):,} triples")

    print("\n[1] Adding owl:sameAs alignment links …")
    driver_align = load_alignments(DRIVERS_TSV)
    team_align   = load_alignments(TEAMS_TSV)
    add_sameas(g, driver_align, team_align)
    print(f"    Drivers: {len(driver_align)} | Teams: {len(team_align)}")
    print(f"    KB after sameAs: {len(g):,} triples")

    phases = [
        ("Phase 1  — F1 races (name, date, season, circuit)",        phase_races),
        ("Phase 2  — F1 seasons (WDC, year)",                        phase_seasons),
        ("Phase 3  — F1 drivers (name, nationality, birth)",         phase_drivers),
        ("Phase 4  — F1 constructors (name, country)",               phase_teams),
        ("Phase 5  — Race winners (direct P1346)",                   phase_winners),
        ("Phase 6  — Podiums 2nd & 3rd (qualified stmts)",           phase_podiums),
        ("Phase 7  — Participation direct wdt:P710",                 phase_participation_direct),
        ("Phase 7b — Participation driver-centric wdt:P1344",        phase_participation_driver),
        ("Phase 8  — Driver careers (team memberships)",             phase_career),
        ("Phase 9  — Season standings (position + points)",          phase_standings),
        ("Phase 10 — F1 circuits (name, country, city)",             phase_circuits),
        ("Phase 11 — Race → circuit URI links",                      phase_race_circuit_links),
        ("Phase 12 — Pole positions per race",                       phase_poles),
        ("Phase 13 — Fastest lap holders per race",                  phase_fastest_laps),
        ("Phase 14 — Driver career statistics",                      phase_driver_stats),
        ("Phase 15 — Constructor championship winners",              phase_constructor_champs),
    ]

    for label, fn in phases:
        print(f"\n[{label}] …")
        try:
            added = fn(g)
            print(f"    → +{added:,} new triples  |  KB total: {len(g):,}")
        except Exception as exc:
            print(f"    [WARNING] Phase failed: {exc} — continuing")
        time.sleep(2)

    print(f"\n[Save] Serialising …")
    OUTPUT_TTL.parent.mkdir(parents=True, exist_ok=True)
    g.serialize(destination=str(OUTPUT_TTL), format="turtle")
    print(f"  → TTL saved  ({len(g):,} triples)  {OUTPUT_TTL}")
    g.serialize(destination=str(OUTPUT_NT), format="ntriples")
    print(f"  → NT  saved  ({len(g):,} triples)  {OUTPUT_NT}")

    write_stats(g, STATS_FILE)

    subjects   = {str(s) for s, _, _ in g if str(s).startswith("http")}
    predicates = {str(p) for _, p, _ in g}
    print("\n" + "=" * 65)
    print("EXPANSION COMPLETE")
    print(f"  Triples    : {len(g):,}")
    print(f"  Entities   : {len(subjects):,}")
    print(f"  Predicates : {len(predicates):,}")

    target_low, target_high = 50_000, 200_000
    if len(g) < target_low:
        print(f"\n  [WARNING] {len(g):,} < target {target_low:,}.")
        print("  Try running build_race_results_kg.py first to add local race results,")
        print("  or increase max_pages in phase_participation_direct / phase_participation_driver.")
    elif len(g) > target_high:
        print(f"\n  [INFO] {len(g):,} > upper bound {target_high:,}.")
        print("  Consider pruning low-frequency predicates before KGE.")
    else:
        print(f"\n  [OK] Volume within target ({target_low:,} – {target_high:,}).")
    print("=" * 65)


if __name__ == "__main__":
    main()
