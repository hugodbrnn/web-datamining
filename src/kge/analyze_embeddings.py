"""
analyze_embeddings.py — Nearest-neighbor & t-SNE analysis of trained KGE models
================================================================================
Loads a trained PyKEEN model and performs:
  1. Nearest-neighbor analysis: top-k most similar entities in embedding space
     (cosine similarity) for a set of query entities.
  2. t-SNE 2D projection with ontology-class colour coding, saved as PNG.

Usage
-----
    python src/kge/analyze_embeddings.py [--model transe] [--top-k 5]
    python src/kge/analyze_embeddings.py --model complex --top-k 10 \\
        --queries MaxVerstappen RedBullRacing Circuit_Monaco LandoNorris

Output
------
    kg_artifacts/kge/nearest_neighbors.md
    kg_artifacts/kge/tsne_embeddings.png   (requires matplotlib + scikit-learn)

Requirements
------------
    pip install pykeen torch matplotlib scikit-learn
"""

import argparse
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
MODELS_DIR   = PROJECT_ROOT / "models"
SPLITS_DIR   = PROJECT_ROOT / "kg_artifacts" / "kge"
KG_DIR       = PROJECT_ROOT / "kg_artifacts"
OUT_DIR      = SPLITS_DIR


# ---------------------------------------------------------------------------
# 1. Load entity→class mapping from the RDF KB
# ---------------------------------------------------------------------------

def load_entity_to_class(ttl_path: Path) -> dict:
    """Return {entity_uri: ontology_class_label} using rdflib."""
    from rdflib import Graph, RDF, URIRef
    g = Graph()
    g.parse(ttl_path, format="turtle")
    mapping = {}
    for s, _, o in g.triples((None, RDF.type, None)):
        if isinstance(s, URIRef):
            cls = str(o).split("#")[-1].split("/")[-1]
            mapping[str(s)] = cls
    return mapping


# ---------------------------------------------------------------------------
# 2. Load trained model and extract entity embeddings
# ---------------------------------------------------------------------------

def get_entity_embeddings(model_dir: Path):
    """Load a trained PyKEEN model; return (embeddings ndarray, id→uri, uri→id)."""
    import torch
    from pykeen.models import model_resolver
    from pykeen.triples import TriplesFactory

    with open(model_dir / "training_summary.json") as f:
        summary = json.load(f)
    model_name = summary["model"]

    tf = TriplesFactory.from_path(SPLITS_DIR / "train.tsv")

    model_cls = model_resolver.lookup(model_name)
    model = model_cls(triples_factory=tf)
    model.load_state_dict(
        torch.load(model_dir / "trained_model.pkl", map_location="cpu")
    )
    model.eval()

    with torch.no_grad():
        # Both TransE and ComplEx expose entity_representations[0]
        all_ids    = torch.arange(tf.num_entities)
        embeddings = model.entity_representations[0](all_ids).numpy()

    id_to_entity = {v: k for k, v in tf.entity_to_id.items()}
    return embeddings, id_to_entity, tf.entity_to_id


# ---------------------------------------------------------------------------
# 3. Cosine-similarity matrix
# ---------------------------------------------------------------------------

def cosine_similarity_matrix(embeddings):
    """Return (N, N) cosine-similarity matrix."""
    import numpy as np
    norms  = np.linalg.norm(embeddings, axis=1, keepdims=True)
    norms  = np.where(norms == 0, 1e-9, norms)
    normed = embeddings / norms
    return normed @ normed.T


# ---------------------------------------------------------------------------
# 4. Nearest-neighbor retrieval
# ---------------------------------------------------------------------------

def nearest_neighbors(
    query_names: list,
    entity_to_id: dict,
    sim_matrix,
    id_to_entity: dict,
    top_k: int = 5,
) -> dict:
    """
    For each query string, find the entity whose URI contains that string,
    then return its top-k nearest neighbors by cosine similarity.
    """
    results = {}
    for name in query_names:
        # Case-insensitive substring match on URI
        candidates = [k for k in entity_to_id if name.lower() in k.lower()]
        if not candidates:
            print(f"  [warn] '{name}' not found in entity map")
            continue
        uri = candidates[0]
        idx = entity_to_id[uri]
        sims    = sim_matrix[idx]
        top_idx = sims.argsort()[::-1][1 : top_k + 1]
        neighbors = [
            (id_to_entity[i], round(float(sims[i]), 4)) for i in top_idx
        ]
        results[uri] = neighbors
        short = uri.split("#")[-1].split("/")[-1]
        print(f"\n  Nearest neighbors of {short}:")
        for n_uri, score in neighbors:
            n_short = n_uri.split("#")[-1].split("/")[-1]
            print(f"    {n_short:<40} cos={score:.4f}")
    return results


# ---------------------------------------------------------------------------
# 5. t-SNE clustering plot
# ---------------------------------------------------------------------------

def run_tsne(
    embeddings,
    id_to_entity: dict,
    entity_to_class: dict,
    out_png: Path,
):
    """Run t-SNE on entity embeddings and save a class-coloured scatter plot."""
    try:
        import numpy as np
        from sklearn.manifold import TSNE
        import matplotlib
        matplotlib.use("Agg")  # headless backend
        import matplotlib.pyplot as plt
    except ImportError:
        print("[skip] t-SNE requires scikit-learn and matplotlib — skipping plot")
        return

    print("\n  Running t-SNE (perplexity=30, n_iter=1000) …")
    tsne   = TSNE(n_components=2, perplexity=30, n_iter=1000, random_state=42)
    coords = tsne.fit_transform(embeddings)

    class_labels  = [
        entity_to_class.get(id_to_entity[i], "Other")
        for i in range(len(id_to_entity))
    ]
    unique_classes = sorted(set(class_labels))
    cmap           = plt.cm.get_cmap("tab10", len(unique_classes))
    color_map      = {c: cmap(i) for i, c in enumerate(unique_classes)}
    colors         = [color_map[c] for c in class_labels]

    fig, ax = plt.subplots(figsize=(12, 9))
    for cls in unique_classes:
        mask = [i for i, c in enumerate(class_labels) if c == cls]
        ax.scatter(
            coords[mask, 0], coords[mask, 1],
            c=[color_map[cls]], label=cls, s=8, alpha=0.6,
        )
    ax.legend(markerscale=3, fontsize=9, loc="best")
    ax.set_title("t-SNE of F1 KG Entity Embeddings (dim=64, 2D projection)")
    ax.set_xlabel("Component 1")
    ax.set_ylabel("Component 2")
    fig.tight_layout()
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png, dpi=150)
    print(f"  Saved: {out_png}")
    plt.close()


# ---------------------------------------------------------------------------
# 6. Write Markdown nearest-neighbor report
# ---------------------------------------------------------------------------

def write_nn_report(nn_results: dict, model_name: str, top_k: int, out_md: Path):
    out_md.parent.mkdir(parents=True, exist_ok=True)
    with open(out_md, "w", encoding="utf-8") as f:
        f.write("# Nearest-Neighbor Analysis — F1 KG Embeddings\n\n")
        f.write(f"**Model:** {model_name} (dim=64, epochs=100).  ")
        f.write("**Similarity metric:** cosine.\n\n")
        for uri, neighbors in nn_results.items():
            label = uri.split("#")[-1].split("/")[-1]
            f.write(f"## {label}\n\n")
            f.write(f"| Rank | Entity | Cosine similarity |\n")
            f.write(f"|---|---|---|\n")
            for rank, (n_uri, score) in enumerate(neighbors, 1):
                n_label = n_uri.split("#")[-1].split("/")[-1]
                f.write(f"| {rank} | {n_label} | {score:.4f} |\n")
            f.write("\n")
    print(f"  Saved: {out_md}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Nearest-neighbor and t-SNE analysis of trained KGE models"
    )
    parser.add_argument(
        "--model", default="transe",
        help="Model directory name under models/ (default: transe)",
    )
    parser.add_argument("--top-k", type=int, default=5, help="Neighbours to retrieve")
    parser.add_argument(
        "--queries", nargs="+",
        default=["MaxVerstappen", "RedBullRacing", "Circuit_Monaco", "LandoNorris"],
        help="Entity name fragments to query (substring match on URI)",
    )
    args = parser.parse_args()

    try:
        import torch  # noqa: F401
        from pykeen.models import model_resolver  # noqa: F401
    except ImportError:
        print("[ERROR] PyKEEN/torch not installed: pip install pykeen torch")
        return

    model_dir = MODELS_DIR / args.model
    if not model_dir.exists():
        print(f"[ERROR] Model not found: {model_dir}")
        print(f"         Run: python src/kge/train_kge.py --models {args.model}")
        return

    print("=" * 60)
    print(f"EMBEDDING ANALYSIS — {args.model.upper()}")
    print("=" * 60)

    # Load embeddings
    embeddings, id_to_entity, entity_to_id = get_entity_embeddings(model_dir)
    print(f"\n  Entities: {len(id_to_entity)}  |  Embedding dim: {embeddings.shape[1]}")

    # Cosine-similarity matrix
    sim_matrix = cosine_similarity_matrix(embeddings)

    # Nearest neighbors
    print("\n[1] Nearest Neighbors")
    nn_results = nearest_neighbors(
        args.queries, entity_to_id, sim_matrix, id_to_entity, args.top_k
    )
    with open(model_dir / "training_summary.json") as f:
        model_name = json.load(f)["model"]
    write_nn_report(
        nn_results, model_name, args.top_k,
        OUT_DIR / "nearest_neighbors.md",
    )

    # t-SNE
    print("\n[2] t-SNE Clustering")
    entity_class: dict = {}
    ttl_candidates = sorted(KG_DIR.glob("*.ttl"))
    if ttl_candidates:
        try:
            entity_class = load_entity_to_class(ttl_candidates[0])
        except Exception as e:
            print(f"  [warn] Could not load ontology classes: {e}")
    run_tsne(embeddings, id_to_entity, entity_class, OUT_DIR / "tsne_embeddings.png")

    print("\n" + "=" * 60)
    print("ANALYSIS COMPLETE")
    print(f"  {OUT_DIR / 'nearest_neighbors.md'}")
    print(f"  {OUT_DIR / 'tsne_embeddings.png'}")
    print("=" * 60)


if __name__ == "__main__":
    main()
