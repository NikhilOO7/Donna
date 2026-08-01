"""
The eval harness's deterministic gates, enforced from pytest.

This makes `pytest tests/` sufficient to catch an agent-quality
regression even where CI doesn't invoke `evals.run` directly — the same
suites, datasets, and committed baselines in evals/baselines.json.
"""

import pytest

from evals import suites as _suites  # noqa: F401 — registers suites
from evals.harness import DETERMINISTIC, gate_violations, load_baselines, run_suite


@pytest.mark.asyncio
async def test_deterministic_eval_gates_hold():
    results = [await run_suite(name) for name in DETERMINISTIC]

    for r in results:
        assert r.status == "ok", f"suite {r.name} did not run: {r.notes}"

    violations = gate_violations(results, load_baselines())
    assert not violations, "Eval gate violations:\n" + "\n".join(violations)
