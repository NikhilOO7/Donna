"""
LLM-stage scribe suite — the pattern for evaluating paid model calls.

Where scribe_precheck grades the free regex gate, this grades the actual
LLM extraction behind it: for every gold utterance the gate passes, does
``_extract_decision`` agree with the human label on is_decision?

Requires a working OPENAI_API_KEY (skips cleanly without one; errors —
e.g. exhausted quota — surface as suite errors, not silent passes).
Cost: ~25 gpt-4o-mini calls per run, a fraction of a cent.
"""

from evals.harness import SuiteResult, load_dataset, suite
from evals.metrics import classification_metrics


@suite("scribe_llm", requires=("openai",))
async def scribe_llm() -> SuiteResult:
    from apps.api.services.meeting.scribe_agent import DECISION_PATTERNS, ScribeAgent

    agent = ScribeAgent()
    cases = load_dataset("scribe_decisions.jsonl")

    pairs, failures, skipped_by_gate = [], [], 0
    for c in cases:
        # The LLM only ever sees utterances the gate passed — evaluate the
        # same conditional distribution production sees.
        if not DECISION_PATTERNS.search(c["text"]):
            skipped_by_gate += 1
            continue
        result = await agent._extract_decision(
            [{"speaker": "Speaker", "text": c["text"]}]
        )
        predicted = bool(result and result.get("is_decision"))
        pairs.append((c["label"], predicted))
        if predicted != c["label"]:
            failures.append({"id": c["id"], "text": c["text"], "expected": c["label"]})

    return SuiteResult(
        name="scribe_llm",
        metrics=classification_metrics(pairs),
        n_cases=len(pairs),
        failures=failures,
        notes=f"{skipped_by_gate} cases never reach the LLM (gate filtered)",
    )
