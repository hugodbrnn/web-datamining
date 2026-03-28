"""
app.py — Local web interface for the F1 Knowledge Graph RAG pipeline
====================================================================
Provides a browser-based demo with:
  - RAG Q&A (NL → SPARQL → Answer via Ollama)
  - Demo mode (5 hardcoded questions, no Ollama needed)
  - KB schema & statistics visualization

Usage
-----
    python src/rag/app.py
    # then open http://localhost:5000
"""

import sys
import logging
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from flask import Flask, render_template, request, jsonify

app = Flask(__name__)
logging.basicConfig(level=logging.WARNING)

# ── Demo data (5 questions, no Ollama needed) ────────────────────────────────

DEMO_QUESTIONS = [
    "Who won the 2024 F1 championship?",
    "Which team does Pierre Gasly drive for in 2021?",
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
    "Which team does Pierre Gasly drive for in 2021?": """PREFIX ex: <http://example.org/f1#>
SELECT DISTINCT ?teamName WHERE {
    ?standing a ex:DriverStanding ;
              ex:forSeason ex:Season2021 ;
              ex:forDriver ex:PierreGasly ;
              ex:forTeam ?team .
    ?team ex:name ?teamName .
}""",
    "How many races did Max Verstappen win in 2023?": """PREFIX ex: <http://example.org/f1#>
SELECT (COUNT(?gp) AS ?wins) WHERE {
    ex:MaxVerstappen ex:hasWon ?gp .
    ?gp ex:inSeason ex:Season2023 .
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

# ── Config (set at startup) ──────────────────────────────────────────────────

_model    = "llama3.2:1b"   # overridden by --model CLI arg
_executor = None
_pipeline = None        # (executor, generator, loop)


def get_executor():
    global _executor
    if _executor is None:
        from src.rag.sparql_executor import SPARQLExecutor
        _executor = SPARQLExecutor()
    return _executor


def get_pipeline():
    global _pipeline
    if _pipeline is None:
        from src.rag.sparql_executor  import SPARQLExecutor
        from src.rag.sparql_generator import SPARQLGenerator
        from src.rag.repair_loop      import RepairLoop
        executor  = SPARQLExecutor()
        generator = SPARQLGenerator(model=_model)
        loop      = RepairLoop(generator, executor)
        _pipeline = (executor, generator, loop)
    return _pipeline


# ── Routes ───────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/ask", methods=["POST"])
def ask():
    data     = request.get_json(silent=True) or {}
    question = data.get("question", "").strip()
    if not question:
        return jsonify({"error": "Empty question"}), 400

    try:
        executor, generator, loop = get_pipeline()
        rows, final_query, error  = loop.run(question)
    except FileNotFoundError as exc:
        return jsonify({"error": str(exc)}), 503
    except Exception as exc:
        return jsonify({"error": f"Pipeline error: {exc}"}), 500

    if error:
        return jsonify({"error": error, "sparql": final_query})

    return jsonify({
        "rows":   rows[:20],
        "sparql": final_query,
        "count":  len(rows),
    })


@app.route("/api/demo")
def demo():
    """Run the 5 hardcoded demo questions (no Ollama needed)."""
    try:
        executor = get_executor()
    except FileNotFoundError as exc:
        return jsonify({"error": str(exc)}), 503

    results = []
    for question in DEMO_QUESTIONS:
        sparql = DEMO_SPARQLS.get(question, "")
        if not sparql:
            continue
        rows, error = executor.run(sparql)
        results.append({
            "question": question,
            "sparql":   sparql,
            "rows":     rows[:50],
            "error":    error,
        })
    return jsonify(results)


@app.route("/api/evaluate")
def evaluate():
    """
    Stream baseline vs RAG results row by row using Server-Sent Events.
    Each question emits one SSE event as soon as it completes — no waiting
    for the full batch.
    """
    import json as _json
    from flask import Response, stream_with_context
    from src.rag.main_rag import EVAL_QUESTIONS, baseline_answer

    def generate():
        try:
            executor, generator, loop = get_pipeline()
        except FileNotFoundError as exc:
            yield f"data: {_json.dumps({'error': str(exc)})}\n\n"
            return

        if not generator.list_models():
            yield (
                "data: " +
                _json.dumps({"error": "Ollama not reachable. Start Ollama and run: ollama pull llama3.2:1b"}) +
                "\n\n"
            )
            return

        # Signal total count so the UI can show a progress bar
        yield f"data: {_json.dumps({'total': len(EVAL_QUESTIONS)})}\n\n"

        for idx, question in enumerate(EVAL_QUESTIONS):
            base = baseline_answer(question, generator)

            kb_rows, final_query, error = loop.run(question)
            if error:
                rag_ans = f"ERROR: {error}"
            elif not kb_rows:
                rag_ans = "(no results)"
            else:
                rag_ans = executor.format_compact_results(kb_rows, max_rows=5)

            row = {
                "idx":      idx,
                "question": question,
                "baseline": base,
                "rag":      rag_ans,
                "sparql":   final_query or "",
                "error":    error,
            }
            yield f"data: {_json.dumps(row)}\n\n"

        yield "data: {\"done\": true}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control":  "no-cache",
            "X-Accel-Buffering": "no",   # disable Nginx buffering if proxied
        },
    )


@app.route("/api/schema")
def schema():
    """Return KB statistics + class/property breakdown for the Schema tab."""
    from src.rag.schema_summary import get_kb_stats, STATIC_SCHEMA

    try:
        executor = get_executor()
        stats    = get_kb_stats()
    except FileNotFoundError as exc:
        return jsonify({"error": str(exc)}), 503

    cls_q = """PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
SELECT ?cls (COUNT(?s) AS ?count) WHERE {
    ?s rdf:type ?cls .
    FILTER(STRSTARTS(STR(?cls), "http://example.org/f1#"))
} GROUP BY ?cls ORDER BY DESC(?count)"""
    cls_rows, _ = executor.run(cls_q)

    prop_q = """SELECT ?p (COUNT(*) AS ?count) WHERE {
    ?s ?p ?o .
    FILTER(STRSTARTS(STR(?p), "http://example.org/f1#"))
} GROUP BY ?p ORDER BY DESC(?count) LIMIT 20"""
    prop_rows, _ = executor.run(prop_q)

    return jsonify({
        "stats":       stats,
        "classes":     cls_rows,
        "properties":  prop_rows,
        "schema_text": STATIC_SCHEMA,
    })


# ── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="F1 KG web demo")
    parser.add_argument("--model",  default="llama3.2:1b",        help="Ollama model (default: llama3.2:1b)")
    parser.add_argument("--port",   default=5000, type=int,       help="Port (default: 5000)")
    parser.add_argument("--ollama", default="http://localhost:11434", help="Ollama URL")
    args = parser.parse_args()

    _model = args.model

    print("\n" + "=" * 55)
    print("  F1 Knowledge Graph — Web Demo")
    print(f"  http://localhost:{args.port}")
    print("=" * 55)
    print(f"  KB  : kg_artifacts/reasoned_kb.ttl")
    print(f"  LLM : {args.model} @ {args.ollama}")
    print( "  Demo tab works without Ollama")
    print("=" * 55 + "\n")
    app.run(debug=False, port=args.port)
