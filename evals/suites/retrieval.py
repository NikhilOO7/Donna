"""
Retrieval-quality suite — wraps the offline IR benchmark.

Runs the three-arm comparison from tests/benchmarks/retrieval_eval.py
(naive dense vs contextual vs the platform's contextual+BM25 hybrid) over
the committed ground-truth corpus, using a local SentenceTransformer —
no API calls. The gated metrics are the platform arm's absolute quality
AND its lift over naive RAG: if a retrieval change makes the hybrid stop
beating the baseline, the gate trips.
"""

import asyncio

from evals.harness import SuiteResult, suite


@suite("retrieval", requires=("local-embedder",))
async def retrieval() -> SuiteResult:
    from tests.benchmarks.retrieval_eval import run_eval

    # Model inference is sync + CPU-heavy — keep it off the event loop.
    results = await asyncio.to_thread(run_eval)

    hybrid = results["contextual_hybrid"]
    baseline = results["baseline"]
    metrics = {
        "hybrid_recall@1": round(hybrid["recall@1"], 4),
        "hybrid_recall@5": round(hybrid["recall@5"], 4),
        "hybrid_mrr": round(hybrid["mrr"], 4),
        "hybrid_ndcg@5": round(hybrid["ndcg@5"], 4),
        "mrr_lift_vs_naive": round(hybrid["mrr"] - baseline["mrr"], 4),
        "recall1_lift_vs_naive": round(hybrid["recall@1"] - baseline["recall@1"], 4),
    }
    return SuiteResult(
        name="retrieval",
        metrics=metrics,
        n_cases=0,
        notes="arms: naive dense · contextual · contextual+BM25 (platform)",
    )
