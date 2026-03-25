"""
train_kge.py — Train TransE and ComplEx KGE models with PyKEEN
==============================================================
Trains two KGE models on the F1 KG triple splits and saves:
  - models/transe/   : trained TransE model + training losses
  - models/complex/  : trained ComplEx model + training losses

Usage
-----
    python src/kge/train_kge.py [--epochs 100] [--dim 64] [--lr 0.01]

Requirements
------------
    pip install pykeen torch
"""

import argparse
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SPLITS_DIR   = PROJECT_ROOT / "kg_artifacts" / "kge"
MODELS_DIR   = PROJECT_ROOT / "models"


def check_splits():
    required = ["train.tsv", "valid.tsv", "test.tsv"]
    missing = [f for f in required if not (SPLITS_DIR / f).exists()]
    if missing:
        raise FileNotFoundError(
            f"Missing split files: {missing}\n"
            "  Run: python src/kge/prepare_splits.py"
        )


def train_model(model_name: str, splits_dir: Path, out_dir: Path,
                epochs: int, embedding_dim: int, learning_rate: float):
    """Train a single KGE model and save it."""
    try:
        from pykeen.pipeline import pipeline
        from pykeen.triples import TriplesFactory
    except ImportError:
        print(
            "[ERROR] PyKEEN not installed.\n"
            "  Install with: pip install pykeen torch"
        )
        return None

    print(f"\n  Training {model_name} (dim={embedding_dim}, lr={learning_rate}, epochs={epochs}) …")

    tf_train = TriplesFactory.from_path(splits_dir / "train.tsv")
    tf_valid = TriplesFactory.from_path(
        splits_dir / "valid.tsv",
        entity_to_id=tf_train.entity_to_id,
        relation_to_id=tf_train.relation_to_id,
    )
    tf_test  = TriplesFactory.from_path(
        splits_dir / "test.tsv",
        entity_to_id=tf_train.entity_to_id,
        relation_to_id=tf_train.relation_to_id,
    )

    result = pipeline(
        model=model_name,
        training=tf_train,
        validation=tf_valid,
        testing=tf_test,
        training_kwargs={
            "num_epochs": epochs,
            "batch_size": min(256, len(tf_train.mapped_triples)),
        },
        model_kwargs={"embedding_dim": embedding_dim},
        optimizer_kwargs={"lr": learning_rate},
        evaluator_kwargs={"filtered": True},
        random_seed=42,
    )

    out_dir.mkdir(parents=True, exist_ok=True)
    result.save_to_directory(out_dir)

    # Save a human-readable summary
    summary = {
        "model": model_name,
        "embedding_dim": embedding_dim,
        "learning_rate": learning_rate,
        "epochs": epochs,
        "num_entities": tf_train.num_entities,
        "num_relations": tf_train.num_relations,
        "num_training_triples": len(tf_train.mapped_triples),
        "num_validation_triples": len(tf_valid.mapped_triples),
        "num_testing_triples": len(tf_test.mapped_triples),
    }
    with open(out_dir / "training_summary.json", "w") as f:
        json.dump(summary, f, indent=2)

    print(f"    → Saved to {out_dir}")
    return result


def main():
    parser = argparse.ArgumentParser(description="Train KGE models")
    parser.add_argument("--epochs", type=int,   default=100,  help="Training epochs")
    parser.add_argument("--dim",    type=int,   default=64,   help="Embedding dimension")
    parser.add_argument("--lr",     type=float, default=0.01, help="Learning rate")
    parser.add_argument("--models", nargs="+",  default=["TransE", "ComplEx"],
                        help="Model names (e.g. TransE ComplEx RotatE)")
    args = parser.parse_args()

    print("=" * 60)
    print("KGE TRAINING — F1 Knowledge Graph")
    print("=" * 60)
    print(f"  Models  : {args.models}")
    print(f"  Epochs  : {args.epochs}")
    print(f"  Dim     : {args.dim}")
    print(f"  LR      : {args.lr}")

    try:
        check_splits()
    except FileNotFoundError as e:
        print(f"[ERROR] {e}")
        return

    results = {}
    for model_name in args.models:
        out_dir = MODELS_DIR / model_name.lower()
        result  = train_model(
            model_name=model_name,
            splits_dir=SPLITS_DIR,
            out_dir=out_dir,
            epochs=args.epochs,
            embedding_dim=args.dim,
            learning_rate=args.lr,
        )
        if result is not None:
            results[model_name] = result

    print("\n" + "=" * 60)
    print("TRAINING COMPLETE")
    for name in results:
        print(f"  {name}: {MODELS_DIR / name.lower()}")
    print("=" * 60)
    print("\nNext step: python src/kge/evaluate_kge.py")


if __name__ == "__main__":
    main()
