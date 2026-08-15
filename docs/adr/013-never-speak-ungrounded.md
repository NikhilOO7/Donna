# ADR-013: Never speak an ungrounded fact-check aloud

**Status:** Accepted · **Date:** 2026-08

## Context
`fact_check` is one of only two nudge types eligible for text-to-speech
(`_SPEAK_TYPES = {"fact_check", "decision_prompt"}`). Its `content` is
**LLM-generated prose** about a claim someone made out loud, synthesized from
web sources fetched at that moment.

That combination is the highest-stakes text the product produces:

- it is generated, so it can invent a figure;
- it cites sources, which makes it *more* credible, not less;
- and it is spoken into a room of people who will act on it immediately,
  with no opportunity to inspect the citation first.

A hallucinated document snippet is a bad search result. A hallucinated
fact-check, read aloud with a source attached, is the product actively
misleading a meeting.

## Decision
Before a fact-check nudge is emitted, its explanation is checked for
groundedness against the source excerpts it was generated from (ADR-012). If
the explanation is not fully supported, `relevance_score` is capped at
**0.75** — strictly below `_SPEAK_MIN_RELEVANCE` (0.8).

The nudge is still **shown**, with its sources, for a human to judge. It is
never **spoken**.

## Consequences
- Donna cannot read an unsupported claim into a room. The failure mode with
  the least recoverable consequences is the one that is refused outright.
- Showing-but-not-speaking is deliberate: suppressing the card entirely would
  hide a possibly-correct fact-check, and the human has the sources in front
  of them on screen in a way they do not when listening.
- The cap is a magic number coupled to the speech threshold. A regression test
  asserts `0.75 < _SPEAK_MIN_RELEVANCE`, because raising the threshold without
  lowering the cap would silently disable this control.
- The `groundedness` report rides along in `source_data`, so the card can show
  that Donna checked her own explanation.

## Notes
The context agent is deliberately **not** covered by this: its `content` is a
verbatim slice of a stored chunk, so it is grounded by construction. There is
no generation step in which a figure could be invented. That reasoning is
recorded in the class docstring so its absence does not read as an oversight.

## Revisit when
The groundedness checker gains semantic-entailment capability (an NLI model or
a judge for the uncertain subset). At that point the cap could become a hard
suppression rather than a speech veto, because the false-positive rate would
be low enough that hiding the card costs less than showing a wrong one.
