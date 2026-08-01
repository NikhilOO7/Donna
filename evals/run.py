"""
Eval harness CLI.

    uv run python -m evals.run                       # run everything runnable
    uv run python -m evals.run --suites deterministic --gate   # CI gate
    uv run python -m evals.run --suites retrieval,flow
    uv run python -m evals.run --update-baselines    # reset floors from this run

Exit codes: 0 = green, 1 = gate violation (with --gate), 2 = bad usage.
"""

import argparse
import asyncio
import sys

from evals import suites as _suites  # noqa: F401 — importing registers suites
from evals.harness import (
    DETERMINISTIC,
    gate_violations,
    load_baselines,
    registered_suites,
    render_report,
    run_suite,
    update_baselines,
    write_artifact,
)


def _resolve_suite_names(arg: str) -> list:
    if arg == "all":
        return registered_suites()
    if arg == "deterministic":
        return [s for s in DETERMINISTIC if s in registered_suites()]
    names = [s.strip() for s in arg.split(",") if s.strip()]
    unknown = [s for s in names if s not in registered_suites()]
    if unknown:
        print(
            f"Unknown suite(s): {', '.join(unknown)}. "
            f"Available: {', '.join(registered_suites())}",
            file=sys.stderr,
        )
        sys.exit(2)
    return names


async def _run(names: list):
    results = []
    for name in names:
        print(f"→ {name} ...", flush=True)
        results.append(await run_suite(name))
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Donna eval harness")
    parser.add_argument(
        "--suites",
        default="all",
        help="'all', 'deterministic', or a comma-separated list",
    )
    parser.add_argument(
        "--gate",
        action="store_true",
        help="exit non-zero when any baseline floor/ceiling is violated",
    )
    parser.add_argument(
        "--update-baselines",
        action="store_true",
        help="rewrite evals/baselines.json floors from this run (observed - margin)",
    )
    args = parser.parse_args()

    names = _resolve_suite_names(args.suites)
    results = asyncio.run(_run(names))

    violations = gate_violations(results, load_baselines())
    artifact = write_artifact(results, violations)
    print(render_report(results, violations))
    print(f"Artifact: {artifact}")

    if args.update_baselines:
        update_baselines(results)
        print("Baselines updated — review the diff in evals/baselines.json")

    if args.gate and violations:
        sys.exit(1)


if __name__ == "__main__":
    main()
