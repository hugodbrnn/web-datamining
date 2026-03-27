# KGE Evaluation Report — F1 Knowledge Graph

## Model Comparison

| Model | MRR | Hits@1 | Hits@3 | Hits@10 |
|---|---|---|---|---|
| TransE | 0.0926 | 0.0273 | 0.1017 | 0.2149 |
| ComplEx | 0.1073 | 0.0628 | 0.1128 | 0.194 |

**Metrics:** filtered rank-based evaluation on test split (10%).
MRR = Mean Reciprocal Rank; Hits@k = fraction of test triples where true entity ranked ≤ k.

## Interpretation

- **TransE** is a translational model; it excels on simple, hierarchical relations.
- **ComplEx** uses complex-valued embeddings; better on antisymmetric and n-ary relations.
- Low absolute Hits@k values are expected with a small KB (~5k triples). After full Wikidata expansion (50k–200k triples), embeddings benefit from denser graph coverage.
- For deployment, prefer the model with higher Hits@10 (recall-oriented link prediction).
