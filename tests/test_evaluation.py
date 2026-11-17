"""The evaluation script runs end to end and the keyword baseline finds most answers."""

from evaluation.eval_retrieval import evaluate


def test_retrieval_evaluation_runs_with_hash_baseline():
    result = evaluate(top_k=3, chunk_size=300, chunk_overlap=50, verbose=False)

    assert result["questions"] == 15
    assert result["embedding_model"].startswith("hash:")
    # Keyword matching is a weak baseline; real embeddings should score higher
    assert result["hit@3"] >= 0.5
    assert 0 < result["mrr"] <= 1
