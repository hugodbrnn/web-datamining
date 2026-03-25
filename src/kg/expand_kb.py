"""
expand_kb.py — SPARQL-based KB expansion via Wikidata.

Strategy
--------
Phase 1  – 1-hop expansion from our confidently aligned entities
           (drivers + teams from alignment TSV files).
Phase 2  – Domain-wide pull: all F1 drivers, constructors, seasons,
           Grand Prix events and circuits known to Wikidata.
           Uses pagination (OFFSET) to bypass the 10 000-row limit.
Phase 3  – Predicate-controlled 2-hop on high-value relations:
           countries of citizenship and awards received.

Cleaning
--------
  • Noisy / meta predicates filtered out (images, coordinates, etc.)
  • Only English or language-neutral literals kept
  • rdflib deduplication (Graph is a set of triples)

Output
------
  kg_artifacts/expanded_kb.ttl   — final expanded KB in Turtle format
  kg_artifacts/stats.md          — statistics report

Season window
-------------
  The private KB covers a rolling 5-season window managed by
  src/crawl/seasons.py (current year + 4 previous). The Wikidata
  expansion is historical and covers all F1 seasons ever.

Usage
-----
  python src/kg/expand_kb.py
"""

import csv
import time
from pathlib import Path
from rdflib import Graph, Namespace, URIRef, Literal
from rdflib.namespace import RDF, OWL, RDFS, XSD
import requests

# ── Paths ──────────────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
KG_FILE      = PROJECT_ROOT / "kg_artifacts" / "auto_kg.ttl"
DRIVERS_TSV  = PROJECT_ROOT / "kg_artifacts" / "alignment_drivers.tsv"
TEAMS_TSV    = PROJECT_ROOT / "kg_artifacts" / "alignment_teams.tsv"
OUTPUT_FILE  = PROJECT_ROOT / "kg_artifacts" / "expanded_kb.ttl"
STATS_FILE   = PROJECT_ROOT / "kg_artifacts" / "stats.md"

# ── Namespaces ─────────────────────────────────────────────────────────────────
EX  = Namespace("http://example.org/f1#")
WD  = Namespace("http://www.wikidata.org/entity/")
WDT = Namespace("http://www.wikidata.org/prop/direct/")

# ── Wikidata SPARQL endpoint ───────────────────────────────────────────────────
WIKIDATA_SPARQL = "https://query.wikidata.org/sparql"
HEADERS = {
    "User-Agent": "f1-kg-project/1.0 (student project; educational use only)",
    "Accept":     "application/sparql-results+json",
}

# ── Predicates to EXCLUDE (noisy, meta, or content-farm) ──────────────────────
EXCLUDE_PRED_PREFIXES = (
    "http://wikiba.se/",
    "http://schema.org/",
    "http://www.w3.org/2004/02/skos/core#",
    "http://www.w3.org/2000/01/rdf-schema#label",
    "http://www.w3.org/2000/01/rdf-schema#comment",
)
EXCLUDE_PRED_EXACT = {
    WDT.P18,    # image
    WDT.P625,   # coordinate location
    WDT.P856,   # official website
    WDT.P373,   # Commons category
    WDT.P910,   # topic's main category
    WDT.P2910,  # icon
    WDT.P8517,  # view
    WDT.P154,   # logo image
    WDT.P14,    # plaque image
    WDT.P3451,  # nighttime view
    WDT.P5775,  # image of interior
    WDT.P242,   # locator map
}

def _is_excluded(pred_uri: str) -> bool:
    if URIRef(pred_uri) in EXCLUDE_PRED_EXACT:
        return True
    for prefix in EXCLUDE_PRED_PREFIXES:
        if pred_uri.startswith(prefix):
            return True
    return False

# ── SPARQL helper ──────────────────────────────────────────────────────────────
def sparql_query(query: str, retries: int = 4) -> list[dict]:
    for attempt in range(retries):
        try:
            resp = requests.get(
                WIKIDATA_SPARQL,
                params={"query": query, "format": "json"},
                headers=HEADERS,
                timeout=90,
            )
            if resp.status_code == 429:
                wait = int(resp.headers.get("Retry-After", 60))
                print(f"    [Rate limit] sleeping {wait}s …")
                time.sleep(wait)
                continue
            if resp.status_code == 500:
                print(f"    [SPARQL 500] query timeout — skipping block")
                return []
            resp.raise_for_status()
            return resp.json().get("results", {}).get("bindings", [])
        except requests.Timeout:
            print(f"    [Timeout] attempt {attempt+1}/{retries}")
            time.sleep(10 * (attempt + 1))
        except Exception as exc:
            print(f"    [ERROR] attempt {attempt+1}/{retries}: {exc}")
            time.sleep(5 * (attempt + 1))
    return []

# ── Triple builder ─────────────────────────────────────────────────────────────
def _make_object(binding: dict):
    """Convert a SPARQL result binding to an rdflib term, or None to skip."""
    t = binding.get("type")
    if t == "uri":
        return URIRef(binding["value"])
    if t in ("literal", "typed-literal"):
        lang     = binding.get("xml:lang", "")
        datatype = binding.get("datatype", "")
        val      = binding["value"]
        if lang and lang not in ("en", ""):
            return None          # keep only English / neutral literals
        if lang:
            return Literal(val, lang=lang)
        if datatype:
            return Literal(val, datatype=URIRef(datatype))
        return Literal(val)
    return None                  # skip blank nodes

def _ingest_rows(g: Graph, rows: list[dict],
                 subj_key: str, pred_key: str, obj_key: str) -> int:
    added = 0
    for row in rows:
        try:
            if subj_key not in row or pred_key not in row or obj_key not in row:
                continue
            p_val = row[pred_key]["value"]
            if _is_excluded(p_val):
                continue
            s = URIRef(row[subj_key]["value"])
            p = URIRef(p_val)
            o = _make_object(row[obj_key])
            if o is None:
                continue
            triple = (s, p, o)
            if triple not in g:
                g.add(triple)
                added += 1
        except Exception:
            continue
    return added

# ── Alignment loader ───────────────────────────────────────────────────────────
def load_aligned_ids(tsv_path: Path, min_conf: float = 0.8) -> list[str]:
    ids, seen = [], set()
    with open(tsv_path, encoding="utf-8") as f:
        for row in csv.DictReader(f, delimiter="\t"):
            if row.get("status") != "auto":
                continue
            try:
                if float(row["confidence"]) < min_conf:
                    continue
            except ValueError:
                continue
            wid = row["candidate_wikidata_id"].strip()
            if wid and wid not in seen:
                ids.append(wid)
                seen.add(wid)
    return ids

# ── Phase 1 – 1-hop on aligned entities ───────────────────────────────────────
def phase1_one_hop(g: Graph, wikidata_ids: list[str]) -> int:
    """Fetch all direct triples for each aligned Wikidata entity."""
    total = 0
    for i, wid in enumerate(wikidata_ids, 1):
        query = f"""
SELECT ?p ?o WHERE {{
  wd:{wid} ?p ?o .
  FILTER(!isLiteral(?o) || lang(?o) = "" || lang(?o) = "en")
}}
LIMIT 1500
"""
        rows = sparql_query(query)
        added = 0
        for row in rows:
            p_val = row.get("p", {}).get("value", "")
            if _is_excluded(p_val):
                continue
            o = _make_object(row.get("o", {}))
            if o is None:
                continue
            triple = (WD[wid], URIRef(p_val), o)
            if triple not in g:
                g.add(triple)
                added += 1
        total += added
        print(f"    [{i:>2}/{len(wikidata_ids)}] wd:{wid}  +{added:>4}  (KB={len(g):,})")
        time.sleep(0.6)
    return total

# ── Paginated bulk query ───────────────────────────────────────────────────────
def _paginated(g: Graph, query_tpl: str,
               subj_key: str, pred_key: str, obj_key: str,
               page: int = 5000, max_pages: int = 20,
               label: str = "") -> int:
    total, offset = 0, 0
    for page_n in range(1, max_pages + 1):
        q = query_tpl.format(limit=page, offset=offset)
        rows = sparql_query(q)
        if not rows:
            break
        added = _ingest_rows(g, rows, subj_key, pred_key, obj_key)
        total += added
        offset += page
        print(f"    {label} page {page_n}: +{added:,}  (KB={len(g):,})")
        if len(rows) < page:
            break                # last page
        time.sleep(1.5)
    return total

# ── Phase 2 – Domain-wide F1 expansion ────────────────────────────────────────
def phase2_f1_drivers(g: Graph) -> int:
    """All drivers who participated in Formula One (wdt:P641 wd:Q1968)."""
    tpl = """
SELECT ?drv ?p ?o WHERE {{
  ?drv wdt:P641 wd:Q1968 .
  ?drv ?p ?o .
  FILTER(!isLiteral(?o) || lang(?o) = "" || lang(?o) = "en")
}}
LIMIT {{limit}} OFFSET {{offset}}
"""
    return _paginated(g, tpl, "drv", "p", "o", page=5000, max_pages=8,
                      label="F1-drivers")

def phase2_f1_constructors(g: Graph) -> int:
    """All Formula One constructors (wdt:P31 wd:Q161764)."""
    tpl = """
SELECT ?team ?p ?o WHERE {{
  ?team wdt:P31 wd:Q161764 .
  ?team ?p ?o .
  FILTER(!isLiteral(?o) || lang(?o) = "" || lang(?o) = "en")
}}
LIMIT {{limit}} OFFSET {{offset}}
"""
    return _paginated(g, tpl, "team", "p", "o", page=5000, max_pages=4,
                      label="F1-constructors")

def phase2_f1_seasons(g: Graph) -> int:
    """All Formula One seasons (wdt:P31 wd:Q22979761)."""
    tpl = """
SELECT ?season ?p ?o WHERE {{
  ?season wdt:P31 wd:Q22979761 .
  ?season ?p ?o .
  FILTER(!isLiteral(?o) || lang(?o) = "" || lang(?o) = "en")
}}
LIMIT {{limit}} OFFSET {{offset}}
"""
    return _paginated(g, tpl, "season", "p", "o", page=5000, max_pages=4,
                      label="F1-seasons")

def phase2_f1_grands_prix(g: Graph) -> int:
    """All Formula One Grand Prix events (wdt:P31 wd:Q10853037)."""
    tpl = """
SELECT ?gp ?p ?o WHERE {{
  ?gp wdt:P31 wd:Q10853037 .
  ?gp ?p ?o .
  FILTER(!isLiteral(?o) || lang(?o) = "" || lang(?o) = "en")
}}
LIMIT {{limit}} OFFSET {{offset}}
"""
    return _paginated(g, tpl, "gp", "p", "o", page=5000, max_pages=8,
                      label="F1-grands-prix")

def phase2_f1_circuits(g: Graph) -> int:
    """Circuits that have hosted a Formula One race."""
    tpl = """
SELECT DISTINCT ?circuit ?p ?o WHERE {{
  ?race wdt:P31 wd:Q10853037 .
  ?race wdt:P276 ?circuit .
  ?circuit ?p ?o .
  FILTER(!isLiteral(?o) || lang(?o) = "" || lang(?o) = "en")
}}
LIMIT {{limit}} OFFSET {{offset}}
"""
    return _paginated(g, tpl, "circuit", "p", "o", page=5000, max_pages=4,
                      label="F1-circuits")

# ── Phase 3 – 2-hop predicate-controlled ──────────────────────────────────────
def phase3_countries(g: Graph) -> int:
    """Countries of citizenship of F1 drivers — 2-hop via wdt:P27."""
    tpl = """
SELECT DISTINCT ?country ?p ?o WHERE {{
  ?driver wdt:P641 wd:Q1968 .
  ?driver wdt:P27  ?country .
  ?country ?p ?o .
  FILTER(!isLiteral(?o) || lang(?o) = "" || lang(?o) = "en")
}}
LIMIT {{limit}} OFFSET {{offset}}
"""
    return _paginated(g, tpl, "country", "p", "o", page=5000, max_pages=2,
                      label="countries")

def phase3_awards(g: Graph) -> int:
    """Awards received by F1 drivers — 2-hop via wdt:P166."""
    tpl = """
SELECT DISTINCT ?award ?p ?o WHERE {{
  ?driver wdt:P641 wd:Q1968 .
  ?driver wdt:P166 ?award .
  ?award  ?p ?o .
  FILTER(!isLiteral(?o) || lang(?o) = "" || lang(?o) = "en")
}}
LIMIT {{limit}} OFFSET {{offset}}
"""
    return _paginated(g, tpl, "award", "p", "o", page=5000, max_pages=2,
                      label="awards")

# ── Stats ──────────────────────────────────────────────────────────────────────
def write_stats(g: Graph, path: Path) -> None:
    subjects   = set(str(s) for s, _, _ in g if isinstance(s, URIRef))
    predicates = set(str(p) for _, p, _ in g)

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
        "## Expansion strategy",
        "",
        "- **Phase 1** – 1-hop on all confidently aligned entities "
        "(alignment_drivers.tsv + alignment_teams.tsv, confidence ≥ 0.8)",
        "- **Phase 2** – Domain-wide pull from Wikidata:",
        "  - All F1 drivers (`wdt:P641 wd:Q1968`)",
        "  - All F1 constructors (`wdt:P31 wd:Q161764`)",
        "  - All F1 seasons (`wdt:P31 wd:Q22979761`)",
        "  - All F1 Grand Prix events (`wdt:P31 wd:Q10853037`)",
        "  - All circuits that hosted an F1 race",
        "- **Phase 3** – 2-hop predicate-controlled:",
        "  - Countries of citizenship of F1 drivers",
        "  - Awards received by F1 drivers",
        "",
        "## Cleaning",
        "",
        "- Excluded predicates: images, coordinates, websites, Commons "
        "categories, wikibase meta-properties, schema.org descriptions, "
        "SKOS labels",
        "- Only English-language or language-neutral literals kept",
        "- rdflib Graph deduplication (set semantics)",
        "",
        "## Source files",
        "",
        "| File | Description |",
        "|---|---|",
        "| `auto_kg.ttl` | Private KB (Formula1.com) + ontology + alignments |",
        "| `expanded_kb.ttl` | This expanded KB |",
        "| `alignment_drivers.tsv` | Driver alignment to Wikidata |",
        "| `alignment_teams.tsv` | Team alignment to Wikidata |",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nStats written → {path}")

# ── Main ───────────────────────────────────────────────────────────────────────
def main() -> None:
    print("=" * 60)
    print("KB EXPANSION — Wikidata SPARQL")
    print("=" * 60)

    # ── Load initial KB ────────────────────────────────────────────
    print("\n[0] Loading initial KB …")
    g = Graph()
    g.parse(KG_FILE, format="turtle")
    g.bind("ex", EX)
    g.bind("wd", WD)
    g.bind("wdt", WDT)
    print(f"    Initial KB: {len(g):,} triples")

    # ── Load aligned Wikidata IDs ──────────────────────────────────
    print("\n[1] Loading aligned entity IDs …")
    driver_ids = load_aligned_ids(DRIVERS_TSV)
    team_ids   = load_aligned_ids(TEAMS_TSV)
    all_ids    = list(dict.fromkeys(driver_ids + team_ids))   # dedup, preserve order
    print(f"    Drivers : {len(driver_ids)}  |  Teams : {len(team_ids)}"
          f"  |  Unique : {len(all_ids)}")

    # ── Phase 1 ────────────────────────────────────────────────────
    print(f"\n[Phase 1] 1-hop expansion on {len(all_ids)} aligned entities …")
    added1 = phase1_one_hop(g, all_ids)
    print(f"  → Phase 1 total: +{added1:,}  KB now {len(g):,} triples")

    # ── Phase 2 ────────────────────────────────────────────────────
    print("\n[Phase 2] Domain-wide F1 expansion …")

    print("  • F1 drivers …")
    added = phase2_f1_drivers(g)
    print(f"    → +{added:,}  KB={len(g):,}")
    time.sleep(2)

    print("  • F1 constructors …")
    added = phase2_f1_constructors(g)
    print(f"    → +{added:,}  KB={len(g):,}")
    time.sleep(2)

    print("  • F1 seasons …")
    added = phase2_f1_seasons(g)
    print(f"    → +{added:,}  KB={len(g):,}")
    time.sleep(2)

    print("  • F1 Grand Prix events …")
    added = phase2_f1_grands_prix(g)
    print(f"    → +{added:,}  KB={len(g):,}")
    time.sleep(2)

    print("  • F1 circuits …")
    added = phase2_f1_circuits(g)
    print(f"    → +{added:,}  KB={len(g):,}")
    time.sleep(2)

    # ── Phase 3 ────────────────────────────────────────────────────
    print("\n[Phase 3] Predicate-controlled 2-hop expansion …")

    print("  • Countries of citizenship …")
    added = phase3_countries(g)
    print(f"    → +{added:,}  KB={len(g):,}")
    time.sleep(2)

    print("  • Awards received …")
    added = phase3_awards(g)
    print(f"    → +{added:,}  KB={len(g):,}")
    time.sleep(2)

    # ── Save ───────────────────────────────────────────────────────
    print(f"\n[Save] Serialising to {OUTPUT_FILE} …")
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    g.serialize(destination=str(OUTPUT_FILE), format="turtle")
    print(f"  → Saved  ({len(g):,} triples)")

    write_stats(g, STATS_FILE)

    # ── Summary ───────────────────────────────────────────────────
    subjects   = set(str(s) for s, _, _ in g if isinstance(s, URIRef))
    predicates = set(str(p) for _, p, _ in g)
    print("\n" + "=" * 60)
    print("EXPANSION COMPLETE")
    print(f"  Triples    : {len(g):,}")
    print(f"  Entities   : {len(subjects):,}")
    print(f"  Predicates : {len(predicates):,}")

    target_low, target_high = 50_000, 200_000
    if len(g) < target_low:
        print(f"\n  [WARNING] {len(g):,} triples < target {target_low:,}.")
        print("  Consider running additional expansion phases.")
    elif len(g) > target_high:
        print(f"\n  [INFO] {len(g):,} triples > upper bound {target_high:,}.")
        print("  Consider pruning low-frequency predicates if KGE is slow.")
    else:
        print(f"\n  [OK] Volume is within target range "
              f"({target_low:,} – {target_high:,}).")
    print("=" * 60)


if __name__ == "__main__":
    main()
