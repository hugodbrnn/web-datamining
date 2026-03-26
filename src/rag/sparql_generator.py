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
- Return ONLY the SPARQL query, no explanation, no markdown fences
- Entity names in the KB use CamelCase with no spaces (e.g. ex:MaxVerstappen, ex:Season2024)
- Use OPTIONAL for properties that may not be present

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
        timeout: int = 60,
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
        for ex in EXAMPLE_QUERIES[:3]:
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
        return sparql

    @staticmethod
    def _extract_sparql(raw: str) -> str:
        """Extract the SPARQL query from LLM output, strip fences, sanitize."""
        fenced = re.search(r"```(?:sparql)?\s*(.*?)```", raw, re.DOTALL | re.IGNORECASE)
        sparql = fenced.group(1).strip() if fenced else raw.strip()
        return SPARQLGenerator._sanitize_sparql(sparql)

    def generate(self, question: str) -> str:
        """
        Generate a SPARQL query for the given NL question.
        Returns a SPARQL string (may be a fallback stub if Ollama is offline).
        """
        messages = self._build_messages(question)
        raw      = self._call_ollama(messages)

        if raw is None:
            logger.warning("Ollama offline — returning fallback SPARQL stub")
            return self._fallback_stub(question)

        return self._extract_sparql(raw)

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
