"""
repair_loop.py — Self-repair loop for failed SPARQL queries
===========================================================
If a generated SPARQL query fails to execute (syntax error, unknown
property, empty results), this module sends the error back to the LLM
and asks it to produce a corrected query. Retries up to MAX_ATTEMPTS.

Design
------
  attempt 1: generate query from question
  attempt 2: send (question + bad_query + error) → ask for fix
  ...
  attempt N: same, but with accumulated error history
  → after MAX_ATTEMPTS, return the last query and its error

Usage
-----
    from src.rag.repair_loop import RepairLoop
    loop = RepairLoop(generator, executor)
    rows, final_query, error = loop.run("Who won the 2023 championship?")
"""

import re
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def _semantic_mismatch(question: str, sparql: str) -> str | None:
    """
    Return an error string if the query is structurally wrong for the question type.
    Returns None if no mismatch detected.
    """
    q = question.lower()
    # "how many" → must have COUNT aggregate
    if re.search(r'\bhow many\b', q) and not re.search(r'\bCOUNT\b', sparql, re.IGNORECASE):
        return (
            "The question asks 'how many' but the query has no COUNT aggregate. "
            "Use: SELECT (COUNT(?gp) AS ?wins) WHERE { ?gp ex:winner ex:DriverName ; ex:inSeason ex:SeasonYYYY . }"
        )
    # "who won … prix/gp" → must use ex:winner (not a standings/teammate pattern)
    if re.search(r'\bwho\s+won\s+the\b', q) and re.search(r'\b(?:prix|gp)\b', q):
        if not re.search(r'ex:winner\b', sparql, re.IGNORECASE) \
           and not re.search(r'ex:isChampionOf\b', sparql, re.IGNORECASE):
            return (
                "Race winner question must use ex:winner. "
                "Use: ?gp ex:inSeason ex:SeasonYYYY ; ex:name ?gpName ; ex:winner ?driver . "
                "?driver ex:name ?driverName . "
                "FILTER(CONTAINS(LCASE(?gpName), \"keyword\"))"
            )
    # "teammates" → must use two DriverStanding patterns sharing ?team
    if re.search(r'\bteammates?\b', q):
        has_two_standings = len(re.findall(r'ex:DriverStanding', sparql)) >= 2
        has_mate_bound    = bool(re.search(r'\?mate\b', sparql[sparql.lower().find('where'):], re.IGNORECASE))
        if not (has_two_standings and has_mate_bound):
            return (
                "Teammate query requires TWO DriverStanding patterns sharing ?team. "
                "Use:\n"
                "  ?s1 a ex:DriverStanding ; ex:forSeason ex:SeasonYYYY ;\n"
                "      ex:forDriver ex:DriverName ; ex:forTeam ?team .\n"
                "  ?s2 a ex:DriverStanding ; ex:forSeason ex:SeasonYYYY ;\n"
                "      ex:forDriver ?mate ; ex:forTeam ?team .\n"
                "  ?mate ex:name ?mateName .\n"
                "  FILTER(ex:DriverName != ?mate)"
            )
    # Nationality query → must filter by ex:nationality
    _nat_keywords = [
        "french", "british", "dutch", "german", "spanish", "monegasque",
        "canadian", "australian", "finnish", "thai", "mexican", "chinese",
        "japanese", "italian", "danish", "argentinian", "american",
        "brazilian", "russian", "polish", "austrian", "swedish", "belgian",
        "new zealand", "swiss",
    ]
    _nat_match = re.search(
        r'(?:give\s+me\s+(?:all\s+(?:the\s+)?)?|list\s+(?:all\s+(?:the\s+)?)?|which\s+|who\s+(?:are\s+(?:the\s+)?)?)'
        r'(' + '|'.join(_nat_keywords) + r')\s+drivers?'
        r'|drivers?\s+from\s+(?:' + '|'.join(_nat_keywords) + r')',
        q,
    )
    if _nat_match and not re.search(r'ex:nationality\b', sparql, re.IGNORECASE):
        return (
            "The question asks for drivers of a specific nationality but the query "
            "does not filter by ex:nationality. "
            "Use: ?driver ex:nationality \"ISO3\" . (e.g. \"FRA\", \"GBR\", \"NED\") "
            "Pattern: ?standing a ex:DriverStanding ; ex:forSeason ex:SeasonYYYY ; "
            "ex:forDriver ?driver . ?driver ex:name ?driverName ; ex:nationality \"ISO3\" ."
        )
    # Year mentioned in question but different (or absent) year used in query
    year_in_q = re.search(r'\b(20\d{2})\b', question)
    if year_in_q:
        q_year = year_in_q.group(1)
        years_in_sparql = re.findall(r'\bex:Season(\d{4})\b', sparql)
        if years_in_sparql and all(y != q_year for y in years_in_sparql):
            wrong = ', '.join(sorted(set(years_in_sparql)))
            return (
                f"The question asks about {q_year} but the query uses Season{wrong}. "
                f"Replace every ex:Season{wrong.split(',')[0].strip()} with ex:Season{q_year}."
            )
    return None


def _unbound_select_vars(sparql: str) -> list[str]:
    """Return SELECT variables that are never bound in the WHERE clause."""
    select_match = re.search(r'SELECT\b(.*?)WHERE\b', sparql, re.IGNORECASE | re.DOTALL)
    if not select_match:
        return []
    select_clause = select_match.group(1)
    # Skip COUNT/aggregates
    select_vars = re.findall(r'\?(\w+)', select_clause)
    where_block  = sparql[select_match.end():]
    unbound = []
    for var in select_vars:
        # A variable is "bound" if it appears in the WHERE block
        if not re.search(r'\?' + var + r'\b', where_block):
            unbound.append(var)
    return unbound

def _try_variants(executor, queries: list[str]) -> tuple[list[dict], str, str | None]:
    """
    Execute SPARQL queries in order; return the first non-empty result.

    Returns (rows, winning_query, None) on success, or
    ([], last_query, error_or_empty_msg) if all variants fail.
    """
    last_error: str | None = None
    for q in queries:
        rows, error = executor.run(q)
        if error is None and rows:
            return rows, q, None
        last_error = error
    return [], queries[-1], last_error or "No data found in the knowledge base for this question."


MAX_ATTEMPTS = 3

REPAIR_PROMPT_TEMPLATE = """The following SPARQL query for the F1 Knowledge Graph failed with a syntax error.

Common mistakes:
- Missing SELECT keyword: the query MUST have the form: PREFIX ex: ... SELECT ?vars WHERE {{ ... }}
  Do NOT output bare triple patterns — always wrap them in SELECT ?vars WHERE {{ ... }}
- Using AND between triple patterns: ?d ex:name ?n AND ex:drivesFor ?t  →  use semicolon: ?d ex:name ?n ; ex:drivesFor ?t .
- Missing PREFIX: always start with PREFIX ex: <http://example.org/f1#>
- Using STRINGS() or FILTER REGEX: use FILTER(CONTAINS(LCASE(?var), "text")) instead
- Selecting ?winner without binding it: must have ex:winner ?driver . ?driver ex:name ?driverName .

Question: {question}

Bad SPARQL:
{bad_query}

Error: {error}

Write a corrected SPARQL SELECT query starting with PREFIX ex: <http://example.org/f1#>
Return ONLY the SPARQL query, no explanation, no markdown.
"""

EMPTY_REPAIR_TEMPLATE = """The following SPARQL query returned no results for this question.

Question: {question}

SPARQL that returned empty results:
{bad_query}

DIAGNOSTIC HINTS — pick the pattern that matches the question:

▸ Race winner ("who won the [RACE] in [YEAR]"):
    ?gp ex:inSeason ex:SeasonYYYY ;
        ex:name ?gpName ;
        ex:winner ?driver .
    ?driver ex:name ?driverName .
    FILTER(CONTAINS(LCASE(?gpName), "keyword"))
  NOTE: use ex:inSeason (NOT ex:partOfSeason) on GrandPrix objects.

▸ Season champion ("who won the [YEAR] championship"):
    ?driver ex:isChampionOf ex:SeasonYYYY ;
            ex:name ?driverName .

▸ Teammates ("who were X's teammates in [YEAR]"):
    ?s1 a ex:DriverStanding ; ex:forSeason ex:SeasonYYYY ;
        ex:forDriver ex:DriverName ; ex:forTeam ?team .
    ?s2 a ex:DriverStanding ; ex:forSeason ex:SeasonYYYY ;
        ex:forDriver ?mate ; ex:forTeam ?team .
    ?mate ex:name ?mateName .
    FILTER(ex:DriverName != ?mate)

▸ Driver's team in a year:
    ?standing a ex:DriverStanding ;
              ex:forSeason ex:SeasonYYYY ;
              ex:forDriver ex:DriverName ;
              ex:forTeam ?team .
    ?team ex:name ?teamName .

RULES:
- If the question names a year YYYY, the query MUST use ex:SeasonYYYY.
- Driver/team URIs are CamelCase: ex:MaxVerstappen, ex:RedBullRacing.
- NEVER use FILTER on driver/team variables — only on string names (ex:name).
- Every variable in SELECT must appear in WHERE.

Return ONLY the corrected SPARQL query starting with PREFIX ex: <http://example.org/f1#>
"""


class RepairLoop:
    """
    Wraps SPARQLGenerator + SPARQLExecutor in a self-repair retry loop.
    """

    def __init__(self, generator, executor, max_attempts: int = MAX_ATTEMPTS):
        self.generator    = generator
        self.executor     = executor
        self.max_attempts = max_attempts

    def run(
        self, question: str
    ) -> tuple[list[dict], str, Optional[str]]:
        """
        Execute with up to max_attempts self-repair iterations.

        First tries the deterministic query_router (regex-based, no LLM).
        Falls through to the LLM generator only if the router doesn't match
        or its query returns an error.

        Returns
        -------
        (rows, final_query, final_error)
        rows        : list of result dicts (empty on failure)
        final_query : the last generated SPARQL string
        final_error : None on success, error string otherwise
        """
        # ── Step 0: deterministic router (avoids LLM hallucinations on common patterns)
        try:
            from src.rag.query_router import route as _route
            routed_query = _route(question)
        except Exception as exc:
            logger.warning(f"[router] Error during routing: {exc}")
            routed_query = None

        if routed_query:
            rows, used_query, error = _try_variants(self.executor, routed_query)
            if rows:
                logger.info(f"[router] Matched — {len(rows)} row(s) — skipping LLM")
                return rows, used_query, None
            logger.warning(f"[router] All variants failed — falling through to LLM")

        # ── Step 1 onwards: LLM-based generation + repair loop
        query = self.generator.generate(question)
        logger.debug(f"[attempt 1] Generated SPARQL:\n{query}")

        # Ollama was offline at generation time — fail fast, no repair possible
        if query == "__OLLAMA_OFFLINE__":
            return [], "", "Ollama is not running. Start Ollama and run: ollama pull llama3.2:1b"

        for attempt in range(1, self.max_attempts + 1):
            # Pre-check 1: detect missing SELECT/ASK keyword — bare triple patterns
            if not re.search(r'\b(SELECT|ASK|CONSTRUCT|DESCRIBE)\b', query, re.IGNORECASE):
                logger.info(f"[attempt {attempt}] Missing SELECT keyword — forcing repair")
                error = "Missing SELECT keyword. The query must start with PREFIX then SELECT. Do not output bare triple patterns."
                rows  = []
            # Pre-check 2: detect SELECT variables never bound in WHERE
            elif _unbound_select_vars(query):
                unbound = _unbound_select_vars(query)
                logger.info(f"[attempt {attempt}] Unbound SELECT vars {unbound} — forcing repair")
                error = f"Unbound SELECT variables: {unbound}. Every variable in SELECT must appear in WHERE."
                rows  = []
            # Pre-check 3: semantic mismatch (how many → no COUNT, teammates → no ?mateName)
            elif _semantic_mismatch(question, query):
                error = _semantic_mismatch(question, query)
                logger.info(f"[attempt {attempt}] Semantic mismatch — forcing repair: {error}")
                rows  = []
            else:
                rows, error = self.executor.run(query)

            if error is None and rows:
                logger.info(f"[attempt {attempt}] Success — {len(rows)} rows")
                return rows, query, None

            if error is None and not rows:
                # Query executed but empty result — try to relax
                if attempt == self.max_attempts:
                    logger.warning(f"[attempt {attempt}] Empty results — giving up")
                    return [], query, "No data found in the knowledge base for this question."
                logger.info(f"[attempt {attempt}] Empty results — requesting repair")
                repair_prompt = EMPTY_REPAIR_TEMPLATE.format(
                    question=question, bad_query=query
                )
            else:
                if attempt == self.max_attempts:
                    logger.warning(f"[attempt {attempt}] SPARQL error — giving up: {error}")
                    return [], query, error
                logger.info(f"[attempt {attempt}] SPARQL error — requesting repair: {error}")
                repair_prompt = REPAIR_PROMPT_TEMPLATE.format(
                    question=question, bad_query=query, error=error
                )

            # Ask the LLM to fix the query (use full system prompt with CRITICAL rules)
            from src.rag.sparql_generator import SYSTEM_PROMPT_TEMPLATE
            full_system = SYSTEM_PROMPT_TEMPLATE.format(schema=self.generator.schema)
            messages = [
                {"role": "system", "content": full_system},
                {"role": "user",   "content": repair_prompt},
            ]
            raw = self.generator._call_ollama(messages)
            if raw is None:
                return [], query, "Ollama is not running. Start Ollama and run: ollama pull llama3.2:1b"
            query = self.generator._extract_sparql(raw)
            logger.debug(f"[attempt {attempt + 1}] Repaired SPARQL:\n{query}")

        # Should not reach here
        return [], query, "Max attempts exceeded"
