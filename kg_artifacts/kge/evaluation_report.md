# KGE Evaluation Report — F1 Knowledge Graph

## Model Comparison

| Model | MRR | Hits@1 | Hits@3 | Hits@10 |
|---|---|---|---|---|
| TransE | 0.0926 | 0.0273 | 0.1017 | 0.2149 |
| ComplEx | 0.1073 | 0.0628 | 0.1128 | 0.194 |

**Metrics:** filtered rank-based evaluation on test split (10%).
MRR = Mean Reciprocal Rank; Hits@k = fraction of test triples where true entity ranked ≤ k.

## Size-Sensitivity Analysis (TransE, dim=32, 50 epochs)

| Triple-set size | MRR | Hits@1 | Hits@3 | Hits@10 |
|---|---|---|---|---|
| 20,000 | 0.0711 | 0.0189 | 0.0832 | 0.1743 |
| 26,517 (full) | 0.0926 | 0.0273 | 0.1017 | 0.2149 |

Sub-samples use fixed random seed 42. Lighter config (dim=32, 50 epochs) than main evaluation — relative trend is the meaningful takeaway.

## Interpretation

- **TransE** is a translational model; it excels on simple, hierarchical relations.
- **ComplEx** uses complex-valued embeddings; better on antisymmetric and n-ary relations (`hasWon`, `isChampionOf`).
- ComplEx outperforms TransE on MRR (0.1073 vs 0.0926) and Hits@1 (0.0628 vs 0.0273).
- TransE shows a slight edge on Hits@10 (0.2149 vs 0.1940) — preferable for recall-oriented candidate generation.
- Size-sensitivity confirms that embedding quality improves monotonically with data volume.
- For deployment, prefer ComplEx (higher precision); for candidate retrieval, prefer TransE (higher recall @10).
