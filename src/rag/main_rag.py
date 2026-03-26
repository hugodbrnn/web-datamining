"""
main_rag.py — RAG pipeline entry point
=======================================
Orchestrates the full NL → SPARQL → Answer pipeline:

  1. schema_summary   : build KB schema string for LLM context
  2. sparql_generator : NL question → SPARQL query (Ollama LLM)
  3. sparql_executor  : run SPARQL against rdflib KB
  4. repair_loop      : retry up to 3× on error / empty results
  5. format answer    : present results to user

Modes
-----
  Interactive REPL  : python src/rag/main_rag.py
  Single question   : python src/rag/main_rag.py -q "Who won in 2024?"
  Demo mode         : python src/rag/main_rag.py --demo  (offline, no Ollama)
  Schema inspect    : python src/rag/main_rag.py --schema

Requirements
------------
  pip install rdflib
  + Ollama running locally: https://ollama.com   (model: mistral or llama3)
  + ollama pull mistral
"""

import argparse
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Demo mode — runs without Ollama using hardcoded SPARQL for known questions
# ─────────────────────────────────────────────────────────────────────────────

DEMO_QUESTIONS = [
    "Who won the 2024 F1 championship?",
    "Which team does Lando Norris drive for?",
    "How many races did Max Verstappen win in 2023?",
    "List all circuits in the 2025 season.",
    "Who were the teammates of Lewis Hamilton in 2024?",
]

DEMO_SPARQLS = {
    "Who won the 2024 F1 championship?": """PREFIX ex: <http://example.org/f1#>
SELECT ?driverName WHERE {
    ?driver ex:isChampionOf ex:Season2024 ;
            ex:name ?driverName .
}""",
    "Which team does Lando Norris drive for?": """PREFIX ex: <http://example.org/f1#>
SELECT ?teamName WHERE {
    ?driver ex:name "Lando Norris" ;
            ex:drivesFor ?team .
    ?team ex:name ?teamName .
}""",
    "How many races did Max Verstappen win in 2023?": """PREFIX ex: <http://example.org/f1#>
SELECT (COUNT(?gp) AS ?wins) WHERE {
    ?driver ex:name "Max Verstappen" ;
            ex:hasWon ?gp .
    ?gp ex:partOfSeason ex:Season2023 .
}""",
    "List all circuits in the 2025 season.": """PREFIX ex: <http://example.org/f1#>
SELECT DISTINCT ?circuitName WHERE {
    ex:Season2025 ex:hasRace ?gp .
    ?gp ex:heldAtCircuit ?circuit .
    ?circuit ex:name ?circuitName .
} ORDER BY ?circuitName""",
    "Who were the teammates of Lewis Hamilton in 2024?": """PREFIX ex: <http://example.org/f1#>
SELECT DISTINCT ?mateName WHERE {
    ?hamilton ex:name "Lewis Hamilton" .
    ?s1 a ex:DriverStanding ; ex:forSeason ex:Season2024 ;
        ex:forDriver ?hamilton ; ex:forTeam ?team .
    ?s2 a ex:DriverStanding ; ex:forSeason ex:Season2024 ;
        ex:forDriver ?mate   ; ex:forTeam ?team .
    ?mate ex:name ?mateName .
    FILTER(?hamilton != ?mate)
}""",
}


def run_demo(executor):
    """Run hardcoded demo questions without Ollama."""
    print("\n" + "=" * 60)
    print("RAG PIPELINE — DEMO MODE (no Ollama required)")
    print("=" * 60)
    print(f"KB: {executor.kb_path.name}  |  {executor.triple_count():,} triples\n")

    for i, question in enumerate(DEMO_QUESTIONS, 1):
        print(f"[Q{i}] {question}")
        sparql = DEMO_SPARQLS.get(question, "")
        if not sparql:
            print("     (no demo query)\n")
            continue
        rows, error = executor.run(sparql)
        if error:
            print(f"     ERROR: {error}\n")
        elif not rows:
            print("     (no results)\n")
        else:
            print(f"     Answer: {executor.format_results(rows, max_rows=5)}\n")


# ─────────────────────────────────────────────────────────────────────────────
# Live pipeline
# ─────────────────────────────────────────────────────────────────────────────

def build_pipeline(model: str, ollama_url: str):
    from src.rag.sparql_executor  import SPARQLExecutor
    from src.rag.sparql_generator import SPARQLGenerator
    from src.rag.repair_loop      import RepairLoop

    executor  = SPARQLExecutor()
    generator = SPARQLGenerator(model=model, ollama_url=ollama_url)
    loop      = RepairLoop(generator, executor)
    return executor, generator, loop


def answer_question(question: str, loop, executor, verbose: bool = False) -> str:
    """Run full pipeline and return a formatted answer string."""
    rows, final_query, error = loop.run(question)

    if verbose:
        print(f"\n[Generated SPARQL]\n{final_query}\n")

    if error:
        return f"⚠ Could not answer: {error}"
    if not rows:
        return "(no results found)"
    return executor.format_results(rows)


def interactive_mode(loop, executor, verbose: bool):
    """REPL loop for interactive questioning."""
    print("\n" + "=" * 60)
    print("F1 Knowledge Graph — RAG Question Answering")
    print("=" * 60)
    print(f"KB: {executor.kb_path.name}  |  {executor.triple_count():,} triples")
    print(f"LLM: {loop.generator.model} @ {loop.generator.ollama_url}")
    models = loop.generator.list_models()
    if models:
        print(f"Available models: {', '.join(models)}")
    print("\nType a question about F1, or 'quit' to exit.\n")

    while True:
        try:
            question = input("Q: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye!")
            break
        if not question or question.lower() in {"quit", "exit", "q"}:
            break
        answer = answer_question(question, loop, executor, verbose=verbose)
        print(f"A: {answer}\n")


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="F1 KG RAG pipeline")
    parser.add_argument("-q", "--question", help="Single question to answer")
    parser.add_argument("--demo",   action="store_true", help="Run offline demo")
    parser.add_argument("--schema", action="store_true", help="Print KB schema and exit")
    parser.add_argument("--model",  default="llama3.2:1b", help="Ollama model name")
    parser.add_argument("--ollama", default="http://localhost:11434", help="Ollama URL")
    parser.add_argument("--verbose", action="store_true", help="Show generated SPARQL")
    args = parser.parse_args()

    # Schema inspection
    if args.schema:
        from src.rag.schema_summary import get_schema_summary
        print(get_schema_summary())
        return

    # Demo mode (no Ollama)
    if args.demo:
        from src.rag.sparql_executor import SPARQLExecutor
        executor = SPARQLExecutor()
        try:
            run_demo(executor)
        except FileNotFoundError as e:
            print(f"[ERROR] {e}")
        return

    # Live pipeline
    executor, generator, loop = build_pipeline(args.model, args.ollama)

    # Check Ollama availability
    models = generator.list_models()
    if not models:
        print(
            f"[WARNING] Cannot reach Ollama at {args.ollama}\n"
            "  Start Ollama: https://ollama.com\n"
            "  Then run:     ollama pull mistral\n"
            "  Or use demo mode: python src/rag/main_rag.py --demo\n"
        )

    if args.question:
        try:
            answer = answer_question(args.question, loop, executor, verbose=args.verbose)
            print(f"Q: {args.question}\nA: {answer}")
        except FileNotFoundError as e:
            print(f"[ERROR] {e}")
    else:
        try:
            interactive_mode(loop, executor, verbose=args.verbose)
        except FileNotFoundError as e:
            print(f"[ERROR] {e}")


if __name__ == "__main__":
    main()
