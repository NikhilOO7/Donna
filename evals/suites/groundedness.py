"""
Groundedness suite — is the generated sentence supported by its sources?

The gap this closes: retrieval quality was measured, but whether the answer
Donna *says* is entailed by the chunks she cites was not measured at all.
An ungrounded claim that arrives with a citation attached is more dangerous
than one without, because the citation is what makes people act on it.

Two graded outcomes, because they fail differently and cost differently:

* **detection** — of the answers a human labeled ungrounded (partial or
  contradicted), how many does the checker flag? Recall-biased on purpose:
  missing a hallucination is far worse than flagging a good answer.
* **false-alarm rate** — of the answers a human labeled supported, how many
  does the checker wrongly flag? Gated with a ceiling, because a checker
  that cries wolf gets switched off, and a switched-off checker detects
  nothing.

The checker is deterministic (no model call), so this suite runs in CI with
no API key alongside the other gates.
"""

from evals.harness import SuiteResult, load_dataset, suite
from evals.metrics import classification_metrics


@suite("groundedness")
async def groundedness() -> SuiteResult:
    """Grade the deterministic groundedness checker against human labels."""
    from apps.api.services.rag.groundedness import assess

    cases = load_dataset("groundedness.jsonl")
    pairs, failures = [], []
    hard_total = hard_correct = 0

    for c in cases:
        report = assess(c["answer"], c["context"])

        # Binary framing: "should a human look at this answer?"
        expected_flag = c["label"] in ("partial", "contradicted")
        predicted_flag = report.label in ("partial", "contradicted")
        pairs.append((expected_flag, predicted_flag))

        if c.get("hard"):
            hard_total += 1
            hard_correct += int(expected_flag == predicted_flag)

        if expected_flag != predicted_flag:
            failures.append(
                {
                    "id": c["id"],
                    "expected": c["label"],
                    "predicted": report.label,
                    "score": round(report.score, 2),
                    "answer": c["answer"][:120],
                    "why": [v.reason for v in report.claims if not v.supported][:3],
                }
            )

    metrics = classification_metrics(pairs)

    # Recall on ungrounded answers is the headline number: it is the share of
    # hallucinations the checker would actually catch.
    metrics["detection_recall"] = metrics.get("recall", 0.0)

    # False alarms, stated directly rather than inferred from precision.
    supported = [(e, p) for e, p in pairs if not e]
    metrics["false_alarm_rate"] = (
        round(sum(p for _e, p in supported) / len(supported), 4) if supported else 0.0
    )

    # Tracked, deliberately ungated: these are the semantic-entailment and
    # arithmetic cases a lexical checker is not expected to win. Publishing the
    # number keeps the suite's limits visible instead of averaging them away.
    if hard_total:
        metrics["hard_case_accuracy"] = round(hard_correct / hard_total, 4)

    return SuiteResult(
        name="groundedness",
        metrics=metrics,
        n_cases=len(cases),
        failures=failures,
        notes=(
            f"{hard_correct}/{hard_total} hard (semantic/arithmetic) cases correct — "
            "ungated by design; a lexical checker is not expected to solve entailment"
        ),
    )
