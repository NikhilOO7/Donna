# ADR-010: A free deterministic gate before every LLM call

**Status:** Accepted · **Date:** 2026-08

## Context
Nine agents run per spoken sentence. A naive implementation pays for nine LLM
calls per utterance, which makes a meeting-hour cost dollars and makes the
product's unit economics impossible.

## Decision
Every LLM-backed agent sits behind a **free, deterministic pre-check**: regex
for decision language and checkable claims, token overlap for expertise and
agenda coverage. Six of nine live agents never call a model at all.

Crucially, **the gates are evaluated**: each has a golden dataset and a
CI-enforced floor, because an untested heuristic rots invisibly.

## Consequences
- The typical utterance costs $0.
- Gate quality becomes a first-class, measurable property rather than a
  guess — and the harness has repeatedly found real bugs in it (a `\b` that
  could never match `$99`; "consider it done" not counting as a decision;
  retrospective references re-firing the scribe).
- Gates are recall-biased on purpose: a missed decision costs more than a
  wasted gpt-4o-mini call, so recall floors sit above precision floors.

## Revisit when
A gate's precision drops far enough that wasted LLM calls dominate cost, or a
model becomes cheap enough that the gate's own false-negative rate costs more
than the calls it saves. Both are measurable from the existing eval metrics
and the per-agent cost breakdown.
