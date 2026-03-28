"""
sparql_generator.py — NL → SPARQL via Ollama LLM
=================================================
Sends a natural-language question + KB schema to a local Ollama model
and returns a SPARQL SELECT query string.

The generator follows a structured few-shot prompt pattern:
  1. System prompt : schema summary + query constraints
  2. Few-shot examples : 3 NL→SPARQL pairs
  3. User message : the question to answer

Supported backends
------------------
- Ollama (local)   : default, uses http://localhost:11434
- Fallback         : returns a minimal SELECT stub (when Ollama is offline)

Usage
-----
    from src.rag.sparql_generator import SPARQLGenerator
    gen = SPARQLGenerator()
    query = gen.generate("Who won the 2024 championship?")
"""

import re
import json
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_KB   = PROJECT_ROOT / "kg_artifacts" / "reasoned_kb.ttl"

OLLAMA_URL    = "http://localhost:11434"
DEFAULT_MODEL = "llama3.2:1b"   # small, fast; alternatives: gemma:2b, deepseek-r1:1.5b

SYSTEM_PROMPT_TEMPLATE = """You are a SPARQL expert for a Formula 1 Knowledge Graph.
Your task: given a natural-language question, output ONE valid SPARQL SELECT query — nothing else.

Rules:
- Use only PREFIX ex: <http://example.org/f1#>
- Use only classes and properties defined in the schema below
- Return ONLY the SPARQL query, starting with PREFIX — no explanation, no markdown fences
- Entity names use CamelCase with no spaces (ex:MaxVerstappen, ex:Season2024, ex:LewisHamilton)
- End every triple pattern group with a period (.) before starting a new subject
- ALWAYS use the EXACT driver/team name from the question — NEVER substitute another name

══════════════════════════════════════════════════
DECISION TREE — read before writing any query:
══════════════════════════════════════════════════

① "Who won the [YEAR] championship/title?" → USE ex:isChampionOf
  SELECT ?driverName WHERE {{
      ?driver ex:isChampionOf ex:SeasonYYYY ;
              ex:name ?driverName . }}

② "Who won the [RACE NAME] Grand Prix in [YEAR]?" → USE ex:winner + ex:inSeason + FILTER on GP name
  SELECT ?driverName WHERE {{
      ?gp ex:inSeason ex:SeasonYYYY ;
          ex:name ?gpName ;
          ex:winner ?driver .
      ?driver ex:name ?driverName .
      FILTER(CONTAINS(LCASE(?gpName), "keyword")) }}

③ "How many races did [DRIVER] win in [YEAR]?" → USE ex:winner (GP→Driver) + COUNT + ex:inSeason
  SELECT (COUNT(?gp) AS ?wins) WHERE {{
      ?gp ex:winner ex:DriverName ;
          ex:inSeason ex:SeasonYYYY . }}

④ "Did [DRIVER] win a race in [YEAR]? / Which races did [DRIVER] win?" → USE ex:winner + ex:inSeason
  SELECT ?gpName WHERE {{
      ?gp ex:winner ex:DriverName ;
          ex:inSeason ex:SeasonYYYY ;
          ex:name ?gpName . }}

⑤ "Who were [DRIVER]'s teammates in [YEAR]?" → USE DriverStanding with forTeam
  SELECT DISTINCT ?mateName WHERE {{
      ?s1 a ex:DriverStanding ; ex:forSeason ex:SeasonYYYY ;
          ex:forDriver ex:DriverName ; ex:forTeam ?team .
      ?s2 a ex:DriverStanding ; ex:forSeason ex:SeasonYYYY ;
          ex:forDriver ?mate ; ex:forTeam ?team .
      ?mate ex:name ?mateName .
      FILTER(ex:DriverName != ?mate) }}

⑥ "Which team does [DRIVER] drive for in [YEAR]?" → USE DriverStanding with forTeam + forSeason
  SELECT DISTINCT ?teamName WHERE {{
      ?standing a ex:DriverStanding ;
                ex:forSeason ex:SeasonYYYY ;
                ex:forDriver ex:DriverName ;
                ex:forTeam ?team .
      ?team ex:name ?teamName . }}

⑦ "What are the standings in [YEAR]?" → USE DriverStanding (NO FILTER unless asked)
  SELECT ?driverName ?position ?points WHERE {{
      ?standing a ex:DriverStanding ;
                ex:forSeason ex:SeasonYYYY ;
                ex:forDriver ?driver ;
                ex:standingPosition ?position ;
                ex:standingPoints ?points .
      ?driver ex:name ?driverName .
  }} ORDER BY ?position

⑧ "What was [DRIVER]'s standing position in [YEAR]?" → USE DriverStanding FILTER by driver URI
  SELECT ?position ?points WHERE {{
      ?standing a ex:DriverStanding ;
                ex:forSeason ex:SeasonYYYY ;
                ex:forDriver ex:DriverName ;
                ex:standingPosition ?position ;
                ex:standingPoints ?points . }}

⑨ "From which country does [DRIVER] come from?" / "[DRIVER]'s nationality?" → USE ex:fromCountry or ex:nationality
  SELECT ?countryName WHERE {{
      ex:DriverName ex:fromCountry ?country .
      ?country ex:name ?countryName . }}
  — OR for nationality code —
  SELECT ?nationality WHERE {{
      ex:DriverName ex:nationality ?nationality . }}

⑩ "Which driver won the most races in [YEAR]?" → USE ex:winner (GP→Driver) + COUNT + ex:inSeason
  SELECT ?driverName (COUNT(?gp) AS ?wins) WHERE {{
      ?gp ex:winner ?driver ;
          ex:inSeason ex:SeasonYYYY .
      ?driver ex:name ?driverName .
  }} GROUP BY ?driverName ORDER BY DESC(?wins) LIMIT 1

⑪ "Who finished [N]th in the [YEAR] championship?" → USE DriverStanding FILTER by position number
  SELECT ?driverName ?points WHERE {{
      ?standing a ex:DriverStanding ;
                ex:forSeason ex:SeasonYYYY ;
                ex:forDriver ?driver ;
                ex:standingPosition ?pos ;
                ex:standingPoints ?points .
      ?driver ex:name ?driverName .
      FILTER(?pos = N) }}

⑫ "Which races were held in [YEAR]?" → USE ex:hasRace
  SELECT ?gpName ?raceDate WHERE {{
      ex:SeasonYYYY ex:hasRace ?gp .
      ?gp ex:name ?gpName .
      OPTIONAL {{ ?gp ex:raceDate ?raceDate . }}
  }} ORDER BY ?raceDate

══════════════════════════════════════════════════
CRITICAL RULES:
══════════════════════════════════════════════════
- EVERY variable in SELECT must be bound in the WHERE clause — NEVER use a variable in SELECT that does not appear in WHERE
- If the question contains a 4-digit year (for example 2017, 2024, 2025), you MUST use that year in the query
- NEVER ignore a 4-digit year mentioned in the question
- For GrandPrix objects: ALWAYS use ex:inSeason (NOT ex:partOfSeason) to link to a season
- For DriverStanding: use ex:forSeason to link to a season
- GP names include the year: "2023 Italian Grand Prix" → FILTER keyword: "italian"
- To find race winner: use ?gp ex:winner ?driver (GP has the winner, not the driver)
- NEVER use ex:hasWon — use ex:winner instead: ?gp ex:winner ex:DriverName ; ex:inSeason ex:SeasonYYYY
- NEVER apply FILTER(CONTAINS()) to resource variables (?driver, ?gp, ?team, ?circuit)
- NEVER use ex:teammateOf to find a team — use DriverStanding pattern (⑤)
- NEVER confuse ex:isChampionOf (season title) with ex:winner (single race winner)
- NEVER substitute a driver name: if question says "Gasly", write "Pierre Gasly", not "Max Verstappen"
- For "which team does X drive for in YEAR" → use DriverStanding pattern (⑥), NOT ex:drivesFor
- Triple patterns: use semicolons (;) to chain same subject, period (.) between different subjects
- NEVER use string literal matching like ex:name "Max Verstappen" to find champion — use ex:isChampionOf

{schema}
"""

FEW_SHOT_TEMPLATE = """Q: {question}
SPARQL:
{sparql}
"""


class SPARQLGenerator:
    """Generate SPARQL from natural language using a local Ollama model."""

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        ollama_url: str = OLLAMA_URL,
        kb_path: Path = DEFAULT_KB,
        temperature: float = 0.0,
        timeout: int = 180,
    ):
        self.model       = model
        self.ollama_url  = ollama_url.rstrip("/")
        self.kb_path     = kb_path
        self.temperature = temperature
        self.timeout     = timeout
        self._schema_str: Optional[str] = None

    @property
    def schema(self) -> str:
        if self._schema_str is None:
            from src.rag.schema_summary import get_schema_summary, EXAMPLE_QUERIES
            self._schema_str = get_schema_summary(self.kb_path, include_examples=False)
            self._examples = EXAMPLE_QUERIES
        return self._schema_str

    def _build_messages(self, question: str) -> list[dict]:
        """Build Ollama chat messages list."""
        from src.rag.schema_summary import EXAMPLE_QUERIES

        system = SYSTEM_PROMPT_TEMPLATE.format(schema=self.schema)

        messages = [{"role": "system", "content": system}]
        for ex in EXAMPLE_QUERIES[:15]:
            messages.append({"role": "user",      "content": ex["question"]})
            messages.append({"role": "assistant", "content": ex["sparql"]})

        messages.append({"role": "user", "content": question})
        return messages

    def _call_ollama(self, messages: list[dict]) -> Optional[str]:
        """POST to Ollama chat API. Returns raw text or None."""
        import urllib.request
        import urllib.error

        url     = f"{self.ollama_url}/api/chat"
        payload = json.dumps({
            "model":    self.model,
            "messages": messages,
            "stream":   False,
            "options":  {"temperature": self.temperature},
        }).encode("utf-8")

        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = json.loads(resp.read().decode("utf-8"))
                return body["message"]["content"].strip()
        except urllib.error.URLError as e:
            logger.warning(f"Ollama unavailable ({e})")
            return None
        except TimeoutError as e:
            logger.warning(f"Ollama timed out ({e})")
            return None
        except (KeyError, json.JSONDecodeError) as e:
            logger.warning(f"Ollama response parse error: {e}")
            return None

    @staticmethod
    def _sanitize_sparql(sparql: str) -> str:
        """Fix common LLM hallucinations so rdflib can parse the query."""
        # STRINGS(?x) CONTAINS("y") → CONTAINS(LCASE(?x), "y")
        sparql = re.sub(
            r'FILTER\s*\(\s*STRINGS?\s*\(\s*(\?\w+)\s*\)\s*CONTAINS\s*\(\s*(["\'][^"\']*["\'])[^)]*\)\s*\)',
            lambda m: f'FILTER(CONTAINS(LCASE({m.group(1)}), {m.group(2)}))',
            sparql, flags=re.IGNORECASE
        )
        # STR(?x) CONTAINS("y") → CONTAINS(LCASE(STR(?x)), "y")
        sparql = re.sub(
            r'FILTER\s*\(\s*(STR\s*\(\s*\?\w+\s*\))\s*CONTAINS\s*\(\s*(["\'][^"\']*["\'])[^)]*\)\s*\)',
            lambda m: f'FILTER(CONTAINS(LCASE({m.group(1)}), {m.group(2)}))',
            sparql, flags=re.IGNORECASE
        )
        # Remaining STRINGS( → STR(
        sparql = re.sub(r'\bSTRINGS\s*\(', 'STR(', sparql, flags=re.IGNORECASE)
        # FILTER REGEX(?x, "y") without "i" flag → CONTAINS(LCASE(?x), "y")
        sparql = re.sub(
            r'FILTER\s+REGEX\s*\(\s*(\?\w+)\s*,\s*(["\'][^"\']*["\'])\s*\)',
            lambda m: f'FILTER(CONTAINS(LCASE({m.group(1)}), {m.group(2).lower()}))',
            sparql, flags=re.IGNORECASE
        )
        # FILTER REGEX(STR(?x), "y") → FILTER(CONTAINS(LCASE(STR(?x)), "y"))
        sparql = re.sub(
            r'FILTER\s+REGEX\s*\(\s*(STR\s*\(\s*\?\w+\s*\))\s*,\s*(["\'][^"\']*["\'])\s*\)',
            lambda m: f'FILTER(CONTAINS(LCASE({m.group(1)}), {m.group(2).lower()}))',
            sparql, flags=re.IGNORECASE
        )
        # Fix wrong property names (common LLM hallucinations)
        sparql = re.sub(r'\bex:standingPos\b',   'ex:standingPosition', sparql)
        sparql = re.sub(r'\bex:position\b',      'ex:standingPosition', sparql)
        sparql = re.sub(r'\bex:rank\b',          'ex:standingPosition', sparql)
        sparql = re.sub(r'\bex:pts\b',           'ex:standingPoints',   sparql)
        sparql = re.sub(r'\bex:totalPoints\b',   'ex:standingPoints',   sparql)
        sparql = re.sub(r'\bex:hasWins\b',       'ex:hasWon',           sparql)
        sparql = re.sub(r'\bex:wins\b',          'ex:hasWon',           sparql)
        # KB uses ex:inSeason (not ex:partOfSeason) on local GP objects.
        # Convert "?gp ex:partOfSeason" → "?gp ex:inSeason"
        # BUT keep "ex:forSeason" unchanged (used on DriverStanding, not GP)
        sparql = re.sub(r'(\?\w+\s+)ex:partOfSeason\b', r'\1ex:inSeason', sparql)
        sparql = re.sub(r'ex:partOfSeason\b(\s+ex:Season)', r'ex:inSeason\1', sparql)
        # Convert ex:DriverName ex:hasWon ?gp → ?gp ex:winner ex:DriverName
        def _rewrite_has_won(m: re.Match) -> str:
            driver_uri = m.group(1).strip()
            gp_var     = m.group(2).strip()
            return f'{gp_var} ex:winner {driver_uri} ;'
        sparql = re.sub(
            r'(ex:\w+)\s+ex:hasWon\s+(\?\w+)\s*[.;]',
            _rewrite_has_won, sparql,
        )
        # Fix bare year URI: ex:2023 → ex:Season2023
        sparql = re.sub(r'\bex:(\d{4})\b', r'ex:Season\1', sparql)
        # Fix CamelCase driver/team names inside string literals: "LandoNorris" → "Lando Norris"
        sparql = re.sub(
            r'"([A-Z][a-z]+[A-Z][a-zA-Z]*)"',
            lambda m: '"' + re.sub(r'([a-z])([A-Z])', r'\1 \2', m.group(1)) + '"',
            sparql
        )
        # Fix SELECT ?winner when WHERE binds ?driverName via ex:name — replace in SELECT only
        if re.search(r'SELECT[^{]*\?winner', sparql, re.IGNORECASE):
            where_block = sparql[sparql.lower().find('where'):]
            if re.search(r'\?driver\w*\s+ex:name\s+\?driverName', where_block, re.IGNORECASE) \
               or re.search(r'ex:name\s+\?driverName', where_block, re.IGNORECASE):
                sparql = re.sub(r'(?i)(SELECT\b.*?)\?winner\b', r'\1?driverName', sparql,
                                count=1, flags=re.DOTALL)
        # Remove FILTER(CONTAINS()) on *Name variables when the keyword looks like a person's name
        # (i.e. no space, title-cased, not a known race/location keyword)
        def _is_person_keyword(m: re.Match) -> str:
            var, keyword = m.group(1), m.group(2).strip('"\'').lower()
            location_words = {'italian','monaco','british','belgian','dutch','japanese',
                              'bahrain','spanish','canadian','austrian','hungarian','singapore',
                              'brazil','mexico','abu','vegas','qatar','saudi','china','miami',
                              'monza','silverstone','spa','suzuka','imola','baku','austin'}
            if keyword in location_words:
                return m.group(0)   # keep it — it's a valid race filter
            if 'name' in var.lower() and keyword not in location_words:
                return ''           # remove — likely a wrong person-name filter
            return m.group(0)
        sparql = re.sub(
            r'\s*FILTER\s*\(\s*CONTAINS\s*\(\s*LCASE\s*\(\s*(\?\w+Name)\s*\)\s*,\s*(["\'][^"\']+["\'])\s*\)\s*\)',
            _is_person_keyword, sparql, flags=re.IGNORECASE
        )
        # Add missing period between triple-pattern groups:
        # detects a line ending without . ; { } followed by a new ?var line
        sparql = re.sub(r'([^\s.;{}])([ \t]*)\n([ \t]+\?)', r'\1 .\n\3', sparql)
        # AND/OR between triple patterns → semicolon (SPARQL uses ; not AND)
        sparql = re.sub(r'\s+AND\s+', ' ;\n    ', sparql, flags=re.IGNORECASE)
        sparql = re.sub(r'\s+OR\s+(?=\?)', ' UNION { ', sparql, flags=re.IGNORECASE)
        # Fix PREFIX ex: without URI — LLM sometimes outputs "PREFIX ex: " (no <...>)
        # Must run before any other PREFIX check.
        sparql = re.sub(
            r'\bPREFIX\s+ex:\s*(?!<)',
            'PREFIX ex: <http://example.org/f1#>\n',
            sparql,
        )
        # Remove Turtle-style semicolons after PREFIX declarations (LLM hallucination)
        sparql = re.sub(r'(PREFIX\s+\w+:\s+<[^>]+>)\s*;', r'\1', sparql)
        # Remove orphan bare-URI lines emitted by LLM (e.g. " <http://example.org/f1#>;")
        # These appear between PREFIX block and SELECT, causing parse errors.
        sparql = re.sub(r'(?m)^\s*<[^>]+>\s*;?\s*$', '', sparql)
        # Remove FILTER(CONTAINS(...)) applied to resource variables (URIs, not strings)
        # e.g. FILTER(CONTAINS(LCASE(?driver), "italian")) makes no sense on a URI
        sparql = re.sub(
            r'\s*FILTER\s*\(\s*CONTAINS\s*\(\s*LCASE\s*\(\s*'
            r'\?(driver|gp|circuit|team|season|result|standing|country)\s*\)'
            r'\s*,\s*[^)]+\)\s*\)',
            '', sparql, flags=re.IGNORECASE
        )
        # Fix SELECT * → replace with actual variables bound in WHERE
        if re.search(r'SELECT\s+\*', sparql, re.IGNORECASE):
            where_m = re.search(r'\{(.*)\}', sparql, re.DOTALL)
            if where_m:
                bound_vars = list(dict.fromkeys(re.findall(r'\?(\w+)', where_m.group(1))))
                # Exclude variables used only inside FILTER / aggregate subexpressions
                filter_only = set(re.findall(r'FILTER\s*\([^)]*\?(\w+)', where_m.group(1), re.IGNORECASE))
                select_vars = [v for v in bound_vars if v not in filter_only]
                if select_vars:
                    sparql = re.sub(
                        r'SELECT\s+\*',
                        'SELECT ' + ' '.join(f'?{v}' for v in select_vars),
                        sparql, count=1, flags=re.IGNORECASE,
                    )

        # Fix ?position in SELECT when WHERE only binds ?pos (and vice-versa)
        select_m = re.search(r'SELECT\b(.*?)WHERE\b', sparql, re.IGNORECASE | re.DOTALL)
        if select_m:
            where_block = sparql[select_m.end():]
            sel_clause  = select_m.group(1)
            where_vars  = set(re.findall(r'\?(\w+)', where_block))
            # Common alias pairs the LLM mixes up
            alias_pairs = [('position', 'pos'), ('points', 'pts'), ('name', 'n')]
            for wanted, actual in alias_pairs:
                if wanted in sel_clause and wanted not in where_vars and actual in where_vars:
                    sparql = re.sub(
                        r'(?<!\w)\?' + wanted + r'(?!\w)',
                        '?' + actual,
                        sparql, count=1,
                    )

        # Ensure PREFIX ex: is present
        if 'ex:' in sparql and 'PREFIX ex:' not in sparql:
            sparql = 'PREFIX ex: <http://example.org/f1#>\n' + sparql
        # If the query has no SELECT/ASK/CONSTRUCT keyword at all, wrap it.
        if not re.search(r'\b(SELECT|ASK|CONSTRUCT|DESCRIBE)\b', sparql, re.IGNORECASE):
            sparql = re.sub(r'^(PREFIX[^\n]*\n)', r'\1SELECT * WHERE {\n', sparql,
                            flags=re.IGNORECASE)
            sparql = sparql.rstrip() + '\n}'
        # If there's WHERE but no SELECT (e.g. tinyllama outputs "WHERE { FILTER(...) }")
        elif re.search(r'\bWHERE\b', sparql, re.IGNORECASE) and \
             not re.search(r'\b(SELECT|ASK|CONSTRUCT|DESCRIBE)\b', sparql[:sparql.lower().find('where')], re.IGNORECASE):
            sparql = re.sub(r'(PREFIX[^\n]*\n)', r'\1', sparql, flags=re.IGNORECASE)
            sparql = re.sub(r'(\bWHERE\b)', r'SELECT * WHERE', sparql, count=1, flags=re.IGNORECASE)
        return sparql

    @staticmethod
    def _extract_sparql(raw: str) -> str:
        """Extract the SPARQL query from LLM output, strip fences, sanitize."""
        fenced = re.search(r"```(?:sparql)?\s*(.*?)```", raw, re.DOTALL | re.IGNORECASE)
        sparql = fenced.group(1).strip() if fenced else raw.strip()
        # Strip any preamble text before PREFIX or SELECT (LLM sometimes adds "Here is the query:")
        m = re.search(r'(PREFIX\b|SELECT\b)', sparql, re.IGNORECASE)
        if m:
            sparql = sparql[m.start():]
        return SPARQLGenerator._sanitize_sparql(sparql)

    @staticmethod
    def _year_correct(sparql: str, question: str) -> str:
        """
        If the question contains exactly one 4-digit year and the LLM used a
        different year in the query, replace all Season URIs with the correct one.
        This guards against the common hallucination where llama3.2:1b substitutes
        the current/most-recent year for the one actually stated in the question.
        """
        years_in_q = re.findall(r'\b(20\d{2})\b', question)
        if len(years_in_q) != 1:
            return sparql  # ambiguous or no year — leave unchanged
        correct = years_in_q[0]
        years_in_sparql = set(re.findall(r'\bex:Season(\d{4})\b', sparql))
        if not years_in_sparql or correct in years_in_sparql:
            return sparql  # already correct or no Season URI present
        return re.sub(r'\bex:Season\d{4}\b', f'ex:Season{correct}', sparql)

    def generate(self, question: str) -> str:
        """
        Generate a SPARQL query for the given NL question via the Ollama LLM.
        Returns a SPARQL string (may be a fallback stub if Ollama is offline).
        """
        messages = self._build_messages(question)
        raw      = self._call_ollama(messages)

        if raw is None:
            logger.warning("Ollama offline — cannot generate SPARQL")
            return "__OLLAMA_OFFLINE__"

        sparql = self._extract_sparql(raw)
        sparql = self._year_correct(sparql, question)
        return sparql

    @staticmethod
    def _fallback_stub(question: str) -> str:
        """Minimal SPARQL stub returned when the LLM is unavailable."""
        return (
            "PREFIX ex: <http://example.org/f1#>\n"
            "# FALLBACK: Ollama offline — could not generate SPARQL\n"
            f"# Question: {question}\n"
            "SELECT ?s ?p ?o WHERE { ?s ?p ?o } LIMIT 5"
        )

    def list_models(self) -> list[str]:
        """List available Ollama models (for diagnostics)."""
        import urllib.request, urllib.error
        try:
            url = f"{self.ollama_url}/api/tags"
            with urllib.request.urlopen(url, timeout=5) as resp:
                data = json.loads(resp.read())
                return [m["name"] for m in data.get("models", [])]
        except Exception:
            return []
