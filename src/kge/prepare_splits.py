"""
prepare_splits.py — Convert the F1 KG to PyKEEN-compatible triple splits
=========================================================================
Reads the reasoned KB (kg_artifacts/reasoned_kb.ttl) and exports:
  - kg_artifacts/kge/triples.tsv   : full triple set (h TAB r TAB t)
  - kg_artifacts/kge/train.tsv     : 80 % of triples
  - kg_artifacts/kge/valid.tsv     : 10 % of triples
  - kg_artifacts/kge/test.tsv      : 10 % of triples
  - kg_artifacts/kge/splits_stats.md

Only object-property triples (URIRef → URIRef) are kept; datatype-property
triples (URIRef → Literal) are excluded because KGE models require integer
entity IDs for both head and tail.

Usage
-----
    python src/kge/prepare_splits.py [--kb path/to/kb.ttl] [--seed 42]
"""

import argparse
import csv
import random
from pathlib import Path

from rdflib import Graph, URIRef
from rdflib.namespace import RDF, OWL, RDFS

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_KB   = PROJECT_ROOT / "kg_artifacts" / "reasoned_kb.ttl"
OUT_DIR      = PROJECT_ROOT / "kg_artifacts" / "kge"

# Predicates to exclude (schema / meta / alignment noise)
EXCLUDED_PREDICATES = {
    str(RDF.type),
    str(OWL.sameAs),
    str(RDFS.label),
    str(RDFS.comment),
    str(OWL.equivalentClass),
    str(OWL.equivalentProperty),
    "http://www.w3.org/2002/07/owl#AnnotationProperty",
    "http://www.w3.org/2002/07/owl#ObjectProperty",
    "http://www.w3.org/2002/07/owl#DatatypeProperty",
}


def shorten(uri: str) -> str:
    """Return the local name of a URI (after # or last /)."""
    if "#" in uri:
        return uri.split("#")[-1]
    return uri.rstrip("/").split("/")[-1]


def load_object_triples(kb_path: Path) -> list[tuple[str, str, str]]:
    """Load all (head, relation, tail) triples where head and tail are URIs."""
    g = Graph()
    g.parse(kb_path, format="turtle")

    triples = []
    for s, p, o in g:
        if not isinstance(s, URIRef) or not isinstance(o, URIRef):
            continue
        if str(p) in EXCLUDED_PREDICATES:
            continue
        triples.append((shorten(str(s)), shorten(str(p)), shorten(str(o))))

    # Deduplicate while preserving order
    seen = set()
    unique = []
    for t in triples:
        if t not in seen:
            seen.add(t)
            unique.append(t)
    return unique


def split(triples: list, train_ratio=0.8, valid_ratio=0.1, seed=42):
    rng = random.Random(seed)
    shuffled = triples[:]
    rng.shuffle(shuffled)
    n = len(shuffled)
    n_train = int(n * train_ratio)
    n_valid = int(n * valid_ratio)
    train = shuffled[:n_train]
    valid = shuffled[n_train:n_train + n_valid]
    test  = shuffled[n_train + n_valid:]
    return train, valid, test


def write_tsv(path: Path, rows: list[tuple]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, delimiter="\t")
        for row in rows:
            writer.writerow(row)


def write_stats(out_dir: Path, all_triples, train, valid, test, kb_path: Path):
    entities  = set()
    relations = set()
    for h, r, t in all_triples:
        entities.update([h, t])
        relations.add(r)

    stats_path = out_dir / "splits_stats.md"
    with open(stats_path, "w", encoding="utf-8") as f:
        f.write("# KGE Split Statistics\n\n")
        f.write(f"**Source KB:** `{kb_path.name}`\n\n")
        f.write("## Counts\n\n")
        f.write("| Set | Triples |\n|---|---|\n")
        f.write(f"| Full (object triples) | {len(all_triples):,} |\n")
        f.write(f"| Train (80%) | {len(train):,} |\n")
        f.write(f"| Valid (10%) | {len(valid):,} |\n")
        f.write(f"| Test  (10%) | {len(test):,} |\n")
        f.write(f"\n**Unique entities:** {len(entities):,}\n")
        f.write(f"**Unique relations:** {len(relations):,}\n\n")
        f.write("## Relation distribution (top 20)\n\n")
        f.write("| Relation | Count |\n|---|---|\n")
        from collections import Counter
        rel_counts = Counter(r for _, r, _ in all_triples)
        for rel, cnt in rel_counts.most_common(20):
            f.write(f"| `{rel}` | {cnt} |\n")
    return stats_path


def main():
    parser = argparse.ArgumentParser(description="Prepare KGE triple splits")
    parser.add_argument("--kb",   default=str(DEFAULT_KB), help="Path to KB .ttl file")
    parser.add_argument("--seed", type=int, default=42,   help="Random seed")
    args = parser.parse_args()

    kb_path = Path(args.kb)
    if not kb_path.exists():
        print(f"[ERROR] KB not found: {kb_path}")
        print("  Run: python src/reason/apply_rules.py")
        return

    print("=" * 60)
    print("KGE SPLIT PREPARATION")
    print("=" * 60)
    print(f"\n[0] Loading {kb_path.name} …")

    triples = load_object_triples(kb_path)
    print(f"    Object triples extracted: {len(triples):,}")

    entities  = set(h for h, _, _ in triples) | set(t for _, _, t in triples)
    relations = set(r for _, r, _ in triples)
    print(f"    Unique entities   : {len(entities):,}")
    print(f"    Unique relations  : {len(relations):,}")

    print(f"\n[1] Splitting (80/10/10, seed={args.seed}) …")
    train, valid, test = split(triples, seed=args.seed)
    print(f"    train: {len(train):,}  valid: {len(valid):,}  test: {len(test):,}")

    print(f"\n[2] Writing TSV files to {OUT_DIR} …")
    write_tsv(OUT_DIR / "triples.tsv", triples)
    write_tsv(OUT_DIR / "train.tsv",   train)
    write_tsv(OUT_DIR / "valid.tsv",   valid)
    write_tsv(OUT_DIR / "test.tsv",    test)
    stats_path = write_stats(OUT_DIR, triples, train, valid, test, kb_path)
    print(f"    Stats: {stats_path}")

    # Also write to kge_data/ as .txt files (project submission requirement)
    kge_data_dir = PROJECT_ROOT / "kge_data"
    kge_data_dir.mkdir(parents=True, exist_ok=True)
    write_tsv(kge_data_dir / "train.txt", train)
    write_tsv(kge_data_dir / "valid.txt", valid)
    write_tsv(kge_data_dir / "test.txt",  test)
    print(f"    kge_data/ copies: train.txt  valid.txt  test.txt")

    print("\n" + "=" * 60)
    print("SPLITS READY")
    print(f"  kg_artifacts/kge/ : triples.tsv  train.tsv  valid.tsv  test.tsv")
    print(f"  kge_data/         : train.txt  valid.txt  test.txt")
    print("=" * 60)


if __name__ == "__main__":
    main()
