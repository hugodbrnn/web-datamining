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

import logging
from typing import Optional

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 3

REPAIR_PROMPT_TEMPLATE = """The following SPARQL query for the F1 Knowledge Graph failed.

Question: {question}

Bad SPARQL:
{bad_query}

Error: {error}

Please write a corrected SPARQL SELECT query that answers the question.
Return ONLY the SPARQL query, no explanation.
"""

EMPTY_REPAIR_TEMPLATE = """The following SPARQL query returned no results.

Question: {question}

SPARQL query that returned empty results:
{bad_query}

The KB uses CamelCase URIs (e.g. ex:MaxVerstappen, ex:Season2024, ex:BahrainGP2023).
Please try a more flexible version using FILTER, REGEX, or OPTIONAL.
Return ONLY the corrected SPARQL query.
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

        Returns
        -------
        (rows, final_query, final_error)
        rows        : list of result dicts (empty on failure)
        final_query : the last generated SPARQL string
        final_error : None on success, error string otherwise
        """
        query = self.generator.generate(question)
        logger.debug(f"[attempt 1] Generated SPARQL:\n{query}")

        for attempt in range(1, self.max_attempts + 1):
            rows, error = self.executor.run(query)

            if error is None and rows:
                logger.info(f"[attempt {attempt}] Success — {len(rows)} rows")
                return rows, query, None

            if error is None and not rows:
                # Query executed but empty result — try to relax
                if attempt == self.max_attempts:
                    logger.warning(f"[attempt {attempt}] Empty results — giving up")
                    return [], query, "Query returned no results"
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

            # Ask the LLM to fix the query
            messages = [
                {"role": "system",    "content": self.generator.schema},
                {"role": "user",      "content": repair_prompt},
            ]
            raw = self.generator._call_ollama(messages)
            if raw is None:
                return [], query, "Ollama offline during repair"
            query = self.generator._extract_sparql(raw)
            logger.debug(f"[attempt {attempt + 1}] Repaired SPARQL:\n{query}")

        # Should not reach here
        return [], query, "Max attempts exceeded"
