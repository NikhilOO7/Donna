"""
Benchmark: retrieval relevance, traditional dense RAG vs the platform's contextual+hybrid.

Substantiates the retrieval-quality claim with real IR metrics (Recall@k, MRR, nDCG@k)
over a ground-truth corpus. This is the regression guard around the benchmark in
tests/benchmarks/retrieval_eval.py — run that module directly for the full report.

Honest finding baked into the assertions:
  - Contextual *embeddings alone* do NOT beat naive dense retrieval here (they homogenise
    chunks within a document), so we do not assert on that arm.
  - Contextual fused with lexical BM25 (the hybrid the ContextAgent runs) DOES beat naive
    dense RAG, with the gains concentrated at rank 1 (Recall@1 / nDCG@1) and in MRR.
"""

import pytest

from tests.benchmarks.retrieval_eval import format_report, run_eval


@pytest.fixture(scope="module")
def eval_results():
    pytest.importorskip("sentence_transformers")
    return run_eval()


class TestRetrievalRelevance:
    def test_hybrid_beats_naive_dense_at_rank1(self, eval_results):
        """The platform's contextual+hybrid must improve top-rank relevance over baseline."""
        base = eval_results["baseline"]
        hybrid = eval_results["contextual_hybrid"]
        print("\n" + format_report(eval_results))
        assert hybrid["recall@1"] >= base["recall@1"], "hybrid regressed Recall@1"
        assert hybrid["ndcg@1"] >= base["ndcg@1"], "hybrid regressed nDCG@1"
        assert hybrid["mrr"] >= base["mrr"], "hybrid regressed MRR"

    def test_hybrid_mean_improvement_is_positive(self, eval_results):
        """Aggregate relative lift of contextual+hybrid over baseline should be positive."""
        base = eval_results["baseline"]
        hybrid = eval_results["contextual_hybrid"]
        metrics = ["recall@1", "recall@3", "recall@5", "mrr", "ndcg@1", "ndcg@3", "ndcg@5"]
        lifts = [
            (hybrid[m] - base[m]) / base[m] for m in metrics if base[m] > 0
        ]
        mean_lift = sum(lifts) / len(lifts)
        assert mean_lift > 0, f"expected positive mean lift, got {mean_lift:.1%}"
