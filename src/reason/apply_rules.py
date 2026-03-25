"""
apply_rules.py — SWRL-style materialisation for the F1 Knowledge Graph
=======================================================================
Applies 4 inference rules (documented in swrl_rules.md) to the expanded KB
and writes a new KB with all inferred triples materialised.

Input  : kg_artifacts/expanded_kb.ttl
Output : kg_artifacts/reasoned_kb.ttl

Rules
-----
1. Champion inference   : DriverStanding(pos=1) → isChampionOf(driver, season)
2. Teammate symmetry    : teammateOf(A,B)       → teammateOf(B,A)
3. Race win             : RaceResult(pos=1)     → hasWon(driver, gp)
4. Season via race      : participatedIn(d,gp) ∧ partOfSeason(gp,s) → competesInSeason(d,s)

Note: OWLReady2's Pellet integration is used when available; pure-rdflib
      materialisation is always applied as a portable fallback.
"""

from pathlib import Path
from rdflib import Graph, Namespace, URIRef, Literal
from rdflib.namespace import RDF, OWL, XSD

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
INPUT_FILE   = PROJECT_ROOT / "kg_artifacts" / "expanded_kb.ttl"
OUTPUT_FILE  = PROJECT_ROOT / "kg_artifacts" / "reasoned_kb.ttl"

EX = Namespace("http://example.org/f1#")


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def add_triple(g: Graph, s, p, o) -> bool:
    """Add a triple if not already present. Returns True if added."""
    if (s, p, o) not in g:
        g.add((s, p, o))
        return True
    return False


# ─────────────────────────────────────────────────────────────────────────────
# Rule 1 — Champion inference
# ─────────────────────────────────────────────────────────────────────────────

def rule_champion(g: Graph) -> int:
    """
    DriverStanding(?s) ∧ forDriver(?s,?d) ∧ forSeason(?s,?season)
    ∧ standingPosition(?s, 1)
    → isChampionOf(?d, ?season)
    """
    added = 0
    for standing in g.subjects(RDF.type, EX.DriverStanding):
        position_vals = list(g.objects(standing, EX.standingPosition))
        if not position_vals:
            continue
        try:
            pos = int(position_vals[0])
        except (ValueError, TypeError):
            continue
        if pos != 1:
            continue
        drivers = list(g.objects(standing, EX.forDriver))
        seasons = list(g.objects(standing, EX.forSeason))
        for driver in drivers:
            for season in seasons:
                if add_triple(g, driver, EX.isChampionOf, season):
                    added += 1
    return added


# ─────────────────────────────────────────────────────────────────────────────
# Rule 2 — Teammate symmetry
# ─────────────────────────────────────────────────────────────────────────────

def rule_teammate_symmetry(g: Graph) -> int:
    """
    teammateOf(?a, ?b) → teammateOf(?b, ?a)
    """
    added = 0
    pairs = list(g.subject_objects(EX.teammateOf))
    for a, b in pairs:
        if add_triple(g, b, EX.teammateOf, a):
            added += 1
    return added


# ─────────────────────────────────────────────────────────────────────────────
# Rule 3 — Race win materialisation
# ─────────────────────────────────────────────────────────────────────────────

def rule_race_win(g: Graph) -> int:
    """
    RaceResult(?r) ∧ forDriver(?r,?d) ∧ forGrandPrix(?r,?gp)
    ∧ finishPosition(?r, 1)
    → hasWon(?d, ?gp)
    """
    added = 0
    for result in g.subjects(RDF.type, EX.RaceResult):
        pos_vals = list(g.objects(result, EX.finishPosition))
        if not pos_vals:
            continue
        try:
            pos = int(pos_vals[0])
        except (ValueError, TypeError):
            continue
        if pos != 1:
            continue
        drivers = list(g.objects(result, EX.forDriver))
        gps     = list(g.objects(result, EX.forGrandPrix))
        for driver in drivers:
            for gp in gps:
                if add_triple(g, driver, EX.hasWon, gp):
                    added += 1
    return added


# ─────────────────────────────────────────────────────────────────────────────
# Rule 4 — Season membership via race participation
# ─────────────────────────────────────────────────────────────────────────────

def rule_season_via_race(g: Graph) -> int:
    """
    Driver(?d) ∧ participatedIn(?d, ?gp) ∧ GrandPrix(?gp)
    ∧ partOfSeason(?gp, ?season)
    → competesInSeason(?d, ?season)
    """
    added = 0
    for driver in g.subjects(RDF.type, EX.Driver):
        for gp in g.objects(driver, EX.participatedIn):
            if (gp, RDF.type, EX.GrandPrix) not in g:
                continue
            for season in g.objects(gp, EX.partOfSeason):
                if add_triple(g, driver, EX.competesInSeason, season):
                    added += 1
    return added


# ─────────────────────────────────────────────────────────────────────────────
# OWLReady2 integration (optional — graceful fallback if not installed)
# ─────────────────────────────────────────────────────────────────────────────

def run_owlready2_reasoner(ttl_path: Path) -> bool:
    """
    Attempt to run Pellet via OWLReady2. Returns True on success.
    This adds class/property inferences that pure rdflib rules cannot derive.
    """
    try:
        import owlready2 as owl2
        from owlready2 import get_ontology, sync_reasoner_pellet
    except ImportError:
        print("  [OWLReady2] Not installed — skipping OWL reasoning (pip install owlready2)")
        return False

    try:
        onto = get_ontology(ttl_path.as_uri()).load()
        with onto:
            sync_reasoner_pellet(infer_property_values=True, infer_data_property_values=True)
        print("  [OWLReady2] Pellet reasoning complete")
        return True
    except Exception as exc:
        print(f"  [OWLReady2] Pellet failed ({exc}) — continuing with rdflib rules only")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("SWRL MATERIALISATION — F1 Knowledge Graph")
    print("=" * 60)

    if not INPUT_FILE.exists():
        print(f"[ERROR] Input file not found: {INPUT_FILE}")
        print("  Run python src/kg/build_local_expansion.py first.")
        return

    # ── Load graph ────────────────────────────────────────────────────────────
    print(f"\n[0] Loading {INPUT_FILE.name} …")
    g = Graph()
    g.bind("ex", EX)
    g.parse(INPUT_FILE, format="turtle")
    triples_before = len(g)
    print(f"    Loaded: {triples_before:,} triples")

    # ── OWLReady2 pass (optional) ─────────────────────────────────────────────
    print("\n[1] OWLReady2 / Pellet pass …")
    run_owlready2_reasoner(INPUT_FILE)

    # ── rdflib materialisation rules ──────────────────────────────────────────
    print("\n[2] Applying SWRL-style materialisation rules …")

    n1 = rule_champion(g)
    print(f"    Rule 1 (Champion inference)    : +{n1:4d} triples")

    n2 = rule_teammate_symmetry(g)
    print(f"    Rule 2 (Teammate symmetry)     : +{n2:4d} triples")

    n3 = rule_race_win(g)
    print(f"    Rule 3 (Race win)              : +{n3:4d} triples")

    n4 = rule_season_via_race(g)
    print(f"    Rule 4 (Season via race)       : +{n4:4d} triples")

    total_inferred = n1 + n2 + n3 + n4
    triples_after  = len(g)

    print(f"\n    Total inferred triples         : +{total_inferred:,}")
    print(f"    KB size before                 : {triples_before:,}")
    print(f"    KB size after                  : {triples_after:,}")

    # ── Serialize ─────────────────────────────────────────────────────────────
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    g.serialize(destination=OUTPUT_FILE, format="turtle")
    print(f"\n[Save] Written to {OUTPUT_FILE}")

    # ── Validation queries ─────────────────────────────────────────────────────
    print("\n[3] Validation queries …")

    q_champions = g.query("""
        PREFIX ex: <http://example.org/f1#>
        SELECT ?driver ?season WHERE {
            ?driver ex:isChampionOf ?season .
        }
    """)
    champions = list(q_champions)
    print(f"    Champions (isChampionOf)       : {len(champions)} entries")
    for row in champions[:6]:
        d = str(row[0]).split("#")[-1]
        s = str(row[1]).split("#")[-1]
        print(f"      {d} → {s}")

    q_wins = g.query("""
        PREFIX ex: <http://example.org/f1#>
        SELECT ?driver (COUNT(?gp) AS ?wins) WHERE {
            ?driver ex:hasWon ?gp .
        }
        GROUP BY ?driver
        ORDER BY DESC(?wins)
        LIMIT 5
    """)
    wins_list = list(q_wins)
    if wins_list:
        print(f"\n    Top-5 race winners (hasWon):")
        for row in wins_list:
            d = str(row[0]).split("#")[-1]
            print(f"      {d}: {row[1]} wins")

    q_sym = g.query("""
        PREFIX ex: <http://example.org/f1#>
        SELECT (COUNT(*) AS ?cnt) WHERE {
            ?a ex:teammateOf ?b .
        }
    """)
    sym_count = int(list(q_sym)[0][0])
    print(f"\n    Symmetric teammateOf triples   : {sym_count}")

    print("\n" + "=" * 60)
    print("REASONING COMPLETE")
    print(f"  Input triples  : {triples_before:,}")
    print(f"  Inferred       : +{total_inferred:,}")
    print(f"  Output triples : {triples_after:,}")
    print(f"  Output file    : {OUTPUT_FILE}")
    print("=" * 60)


if __name__ == "__main__":
    main()
