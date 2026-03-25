"""
sparql_executor.py — Execute SPARQL queries against the local RDF KB
====================================================================
Loads the reasoned KB once (lazy singleton) and executes SPARQL SELECT
queries, returning results as a list of row dicts.

Usage
-----
    from src.rag.sparql_executor import SPARQLExecutor
    exec = SPARQLExecutor()
    rows, error = exec.run("SELECT ?n WHERE { ?d ex:name ?n } LIMIT 5")
"""

import logging
from pathlib import Path
from typing import Optional

from rdflib import Graph
from rdflib.exceptions import ParserError

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_KB   = PROJECT_ROOT / "kg_artifacts" / "reasoned_kb.ttl"

# Maximum rows to return (safety cap)
MAX_ROWS = 200


class SPARQLExecutor:
    """Lazy-loading SPARQL executor backed by rdflib."""

    def __init__(self, kb_path: Path = DEFAULT_KB):
        self.kb_path = kb_path
        self._graph: Optional[Graph] = None

    @property
    def graph(self) -> Graph:
        if self._graph is None:
            if not self.kb_path.exists():
                raise FileNotFoundError(
                    f"KB not found: {self.kb_path}\n"
                    "  Run: python src/reason/apply_rules.py"
                )
            logger.info(f"Loading KB from {self.kb_path} …")
            self._graph = Graph()
            self._graph.parse(self.kb_path, format="turtle")
            logger.info(f"KB loaded: {len(self._graph):,} triples")
        return self._graph

    def run(self, sparql: str) -> tuple[list[dict], Optional[str]]:
        """
        Execute a SPARQL SELECT query.

        Returns
        -------
        (rows, error_message)
        rows : list of {var: value} dicts (empty list on failure)
        error_message : None on success, string on failure
        """
        try:
            results = self.graph.query(sparql)
        except Exception as exc:
            error_str = str(exc)
            logger.warning(f"SPARQL execution error: {error_str}")
            return [], error_str

        rows = []
        for i, row in enumerate(results):
            if i >= MAX_ROWS:
                logger.warning(f"Result truncated at {MAX_ROWS} rows")
                break
            row_dict = {}
            for var in results.vars:
                val = row[var]
                if val is None:
                    row_dict[str(var)] = None
                else:
                    # Shorten URIs to local names for readability
                    val_str = str(val)
                    if "#" in val_str:
                        val_str = val_str.split("#")[-1]
                    row_dict[str(var)] = val_str
            rows.append(row_dict)

        return rows, None

    def format_results(self, rows: list[dict], max_rows: int = 20) -> str:
        """Format query results as a readable string."""
        if not rows:
            return "(no results)"
        cols = list(rows[0].keys())
        lines = [" | ".join(cols)]
        lines.append("-" * len(lines[0]))
        for row in rows[:max_rows]:
            lines.append(" | ".join(str(row.get(c, "")) for c in cols))
        if len(rows) > max_rows:
            lines.append(f"… ({len(rows) - max_rows} more rows)")
        return "\n".join(lines)

    def triple_count(self) -> int:
        """Return total triple count in the loaded graph."""
        return len(self.graph)
