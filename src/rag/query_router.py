"""
query_router.py — Deterministic regex-based SPARQL query router
===============================================================
Intercepts common question patterns before they reach the LLM and returns
a correct SPARQL query from a hardcoded template.  This avoids the frequent
hallucinations produced by small models (llama3.2:1b) on structured queries.

If no pattern matches, the function returns None and the caller falls through
to the LLM-based generator.

Supported patterns
------------------
1.  Championship winner     : "who won the 2024 F1 championship"
2.  Race win count          : "how many races did Verstappen win in 2023"
3.  Race wins list          : "did Hamilton win a race in 2024" /
                              "which races did Norris win in 2024"
4.  Single race winner      : "who won the Monaco Grand Prix in 2024"
5.  Driver team             : "which team does Norris drive for"
6.  Driver standings        : "what are the driver standings in 2024"
7.  Teammate lookup         : "who were Hamilton's teammates in 2024"
8.  Standing position       : "who finished 2nd in the 2023 championship"
9.  Driver nationality      : "what is Verstappen's nationality"
10. Season race list        : "which races were held in 2024"
11. Drivers by nationality  : "give me all the French drivers in 2026"
"""

import re
from typing import Optional

PREFIX = "PREFIX ex: <http://example.org/f1#>\n"

# ──────────────────────────────────────────────────────────────────────────────
# Driver alias table  (lower-cased key → KB URI fragment)
# Built from real KB URIs extracted at build time.
# ──────────────────────────────────────────────────────────────────────────────

DRIVER_ALIASES: dict[str, str] = {
    # Verstappen
    "verstappen": "MaxVerstappen",
    "max verstappen": "MaxVerstappen",
    "max": "MaxVerstappen",
    # Hamilton
    "hamilton": "LewisHamilton",
    "lewis hamilton": "LewisHamilton",
    # Norris
    "norris": "LandoNorris",
    "lando norris": "LandoNorris",
    # Leclerc
    "leclerc": "CharlesLeclerc",
    "charles leclerc": "CharlesLeclerc",
    # Sainz
    "sainz": "CarlosSainz",
    "carlos sainz": "CarlosSainz",
    # Russell
    "russell": "GeorgeRussell",
    "george russell": "GeorgeRussell",
    # Alonso
    "alonso": "FernandoAlonso",
    "fernando alonso": "FernandoAlonso",
    # Perez
    "perez": "SergioPerez",
    "sergio perez": "SergioPerez",
    "checo": "SergioPerez",
    # Gasly
    "gasly": "PierreGasly",
    "pierre gasly": "PierreGasly",
    # Piastri
    "piastri": "OscarPiastri",
    "oscar piastri": "OscarPiastri",
    # Ocon
    "ocon": "EstebanOcon",
    "esteban ocon": "EstebanOcon",
    # Tsunoda
    "tsunoda": "YukiTsunoda",
    "yuki tsunoda": "YukiTsunoda",
    # Bottas
    "bottas": "ValtteriBottas",
    "valtteri bottas": "ValtteriBottas",
    # Stroll
    "stroll": "LanceStroll",
    "lance stroll": "LanceStroll",
    # Magnussen
    "magnussen": "KevinMagnussen",
    "kevin magnussen": "KevinMagnussen",
    # Hulkenberg
    "hulkenberg": "NicoHulkenberg",
    "nico hulkenberg": "NicoHulkenberg",
    "hulk": "NicoHulkenberg",
    # Albon
    "albon": "AlexanderAlbon",
    "alexander albon": "AlexanderAlbon",
    # Zhou
    "zhou": "ZhouGuanyu",
    "guanyu zhou": "ZhouGuanyu",
    "zhou guanyu": "ZhouGuanyu",
    # Sargeant
    "sargeant": "LoganSargeant",
    "logan sargeant": "LoganSargeant",
    # Lawson
    "lawson": "LiamLawson",
    "liam lawson": "LiamLawson",
    # Colapinto
    "colapinto": "FrancoColapinto",
    "franco colapinto": "FrancoColapinto",
    # Bearman
    "bearman": "OliverBearman",
    "oliver bearman": "OliverBearman",
    # Hadjar
    "hadjar": "IsackHadjar",
    "isack hadjar": "IsackHadjar",
    # Antonelli
    "antonelli": "KimiAntonelli",
    "kimi antonelli": "KimiAntonelli",
    # Doohan
    "doohan": "JackDoohan",
    "jack doohan": "JackDoohan",
    # Bortoleto
    "bortoleto": "GabrielBortoleto",
    "gabriel bortoleto": "GabrielBortoleto",
    # Rosberg
    "rosberg": "NicoRosberg",
    "nico rosberg": "NicoRosberg",
    # Vettel
    "vettel": "SebastianVettel",
    "sebastian vettel": "SebastianVettel",
    # Ricciardo
    "ricciardo": "DanielRicciardo",
    "daniel ricciardo": "DanielRicciardo",
    # De Vries
    "de vries": "NyckDeVries",
    "nyck de vries": "NyckDeVries",
    # Schumacher (Mick only — no Michael in KB)
    "mick schumacher": "MickSchumacher",
    "schumacher": "MickSchumacher",
    # Kvyat
    "kvyat": "DaniilKvyat",
    "daniil kvyat": "DaniilKvyat",
    # Grosjean
    "grosjean": "RomainGrosjean",
    "romain grosjean": "RomainGrosjean",
    # Button
    "button": "JensonButton",
    "jenson button": "JensonButton",
    # Massa
    "massa": "FelipeMassa",
    "felipe massa": "FelipeMassa",
    # Räikkönen
    "raikkonen": "KimiRikknen",
    "kimi raikkonen": "KimiRikknen",
    "räikkönen": "KimiRikknen",
    "kimi räikkönen": "KimiRikknen",
    "kimi": "KimiRikknen",
}

# ──────────────────────────────────────────────────────────────────────────────
# Race keyword → KB URI fragment  (ex:GP_{YEAR}_{FRAGMENT})
# Derived from actual URI patterns in reasoned_kb.ttl
# ──────────────────────────────────────────────────────────────────────────────

RACE_URI_FRAGMENTS: dict[str, str] = {
    "australian": "Australia",   "australia": "Australia",
    "bahrain": "Bahrain",
    "saudi arabian": "SaudiArabia", "saudi": "SaudiArabia",
    "japanese": "Japan",         "japan": "Japan",    "suzuka": "Japan",
    "chinese": "China",          "china": "China",
    "miami": "Miami",
    "emilia romagna": "EmiliaRomagna", "imola": "EmiliaRomagna",
    "monaco": "Monaco",
    "canadian": "Canada",        "canada": "Canada",
    "spanish": "Spain",          "spain": "Spain",    "barcelona": "Spain",
    "austrian": "Austria",       "austria": "Austria",
    "british": "GreatBritain",   "britain": "GreatBritain", "silverstone": "GreatBritain",
    "hungarian": "Hungary",      "hungary": "Hungary",
    "belgian": "Belgium",        "belgium": "Belgium", "spa": "Belgium",
    "dutch": "Netherlands",      "netherlands": "Netherlands", "zandvoort": "Netherlands",
    "italian": "Italy",          "italy": "Italy",    "monza": "Italy",
    "azerbaijan": "Azerbaijan",  "baku": "Azerbaijan",
    "singapore": "Singapore",
    "united states": "UnitedStates", "us grand prix": "UnitedStates",
    "cota": "UnitedStates",      "austin": "UnitedStates",
    "mexican": "Mexico",         "mexico": "Mexico",
    "são paulo": "Brazil",       "sao paulo": "Brazil",
    "brazilian": "Brazil",       "brazil": "Brazil",  "interlagos": "Brazil",
    "las vegas": "LasVegas",     "vegas": "LasVegas",
    "qatar": "Qatar",            "lusail": "Qatar",
    "abu dhabi": "AbuDhabi",     "yas": "AbuDhabi",
}

# Keep RACE_KEYWORDS as a fallback for LLM-generated queries using ex:name + FILTER
RACE_KEYWORDS: dict[str, str] = {k: v.lower() for k, v in RACE_URI_FRAGMENTS.items()}

# ──────────────────────────────────────────────────────────────────────────────
# Nationality adjective → ISO 3166-1 alpha-3 code (as stored in KB)
# ──────────────────────────────────────────────────────────────────────────────

NATIONALITY_CODES: dict[str, str] = {
    "french": "FRA",      "france": "FRA",
    "british": "GBR",     "english": "GBR",   "uk": "GBR",
    "dutch": "NED",       "netherlands": "NED",
    "german": "GER",      "germany": "GER",
    "spanish": "ESP",     "spain": "ESP",
    "monegasque": "MON",  "monaco": "MON",
    "canadian": "CAN",    "canada": "CAN",
    "australian": "AUS",  "australia": "AUS",
    "finnish": "FIN",     "finland": "FIN",
    "thai": "THA",        "thailand": "THA",
    "mexican": "MEX",     "mexico": "MEX",
    "chinese": "CHN",     "china": "CHN",
    "japanese": "JPN",    "japan": "JPN",
    "italian": "ITA",     "italy": "ITA",
    "danish": "DEN",      "denmark": "DEN",
    "argentinian": "ARG", "argentine": "ARG", "argentina": "ARG",
    "american": "USA",    "usa": "USA",
    "new zealand": "NZL", "new zealander": "NZL",
    "swiss": "SUI",       "switzerland": "SUI",
    "brazilian": "BRA",   "brazil": "BRA",
    "russian": "RUS",     "russia": "RUS",
    "polish": "POL",      "poland": "POL",
    "austrian": "AUT",    "austria": "AUT",
    "swedish": "SWE",     "sweden": "SWE",
    "belgian": "BEL",     "belgium": "BEL",
}


def _normalize_apostrophes(text: str) -> str:
    """Replace all apostrophe-like Unicode characters with a plain ASCII apostrophe."""
    # Covers: right/left single quotes, modifier letter apostrophe, prime, grave, etc.
    return re.sub(r"[\u2018\u2019\u201a\u201b\u02bc\u02b9\u0060\u00b4\u2032\uff07]", "'", text)


def _resolve_driver(text: str) -> Optional[str]:
    """Return the KB URI fragment for a driver name, or None if unknown."""
    return DRIVER_ALIASES.get(text.lower().strip())


def _resolve_race_fragment(text: str) -> Optional[str]:
    """Return the KB URI fragment for a race (ex:GP_YYYY_{fragment}), or None."""
    t = text.lower().strip()
    # Try longest key first to avoid "spa" matching "spain" before "spain" does
    for k in sorted(RACE_URI_FRAGMENTS, key=len, reverse=True):
        if k in t:
            return RACE_URI_FRAGMENTS[k]
    return None


def _resolve_race(text: str) -> Optional[str]:
    """Return the CONTAINS keyword for a race name (legacy fallback), or None."""
    fragment = _resolve_race_fragment(text)
    return fragment.lower() if fragment else None


def _resolve_nationality(text: str) -> Optional[str]:
    """Return the ISO-3 nationality code for a nationality adjective, or None."""
    t = text.lower().strip()
    # Try longest key first
    for k in sorted(NATIONALITY_CODES, key=len, reverse=True):
        if k in t:
            return NATIONALITY_CODES[k]
    return None


# ──────────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────────

def route(question: str) -> Optional[list[str]]:
    """
    Try to match *question* against known patterns.

    Returns a list of SPARQL SELECT strings to try in order (first non-empty
    result wins), or None if no pattern matched.
    The caller should fall through to the LLM generator when None is returned.
    """
    q = _normalize_apostrophes(question.lower().strip())

    # ── 1. Championship winner ────────────────────────────────────────────────
    m = re.search(
        r'(?:who\s+won\s+the|who\s+is\s+the)\s+(\d{4})\s+'
        r'(?:f1\s+|formula\s+(?:1|one)\s+)?(?:world\s+)?'
        r'(?:drivers?\s+)?(?:championship|title|champion\b|wdc)',
        q,
    )
    if m:
        year = m.group(1)
        return [
            # Variant A: isChampionOf (inferred by SWRL Rule 1)
            PREFIX + f"""SELECT ?driverName WHERE {{
    ?driver ex:isChampionOf ex:Season{year} ;
            ex:name ?driverName .
}}""",
            # Variant B: DriverStanding position = 1 (raw data fallback)
            PREFIX + f"""SELECT ?driverName WHERE {{
    ?standing a ex:DriverStanding ;
              ex:forSeason ex:Season{year} ;
              ex:forDriver ?driver ;
              ex:standingPosition ?pos .
    ?driver ex:name ?driverName .
    FILTER(?pos = 1)
}}""",
        ]

    # ── 1b. From which country does DRIVER come from ─────────────────────────
    m = re.search(
        r'from\s+which\s+country\s+does\s+(.+?)\s+come\s+from'
        r'|which\s+country\s+does\s+(.+?)\s+come\s+from',
        q,
    )
    if m:
        driver_text = (m.group(1) or m.group(2) or "").strip()
        driver_uri = _resolve_driver(driver_text)
        if driver_uri:
            return [PREFIX + f"""SELECT ?countryName WHERE {{
    ex:{driver_uri} ex:fromCountry ?country .
    ?country ex:name ?countryName .
}}"""]

    # ── 2. How many races did DRIVER win in YEAR ───────────────────────────────
    m = re.search(
        r'how\s+many\s+races?\s+did\s+(.+?)\s+win\s+in\s+(\d{{4}})'
        .replace('{{', '{').replace('}}', '}'),
        q,
    )
    if m:
        driver_uri = _resolve_driver(m.group(1))
        year = m.group(2)
        if driver_uri:
            return [
                PREFIX + f"""SELECT (COUNT(?gp) AS ?wins) WHERE {{
    ex:{driver_uri} ex:hasWon ?gp .
    ?gp ex:inSeason ex:Season{year} .
}}""",
                PREFIX + f"""SELECT (COUNT(?gp) AS ?wins) WHERE {{
    ?gp ex:inSeason ex:Season{year} ;
        ex:winner ex:{driver_uri} .
}}""",
                PREFIX + f"""SELECT (COUNT(?gp) AS ?wins) WHERE {{
    ex:{driver_uri} ex:hasWon ?gp .
    ?gp ex:partOfSeason ex:Season{year} .
}}""",
            ]

    # ── 3. Which races did DRIVER win in YEAR ─────────────────────────────────
    m = re.search(
        r'(?:did\s+(.+?)\s+win\s+(?:a\s+|any\s+)?races?'
        r'|which\s+races?\s+did\s+(.+?)\s+win'
        r'|(?:list\s+)?races?\s+won\s+by\s+(.+?))'
        r'(?:\s+in\s+(\d{4}))?',
        q,
    )
    if m:
        driver_text = (m.group(1) or m.group(2) or m.group(3) or "").strip()
        year = m.group(4)
        driver_uri = _resolve_driver(driver_text)
        if driver_uri:
            if year:
                return [
                    PREFIX + f"""SELECT ?gpName WHERE {{
    ex:{driver_uri} ex:hasWon ?gp .
    ?gp ex:inSeason ex:Season{year} .
    BIND(REPLACE(STR(?gp), ".*#GP_[0-9]+_", "") AS ?gpName)
}}""",
                    PREFIX + f"""SELECT ?gpName WHERE {{
    ?gp ex:inSeason ex:Season{year} ;
        ex:winner ex:{driver_uri} .
    BIND(REPLACE(STR(?gp), ".*#GP_[0-9]+_", "") AS ?gpName)
}}""",
                    PREFIX + f"""SELECT ?gpName WHERE {{
    ex:{driver_uri} ex:hasWon ?gp .
    ?gp ex:partOfSeason ex:Season{year} .
    BIND(REPLACE(STR(?gp), ".*#GP_[0-9]+_", "") AS ?gpName)
}}""",
                ]
            else:
                return [
                    PREFIX + f"""SELECT ?gpName WHERE {{
    ex:{driver_uri} ex:hasWon ?gp .
    BIND(REPLACE(STR(?gp), ".*#GP_[0-9]+_", "") AS ?gpName)
}} ORDER BY ?gpName""",
                    PREFIX + f"""SELECT ?gpName WHERE {{
    ?gp ex:winner ex:{driver_uri} .
    BIND(REPLACE(STR(?gp), ".*#GP_[0-9]+_", "") AS ?gpName)
}} ORDER BY ?gpName""",
                ]

    # ── 4. Who won the RACE [Grand] Prix / GP in YEAR ────────────────────────
    m = re.search(
        r'who\s+won\s+the\s+(.+?)\s+(?:grand\s+)?(?:prix|gp)\b.*?in\s+(\d{4})',
        q,
    )
    if m:
        fragment = _resolve_race_fragment(m.group(1))
        year = m.group(2)
        if fragment:
            return [
                PREFIX + f"""SELECT ?driverName WHERE {{
    ex:GP_{year}_{fragment} ex:winner ?driver .
    ?driver ex:name ?driverName .
}}""",
                PREFIX + f"""SELECT ?driverName WHERE {{
    ?gp ex:inSeason ex:Season{year} ;
        ex:winner ?driver .
    FILTER(CONTAINS(LCASE(STR(?gp)), "{fragment.lower()}"))
    ?driver ex:name ?driverName .
}}""",
            ]

    # ── 4b. Who won the YEAR RACE [Grand] Prix / GP  (year before race name) ──
    m = re.search(
        r'(?:who\s+won\s+the|winner\s+of\s+the)\s+(\d{4})\s+(.+?)\s+(?:grand\s+)?(?:prix|gp)\b',
        q,
    )
    if not m:
        m = re.search(r'(\d{4})\s+(.+?)\s+(?:grand\s+)?(?:prix|gp)\b.*winner', q)
    if m:
        year     = m.group(1)
        fragment = _resolve_race_fragment(m.group(2))
        if fragment:
            return [
                PREFIX + f"""SELECT ?driverName WHERE {{
    ex:GP_{year}_{fragment} ex:winner ?driver .
    ?driver ex:name ?driverName .
}}""",
                PREFIX + f"""SELECT ?driverName WHERE {{
    ?gp ex:inSeason ex:Season{year} ;
        ex:winner ?driver .
    FILTER(CONTAINS(LCASE(STR(?gp)), "{fragment.lower()}"))
    ?driver ex:name ?driverName .
}}""",
            ]

    # ── 5. Which team does DRIVER drive for in YEAR ───────────────────────────
    m = re.search(
        r'(?:which|what)\s+team\s+does\s+(.+?)\s+(?:drive|race)\s+for\s+in\s+(\d{4})',
        q,
    )
    if m:
        driver_text = m.group(1).strip()
        year = m.group(2)
        driver_uri = _resolve_driver(driver_text)
        if driver_uri:
            return [
                PREFIX + f"""SELECT DISTINCT ?teamName WHERE {{
    ?standing a ex:DriverStanding ;
              ex:forSeason ex:Season{year} ;
              ex:forDriver ex:{driver_uri} ;
              ex:forTeam ?team .
    ?team ex:name ?teamName .
}}""",
                PREFIX + f"""SELECT DISTINCT ?teamName WHERE {{
    ex:{driver_uri} ex:drivesFor ?team .
    ?team ex:name ?teamName .
}}""",
            ]

    # ── 5b. Which team does DRIVER drive for (no year) ───────────────────────
    m = re.search(
        r'(?:which|what)\s+team\s+(?:does\s+(.+?)\s+(?:drive|race)\s+for'
        r'|is\s+(.+?)\s+(?:driving|racing|on|in))',
        q,
    )
    if not m:
        m = re.search(r'(.+?)[\'\u2019]s\s+team\b', q)
        if m:
            driver_text = m.group(1).strip()
            driver_uri = _resolve_driver(driver_text)
            if driver_uri:
                return [
                    PREFIX + f"""SELECT DISTINCT ?teamName WHERE {{
    ex:{driver_uri} ex:drivesFor ?team .
    ?team ex:name ?teamName .
}}""",
                    PREFIX + f"""SELECT DISTINCT ?teamName WHERE {{
    ?standing a ex:DriverStanding ;
              ex:forDriver ex:{driver_uri} ;
              ex:forTeam ?team .
    ?team ex:name ?teamName .
}}""",
                ]
    if m:
        driver_text = (m.group(1) or m.group(2) or "").strip()
        driver_uri = _resolve_driver(driver_text)
        if driver_uri:
            return [
                PREFIX + f"""SELECT DISTINCT ?teamName WHERE {{
    ex:{driver_uri} ex:drivesFor ?team .
    ?team ex:name ?teamName .
}}""",
                PREFIX + f"""SELECT DISTINCT ?teamName WHERE {{
    ?standing a ex:DriverStanding ;
              ex:forDriver ex:{driver_uri} ;
              ex:forTeam ?team .
    ?team ex:name ?teamName .
}}""",
            ]

    # ── 6. Driver's standing position in YEAR ────────────────────────────────
    m = re.search(
        r'what\s+was\s+(.+?)[\'\u2019]s\s+standing\s+position\s+in\s+(?:the\s+)?(\d{4})'
        r'(?:\s+(?:championship|season))?',
        q,
    )
    if m:
        driver_text = m.group(1).strip()
        year = m.group(2)
        driver_uri = _resolve_driver(driver_text)
        if driver_uri:
            return [PREFIX + f"""SELECT ?position WHERE {{
    ?standing a ex:DriverStanding ;
              ex:forSeason ex:Season{year} ;
              ex:forDriver ex:{driver_uri} ;
              ex:standingPosition ?position .
}}"""]

    # ── 6b. All driver standings in YEAR ──────────────────────────────────────
    m = re.search(
        r'(?:driver|championship|season)\s+standings?\s+(?:in|for)\s+(\d{4})'
        r'|standings?\s+(?:in|for)\s+(\d{4})',
        q,
    )
    if m:
        year = m.group(1) or m.group(2)
        return [
            PREFIX + f"""SELECT ?driverName ?position ?points WHERE {{
    ?standing a ex:DriverStanding ;
              ex:forSeason ex:Season{year} ;
              ex:forDriver ?driver ;
              ex:standingPosition ?position ;
              ex:standingPoints ?points .
    ?driver ex:name ?driverName .
}} ORDER BY ?position""",
            # Fallback without points (in case standingPoints absent)
            PREFIX + f"""SELECT ?driverName ?position WHERE {{
    ?standing a ex:DriverStanding ;
              ex:forSeason ex:Season{year} ;
              ex:forDriver ?driver ;
              ex:standingPosition ?position .
    ?driver ex:name ?driverName .
}} ORDER BY ?position""",
        ]

    # ── 7. Teammates of DRIVER in YEAR ────────────────────────────────────────
    m = re.search(
        r'(?:who\s+(?:were|was|is|are)\s+)?(.+?)[\'\u2019]s\s+teammates?\s+in\s+(\d{4})'
        r'|teammates?\s+of\s+(.+?)\s+in\s+(\d{4})',
        q,
    )
    if m:
        driver_text = (m.group(1) or m.group(3) or "").strip()
        year = m.group(2) or m.group(4)
        driver_uri = _resolve_driver(driver_text)
        if driver_uri and year:
            return [
                # Variant A: two DriverStanding nodes sharing ?team
                PREFIX + f"""SELECT DISTINCT ?mateName WHERE {{
    ?s1 a ex:DriverStanding ; ex:forSeason ex:Season{year} ;
        ex:forDriver ex:{driver_uri} ; ex:forTeam ?team .
    ?s2 a ex:DriverStanding ; ex:forSeason ex:Season{year} ;
        ex:forDriver ?mate ; ex:forTeam ?team .
    ?mate ex:name ?mateName .
    FILTER(ex:{driver_uri} != ?mate)
}}""",
                # Variant B: materialized teammateOf triples
                PREFIX + f"""SELECT ?mateName WHERE {{
    ex:{driver_uri} ex:teammateOf ?mate .
    ?mate ex:name ?mateName .
}}""",
            ]

    # ── 8. Who finished POSITION in the YEAR championship ─────────────────────
    m = re.search(
        r'who\s+finished\s+(\d+)(?:st|nd|rd|th)?\s+in\s+(?:the\s+)?(\d{4})',
        q,
    )
    if m:
        pos = m.group(1)
        year = m.group(2)
        return [
            PREFIX + f"""SELECT ?driverName ?points WHERE {{
    ?standing a ex:DriverStanding ;
              ex:forSeason ex:Season{year} ;
              ex:forDriver ?driver ;
              ex:standingPosition ?pos ;
              ex:standingPoints ?points .
    ?driver ex:name ?driverName .
    FILTER(?pos = {pos})
}}""",
            # Fallback without points
            PREFIX + f"""SELECT ?driverName WHERE {{
    ?standing a ex:DriverStanding ;
              ex:forSeason ex:Season{year} ;
              ex:forDriver ?driver ;
              ex:standingPosition ?pos .
    ?driver ex:name ?driverName .
    FILTER(?pos = {pos})
}}""",
        ]

    # ── 9. Driver nationality ──────────────────────────────────────────────────
    m = re.search(
        r'(?:what\s+is\s+)?(.+?)[\'\u2019]s\s+nationality'
        r'|what\s+nationality\s+is\s+(.+)',
        q,
    )
    if m:
        driver_text = (m.group(1) or m.group(2) or "").strip()
        driver_uri = _resolve_driver(driver_text)
        if driver_uri:
            return [PREFIX + f"""SELECT ?nationality WHERE {{
    ex:{driver_uri} ex:nationality ?nationality .
}}"""]

    # ── 10. Driver with most wins in YEAR ─────────────────────────────────────
    m = re.search(
        r'which\s+driver\s+won\s+the\s+most\s+races?\s+in\s+(\d{4})',
        q,
    )
    if m:
        year = m.group(1)
        return [
            PREFIX + f"""SELECT ?driverName (COUNT(?gp) AS ?wins) WHERE {{
    ?gp ex:inSeason ex:Season{year} ;
        ex:winner ?driver .
    ?driver ex:name ?driverName .
}} GROUP BY ?driverName ORDER BY DESC(?wins) LIMIT 1""",
            PREFIX + f"""SELECT ?driverName (COUNT(?gp) AS ?wins) WHERE {{
    ?driver ex:hasWon ?gp .
    ?gp ex:inSeason ex:Season{year} .
    ?driver ex:name ?driverName .
}} GROUP BY ?driverName ORDER BY DESC(?wins) LIMIT 1""",
        ]

    # ── 10b. Season race calendar ─────────────────────────────────────────────
    m = re.search(
        r'(?:which|list|what)\s+races?\s+(?:were\s+(?:held|run)|(?:are\s+)?in|took\s+place)\s+in\s+(\d{4})'
        r'|(\d{4})\s+(?:f1\s+)?(?:race\s+)?calendar',
        q,
    )
    if m:
        year = m.group(1) or m.group(2)
        return [
            PREFIX + f"""SELECT ?gpName ?raceDate WHERE {{
    ex:Season{year} ex:hasRace ?gp .
    ?gp ex:name ?gpName .
    OPTIONAL {{ ?gp ex:raceDate ?raceDate . }}
}} ORDER BY ?raceDate""",
            # Fallback: inSeason triples (GPs without ex:name)
            PREFIX + f"""SELECT ?gpName WHERE {{
    ?gp ex:inSeason ex:Season{year} .
    BIND(REPLACE(STR(?gp), ".*#GP_[0-9]+_", "") AS ?gpName)
}} ORDER BY ?gpName""",
        ]

    # ── 11. Drivers by nationality in YEAR ───────────────────────────────────
    m = re.search(
        r'(?:give\s+(?:me\s+)?(?:all\s+(?:the\s+)?)?|list\s+(?:all\s+(?:the\s+)?)?|which\s+|who\s+(?:are\s+(?:the\s+)?)?)'
        r'(\w[\w\s]*?)\s+drivers?'
        r'(?:\s+in\s+(\d{4}))?',
        q,
    )
    if not m:
        m = re.search(
            r'drivers?\s+from\s+(\w[\w\s]*?)\s+in\s+(\d{4})',
            q,
        )
    if m:
        nat_text = m.group(1).strip()
        year = m.group(2) if m.lastindex >= 2 else None
        nat_code = _resolve_nationality(nat_text)
        if nat_code:
            if year:
                return [PREFIX + f"""SELECT DISTINCT ?driverName WHERE {{
    ?standing a ex:DriverStanding ;
              ex:forSeason ex:Season{year} ;
              ex:forDriver ?driver .
    ?driver ex:name ?driverName ;
            ex:nationality "{nat_code}" .
}}"""]
            else:
                return [PREFIX + f"""SELECT DISTINCT ?driverName WHERE {{
    ?driver a ex:Driver ;
            ex:name ?driverName ;
            ex:nationality "{nat_code}" .
}}"""]

    return None
