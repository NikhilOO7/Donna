# ADR-012: Deterministic groundedness checking, not an LLM judge

**Status:** Accepted · **Date:** 2026-08

## Context
Retrieval quality was measured (MRR, nDCG, Recall@k). Whether the *generated
sentence* was supported by the chunks it cited was not measured at all. This
is the more dangerous gap: an ungrounded claim that arrives **with a citation
attached** is more credible than one without, because the citation is what
makes people act on it.

## Decision
A deterministic, lexical groundedness checker
(`apps/api/services/rag/groundedness.py`) rather than an LLM judge.

It targets the failure mode that actually hurts in a meeting — **fabricated
specifics**. A number, date, money amount or proper noun present in the answer
but absent from the retrieved context is the highest-risk and most detectable
class of hallucination. It does not attempt semantic entailment.

Used in three places at once, which an LLM judge could not be:
1. inline on every live RAG answer (`groundedness` field on the response),
2. as a CI-gated eval suite (30 human-labelled cases, no API key needed),
3. as a debugging tool.

## Consequences
- Costs microseconds, so it can run on every answer for free.
- Measured: detection recall **0.93**, false-alarm rate **0.00**, with a
  ceiling gate on false alarms because a checker that cries wolf gets switched
  off, and a switched-off checker detects nothing.
- **Known limit, deliberately un-papered-over:** it cannot catch semantic
  contradiction where the vocabulary matches but the meaning inverts
  ("rollback is manual" → "rollbacks are fully automated"). That case is in
  the dataset, failing, and `hard_case_accuracy` is reported but ungated.

## Revisit when
Groundedness becomes a *gating* decision (refusing to show an answer) rather
than an advisory signal. At that point the false-alarm cost rises sharply and
an LLM judge — or an NLI model — earns its latency for the subset the lexical
checker marks uncertain.
