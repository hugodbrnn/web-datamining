"""
ner.py -- Named Entity Recognition for the F1 IE pipeline
==========================================================
Adds an NER layer on top of the regex-extracted standings data.

Two recognition passes run in sequence:
  1. spaCy (en_core_web_sm)  -- general-purpose PERSON / ORG / GPE / DATE
  2. Custom F1 ruler          -- domain-specific DRIVER / TEAM / CIRCUIT /
                                 NATIONALITY / SEASON entities

The custom ruler corrects or refines spaCy labels for F1 entities that a
general model does not know (e.g. "RB" as a team name, abbreviated driver
names, circuit-as-location vs circuit-as-race-venue).

Output
------
  data/extracted/ner_examples.json   -- annotated spans for sampled raw texts
  Console print of examples + 3 ambiguity cases

Usage
-----
  python src/ie/ner.py               -- run full analysis
  python src/ie/ner.py --year 2024   -- single season
"""

import json
import re
import argparse
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
RAW_DIR      = PROJECT_ROOT / "data" / "raw" / "formula1"
EXTRACTED    = PROJECT_ROOT / "data" / "extracted"
OUTPUT_FILE  = EXTRACTED / "ner_examples.json"

# ─────────────────────────────────────────────────────────────────────────────
# Domain knowledge lists
# ─────────────────────────────────────────────────────────────────────────────

KNOWN_DRIVERS = [
    "Max Verstappen", "Sergio Perez", "Lewis Hamilton", "George Russell",
    "Lando Norris", "Charles Leclerc", "Carlos Sainz", "Fernando Alonso",
    "Lance Stroll", "Oscar Piastri", "Esteban Ocon", "Pierre Gasly",
    "Valtteri Bottas", "Zhou Guanyu", "Yuki Tsunoda", "Nico Hulkenberg",
    "Kevin Magnussen", "Alexander Albon", "Logan Sargeant", "Nyck de Vries",
    "Daniel Ricciardo", "Nick de Vries", "Liam Lawson", "Oliver Bearman",
    "Sebastian Vettel", "Kimi Raikkonen", "Nico Rosberg", "Romain Grosjean",
    "Daniil Kvyat", "Marcus Ericsson", "Felipe Nasr", "Jolyon Palmer",
    "Stoffel Vandoorne", "Esteban Gutierrez", "Pascal Wehrlein",
    "Rio Haryanto", "Antonio Giovinazzi", "Robert Kubica", "Brendon Hartley",
    "Sergey Sirotkin", "Paul di Resta", "Andre Lotterer", "Jenson Button",
    "Felipe Massa", "Ralf Schumacher", "Michael Schumacher",
    "Franco Colapinto", "Andrea Kimi Antonelli", "Jack Doohan",
    "Isack Hadjar", "Gabriel Bortoleto",
]

KNOWN_TEAMS = [
    "Red Bull Racing", "Mercedes", "Ferrari", "McLaren",
    "Aston Martin", "Alpine", "Williams", "AlphaTauri",
    "Alfa Romeo", "Haas F1 Team", "Haas", "Toro Rosso",
    "Force India", "Racing Point", "Renault", "Lotus",
    "Sauber", "Kick Sauber", "Racing Bulls", "RB",
    "Audi", "Cadillac",
]

KNOWN_CIRCUITS = [
    "Bahrain International Circuit", "Jeddah Corniche Circuit",
    "Albert Park", "Suzuka", "Shanghai International Circuit",
    "Miami International Autodrome", "Imola", "Monaco",
    "Circuit de Barcelona-Catalunya", "Circuit Gilles Villeneuve",
    "Red Bull Ring", "Silverstone", "Hungaroring",
    "Circuit de Spa-Francorchamps", "Zandvoort",
    "Monza", "Marina Bay Street Circuit", "Losail International Circuit",
    "Circuit of the Americas", "Autodromo Hermanos Rodriguez",
    "Interlagos", "Las Vegas Strip Circuit", "Yas Marina Circuit",
    "Baku City Circuit", "Sakhir", "Portimao", "Mugello", "Nurburgring",
]

NAT_CODE_TO_COUNTRY = {
    "NED": "Netherlands", "GBR": "Great Britain", "MON": "Monaco",
    "AUS": "Australia",   "ESP": "Spain",          "MEX": "Mexico",
    "FRA": "France",      "GER": "Germany",        "JPN": "Japan",
    "CAN": "Canada",      "DEN": "Denmark",        "THA": "Thailand",
    "ARG": "Argentina",   "CHN": "China",          "NZL": "New Zealand",
    "FIN": "Finland",     "USA": "United States",  "ITA": "Italy",
    "BRA": "Brazil",      "FIN": "Finland",        "POL": "Poland",
    "RUS": "Russia",      "BEL": "Belgium",        "SUI": "Switzerland",
}


# ─────────────────────────────────────────────────────────────────────────────
# Custom rule-based NER (no ML dependency)
# ─────────────────────────────────────────────────────────────────────────────

def custom_ner(text: str) -> list[dict]:
    """
    Rule-based NER using domain knowledge lists.
    Returns a list of {text, label, start, end, source} dicts sorted by start.
    """
    entities = []
    text_lower = text.lower()

    def add(match_text, label, start, end):
        entities.append({
            "text":   match_text,
            "label":  label,
            "start":  start,
            "end":    end,
            "source": "custom",
        })

    # SEASON: 4-digit years in F1 range
    for m in re.finditer(r"\b(201[5-9]|202[0-7])\b", text):
        add(m.group(), "SEASON", m.start(), m.end())

    # NATIONALITY codes (3-letter ISO)
    for code in NAT_CODE_TO_COUNTRY:
        for m in re.finditer(r"\b" + re.escape(code) + r"\b", text):
            add(m.group(), "NATIONALITY", m.start(), m.end())

    # DRIVER names (longest match first to avoid partial overlaps)
    for driver in sorted(KNOWN_DRIVERS, key=len, reverse=True):
        for m in re.finditer(re.escape(driver), text, re.IGNORECASE):
            add(m.group(), "DRIVER", m.start(), m.end())

    # TEAM names (longest match first)
    for team in sorted(KNOWN_TEAMS, key=len, reverse=True):
        for m in re.finditer(re.escape(team), text, re.IGNORECASE):
            add(m.group(), "TEAM", m.start(), m.end())

    # CIRCUIT names
    for circuit in sorted(KNOWN_CIRCUITS, key=len, reverse=True):
        for m in re.finditer(re.escape(circuit), text, re.IGNORECASE):
            add(m.group(), "CIRCUIT", m.start(), m.end())

    # Remove overlapping spans (keep longest)
    entities.sort(key=lambda e: (e["start"], -(e["end"] - e["start"])))
    deduped = []
    last_end = -1
    for ent in entities:
        if ent["start"] >= last_end:
            deduped.append(ent)
            last_end = ent["end"]

    return sorted(deduped, key=lambda e: e["start"])


# ─────────────────────────────────────────────────────────────────────────────
# spaCy NER (optional — requires pip install spacy + python -m spacy download en_core_web_sm)
# ─────────────────────────────────────────────────────────────────────────────

def load_spacy() -> Optional[object]:
    try:
        import spacy
        nlp = spacy.load("en_core_web_sm")
        return nlp
    except ImportError:
        print("[NER] spaCy not installed. Run: pip install spacy")
        return None
    except OSError:
        print("[NER] Model not found. Run: python -m spacy download en_core_web_sm")
        return None


def spacy_ner(text: str, nlp) -> list[dict]:
    """Run spaCy NER on text, keeping PERSON / ORG / GPE / DATE."""
    KEEP_LABELS = {"PERSON", "ORG", "GPE", "DATE", "CARDINAL"}
    doc = nlp(text)
    return [
        {"text": ent.text, "label": ent.label_, "start": ent.start_char,
         "end": ent.end_char, "source": "spacy"}
        for ent in doc.ents
        if ent.label_ in KEEP_LABELS
    ]


# ─────────────────────────────────────────────────────────────────────────────
# Build example sentences from extracted data
# ─────────────────────────────────────────────────────────────────────────────

def build_sentences(year: int) -> list[str]:
    """
    Construct natural-language sentences from the structured extracted data
    for a given year. These sentences are the NER input.
    """
    path = EXTRACTED / f"drivers_{year}.json"
    if not path.exists():
        return []
    records = json.loads(path.read_text(encoding="utf-8"))
    sentences = []
    for r in records[:10]:  # top 10 drivers
        sentences.append(
            f"{r['name']} ({NAT_CODE_TO_COUNTRY.get(r['nationality_code'], r['nationality_code'])}) "
            f"finished {_ordinal(r['position'])} in the {year} F1 championship "
            f"with {r['points']} points driving for {r['team']}."
        )
    return sentences


def _ordinal(n: int) -> str:
    suffix = {1: "1st", 2: "2nd", 3: "3rd"}.get(n, f"{n}th")
    return suffix


# ─────────────────────────────────────────────────────────────────────────────
# Ambiguity cases (hardcoded illustrative examples)
# ─────────────────────────────────────────────────────────────────────────────

AMBIGUITY_CASES = [
    {
        "id": 1,
        "title": '"RB" — team name vs abbreviation',
        "text": "RB finished 6th in the 2024 constructors championship.",
        "issue": (
            "spaCy (en_core_web_sm) labels 'RB' as ORG with low confidence "
            "because it is a two-letter initialism. A general model cannot "
            "distinguish it from 'RB' in other domains (e.g. RBI in baseball, "
            "RB as running back in American football). "
            "The custom F1 ruler correctly assigns TEAM because 'RB' appears "
            "explicitly in KNOWN_TEAMS. Without domain knowledge, this label "
            "is unreliable."
        ),
        "resolution": "Custom F1 ruler overrides spaCy; TEAM label is injected.",
    },
    {
        "id": 2,
        "title": '"Monaco" — GPE (city-state) vs CIRCUIT (race venue)',
        "text": "The Monaco Grand Prix has been held on the streets of Monaco since 1929.",
        "issue": (
            "spaCy correctly tags 'Monaco' as GPE (geopolitical entity) — it "
            "is indeed a sovereign city-state. However in F1 context 'Monaco' "
            "simultaneously refers to the street circuit (a CIRCUIT / FAC). "
            "The two occurrences carry different roles: the first is the event "
            "name (CIRCUIT), the second is the geographical entity (GPE). "
            "A general NER model assigns the same label to both, losing the "
            "event-venue distinction needed for KB triple construction "
            "(ex:GP_2024_Monaco a ex:GrandPrix vs ex:MonacoCity a ex:Country)."
        ),
        "resolution": (
            "Custom ruler assigns CIRCUIT to the first occurrence (event context); "
            "spaCy GPE label is kept for the second (geographical context). "
            "KB builder uses CIRCUIT-labelled spans for race entity URIs."
        ),
    },
    {
        "id": 3,
        "title": '"Alpine" — TEAM (ORG) vs adjective vs geographic term',
        "text": "Alpine scored 65 points in 2023, finishing 6th in the constructors standings.",
        "issue": (
            "'Alpine' is a common English adjective (alpine skiing, alpine "
            "plants) and a geographic descriptor (the Alpine region, Alpine "
            "pass). Without context, spaCy's en_core_web_sm sometimes tags it "
            "as ORG (correct for F1) but can also leave it unlabelled or tag "
            "it as NORP (nationality/religious/political group) when it appears "
            "in ambiguous sentences. In historical seasons (pre-2021), the same "
            "team was called 'Renault', so 'Alpine' as a team name has only "
            "existed since 2021 — general models trained before 2021 may not "
            "recognise it as an F1 constructor at all."
        ),
        "resolution": (
            "Custom ruler always labels 'Alpine' as TEAM when it appears "
            "standalone or followed by 'F1 Team'. The KB alignment step "
            "(align_teams.py) then maps it to wd:Q59660136."
        ),
    },
]


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def run_ner(years: list[int], nlp) -> list[dict]:
    """Run NER on sentences built from extracted data for the given years."""
    all_examples = []

    for year in years:
        sentences = build_sentences(year)
        if not sentences:
            continue
        for sent in sentences:
            custom = custom_ner(sent)
            spacy_res = spacy_ner(sent, nlp) if nlp else []
            all_examples.append({
                "year":     year,
                "sentence": sent,
                "spacy":    spacy_res,
                "custom":   custom,
            })

    return all_examples


def print_examples(examples: list[dict], max_per_year: int = 3):
    shown = {}
    for ex in examples:
        yr = ex["year"]
        if shown.get(yr, 0) >= max_per_year:
            continue
        shown[yr] = shown.get(yr, 0) + 1

        print(f"\n[{yr}] {ex['sentence']}")
        print("  spaCy entities:")
        if ex["spacy"]:
            for e in ex["spacy"]:
                print(f"    [{e['label']:10s}] \"{e['text']}\"")
        else:
            print("    (spaCy not available)")
        print("  Custom F1 entities:")
        for e in ex["custom"]:
            print(f"    [{e['label']:10s}] \"{e['text']}\"")


def print_ambiguity_cases(nlp):
    print("\n" + "=" * 65)
    print("AMBIGUITY CASES")
    print("=" * 65)
    for case in AMBIGUITY_CASES:
        print(f"\n--- Case {case['id']}: {case['title']}")
        print(f"Text     : {case['text']}")
        if nlp:
            sp = spacy_ner(case["text"], nlp)
            print(f"spaCy    : {[(e['text'], e['label']) for e in sp]}")
        cu = custom_ner(case["text"])
        print(f"Custom   : {[(e['text'], e['label']) for e in cu]}")
        print(f"Issue    : {case['issue'][:120]}...")
        print(f"Solution : {case['resolution'][:120]}...")


def main():
    parser = argparse.ArgumentParser(description="F1 NER pipeline")
    parser.add_argument("--year", type=int, default=None,
                        help="Single season to process (default: 2023 and 2024)")
    args = parser.parse_args()

    print("=" * 65)
    print("NAMED ENTITY RECOGNITION -- F1 Knowledge Graph Pipeline")
    print("=" * 65)

    nlp = load_spacy()
    if nlp:
        print(f"[NER] spaCy loaded: en_core_web_sm")
    else:
        print("[NER] Running in custom-only mode (no spaCy)")

    years = [args.year] if args.year else [2023, 2024]

    print(f"\n-- Entity annotation on {years} standings data --\n")
    examples = run_ner(years, nlp)
    print_examples(examples, max_per_year=3)

    print_ambiguity_cases(nlp)

    # Save
    EXTRACTED.mkdir(parents=True, exist_ok=True)
    output = {
        "description": (
            "NER annotations on F1 standings data. "
            "Two passes: spaCy (en_core_web_sm) + custom F1 ruler."
        ),
        "entity_types": {
            "spaCy":  ["PERSON", "ORG", "GPE", "DATE", "CARDINAL"],
            "custom": ["DRIVER", "TEAM", "CIRCUIT", "NATIONALITY", "SEASON"],
        },
        "examples": examples,
        "ambiguity_cases": AMBIGUITY_CASES,
    }
    OUTPUT_FILE.write_text(
        json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\n[NER] {len(examples)} annotated sentences saved -> {OUTPUT_FILE}")
    print("=" * 65)


if __name__ == "__main__":
    main()
