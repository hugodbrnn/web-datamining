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
# Race keyword → CONTAINS filter keyword
# ──────────────────────────────────────────────────────────────────────────────

RACE_KEYWORDS: dict[str, str] = {
    "australian": "australian", "australia": "australian",
    "bahrain": "bahrain",
    "saudi arabian": "saudi", "saudi": "saudi",
    "japanese": "japanese", "japan": "japanese",
    "chinese": "chinese", "china": "chinese",
    "miami": "miami",
    "emilia romagna": "emilia", "imola": "emilia",
    "monaco": "monaco",
    "canadian": "canadian", "canada": "canadian",
    "spanish": "spanish", "spain": "spanish", "barcelona": "spanish",
    "austrian": "austrian", "austria": "austrian",
    "british": "british", "britain": "british", "silverstone": "british",
    "hungarian": "hungarian", "hungary": "hungarian",
    "belgian": "belgian", "belgium": "belgian", "spa": "belgian",
    "dutch": "dutch", "netherlands": "dutch", "zandvoort": "dutch",
    "italian": "italian", "italy": "italian", "monza": "italian",
    "azerbaijan": "azerbaijan", "baku": "azerbaijan",
    "singapore": "singapore",
    "united states": "united states", "us grand prix": "united states",
    "cota": "united states", "austin": "united states",
    "mexican": "mexico city", "mexico": "mexico city",
    "são paulo": "são paulo", "sao paulo": "são paulo",
    "brazilian": "são paulo", "brazil": "são paulo", "interlagos": "são paulo",
    "las vegas": "las vegas", "vegas": "las vegas",
    "qatar": "qatar", "lusail": "qatar",
    "abu dhabi": "abu dhabi", "yas": "abu dhabi",
}


def _resolve_driver(text: str) -> Optional[str]:
    """Return the KB URI fragment for a driver name, or None if unknown."""
    return DRIVER_ALIASES.get(text.lower().strip())


def _resolve_race(text: str) -> Optional[str]:
    """Return the CONTAINS keyword for a race name, or None if unknown."""
    t = text.lower().strip()
    for k, v in RACE_KEYWORDS.items():
        if k in t:
            return v
    return None


# ──────────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────────

def route(question: str) -> Optional[str]:
    """
    Try to match *question* against known patterns.

    Returns a complete SPARQL SELECT string, or None if no pattern matched.
    The caller should fall through to the LLM generator when None is returned.
    """
    q = question.lower().strip()

    # ── 1. Championship winner ────────────────────────────────────────────────
    # "who won the 2024 F1 / world championship / title"
    # "who is the 2024 world champion"
    m = re.search(
        r'(?:who\s+won\s+the|who\s+is\s+the)\s+(\d{4})\s+'
        r'(?:f1\s+|formula\s+(?:1|one)\s+)?(?:world\s+)?'
        r'(?:drivers?\s+)?(?:championship|title|champion\b|wdc)',
        q,
    )
    if m:
        year = m.group(1)
        return PREFIX + f"""SELECT ?driverName WHERE {{
    ?driver ex:isChampionOf ex:Season{year} ;
            ex:name ?driverName .
}}"""

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
            return PREFIX + f"""SELECT ?countryName WHERE {{
    ex:{driver_uri} ex:fromCountry ?country .
    ?country ex:name ?countryName .
}}"""

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
            return PREFIX + f"""SELECT (COUNT(?gp) AS ?wins) WHERE {{
    ex:{driver_uri} ex:hasWon ?gp .
    ?gp ex:partOfSeason ex:Season{year} .
}}"""

    # ── 3. Did DRIVER win (a) race in YEAR  /  Which races did DRIVER win in YEAR
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
                return PREFIX + f"""SELECT ?gpName WHERE {{
    ex:{driver_uri} ex:hasWon ?gp .
    ?gp ex:partOfSeason ex:Season{year} ;
        ex:name ?gpName .
}}"""
            else:
                return PREFIX + f"""SELECT ?gpName WHERE {{
    ex:{driver_uri} ex:hasWon ?gp .
    ?gp ex:name ?gpName .
}} ORDER BY ?gpName"""

    # ── 4. Who won the RACE Grand Prix in YEAR ────────────────────────────────
    m = re.search(
        r'who\s+won\s+the\s+(.+?)\s+grand\s+prix\s+in\s+(\d{4})',
        q,
    )
    if m:
        keyword = _resolve_race(m.group(1))
        year = m.group(2)
        if keyword:
            return PREFIX + f"""SELECT ?driverName WHERE {{
    ?gp ex:partOfSeason ex:Season{year} ;
        ex:name ?gpName ;
        ex:winner ?driver .
    ?driver ex:name ?driverName .
    FILTER(CONTAINS(LCASE(?gpName), "{keyword}"))
}}"""

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
            return PREFIX + f"""SELECT DISTINCT ?teamName WHERE {{
    ?standing a ex:DriverStanding ;
              ex:forSeason ex:Season{year} ;
              ex:forDriver ex:{driver_uri} ;
              ex:forTeam ?team .
    ?team ex:name ?teamName .
}}"""

    # ── 5b. Which team does DRIVER drive for ──────────────────────────────────
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
                return PREFIX + f"""SELECT DISTINCT ?teamName WHERE {{
    ex:{driver_uri} ex:drivesFor ?team .
    ?team ex:name ?teamName .
}}"""
    if m:
        driver_text = (m.group(1) or m.group(2) or "").strip()
        driver_uri = _resolve_driver(driver_text)
        if driver_uri:
            return PREFIX + f"""SELECT DISTINCT ?teamName WHERE {{
    ex:{driver_uri} ex:drivesFor ?team .
    ?team ex:name ?teamName .
}}"""

    # ── 6. Driver standings in YEAR ───────────────────────────────────────────
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
            return PREFIX + f"""SELECT ?position WHERE {{
    ?standing a ex:DriverStanding ;
              ex:forSeason ex:Season{year} ;
              ex:forDriver ex:{driver_uri} ;
              ex:standingPosition ?position .
}}"""

    # ── 6b. Driver standings in YEAR ──────────────────────────────────────────
    m = re.search(
        r'(?:driver|championship|season)\s+standings?\s+(?:in|for)\s+(\d{4})'
        r'|standings?\s+(?:in|for)\s+(\d{4})',
        q,
    )
    if m:
        year = m.group(1) or m.group(2)
        return PREFIX + f"""SELECT ?driverName ?position ?points WHERE {{
    ?standing a ex:DriverStanding ;
              ex:forSeason ex:Season{year} ;
              ex:forDriver ?driver ;
              ex:standingPosition ?position ;
              ex:standingPoints ?points .
    ?driver ex:name ?driverName .
}} ORDER BY ?position"""

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
            return PREFIX + f"""SELECT DISTINCT ?mateName WHERE {{
    ?s1 a ex:DriverStanding ; ex:forSeason ex:Season{year} ;
        ex:forDriver ex:{driver_uri} ; ex:forTeam ?team .
    ?s2 a ex:DriverStanding ; ex:forSeason ex:Season{year} ;
        ex:forDriver ?mate ; ex:forTeam ?team .
    ?mate ex:name ?mateName .
    FILTER(ex:{driver_uri} != ?mate)
}}"""

    # ── 8. Who finished POSITION in the YEAR championship ─────────────────────
    m = re.search(
        r'who\s+finished\s+(\d+)(?:st|nd|rd|th)?\s+in\s+(?:the\s+)?(\d{4})',
        q,
    )
    if m:
        pos = m.group(1)
        year = m.group(2)
        return PREFIX + f"""SELECT ?driverName ?points WHERE {{
    ?standing a ex:DriverStanding ;
              ex:forSeason ex:Season{year} ;
              ex:forDriver ?driver ;
              ex:standingPosition ?pos ;
              ex:standingPoints ?points .
    ?driver ex:name ?driverName .
    FILTER(?pos = {pos})
}}"""

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
            return PREFIX + f"""SELECT ?nationality WHERE {{
    ex:{driver_uri} ex:nationality ?nationality .
}}"""

    # ── 10. Season race calendar ──────────────────────────────────────────────
    m = re.search(
        r'which\s+driver\s+won\s+the\s+most\s+races?\s+in\s+(\d{4})',
        q,
    )
    if m:
        year = m.group(1)
        return PREFIX + f"""SELECT ?driverName WHERE {{
    ?gp ex:name ?gpName ;
        ex:winner ?driver .
    ?driver ex:name ?driverName .
    FILTER(CONTAINS(LCASE(?gpName), "{year}"))
}}
GROUP BY ?driverName
ORDER BY DESC(COUNT(?gp))
LIMIT 1"""

    # ── 10b. Season race calendar ─────────────────────────────────────────────
    m = re.search(
        r'(?:which|list|what)\s+races?\s+(?:were\s+(?:held|run)|(?:are\s+)?in|took\s+place)\s+in\s+(\d{4})'
        r'|(\d{4})\s+(?:f1\s+)?(?:race\s+)?calendar',
        q,
    )
    if m:
        year = m.group(1) or m.group(2)
        return PREFIX + f"""SELECT ?gpName ?raceDate WHERE {{
    ex:Season{year} ex:hasRace ?gp .
    ?gp ex:name ?gpName .
    OPTIONAL {{ ?gp ex:raceDate ?raceDate . }}
}} ORDER BY ?raceDate"""

    return None
