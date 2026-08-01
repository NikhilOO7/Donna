# Donna Eval Harness

Production-style evaluation for every AI surface in Donna. The same idea
as unit tests, one level up: **golden datasets + metric floors, gated in
CI**, so a prompt tweak or regex change that silently degrades agent
quality fails the build the way a broken function would.

## Run it

```bash
uv run python -m evals.run                              # everything runnable
uv run python -m evals.run --suites deterministic --gate  # what CI runs
uv run python -m evals.run --suites retrieval,flow
uv run python -m evals.run --update-baselines           # reset floors from this run
```

Every run writes a JSON artifact to `evals/results/` (gitignored) stamped
with git SHA + timestamp, and prints a markdown report.

## The suites

| Suite | What it grades | Needs |
|---|---|---|
| `scribe_precheck` | The regex gate that decides when a decision *might* have been made (recall-biased: a missed decision costs more than a wasted LLM call) | nothing |
| `factcheck_precheck` | The claim gate — checkable facts vs opinions | nothing |
| `activation` | Expertise matcher: right person activated, nobody spammed | nothing |
| `agenda_coverage` | Lexical agenda matcher: is this item actually being discussed? | nothing |
| `flow` | Meeting-flow judgment: dominance + no-decision-yet calls | nothing |
| `retrieval` | IR quality (Recall@k / MRR / nDCG) of the contextual+BM25 hybrid, **and its lift over naive dense RAG** — the hybrid must keep beating the baseline | local embedder (offline) |
| `scribe_llm` | The LLM extraction *behind* the scribe gate, on the same conditional distribution production sees | `OPENAI_API_KEY` |

Suites with unmet requirements **skip with a reason**; suites that error
(e.g. exhausted API quota) show up loudly as errors — never as silent
passes. Errors only trip the gate once the suite has committed baselines.

## The workflow this enables

1. Change an agent (prompt, regex, threshold).
2. `uv run python -m evals.run --suites deterministic` — see exactly which
   golden cases you won or lost, by ID.
3. Fix or accept; when metrics improve, `--update-baselines` ratchets the
   floors up (observed − 0.05 margin). The baselines diff is reviewed
   like any other code change — a floor *drop* must be a conscious call.

This loop already paid for itself on day one: the first run exposed that
`$99`-style claims never matched the fact-check gate (a `\b` can't sit
between a space and `$`), that "consider it done" wasn't decision
language, and that "we should probably think about it" *was* — all fixed
and now locked in by the floors.

## Extending

- **New cases**: append JSONL lines to `evals/datasets/*.jsonl` (label by
  human judgment, not by what the code currently does — honest datasets
  include cases the implementation gets wrong).
- **New suite**: add a module under `evals/suites/`, decorate an async
  function with `@suite("name", requires=(...))`, return a `SuiteResult`,
  import it in `evals/suites/__init__.py`, and run `--update-baselines`.
- **LLM-judged suites** follow the `scribe_llm` pattern: declare
  `requires=("openai",)` and evaluate the same conditional path
  production runs.

## Enforcement points

- **CI**: `evals.run --suites deterministic --gate` is a blocking step.
- **pytest**: `tests/unit/test_eval_gates.py` runs the same gates, so a
  plain local `pytest tests/` catches regressions too.
