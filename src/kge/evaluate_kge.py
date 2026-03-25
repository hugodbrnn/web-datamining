"""
evaluate_kge.py — Evaluate trained KGE models and write report
==============================================================
Loads each trained model from models/<name>/ and runs link-prediction
evaluation on the test split, reporting:
  - MRR (Mean Reciprocal Rank)
  - Hits@1, Hits@3, Hits@10

Also runs a size-sensitivity analysis by training lightweight models on
sub-samples of the triple set (20k / 50k / full) — using the local
reasoned_kb.ttl at its actual size for the 'full' condition.

Usage
-----
    python src/kge/evaluate_kge.py [--models transe complex]
    python src/kge/evaluate_kge.py --size-sensitivity

Output
------
    kg_artifacts/kge/evaluation_report.md
"""

import argparse
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SPLITS_DIR   = PROJECT_ROOT / "kg_artifacts" / "kge"
MODELS_DIR   = PROJECT_ROOT / "models"
OUT_FILE     = SPLITS_DIR / "evaluation_report.md"


def load_metrics(model_dir: Path) -> dict | None:
    """Load saved PyKEEN evaluation metrics from results.json."""
    results_path = model_dir / "results.json"
    if not results_path.exists():
        return None
    with open(results_path) as f:
        data = json.load(f)
    # PyKEEN stores metrics under data["metrics"]["both"]["realistic"]
    try:
        metrics = data["metrics"]["both"]["realistic"]
        return {
            "mrr":     round(metrics.get("inverse_harmonic_mean_rank", 0), 4),
            "hits@1":  round(metrics.get("hits_at_1", 0), 4),
            "hits@3":  round(metrics.get("hits_at_3", 0), 4),
            "hits@10": round(metrics.get("hits_at_10", 0), 4),
        }
    except (KeyError, TypeError):
        return None


def evaluate_model(model_name: str) -> dict | None:
    """Evaluate a trained model against the test split."""
    try:
        from pykeen.pipeline import pipeline
        from pykeen.triples import TriplesFactory
        import torch
    except ImportError:
        print("[ERROR] PyKEEN not installed: pip install pykeen torch")
        return None

    model_dir = MODELS_DIR / model_name.lower()
    if not model_dir.exists():
        print(f"  [skip] {model_name}: not found at {model_dir}")
        print(f"          Run: python src/kge/train_kge.py --models {model_name}")
        return None

    # Try to read pre-computed metrics first (saved by train_kge.py)
    metrics = load_metrics(model_dir)
    if metrics:
        print(f"  {model_name}: loaded pre-computed metrics")
        return metrics

    # Otherwise re-evaluate
    print(f"  {model_name}: re-evaluating on test split …")
    try:
        from pykeen.models import model_resolver
        model_cls = model_resolver.lookup(model_name)
        tf_train = TriplesFactory.from_path(SPLITS_DIR / "train.tsv")
        tf_test  = TriplesFactory.from_path(
            SPLITS_DIR / "test.tsv",
            entity_to_id=tf_train.entity_to_id,
            relation_to_id=tf_train.relation_to_id,
        )
        model = model_cls(triples_factory=tf_train)
        model.load_state_dict(torch.load(model_dir / "trained_model.pkl", map_location="cpu"))
        from pykeen.evaluation import RankBasedEvaluator
        evaluator = RankBasedEvaluator()
        result = evaluator.evaluate(model, tf_test.mapped_triples,
                                    additional_filter_triples=[tf_train.mapped_triples])
        m = result.to_dict()
        return {
            "mrr":     round(m.get("both.realistic.inverse_harmonic_mean_rank", 0), 4),
            "hits@1":  round(m.get("both.realistic.hits_at_1", 0), 4),
            "hits@3":  round(m.get("both.realistic.hits_at_3", 0), 4),
            "hits@10": round(m.get("both.realistic.hits_at_10", 0), 4),
        }
    except Exception as e:
        print(f"    [ERROR] {e}")
        return None


def size_sensitivity(sizes: list[int], epochs: int = 50) -> list[dict]:
    """Train TransE on sub-samples of the full triple set."""
    try:
        from pykeen.pipeline import pipeline
        from pykeen.triples import TriplesFactory
    except ImportError:
        print("[ERROR] PyKEEN not installed: pip install pykeen torch")
        return []

    import random
    triples_file = SPLITS_DIR / "triples.tsv"
    if not triples_file.exists():
        print(f"[ERROR] {triples_file} not found. Run prepare_splits.py first.")
        return []

    with open(triples_file) as f:
        all_triples = [line.strip().split("\t") for line in f if line.strip()]

    results = []
    for size in sizes:
        actual = min(size, len(all_triples))
        label  = f"{actual:,}"
        print(f"\n  Size-sensitivity: n={label} triples …")

        sample = random.Random(42).sample(all_triples, actual)
        n = len(sample)
        n_train = int(n * 0.8)
        n_valid = int(n * 0.1)
        train_triples = sample[:n_train]
        valid_triples = sample[n_train:n_train + n_valid]
        test_triples  = sample[n_train + n_valid:]

        if len(train_triples) < 10 or len(test_triples) < 5:
            print(f"    [skip] Too few triples for meaningful evaluation")
            continue

        import tempfile, os
        with tempfile.TemporaryDirectory() as tmpdir:
            def write_tmp(name, rows):
                p = Path(tmpdir) / name
                with open(p, "w") as f:
                    for row in rows:
                        f.write("\t".join(row) + "\n")
                return p

            tf_train = TriplesFactory.from_path(write_tmp("train.tsv", train_triples))
            tf_valid = TriplesFactory.from_path(write_tmp("valid.tsv", valid_triples),
                                                entity_to_id=tf_train.entity_to_id,
                                                relation_to_id=tf_train.relation_to_id)
            tf_test  = TriplesFactory.from_path(write_tmp("test.tsv",  test_triples),
                                                entity_to_id=tf_train.entity_to_id,
                                                relation_to_id=tf_train.relation_to_id)

            try:
                r = pipeline(
                    model="TransE",
                    training=tf_train,
                    validation=tf_valid,
                    testing=tf_test,
                    training_kwargs={"num_epochs": epochs,
                                     "batch_size": min(128, len(train_triples))},
                    model_kwargs={"embedding_dim": 32},
                    evaluator_kwargs={"filtered": True},
                    random_seed=42,
                )
                m = r.metric_results.to_dict()
                results.append({
                    "size": label,
                    "mrr":     round(m.get("both.realistic.inverse_harmonic_mean_rank", 0), 4),
                    "hits@1":  round(m.get("both.realistic.hits_at_1", 0), 4),
                    "hits@3":  round(m.get("both.realistic.hits_at_3", 0), 4),
                    "hits@10": round(m.get("both.realistic.hits_at_10", 0), 4),
                })
            except Exception as e:
                print(f"    [ERROR] {e}")
                results.append({"size": label, "error": str(e)})

    return results


def write_report(model_metrics: dict, sensitivity: list):
    """Write Markdown evaluation report."""
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        f.write("# KGE Evaluation Report — F1 Knowledge Graph\n\n")

        f.write("## Model Comparison\n\n")
        f.write("| Model | MRR | Hits@1 | Hits@3 | Hits@10 |\n")
        f.write("|---|---|---|---|---|\n")
        for model, m in model_metrics.items():
            if m:
                f.write(f"| {model} | {m['mrr']} | {m['hits@1']} | {m['hits@3']} | {m['hits@10']} |\n")
            else:
                f.write(f"| {model} | – | – | – | – |\n")

        f.write("\n**Metrics:** filtered rank-based evaluation on test split (10%).\n")
        f.write("MRR = Mean Reciprocal Rank; Hits@k = fraction of test triples where true entity ranked ≤ k.\n\n")

        if sensitivity:
            f.write("## Size-Sensitivity Analysis (TransE)\n\n")
            f.write("| Triple set size | MRR | Hits@1 | Hits@3 | Hits@10 |\n")
            f.write("|---|---|---|---|---|\n")
            for row in sensitivity:
                if "error" in row:
                    f.write(f"| {row['size']} | ERROR | – | – | – |\n")
                else:
                    f.write(f"| {row['size']} | {row['mrr']} | {row['hits@1']} | {row['hits@3']} | {row['hits@10']} |\n")
            f.write("\nNote: sub-samples use a fixed random seed (42) for reproducibility.\n")
            f.write("On the local KB (≈5k triples) all size conditions collapse to the same set.\n")
            f.write("Re-run after Wikidata SPARQL expansion for meaningful size-sensitivity curves.\n\n")

        f.write("## Interpretation\n\n")
        f.write("- **TransE** is a translational model; it excels on simple, hierarchical relations.\n")
        f.write("- **ComplEx** uses complex-valued embeddings; better on antisymmetric and n-ary relations.\n")
        f.write("- Low absolute Hits@k values are expected with a small KB (~5k triples). ")
        f.write("After full Wikidata expansion (50k–200k triples), embeddings benefit from denser graph coverage.\n")
        f.write("- For deployment, prefer the model with higher Hits@10 (recall-oriented link prediction).\n")

    print(f"\n[Report] Written to {OUT_FILE}")


def main():
    parser = argparse.ArgumentParser(description="Evaluate KGE models")
    parser.add_argument("--models", nargs="+", default=["TransE", "ComplEx"],
                        help="Models to evaluate")
    parser.add_argument("--size-sensitivity", action="store_true",
                        help="Run size-sensitivity analysis")
    parser.add_argument("--epochs", type=int, default=50,
                        help="Epochs for size-sensitivity runs")
    args = parser.parse_args()

    print("=" * 60)
    print("KGE EVALUATION — F1 Knowledge Graph")
    print("=" * 60)

    # Evaluate trained models
    print(f"\n[1] Evaluating models: {args.models}")
    model_metrics = {}
    for m in args.models:
        metrics = evaluate_model(m)
        model_metrics[m] = metrics
        if metrics:
            print(f"    {m}: MRR={metrics['mrr']}  H@1={metrics['hits@1']}  H@3={metrics['hits@3']}  H@10={metrics['hits@10']}")

    # Size-sensitivity (optional)
    sensitivity = []
    if args.size_sensitivity:
        print("\n[2] Size-sensitivity analysis …")
        # Use actual KB size for 'full'; cap 20k/50k at KB size
        total = sum(1 for _ in open(SPLITS_DIR / "triples.tsv"))
        sizes = [min(20_000, total), min(50_000, total), total]
        sizes = sorted(set(sizes))
        sensitivity = size_sensitivity(sizes, epochs=args.epochs)

    write_report(model_metrics, sensitivity)

    print("\n" + "=" * 60)
    print("EVALUATION COMPLETE")
    print(f"  Report: {OUT_FILE}")
    print("=" * 60)


if __name__ == "__main__":
    main()
