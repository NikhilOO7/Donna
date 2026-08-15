"""
Deterministic agent suites — the zero-dependency core of the harness.

These evaluate the LLM-free logic that runs on EVERY utterance: the
regex gates that decide when to pay for an LLM call (scribe, fact-check)
and the fully deterministic agents (activation, agenda, flow). They run
in milliseconds with no API keys, no DB, no Redis — so they gate CI.

Gate philosophy: the pre-checks are recall-biased by design (a missed
decision is worse than a wasted LLM call), so recall floors sit high and
precision floors sit lower.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

from evals.harness import SuiteResult, load_dataset, suite
from evals.metrics import classification_metrics, exact_match_rate


@suite("scribe_precheck")
async def scribe_precheck() -> SuiteResult:
    """Does the decision-language gate fire on real decisions (and only them)?

    Grades ``is_decision_language`` — the function the dispatcher actually
    calls — not the raw pattern, so the retrospective-reference exclusion is
    covered too. Grading the regex alone would have scored a behaviour the
    product no longer has.
    """
    from apps.api.services.meeting.scribe_agent import is_decision_language

    cases = load_dataset("scribe_decisions.jsonl")
    pairs, failures = [], []
    for c in cases:
        predicted = is_decision_language(c["text"])
        pairs.append((c["label"], predicted))
        if predicted != c["label"]:
            failures.append({"id": c["id"], "text": c["text"], "expected": c["label"]})
    return SuiteResult(
        name="scribe_precheck",
        metrics=classification_metrics(pairs),
        n_cases=len(cases),
        failures=failures,
    )


@suite("factcheck_precheck")
async def factcheck_precheck() -> SuiteResult:
    """Does the claim gate fire on checkable claims (and skip opinions)?"""
    from apps.api.services.meeting.fact_check_agent import CLAIM_PATTERNS

    cases = load_dataset("factcheck_claims.jsonl")
    pairs, failures = [], []
    for c in cases:
        predicted = bool(CLAIM_PATTERNS.search(c["text"]))
        pairs.append((c["label"], predicted))
        if predicted != c["label"]:
            failures.append({"id": c["id"], "text": c["text"], "expected": c["label"]})
    return SuiteResult(
        name="factcheck_precheck",
        metrics=classification_metrics(pairs),
        n_cases=len(cases),
        failures=failures,
    )


@suite("activation")
async def activation() -> SuiteResult:
    """Does the expertise matcher activate the right person (or nobody)?"""
    from apps.api.services.meeting.activation_agent import ActivationAgent

    cases = load_dataset("activation_cases.jsonl")
    pairs, failures = [], []
    for c in cases:
        agent = ActivationAgent()  # fresh: no cooldown carry-over between cases
        result = await agent.analyze(c["utterances"], c["attendees"], f"eval-{c['id']}")
        predicted = result["source_data"]["person"] if result else None
        pairs.append((c["expected_person"], predicted))
        if predicted != c["expected_person"]:
            failures.append(
                {
                    "id": c["id"],
                    "expected": c["expected_person"],
                    "predicted": predicted,
                }
            )
    return SuiteResult(
        name="activation",
        metrics={"accuracy": exact_match_rate(pairs)},
        n_cases=len(cases),
        failures=failures,
    )


@suite("agenda_coverage")
async def agenda_coverage() -> SuiteResult:
    """Does the lexical coverage matcher mark the right items covered?"""
    from apps.api.services.meeting.agenda_agent import _content_tokens, _covers

    cases = load_dataset("agenda_coverage.jsonl")
    pairs, failures = [], []
    for c in cases:
        window_tokens = set(_content_tokens(" ".join(c["window"])))
        predicted = _covers(c["item"], window_tokens)
        pairs.append((c["covered"], predicted))
        if predicted != c["covered"]:
            failures.append(
                {"id": c["id"], "item": c["item"], "expected": c["covered"]}
            )
    return SuiteResult(
        name="agenda_coverage",
        metrics=classification_metrics(pairs),
        n_cases=len(cases),
        failures=failures,
    )


@suite("flow")
async def flow() -> SuiteResult:
    """Does the flow agent call the room's dynamics the way a human would?"""
    from apps.api.services.meeting.flow_agent import FlowAgent

    cases = load_dataset("flow_scenarios.jsonl")
    pairs, failures = [], []
    for c in cases:
        total = sum(w for _, w in c["stats"])
        stats = [
            {"speaker": s, "words": w, "share": round(w / total, 3)}
            for s, w in c["stats"]
        ]
        started = datetime.now(timezone.utc) - timedelta(
            minutes=c["elapsed_minutes"] or 0
        )
        agent = FlowAgent()
        with (
            patch.object(
                FlowAgent, "_speaker_stats", new=AsyncMock(return_value=stats)
            ),
            patch.object(FlowAgent, "_broadcast_flow", new=AsyncMock()),
            patch.object(FlowAgent, "_once", new=AsyncMock(return_value=True)),
        ):
            result = await agent.analyze(
                f"eval-{c['id']}",
                utterance_count=c["utterance_count"],
                started_at=started,
                decision_count=c["decision_count"],
            )
        if result is None:
            predicted = None
        elif "no decision" in result["title"].lower():
            predicted = "no_decision"
        else:
            predicted = "balance"
        pairs.append((c["expect"], predicted))
        if predicted != c["expect"]:
            failures.append(
                {"id": c["id"], "expected": c["expect"], "predicted": predicted}
            )
    return SuiteResult(
        name="flow",
        metrics={"accuracy": exact_match_rate(pairs)},
        n_cases=len(cases),
        failures=failures,
    )
