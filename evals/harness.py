"""
Eval harness core — production-style evaluation for Donna's AI surfaces.

Concepts (mirrors how production AI teams run evals):

- **Suite** — one evaluated capability (scribe pre-check, retrieval, …),
  registered via ``@suite(name, requires=...)``. Runs against a versioned
  golden dataset in ``evals/datasets/`` and returns metrics + failures.
- **Requirements** — suites declare what they need ("openai",
  "local-embedder"). Missing requirement → the suite SKIPS with a reason
  instead of erroring, so the deterministic core always runs (CI, laptops,
  no API keys).
- **Baselines** — ``evals/baselines.json`` holds committed metric floors
  (and ceilings). ``--gate`` turns violations into a non-zero exit: a
  change that silently degrades decision detection fails CI the same way
  a broken unit test would.
- **Artifacts** — every run writes JSON to ``evals/results/`` (gitignored)
  stamped with git SHA + timestamp, so runs are comparable over time.
"""

from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

EVALS_DIR = Path(__file__).parent
DATASETS_DIR = EVALS_DIR / "datasets"
RESULTS_DIR = EVALS_DIR / "results"
BASELINES_PATH = EVALS_DIR / "baselines.json"

# Suites with no external dependencies — always runnable, always gated.
DETERMINISTIC = (
    "scribe_precheck",
    "factcheck_precheck",
    "activation",
    "agenda_coverage",
    "flow",
    "groundedness",
)


@dataclass
class SuiteResult:
    name: str
    status: str = "ok"  # ok | skipped | error
    metrics: Dict[str, float] = field(default_factory=dict)
    n_cases: int = 0
    failures: List[Dict[str, Any]] = field(default_factory=list)
    notes: str = ""
    duration_s: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "metrics": self.metrics,
            "n_cases": self.n_cases,
            "failures": self.failures[:10],  # sample, not the firehose
            "notes": self.notes,
            "duration_s": round(self.duration_s, 2),
        }


_REGISTRY: Dict[str, Tuple[Callable[[], Awaitable[SuiteResult]], Tuple[str, ...]]] = {}


def suite(name: str, requires: Tuple[str, ...] = ()):
    """Register an async suite function under ``name``."""

    def decorator(fn: Callable[[], Awaitable[SuiteResult]]):
        _REGISTRY[name] = (fn, requires)
        return fn

    return decorator


def registered_suites() -> List[str]:
    return list(_REGISTRY.keys())


def requirement_missing(req: str) -> Optional[str]:
    """Human-readable reason a requirement is unmet, or None if satisfied."""
    if req == "openai":
        from apps.api.core.config import settings

        if not settings.openai_api_key:
            return "OPENAI_API_KEY not set"
        return None
    if req == "local-embedder":
        try:
            import sentence_transformers  # noqa: F401
        except ImportError:
            return "sentence-transformers not installed"
        return None
    if req == "qdrant":
        return None  # checked at runtime by the suite itself
    return f"unknown requirement '{req}'"


async def run_suite(name: str) -> SuiteResult:
    fn, requires = _REGISTRY[name]
    for req in requires:
        reason = requirement_missing(req)
        if reason:
            return SuiteResult(name=name, status="skipped", notes=reason)
    start = time.perf_counter()
    try:
        result = await fn()
    except Exception as e:
        return SuiteResult(
            name=name,
            status="error",
            notes=f"{type(e).__name__}: {e}"[:300],
            duration_s=time.perf_counter() - start,
        )
    result.duration_s = time.perf_counter() - start
    return result


def load_dataset(filename: str) -> List[Dict[str, Any]]:
    path = DATASETS_DIR / filename
    cases = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            cases.append(json.loads(line))
    return cases


# -- Baselines ---------------------------------------------------------------


def load_baselines() -> Dict[str, Dict[str, Dict[str, float]]]:
    if BASELINES_PATH.exists():
        return json.loads(BASELINES_PATH.read_text())
    return {}


def gate_violations(
    results: List[SuiteResult],
    baselines: Dict[str, Dict[str, Dict[str, float]]],
) -> List[str]:
    """Every way this run is worse than the committed floors/ceilings."""
    violations = []
    for r in results:
        if r.status != "ok":
            if r.status == "error" and r.name in baselines:
                violations.append(f"{r.name}: errored ({r.notes})")
            continue
        for metric, bounds in baselines.get(r.name, {}).items():
            value = r.metrics.get(metric)
            if value is None:
                violations.append(f"{r.name}: metric '{metric}' missing from run")
                continue
            if "min" in bounds and value < bounds["min"]:
                violations.append(
                    f"{r.name}: {metric}={value} below floor {bounds['min']}"
                )
            if "max" in bounds and value > bounds["max"]:
                violations.append(
                    f"{r.name}: {metric}={value} above ceiling {bounds['max']}"
                )
    return violations


def update_baselines(results: List[SuiteResult], margin: float = 0.05) -> None:
    """Reset floors to (observed - margin) for every ok suite. Reviewed like
    any other diff — a baseline drop must be a conscious decision."""
    baselines = load_baselines()
    for r in results:
        if r.status != "ok":
            continue
        entry = baselines.setdefault(r.name, {})
        for metric, value in r.metrics.items():
            if metric.startswith(("n_", "duration")):
                continue
            entry[metric] = {"min": round(max(0.0, value - margin), 4)}
    BASELINES_PATH.write_text(json.dumps(baselines, indent=2, sort_keys=True) + "\n")


# -- Reporting ---------------------------------------------------------------


def _git_sha() -> str:
    try:
        return (
            subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                capture_output=True,
                text=True,
                timeout=5,
            ).stdout.strip()
            or "unknown"
        )
    except Exception:
        return "unknown"


def write_artifact(results: List[SuiteResult], violations: List[str]) -> Path:
    RESULTS_DIR.mkdir(exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    sha = _git_sha()
    path = RESULTS_DIR / f"{stamp}-{sha}.json"
    path.write_text(
        json.dumps(
            {
                "timestamp": stamp,
                "git_sha": sha,
                "suites": [r.to_dict() for r in results],
                "gate_violations": violations,
            },
            indent=2,
        )
    )
    return path


def render_report(results: List[SuiteResult], violations: List[str]) -> str:
    lines = ["", "## Donna eval run", ""]
    lines.append("| Suite | Status | Cases | Metrics | Time |")
    lines.append("|---|---|---|---|---|")
    for r in results:
        metrics = " · ".join(f"{k}={v}" for k, v in r.metrics.items()) or "—"
        status = {"ok": "✅ ok", "skipped": "⏭ skipped", "error": "💥 error"}[r.status]
        note = f" ({r.notes})" if r.status != "ok" and r.notes else ""
        lines.append(
            f"| {r.name} | {status}{note} | {r.n_cases or '—'} "
            f"| {metrics} | {r.duration_s:.1f}s |"
        )
    lines.append("")
    if violations:
        lines.append("### ❌ Gate violations")
        lines.extend(f"- {v}" for v in violations)
    else:
        lines.append("### ✅ All gates green")
    lines.append("")
    return "\n".join(lines)
