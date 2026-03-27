"""
reason_family.py — SWRL reasoning on family.owl
================================================
Applies the SWRL rule:

    Person(?p) ∧ age(?p, ?a) ∧ swrlb:greaterThan(?a, 60) → OldPerson(?p)

Two execution paths:
  1. OWLReady2 + Pellet  (primary)   — native SWRL rule with sync_reasoner_pellet
  2. rdflib Python loop  (fallback)  — equivalent materialisation without Pellet

Usage
-----
    python src/reason/reason_family.py

Output
------
  Prints which individuals are inferred to be OldPerson and why.
  Does NOT modify family.owl.
"""

from pathlib import Path
from rdflib import Graph, Namespace, RDF, XSD

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
FAMILY_OWL   = PROJECT_ROOT / "data" / "family.owl"

FAM = Namespace("http://example.org/family#")

SWRL_RULE = (
    "Person(?p), age(?p, ?a), swrlb:greaterThan(?a, 60) -> OldPerson(?p)"
)


# ─────────────────────────────────────────────────────────────────────────────
# Path 1 — OWLReady2 + Pellet
# ─────────────────────────────────────────────────────────────────────────────

def run_owlready2(owl_path: Path) -> list[str] | None:
    """
    Load the ontology with OWLReady2, inject the SWRL rule, run Pellet,
    and return a list of individual names classified as OldPerson.
    Returns None if OWLReady2 / Pellet is unavailable.
    """
    try:
        from owlready2 import get_ontology, sync_reasoner_pellet, Imp
    except ImportError:
        print("  [OWLReady2] Not installed (pip install owlready2) — using rdflib fallback.")
        return None

    print(f"  [OWLReady2] Loading {owl_path.name} …")
    onto = get_ontology(owl_path.as_uri()).load()

    with onto:
        rule = Imp()
        rule.set_as_rule(SWRL_RULE)
        print(f"  [OWLReady2] Rule defined: {SWRL_RULE}")
        try:
            sync_reasoner_pellet(infer_property_values=True, infer_data_property_values=True)
            print("  [OWLReady2] Pellet reasoning complete.")
        except Exception as exc:
            print(f"  [OWLReady2] Pellet failed ({exc}) — using rdflib fallback.")
            return None

    OldPerson = onto.OldPerson
    if OldPerson is None:
        return []
    return [ind.name for ind in OldPerson.instances()]


# ─────────────────────────────────────────────────────────────────────────────
# Path 2 — rdflib Python-loop materialisation (always available)
# ─────────────────────────────────────────────────────────────────────────────

def run_rdflib(owl_path: Path) -> list[tuple[str, int]]:
    """
    Load the ontology with rdflib, apply the SWRL rule as a Python loop,
    and return a list of (name, age) pairs for newly classified OldPerson individuals.
    """
    print(f"  [rdflib] Loading {owl_path.name} …")
    g = Graph()
    g.parse(owl_path, format="turtle")
    print(f"  [rdflib] {len(g):,} triples loaded.")

    results = []
    for person in g.subjects(RDF.type, FAM.Person):
        ages = list(g.objects(person, FAM.age))
        if not ages:
            continue
        age_val = int(ages[0])
        if age_val > 60:
            name_vals = list(g.objects(person, FAM.name))
            label = str(name_vals[0]) if name_vals else str(person).split("#")[-1]
            # Only report if not already declared OldPerson in the ontology
            already = (person, RDF.type, FAM.OldPerson) in g
            results.append((label, age_val, already))

    return results


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("SWRL REASONING — family.owl")
    print("=" * 60)
    print(f"\nOntology : {FAMILY_OWL}")
    print(f"\nSWRL rule:\n  {SWRL_RULE}\n")
    print("Interpretation: any individual that is a Person AND has an age")
    print("strictly greater than 60 is inferred to belong to OldPerson.\n")

    if not FAMILY_OWL.exists():
        print(f"[ERROR] {FAMILY_OWL} not found.")
        return

    print("-" * 60)

    # Try OWLReady2 first
    owl2_result = run_owlready2(FAMILY_OWL)

    print("\n-- Results " + "-" * 49)

    if owl2_result is not None:
        print(f"\n[OWLReady2 + Pellet] Individuals inferred as OldPerson ({len(owl2_result)}):")
        for name in sorted(owl2_result):
            print(f"  [YES]  {name}")
    else:
        # Fallback: rdflib
        rdflib_result = run_rdflib(FAMILY_OWL)
        print(f"\n[rdflib fallback] Individuals satisfying age > 60 ({len(rdflib_result)}):")
        for name, age, pre_declared in sorted(rdflib_result):
            status = "(pre-declared)" if pre_declared else "(inferred by rule)"
            print(f"  [YES]  {name:10s}  age={age:3d}  {status}")

    # Always show the rdflib analysis for reporting
    print("\n-- Full individual inventory " + "-" * 32)

    g = Graph()
    g.parse(FAMILY_OWL, format="turtle")
    all_persons = list(g.subjects(RDF.type, FAM.Person))

    print(f"\n{'Individual':<12} {'Age':>5}  {'OldPerson?':<12}  {'Status'}")
    print("-" * 55)
    for person in sorted(all_persons, key=lambda p: str(p)):
        ages = list(g.objects(person, FAM.age))
        name_vals = list(g.objects(person, FAM.name))
        label = str(name_vals[0]) if name_vals else str(person).split("#")[-1]
        age_val = int(ages[0]) if ages else "?"
        is_old = isinstance(age_val, int) and age_val > 60
        marker = "[YES]" if is_old else " no "
        rule_note = " <- SWRL rule fires" if is_old else ""
        print(f"  {label:<12} {str(age_val):>5}  {marker:<12}{rule_note}")

    old_count = sum(1 for p in all_persons
                    if list(g.objects(p, FAM.age)) and int(list(g.objects(p, FAM.age))[0]) > 60)
    print(f"\n  -> {old_count} individual(s) classified as OldPerson out of {len(all_persons)}")
    print(f"  -> Rule threshold: age > 60  (Fiona age=60 is NOT classified)")

    print("\n" + "=" * 60)
    print("REASONING COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    main()
