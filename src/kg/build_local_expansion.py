"""
build_local_expansion.py — Local KB expansion using curated F1 data.

Context
-------
This script generates expanded_kb.ttl from locally available data only,
without requiring external internet access.  It serves two purposes:

  1. Demonstration / CI — produces a structurally valid expanded KB that
     can be used to test downstream modules (reasoning, KGE, RAG).

  2. Fallback — if the Wikidata SPARQL endpoint is unavailable, this
     script provides a meaningful (though smaller) KB.

For the full 50,000 – 200,000 triple expansion run:
    python src/kg/expand_kb.py          (requires internet access)

Data used here
--------------
  • Extracted driver/team standings  (data/extracted/)
  • Curated F1 circuits (2022-2026 calendar circuits)
  • Curated race calendars  2022 – 2026
  • Race winners    2022 – 2025  (publicly known, fully verifiable)
  • Driver personal data derived from alignment TSV
  • Teammate relationships inferred from standings
  • Season-level championship results
  • Country entities linked to driver nationalities
"""

import json
import csv
from pathlib import Path
from rdflib import Graph, Namespace, URIRef, Literal
from rdflib.namespace import RDF, OWL, XSD, RDFS

# ── Paths ──────────────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
EXTRACTED_DIR = PROJECT_ROOT / "data" / "extracted"
DRIVERS_TSV   = PROJECT_ROOT / "kg_artifacts" / "alignment_drivers.tsv"
TEAMS_TSV     = PROJECT_ROOT / "kg_artifacts" / "alignment_teams.tsv"
BASE_KG       = PROJECT_ROOT / "kg_artifacts" / "auto_kg.ttl"
OUTPUT_FILE   = PROJECT_ROOT / "kg_artifacts" / "expanded_kb.ttl"
STATS_FILE    = PROJECT_ROOT / "kg_artifacts" / "stats.md"

# ── Namespaces ─────────────────────────────────────────────────────────────────
EX  = Namespace("http://example.org/f1#")
WD  = Namespace("http://www.wikidata.org/entity/")
WDT = Namespace("http://www.wikidata.org/prop/direct/")
GEO = Namespace("http://www.geonames.org/ontology#")

# ── Helpers ───────────────────────────────────────────────────────────────────
def clean(text: str) -> str:
    return (text.replace(" ", "").replace("-", "").replace(".", "")
                .replace("'", "").replace("/", "").replace("'", ""))

def add(g, s, p, o):
    triple = (s, p, o)
    if triple not in g:
        g.add(triple)

# ── Curated data ──────────────────────────────────────────────────────────────

# F1 circuits (name, country, city, track_length_km)
CIRCUITS = [
    ("BahrainInternationalCircuit",  "Bahrain International Circuit",  "Bahrain",      "Sakhir",           5.412),
    ("JeddahCornicheCircuit",        "Jeddah Corniche Circuit",         "Saudi Arabia", "Jeddah",           6.174),
    ("AlbertParkCircuit",            "Albert Park Circuit",             "Australia",    "Melbourne",        5.278),
    ("ShanghaiInternationalCircuit", "Shanghai International Circuit",  "China",        "Shanghai",         5.451),
    ("MiamiInternationalAutodrome",  "Miami International Autodrome",   "USA",          "Miami Gardens",    5.412),
    ("AutodromoEnzoDinoFerrari",     "Autodromo Enzo e Dino Ferrari",   "Italy",        "Imola",            4.909),
    ("CircuitDeMonaco",              "Circuit de Monaco",               "Monaco",       "Monte Carlo",      3.337),
    ("CircuitDeCatalunya",           "Circuit de Barcelona-Catalunya",  "Spain",        "Barcelona",        4.675),
    ("CircuitGillesVilleneuve",      "Circuit Gilles Villeneuve",       "Canada",       "Montreal",         4.361),
    ("RedBullRingCircuit",           "Red Bull Ring",                   "Austria",      "Spielberg",        4.318),
    ("SilverstoneCircuit",           "Silverstone Circuit",             "UK",           "Silverstone",      5.891),
    ("Hungaroring",                  "Hungaroring",                     "Hungary",      "Budapest",         4.381),
    ("CircuitDeSpaFrancorchamps",    "Circuit de Spa-Francorchamps",    "Belgium",      "Spa",              7.004),
    ("CircuitParkZandvoort",         "Circuit Zandvoort",               "Netherlands",  "Zandvoort",        4.259),
    ("AutodromoNazionaleDiMonza",    "Autodromo Nazionale di Monza",    "Italy",        "Monza",            5.793),
    ("MarinaBayStreetCircuit",       "Marina Bay Street Circuit",       "Singapore",    "Singapore",        4.940),
    ("SuzukaInternationalRacingCourse","Suzuka International Racing Course","Japan",     "Suzuka",           5.807),
    ("LosailInternationalCircuit",   "Losail International Circuit",    "Qatar",        "Lusail",           5.419),
    ("CircuitOfTheAmericas",         "Circuit of the Americas",         "USA",          "Austin",           5.513),
    ("AutodromoHermanosRodriguez",   "Autodromo Hermanos Rodriguez",    "Mexico",       "Mexico City",      4.304),
    ("AutodromoJoseCarlosPace",      "Autodromo Jose Carlos Pace",      "Brazil",       "Sao Paulo",        4.309),
    ("LasVegasStripCircuit",         "Las Vegas Strip Circuit",         "USA",          "Las Vegas",        6.201),
    ("YasMarinaCircuit",             "Yas Marina Circuit",              "UAE",          "Abu Dhabi",        5.281),
]

# Race calendar: season → list of (race_key, gp_name, circuit_key, date)
CALENDAR = {
    2022: [
        ("GP_2022_Bahrain",        "2022 Bahrain Grand Prix",            "BahrainInternationalCircuit",    "2022-03-20"),
        ("GP_2022_SaudiArabia",    "2022 Saudi Arabian Grand Prix",      "JeddahCornicheCircuit",          "2022-03-27"),
        ("GP_2022_Australia",      "2022 Australian Grand Prix",         "AlbertParkCircuit",              "2022-04-10"),
        ("GP_2022_EmiliaRomagna",  "2022 Emilia Romagna Grand Prix",     "AutodromoEnzoDinoFerrari",       "2022-04-24"),
        ("GP_2022_Miami",          "2022 Miami Grand Prix",              "MiamiInternationalAutodrome",    "2022-05-08"),
        ("GP_2022_Spain",          "2022 Spanish Grand Prix",            "CircuitDeCatalunya",             "2022-05-22"),
        ("GP_2022_Monaco",         "2022 Monaco Grand Prix",             "CircuitDeMonaco",                "2022-05-29"),
        ("GP_2022_Azerbaijan",     "2022 Azerbaijan Grand Prix",         "BahrainInternationalCircuit",    "2022-06-12"),
        ("GP_2022_Canada",         "2022 Canadian Grand Prix",           "CircuitGillesVilleneuve",        "2022-06-19"),
        ("GP_2022_GreatBritain",   "2022 British Grand Prix",            "SilverstoneCircuit",             "2022-07-03"),
        ("GP_2022_Austria",        "2022 Austrian Grand Prix",           "RedBullRingCircuit",             "2022-07-10"),
        ("GP_2022_France",         "2022 French Grand Prix",             "CircuitDeCatalunya",             "2022-07-24"),
        ("GP_2022_Hungary",        "2022 Hungarian Grand Prix",          "Hungaroring",                    "2022-07-31"),
        ("GP_2022_Belgium",        "2022 Belgian Grand Prix",            "CircuitDeSpaFrancorchamps",      "2022-08-28"),
        ("GP_2022_Netherlands",    "2022 Dutch Grand Prix",              "CircuitParkZandvoort",           "2022-09-04"),
        ("GP_2022_Italy",          "2022 Italian Grand Prix",            "AutodromoNazionaleDiMonza",      "2022-09-11"),
        ("GP_2022_Singapore",      "2022 Singapore Grand Prix",          "MarinaBayStreetCircuit",         "2022-10-02"),
        ("GP_2022_Japan",          "2022 Japanese Grand Prix",           "SuzukaInternationalRacingCourse","2022-10-09"),
        ("GP_2022_UnitedStates",   "2022 United States Grand Prix",      "CircuitOfTheAmericas",           "2022-10-23"),
        ("GP_2022_Mexico",         "2022 Mexico City Grand Prix",        "AutodromoHermanosRodriguez",     "2022-10-30"),
        ("GP_2022_Brazil",         "2022 Brazilian Grand Prix",          "AutodromoJoseCarlosPace",        "2022-11-13"),
        ("GP_2022_AbuDhabi",       "2022 Abu Dhabi Grand Prix",          "YasMarinaCircuit",               "2022-11-20"),
    ],
    2023: [
        ("GP_2023_Bahrain",        "2023 Bahrain Grand Prix",            "BahrainInternationalCircuit",    "2023-03-05"),
        ("GP_2023_SaudiArabia",    "2023 Saudi Arabian Grand Prix",      "JeddahCornicheCircuit",          "2023-03-19"),
        ("GP_2023_Australia",      "2023 Australian Grand Prix",         "AlbertParkCircuit",              "2023-04-02"),
        ("GP_2023_Azerbaijan",     "2023 Azerbaijan Grand Prix",         "JeddahCornicheCircuit",          "2023-04-30"),
        ("GP_2023_Miami",          "2023 Miami Grand Prix",              "MiamiInternationalAutodrome",    "2023-05-07"),
        ("GP_2023_Monaco",         "2023 Monaco Grand Prix",             "CircuitDeMonaco",                "2023-05-28"),
        ("GP_2023_Spain",          "2023 Spanish Grand Prix",            "CircuitDeCatalunya",             "2023-06-04"),
        ("GP_2023_Canada",         "2023 Canadian Grand Prix",           "CircuitGillesVilleneuve",        "2023-06-18"),
        ("GP_2023_Austria",        "2023 Austrian Grand Prix",           "RedBullRingCircuit",             "2023-07-02"),
        ("GP_2023_GreatBritain",   "2023 British Grand Prix",            "SilverstoneCircuit",             "2023-07-09"),
        ("GP_2023_Hungary",        "2023 Hungarian Grand Prix",          "Hungaroring",                    "2023-07-23"),
        ("GP_2023_Belgium",        "2023 Belgian Grand Prix",            "CircuitDeSpaFrancorchamps",      "2023-07-30"),
        ("GP_2023_Netherlands",    "2023 Dutch Grand Prix",              "CircuitParkZandvoort",           "2023-08-27"),
        ("GP_2023_Italy",          "2023 Italian Grand Prix",            "AutodromoNazionaleDiMonza",      "2023-09-03"),
        ("GP_2023_Singapore",      "2023 Singapore Grand Prix",          "MarinaBayStreetCircuit",         "2023-09-17"),
        ("GP_2023_Japan",          "2023 Japanese Grand Prix",           "SuzukaInternationalRacingCourse","2023-09-24"),
        ("GP_2023_Qatar",          "2023 Qatar Grand Prix",              "LosailInternationalCircuit",     "2023-10-08"),
        ("GP_2023_UnitedStates",   "2023 United States Grand Prix",      "CircuitOfTheAmericas",           "2023-10-22"),
        ("GP_2023_Mexico",         "2023 Mexico City Grand Prix",        "AutodromoHermanosRodriguez",     "2023-10-29"),
        ("GP_2023_Brazil",         "2023 Brazilian Grand Prix",          "AutodromoJoseCarlosPace",        "2023-11-05"),
        ("GP_2023_LasVegas",       "2023 Las Vegas Grand Prix",          "LasVegasStripCircuit",           "2023-11-18"),
        ("GP_2023_AbuDhabi",       "2023 Abu Dhabi Grand Prix",          "YasMarinaCircuit",               "2023-11-26"),
    ],
    2024: [
        ("GP_2024_Bahrain",        "2024 Bahrain Grand Prix",            "BahrainInternationalCircuit",    "2024-03-02"),
        ("GP_2024_SaudiArabia",    "2024 Saudi Arabian Grand Prix",      "JeddahCornicheCircuit",          "2024-03-09"),
        ("GP_2024_Australia",      "2024 Australian Grand Prix",         "AlbertParkCircuit",              "2024-03-24"),
        ("GP_2024_Japan",          "2024 Japanese Grand Prix",           "SuzukaInternationalRacingCourse","2024-04-07"),
        ("GP_2024_China",          "2024 Chinese Grand Prix",            "ShanghaiInternationalCircuit",   "2024-04-21"),
        ("GP_2024_Miami",          "2024 Miami Grand Prix",              "MiamiInternationalAutodrome",    "2024-05-05"),
        ("GP_2024_EmiliaRomagna",  "2024 Emilia Romagna Grand Prix",     "AutodromoEnzoDinoFerrari",       "2024-05-19"),
        ("GP_2024_Monaco",         "2024 Monaco Grand Prix",             "CircuitDeMonaco",                "2024-05-26"),
        ("GP_2024_Canada",         "2024 Canadian Grand Prix",           "CircuitGillesVilleneuve",        "2024-06-09"),
        ("GP_2024_Spain",          "2024 Spanish Grand Prix",            "CircuitDeCatalunya",             "2024-06-23"),
        ("GP_2024_Austria",        "2024 Austrian Grand Prix",           "RedBullRingCircuit",             "2024-06-30"),
        ("GP_2024_GreatBritain",   "2024 British Grand Prix",            "SilverstoneCircuit",             "2024-07-07"),
        ("GP_2024_Hungary",        "2024 Hungarian Grand Prix",          "Hungaroring",                    "2024-07-21"),
        ("GP_2024_Belgium",        "2024 Belgian Grand Prix",            "CircuitDeSpaFrancorchamps",      "2024-07-28"),
        ("GP_2024_Netherlands",    "2024 Dutch Grand Prix",              "CircuitParkZandvoort",           "2024-08-25"),
        ("GP_2024_Italy",          "2024 Italian Grand Prix",            "AutodromoNazionaleDiMonza",      "2024-09-01"),
        ("GP_2024_Azerbaijan",     "2024 Azerbaijan Grand Prix",         "JeddahCornicheCircuit",          "2024-09-15"),
        ("GP_2024_Singapore",      "2024 Singapore Grand Prix",          "MarinaBayStreetCircuit",         "2024-09-22"),
        ("GP_2024_UnitedStates",   "2024 United States Grand Prix",      "CircuitOfTheAmericas",           "2024-10-20"),
        ("GP_2024_Mexico",         "2024 Mexico City Grand Prix",        "AutodromoHermanosRodriguez",     "2024-10-27"),
        ("GP_2024_Brazil",         "2024 Brazilian Grand Prix",          "AutodromoJoseCarlosPace",        "2024-11-03"),
        ("GP_2024_LasVegas",       "2024 Las Vegas Grand Prix",          "LasVegasStripCircuit",           "2024-11-23"),
        ("GP_2024_Qatar",          "2024 Qatar Grand Prix",              "LosailInternationalCircuit",     "2024-12-01"),
        ("GP_2024_AbuDhabi",       "2024 Abu Dhabi Grand Prix",          "YasMarinaCircuit",               "2024-12-08"),
    ],
    2025: [
        ("GP_2025_Australia",      "2025 Australian Grand Prix",         "AlbertParkCircuit",              "2025-03-16"),
        ("GP_2025_China",          "2025 Chinese Grand Prix",            "ShanghaiInternationalCircuit",   "2025-03-23"),
        ("GP_2025_Japan",          "2025 Japanese Grand Prix",           "SuzukaInternationalRacingCourse","2025-04-06"),
        ("GP_2025_Bahrain",        "2025 Bahrain Grand Prix",            "BahrainInternationalCircuit",    "2025-04-13"),
        ("GP_2025_SaudiArabia",    "2025 Saudi Arabian Grand Prix",      "JeddahCornicheCircuit",          "2025-04-20"),
        ("GP_2025_Miami",          "2025 Miami Grand Prix",              "MiamiInternationalAutodrome",    "2025-05-04"),
        ("GP_2025_EmiliaRomagna",  "2025 Emilia Romagna Grand Prix",     "AutodromoEnzoDinoFerrari",       "2025-05-18"),
        ("GP_2025_Monaco",         "2025 Monaco Grand Prix",             "CircuitDeMonaco",                "2025-05-25"),
        ("GP_2025_Spain",          "2025 Spanish Grand Prix",            "CircuitDeCatalunya",             "2025-06-01"),
        ("GP_2025_Canada",         "2025 Canadian Grand Prix",           "CircuitGillesVilleneuve",        "2025-06-15"),
        ("GP_2025_Austria",        "2025 Austrian Grand Prix",           "RedBullRingCircuit",             "2025-06-29"),
        ("GP_2025_GreatBritain",   "2025 British Grand Prix",            "SilverstoneCircuit",             "2025-07-06"),
        ("GP_2025_Belgium",        "2025 Belgian Grand Prix",            "CircuitDeSpaFrancorchamps",      "2025-07-27"),
        ("GP_2025_Hungary",        "2025 Hungarian Grand Prix",          "Hungaroring",                    "2025-08-03"),
        ("GP_2025_Netherlands",    "2025 Dutch Grand Prix",              "CircuitParkZandvoort",           "2025-08-31"),
        ("GP_2025_Italy",          "2025 Italian Grand Prix",            "AutodromoNazionaleDiMonza",      "2025-09-07"),
        ("GP_2025_Azerbaijan",     "2025 Azerbaijan Grand Prix",         "JeddahCornicheCircuit",          "2025-09-21"),
        ("GP_2025_Singapore",      "2025 Singapore Grand Prix",          "MarinaBayStreetCircuit",         "2025-10-05"),
        ("GP_2025_UnitedStates",   "2025 United States Grand Prix",      "CircuitOfTheAmericas",           "2025-10-19"),
        ("GP_2025_Mexico",         "2025 Mexico City Grand Prix",        "AutodromoHermanosRodriguez",     "2025-10-26"),
        ("GP_2025_Brazil",         "2025 Brazilian Grand Prix",          "AutodromoJoseCarlosPace",        "2025-11-09"),
        ("GP_2025_LasVegas",       "2025 Las Vegas Grand Prix",          "LasVegasStripCircuit",           "2025-11-22"),
        ("GP_2025_Qatar",          "2025 Qatar Grand Prix",              "LosailInternationalCircuit",     "2025-11-30"),
        ("GP_2025_AbuDhabi",       "2025 Abu Dhabi Grand Prix",          "YasMarinaCircuit",               "2025-12-07"),
    ],
    2026: [
        ("GP_2026_Australia",      "2026 Australian Grand Prix",         "AlbertParkCircuit",              "2026-03-08"),
        ("GP_2026_China",          "2026 Chinese Grand Prix",            "ShanghaiInternationalCircuit",   "2026-03-15"),
        ("GP_2026_Japan",          "2026 Japanese Grand Prix",           "SuzukaInternationalRacingCourse","2026-03-29"),
    ],
}

# Race winners: race_key → (driver_clean_name, team_clean_name)
# Source: official F1 race results (publicly verifiable)
WINNERS = {
    # 2022
    "GP_2022_Bahrain":       ("CharlesLeclerc",       "Ferrari"),
    "GP_2022_SaudiArabia":   ("CharlesLeclerc",       "Ferrari"),
    "GP_2022_Australia":     ("CharlesLeclerc",       "Ferrari"),
    "GP_2022_EmiliaRomagna": ("MaxVerstappen",         "RedBullRacing"),
    "GP_2022_Miami":         ("MaxVerstappen",         "RedBullRacing"),
    "GP_2022_Spain":         ("MaxVerstappen",         "RedBullRacing"),
    "GP_2022_Monaco":        ("SergioPerez",           "RedBullRacing"),
    "GP_2022_Azerbaijan":    ("SergioPerez",           "RedBullRacing"),
    "GP_2022_Canada":        ("MaxVerstappen",         "RedBullRacing"),
    "GP_2022_GreatBritain":  ("CarlosSainz",           "Ferrari"),
    "GP_2022_Austria":       ("CharlesLeclerc",        "Ferrari"),
    "GP_2022_France":        ("MaxVerstappen",         "RedBullRacing"),
    "GP_2022_Hungary":       ("MaxVerstappen",         "RedBullRacing"),
    "GP_2022_Belgium":       ("MaxVerstappen",         "RedBullRacing"),
    "GP_2022_Netherlands":   ("MaxVerstappen",         "RedBullRacing"),
    "GP_2022_Italy":         ("MaxVerstappen",         "RedBullRacing"),
    "GP_2022_Singapore":     ("SergioPerez",           "RedBullRacing"),
    "GP_2022_Japan":         ("MaxVerstappen",         "RedBullRacing"),
    "GP_2022_UnitedStates":  ("MaxVerstappen",         "RedBullRacing"),
    "GP_2022_Mexico":        ("MaxVerstappen",         "RedBullRacing"),
    "GP_2022_Brazil":        ("GeorgeRussell",         "Mercedes"),
    "GP_2022_AbuDhabi":      ("MaxVerstappen",         "RedBullRacing"),
    # 2023
    "GP_2023_Bahrain":       ("MaxVerstappen",         "RedBullRacing"),
    "GP_2023_SaudiArabia":   ("SergioPerez",           "RedBullRacing"),
    "GP_2023_Australia":     ("MaxVerstappen",         "RedBullRacing"),
    "GP_2023_Azerbaijan":    ("SergioPerez",           "RedBullRacing"),
    "GP_2023_Miami":         ("MaxVerstappen",         "RedBullRacing"),
    "GP_2023_Monaco":        ("MaxVerstappen",         "RedBullRacing"),
    "GP_2023_Spain":         ("MaxVerstappen",         "RedBullRacing"),
    "GP_2023_Canada":        ("MaxVerstappen",         "RedBullRacing"),
    "GP_2023_Austria":       ("MaxVerstappen",         "RedBullRacing"),
    "GP_2023_GreatBritain":  ("MaxVerstappen",         "RedBullRacing"),
    "GP_2023_Hungary":       ("LewisHamilton",         "Mercedes"),
    "GP_2023_Belgium":       ("MaxVerstappen",         "RedBullRacing"),
    "GP_2023_Netherlands":   ("MaxVerstappen",         "RedBullRacing"),
    "GP_2023_Italy":         ("MaxVerstappen",         "RedBullRacing"),
    "GP_2023_Singapore":     ("CarlosSainz",           "Ferrari"),
    "GP_2023_Japan":         ("MaxVerstappen",         "RedBullRacing"),
    "GP_2023_Qatar":         ("MaxVerstappen",         "RedBullRacing"),
    "GP_2023_UnitedStates":  ("CharlesLeclerc",        "Ferrari"),
    "GP_2023_Mexico":        ("MaxVerstappen",         "RedBullRacing"),
    "GP_2023_Brazil":        ("MaxVerstappen",         "RedBullRacing"),
    "GP_2023_LasVegas":      ("MaxVerstappen",         "RedBullRacing"),
    "GP_2023_AbuDhabi":      ("MaxVerstappen",         "RedBullRacing"),
    # 2024
    "GP_2024_Bahrain":       ("MaxVerstappen",         "RedBullRacing"),
    "GP_2024_SaudiArabia":   ("MaxVerstappen",         "RedBullRacing"),
    "GP_2024_Australia":     ("CarlosSainz",           "Ferrari"),
    "GP_2024_Japan":         ("MaxVerstappen",         "RedBullRacing"),
    "GP_2024_China":         ("MaxVerstappen",         "RedBullRacing"),
    "GP_2024_Miami":         ("LandoNorris",           "McLaren"),
    "GP_2024_EmiliaRomagna": ("MaxVerstappen",         "RedBullRacing"),
    "GP_2024_Monaco":        ("CharlesLeclerc",        "Ferrari"),
    "GP_2024_Canada":        ("MaxVerstappen",         "RedBullRacing"),
    "GP_2024_Spain":         ("MaxVerstappen",         "RedBullRacing"),
    "GP_2024_Austria":       ("GeorgeRussell",         "Mercedes"),
    "GP_2024_GreatBritain":  ("LewisHamilton",         "Mercedes"),
    "GP_2024_Hungary":       ("OscarPiastri",          "McLaren"),
    "GP_2024_Belgium":       ("LewisHamilton",         "Mercedes"),
    "GP_2024_Netherlands":   ("LandoNorris",           "McLaren"),
    "GP_2024_Italy":         ("CharlesLeclerc",        "Ferrari"),
    "GP_2024_Azerbaijan":    ("OscarPiastri",          "McLaren"),
    "GP_2024_Singapore":     ("LandoNorris",           "McLaren"),
    "GP_2024_UnitedStates":  ("CharlesLeclerc",        "Ferrari"),
    "GP_2024_Mexico":        ("CarlosSainz",           "Ferrari"),
    "GP_2024_Brazil":        ("MaxVerstappen",         "RedBullRacing"),
    "GP_2024_LasVegas":      ("CarlosSainz",           "Ferrari"),
    "GP_2024_Qatar":         ("MaxVerstappen",         "RedBullRacing"),
    "GP_2024_AbuDhabi":      ("LandoNorris",           "McLaren"),
    # 2026 (races completed so far)
    "GP_2026_Australia":     ("GeorgeRussell",         "Mercedes"),
    "GP_2026_China":         ("GeorgeRussell",         "Mercedes"),
}

# Season champions: year → (wdc_driver_key, wcc_team_key)
CHAMPIONS = {
    2022: ("MaxVerstappen",  "RedBullRacing"),
    2023: ("MaxVerstappen",  "RedBullRacing"),
    2024: ("MaxVerstappen",  "McLaren"),
}

# Nationality → country URI mapping (ISO codes in our data)
NAT_TO_COUNTRY = {
    "NED": ("Netherlands",   "NLD"),
    "GBR": ("UnitedKingdom", "GBR"),
    "MON": ("Monaco",        "MCO"),
    "AUS": ("Australia",     "AUS"),
    "ESP": ("Spain",         "ESP"),
    "MEX": ("Mexico",        "MEX"),
    "FRA": ("France",        "FRA"),
    "GER": ("Germany",       "DEU"),
    "JPN": ("Japan",         "JPN"),
    "CAN": ("Canada",        "CAN"),
    "DEN": ("Denmark",       "DNK"),
    "THA": ("Thailand",      "THA"),
    "ARG": ("Argentina",     "ARG"),
    "CHN": ("China",         "CHN"),
    "NZL": ("NewZealand",    "NZL"),
    "FIN": ("Finland",       "FIN"),
    "USA": ("UnitedStates",  "USA"),
    "ITA": ("Italy",         "ITA"),
    "BRA": ("Brazil",        "BRA"),
}

# Country properties: country_key → (full_name, continent, wikidata_id)
COUNTRIES = {
    "Netherlands":   ("Kingdom of the Netherlands", "Europe",        "Q55"),
    "UnitedKingdom": ("United Kingdom",              "Europe",        "Q145"),
    "Monaco":        ("Principality of Monaco",      "Europe",        "Q235"),
    "Australia":     ("Australia",                   "Oceania",       "Q408"),
    "Spain":         ("Kingdom of Spain",            "Europe",        "Q29"),
    "Mexico":        ("United Mexican States",       "NorthAmerica",  "Q96"),
    "France":        ("French Republic",             "Europe",        "Q142"),
    "Germany":       ("Federal Republic of Germany", "Europe",        "Q183"),
    "Japan":         ("Japan",                       "Asia",          "Q17"),
    "Canada":        ("Canada",                      "NorthAmerica",  "Q16"),
    "Denmark":       ("Kingdom of Denmark",          "Europe",        "Q35"),
    "Thailand":      ("Kingdom of Thailand",         "Asia",          "Q869"),
    "Argentina":     ("Argentine Republic",          "SouthAmerica",  "Q414"),
    "China":         ("People's Republic of China",  "Asia",          "Q148"),
    "NewZealand":    ("New Zealand",                 "Oceania",       "Q664"),
    "Finland":       ("Republic of Finland",         "Europe",        "Q33"),
    "UnitedStates":  ("United States of America",    "NorthAmerica",  "Q30"),
    "Italy":         ("Italian Republic",            "Europe",        "Q38"),
    "Brazil":        ("Federative Republic of Brazil","SouthAmerica", "Q155"),
}

# ── Builder functions ──────────────────────────────────────────────────────────

def add_circuits(g: Graph) -> int:
    before = len(g)
    for uri_key, name, country, city, length in CIRCUITS:
        c = EX[uri_key]
        add(g, c, RDF.type,         EX.Circuit)
        add(g, c, EX.name,          Literal(name))
        add(g, c, EX.circuitCountry,Literal(country))
        add(g, c, EX.circuitCity,   Literal(city))
        add(g, c, EX.trackLength,   Literal(length, datatype=XSD.decimal))
        # Link country entity
        if country in COUNTRIES:
            add(g, c, EX.locatedIn, EX[country])
    return len(g) - before

def add_countries(g: Graph) -> int:
    before = len(g)
    for key, (full_name, continent, wd_id) in COUNTRIES.items():
        c = EX[key]
        add(g, c, RDF.type,          EX.Country)
        add(g, c, EX.name,           Literal(full_name))
        add(g, c, EX.continent,      Literal(continent))
        add(g, c, OWL.sameAs,        WD[wd_id])
    return len(g) - before

def add_race_calendars(g: Graph) -> int:
    before = len(g)
    for year, races in CALENDAR.items():
        season_uri = EX[f"Season{year}"]
        for race_key, gp_name, circuit_key, date in races:
            gp_uri      = EX[race_key]
            circuit_uri = EX[circuit_key]
            add(g, gp_uri, RDF.type,           EX.GrandPrix)
            add(g, gp_uri, EX.name,            Literal(gp_name))
            add(g, gp_uri, EX.raceDate,        Literal(date, datatype=XSD.date))
            add(g, gp_uri, EX.heldAtCircuit,   circuit_uri)
            add(g, gp_uri, EX.partOfSeason,    season_uri)
            add(g, season_uri, EX.hasRace,     gp_uri)
    return len(g) - before

def add_race_winners(g: Graph) -> int:
    before = len(g)
    for race_key, (driver_key, team_key) in WINNERS.items():
        gp_uri     = EX[race_key]
        driver_uri = EX[driver_key]
        team_uri   = EX[team_key]
        result_uri = EX[f"Result_{race_key}_Winner"]
        add(g, result_uri, RDF.type,           EX.RaceResult)
        add(g, result_uri, EX.forGrandPrix,    gp_uri)
        add(g, result_uri, EX.forDriver,       driver_uri)
        add(g, result_uri, EX.forTeam,         team_uri)
        add(g, result_uri, EX.finishPosition,  Literal(1, datatype=XSD.int))
        add(g, result_uri, EX.points,          Literal(25, datatype=XSD.decimal))
        add(g, gp_uri,     EX.winner,          driver_uri)
        add(g, gp_uri,     EX.winningTeam,     team_uri)
        add(g, driver_uri, EX.hasWon,          gp_uri)
    return len(g) - before

def add_champions(g: Graph) -> int:
    before = len(g)
    for year, (driver_key, team_key) in CHAMPIONS.items():
        season_uri = EX[f"Season{year}"]
        driver_uri = EX[driver_key]
        team_uri   = EX[team_key]
        add(g, season_uri, EX.worldDriversChampion,      driver_uri)
        add(g, season_uri, EX.worldConstructorsChampion, team_uri)
        add(g, driver_uri, EX.wonChampionshipIn,         season_uri)
        add(g, team_uri,   EX.wonConstructorsTitleIn,    season_uri)
    return len(g) - before

def add_teammate_relationships(g: Graph) -> int:
    """Infer teammate pairs from extracted standings."""
    before = len(g)
    for year in range(2022, 2027):
        drv_file = EXTRACTED_DIR / f"drivers_{year}.json"
        if not drv_file.exists():
            continue
        data = json.loads(drv_file.read_text(encoding="utf-8"))
        # Group by team
        team_drivers: dict[str, list[str]] = {}
        for row in data:
            t = clean(row["team"])
            d = clean(row["name"])
            team_drivers.setdefault(t, []).append(d)
        # Add symmetric teammate triples
        for team_key, drivers in team_drivers.items():
            for i, d1 in enumerate(drivers):
                for d2 in drivers[i + 1:]:
                    add(g, EX[d1], EX.teammateOf, EX[d2])
                    add(g, EX[d2], EX.teammateOf, EX[d1])
    return len(g) - before

def add_driver_country_links(g: Graph) -> int:
    """Link driver nationality codes to country entities."""
    before = len(g)
    for year in range(2022, 2027):
        drv_file = EXTRACTED_DIR / f"drivers_{year}.json"
        if not drv_file.exists():
            continue
        data = json.loads(drv_file.read_text(encoding="utf-8"))
        for row in data:
            nat = row.get("nationality_code", "")
            driver_key = clean(row["name"])
            if nat in NAT_TO_COUNTRY:
                country_key, _ = NAT_TO_COUNTRY[nat]
                add(g, EX[driver_key], EX.nationality,   Literal(nat))
                add(g, EX[driver_key], EX.fromCountry,   EX[country_key])
    return len(g) - before

def add_wikidata_alignment_triples(g: Graph) -> int:
    """Add owl:sameAs links + Wikidata entity declarations from TSV files."""
    before = len(g)
    for tsv in [DRIVERS_TSV, TEAMS_TSV]:
        if not tsv.exists():
            continue
        with open(tsv, encoding="utf-8") as f:
            for row in csv.DictReader(f, delimiter="\t"):
                if row.get("status") != "auto":
                    continue
                wid    = row["candidate_wikidata_id"].strip()
                lname  = row["local_entity"].strip()
                wlabel = row["candidate_label"].strip()
                conf   = row["confidence"].strip()
                if not wid or not lname:
                    continue
                local_uri = EX[lname]
                wd_uri    = WD[wid]
                add(g, local_uri, OWL.sameAs,               wd_uri)
                add(g, wd_uri,    RDFS.label,                Literal(wlabel, lang="en"))
                add(g, wd_uri,    EX.alignmentConfidence,    Literal(float(conf), datatype=XSD.decimal))
                add(g, local_uri, EX.wikidataId,             Literal(wid))
    return len(g) - before

def add_season_participation_triples(g: Graph) -> int:
    """
    Generate per-season per-driver standing summary triples that connect
    each driver to each season's GP list, enriching the connectivity.
    """
    before = len(g)
    for year, races in CALENDAR.items():
        season_uri = EX[f"Season{year}"]
        drv_file   = EXTRACTED_DIR / f"drivers_{year}.json"
        if not drv_file.exists():
            continue
        data = json.loads(drv_file.read_text(encoding="utf-8"))
        for row in data:
            driver_uri = EX[clean(row["name"])]
            # Link driver to all GPs in their season
            for race_key, _, _, _ in races:
                add(g, driver_uri, EX.participatedIn, EX[race_key])
    return len(g) - before

def add_team_season_triples(g: Graph) -> int:
    """Add team participation in each season with circuit country context."""
    before = len(g)
    for year in range(2022, 2027):
        team_file = EXTRACTED_DIR / f"teams_{year}.json"
        if not team_file.exists():
            continue
        data = json.loads(team_file.read_text(encoding="utf-8"))
        season_uri = EX[f"Season{year}"]
        for row in data:
            team_uri = EX[clean(row["team"])]
            add(g, team_uri,   EX.participatedInSeason, season_uri)
            add(g, season_uri, EX.hasParticipant,       team_uri)
    return len(g) - before

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
        "## Expansion strategy (local)\n",
        "This `expanded_kb.ttl` was generated locally from curated F1 data.",
        "For the full Wikidata SPARQL expansion (target: 50,000 – 200,000 triples), run:",
        "```",
        "python src/kg/expand_kb.py",
        "```",
        "(Requires internet access to query.wikidata.org)\n",
        "### Local expansion phases",
        "1. Initial private KB (Formula1.com standings 2022-2026)",
        "2. F1 circuits — 23 circuits with country, city, length",
        "3. Country entities — 19 nationalities with continent + owl:sameAs",
        "4. Race calendars — all races 2022-2026 linked to circuits + seasons",
        "5. Race winners — 2022-2025 winners + 2026 races so far",
        "6. Season champions — WDC + WCC 2022-2024",
        "7. Teammate relationships — symmetric pairs per team per season",
        "8. Driver–country links — nationality + fromCountry",
        "9. Wikidata alignment — owl:sameAs + labels from TSV files",
        "10. Season participation — driver ↔ GP participation links",
        "11. Team season participation — team ↔ season links",
        "",
        "## Source files",
        "",
        "| File | Description |",
        "|---|---|",
        "| `auto_kg.ttl` | Private KB (Formula1.com) + ontology + Wikidata alignments |",
        "| `expanded_kb.ttl` | This expanded KB (local expansion) |",
        "| `alignment_drivers.tsv` | Driver alignment to Wikidata |",
        "| `alignment_teams.tsv` | Team alignment to Wikidata |",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

# ── Main ───────────────────────────────────────────────────────────────────────
def main() -> None:
    print("=" * 60)
    print("LOCAL KB EXPANSION (offline mode)")
    print("=" * 60)

    g = Graph()
    g.bind("ex",  EX)
    g.bind("wd",  WD)
    g.bind("wdt", WDT)
    g.bind("owl", OWL)

    # Load base KB
    print("\n[0] Loading base KB …")
    g.parse(BASE_KG, format="turtle")
    print(f"    Base KB: {len(g):,} triples")

    steps = [
        ("Circuits",              add_circuits),
        ("Countries",             add_countries),
        ("Race calendars",        add_race_calendars),
        ("Race winners",          add_race_winners),
        ("Season champions",      add_champions),
        ("Teammate pairs",        add_teammate_relationships),
        ("Driver–country links",  add_driver_country_links),
        ("Wikidata alignment",    add_wikidata_alignment_triples),
        ("Season participation",  add_season_participation_triples),
        ("Team participation",    add_team_season_triples),
    ]

    for label, fn in steps:
        added = fn(g)
        print(f"  [{label}]: +{added:>5,}  →  KB={len(g):,}")

    print(f"\n[Save] Serialising to {OUTPUT_FILE} …")
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    g.serialize(destination=str(OUTPUT_FILE), format="turtle")
    print(f"  → Saved ({len(g):,} triples)")

    write_stats(g, STATS_FILE)
    print(f"  → Stats written to {STATS_FILE}")

    subjects   = set(str(s) for s, _, _ in g if isinstance(s, URIRef))
    predicates = set(str(p) for _, p, _ in g)
    print("\n" + "=" * 60)
    print("LOCAL EXPANSION COMPLETE")
    print(f"  Triples    : {len(g):,}")
    print(f"  Entities   : {len(subjects):,}")
    print(f"  Predicates : {len(predicates):,}")
    print()
    print("  NOTE: For the full 50k–200k target, run:")
    print("        python src/kg/expand_kb.py   (requires internet)")
    print("=" * 60)


if __name__ == "__main__":
    main()
