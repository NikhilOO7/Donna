"""
Groundedness — is a generated answer actually supported by its sources?

Retrieval quality is measured (MRR, nDCG, Recall@k). Whether the *sentence
Donna says* is supported by the chunks it cites was not measured at all —
and a hallucination that arrives WITH a citation attached is more credible
than one without, not less. Provenance without groundedness is a confidence
amplifier pointed at an unverified claim.

This module is deliberately **deterministic**: no model call, no API key, a
few hundred microseconds. That makes it usable in three places at once —
inline on live answers, as a CI-gated eval suite, and as a debugging tool —
where an LLM judge would be too slow and too expensive for the first.

It does NOT attempt semantic entailment. It targets the failure mode that
actually hurts in a meeting: **fabricated specifics.** A number, date, money
amount or proper noun that appears in the answer but nowhere in the retrieved
context is the highest-risk, highest-detectability class of hallucination, and
catching it well beats catching everything badly.

Scoring is intentionally conservative: unsupported specifics dominate the
score, because "revenue grew 15%" being wrong matters far more than a
connective sentence having low lexical overlap.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set

# Sentence splitter: good enough, and dependency-free. Avoids breaking on
# common abbreviations and decimals ("$1.5M", "Q3 2024", "approx. 12").
_ABBREV = r"(?<!\b[A-Z])(?<!\bapprox)(?<!\bvs)(?<!\betc)(?<!\bNo)(?<!\bFig)"
_SENT_SPLIT = re.compile(rf"{_ABBREV}(?<=[.!?])\s+(?=[A-Z0-9$])")

# A "specific" is a token whose exact value carries the claim's risk.
_NUMERIC = re.compile(
    r"""
    (?:\$\s?\d[\d,]*(?:\.\d+)?\s?(?:[kKmMbB]|million|billion|thousand)?)  # money
  | (?:\d[\d,]*(?:\.\d+)?\s?%)                                            # percent
  | (?:\b\d{4}\b)                                                         # year
  | (?:\b\d[\d,]*(?:\.\d+)?\b)                                            # bare number
    """,
    re.VERBOSE,
)

# Capitalised multi-word or single proper nouns, excluding sentence openers
# handled by the caller's position check.
_PROPER = re.compile(r"\b[A-Z][a-zA-Z0-9&.\-]*(?:\s+[A-Z][a-zA-Z0-9&.\-]*)*\b")

_STOP = {
    "the",
    "a",
    "an",
    "and",
    "or",
    "but",
    "if",
    "then",
    "than",
    "that",
    "this",
    "these",
    "those",
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "being",
    "to",
    "of",
    "in",
    "on",
    "for",
    "with",
    "as",
    "by",
    "at",
    "from",
    "it",
    "its",
    "we",
    "you",
    "they",
    "there",
    "their",
    "our",
    "your",
    "has",
    "have",
    "had",
    "will",
    "would",
    "should",
    "could",
    "may",
    "might",
    "can",
    "do",
    "does",
    "did",
    "not",
    "no",
    "so",
    "up",
    "out",
    "about",
    "into",
    "over",
    "also",
    "which",
    "who",
    "what",
    "when",
    "where",
    "how",
    "per",
    "based",
    "according",
}

# Evidential framing — words that talk ABOUT the evidence rather than assert
# anything. "The sources confirm revenue grew 15%" makes exactly one factual
# claim ("revenue grew 15%"); "the sources confirm" is scaffolding, and it
# legitimately never appears in the source text.
#
# This matters most for fact-check explanations, which are prose *about*
# sources by construction — without it, a perfectly grounded verdict scores as
# unsupported purely for being phrased as a verdict.
_EVIDENTIAL = {
    "source",
    "sources",
    "document",
    "documents",
    "context",
    "excerpt",
    "confirm",
    "confirms",
    "confirmed",
    "confirming",
    "state",
    "states",
    "stated",
    "indicate",
    "indicates",
    "indicated",
    "suggest",
    "suggests",
    "suggested",
    "appear",
    "appears",
    "appeared",
    "show",
    "shows",
    "shown",
    "showed",
    "note",
    "notes",
    "noted",
    "mention",
    "mentions",
    "mentioned",
    "say",
    "says",
    "said",
    "report",
    "reports",
    "reported",
    "article",
    "indicates",
    "support",
    "supports",
    "supported",
    "contradict",
    "contradicts",
    "claim",
    "claims",
    "claimed",
    "evidence",
    "indicating",
    "accurate",
    "correct",
    "incorrect",
    "indeed",
    "actually",
}
_STOP |= _EVIDENTIAL

# Hedges: a sentence that explicitly declines to assert is not a hallucination
# risk. "The documents don't say" is the honest answer, not an ungrounded one.
# NOTE: the do/does/did alternation is load-bearing — an earlier version only
# matched "does not specify" and therefore scored the correct, honest answer
# "The documents don't specify pricing" as a hallucination (eval case gr-13).
_HEDGE = re.compile(
    r"\b(?:"
    r"i (?:don'?t|do not) (?:know|have)"
    r"|not (?:enough|sure|specified|stated|mentioned|available|included|covered)"
    r"|no (?:information|mention|data|record|details?)"
    r"|unclear|cannot (?:determine|find|tell)|unable to"
    r"|(?:do|does|did)(?:n'?t| not) (?:say|specify|mention|state|include|cover|contain|indicate)"
    r"|(?:isn'?t|aren'?t|wasn'?t) (?:specified|stated|mentioned|included)"
    r")\b",
    re.IGNORECASE,
)

# Sentences that are pure discourse carry no factual load.
_CONNECTIVE = re.compile(
    r"^\s*(?:however|additionally|in summary|to summarize|overall|in short|"
    r"that said|furthermore|moreover|finally|note that)\b[^.]*\.?\s*$",
    re.IGNORECASE,
)


def _norm_number(tok: str) -> str:
    """Normalise a numeric token so '1,200', '1200' and '$1,200' compare equal."""
    t = tok.lower().replace(",", "").replace("$", "").strip()
    t = re.sub(r"\s+", "", t)
    # 1.5m / 1.5million -> 1500000 so magnitude suffixes match spelled-out forms
    m = re.fullmatch(r"(\d+(?:\.\d+)?)(k|m|b|thousand|million|billion)?%?", t)
    if not m:
        return t
    value, suffix = m.group(1), m.group(2)
    mult = {
        "k": 1_000,
        "thousand": 1_000,
        "m": 1_000_000,
        "million": 1_000_000,
        "b": 1_000_000_000,
        "billion": 1_000_000_000,
    }.get(suffix or "", 1)
    try:
        num = float(value) * mult
    except ValueError:
        return t
    return str(int(num)) if num.is_integer() else str(num)


def _numbers(text: str) -> Set[str]:
    return {_norm_number(m.group(0)) for m in _NUMERIC.finditer(text)}


def _proper_nouns(text: str) -> Set[str]:
    """Named entities, plus the initialisms of any multi-word names present.

    A document that says "Master Services Agreement" licenses an answer to say
    "MSA", and one that says "Service Level Agreement" licenses "SLA" — these
    are references to the source, not fabrications. Without expanding
    initialisms the checker flags ordinary domain shorthand as hallucinated
    (eval case gr-05).
    """
    out: Set[str] = set()
    for sent in _SENT_SPLIT.split(text):
        for i, m in enumerate(_PROPER.finditer(sent)):
            tok = m.group(0)
            # Skip a capitalised first word — it is capitalised by position,
            # not because it is a name.
            if m.start() == 0 and i == 0 and " " not in tok:
                continue
            if tok.lower() in _STOP or _is_acronym(tok):
                continue
            out.add(tok.lower())

            # Register the initialism of a multi-word name.
            words = [w for w in tok.split() if w]
            if len(words) >= 2:
                out.add("".join(w[0] for w in words).lower())

    # Also allow initialisms formed from any run of capitalised words in the
    # raw text, which catches names split across the proper-noun regex.
    for run in re.finditer(r"(?:\b[A-Z][a-z]+\b\s+){1,4}\b[A-Z][a-z]+\b", text):
        words = run.group(0).split()
        if len(words) >= 2:
            out.add("".join(w[0] for w in words).lower())
    return out


# Suffix stemming, deliberately crude and dependency-free. Its only job is to
# stop obvious morphological variants from reading as different topics —
# "migrating"/"migration", "document"/"documentation". Without it, a correct
# paraphrase of the context scores as unsupported purely for rewording (eval
# case gr-20). Prefixes are NOT stripped: "undocumented" -> "document" would
# erase a negation, and polarity is not this function's job.
_SUFFIXES = (
    "ational",
    "ization",
    "isation",
    "fulness",
    "ousness",
    "iveness",
    "ation",
    "ition",
    "ement",
    "ments",
    "ingly",
    "ities",
    "ment",
    "ness",
    "ance",
    "ence",
    "tion",
    "sion",
    "able",
    "ible",
    "ing",
    "ies",
    "ied",
    "ive",
    "ity",
    "ers",
    "est",
    "ed",
    "es",
    "ly",
    "s",
)


def _stem(token: str) -> str:
    """Strip a trailing morphological suffix, keeping a usable root."""
    for suf in _SUFFIXES:
        if token.endswith(suf) and len(token) - len(suf) >= 4:
            root = token[: -len(suf)]
            # Undo common doubling/elision so the roots actually collide.
            if len(root) > 4 and root[-1] == root[-2]:
                root = root[:-1]
            return root
    return token


# Short all-caps tokens (SLA, MSA, API, P1, SOAP) are domain vocabulary, not
# assertions. They are neither a fabrication risk — nobody hallucinates a
# meeting by inventing the word "SLA" — nor evidence of grounding, so they are
# excluded from BOTH the entity check and the overlap denominator. Counting
# them scored a correct answer as a hallucination for using ordinary shorthand
# (eval case gr-05).
_ACRONYM = re.compile(r"^[A-Z][A-Z0-9]{1,4}$")


def _is_acronym(token: str) -> bool:
    return bool(_ACRONYM.match(token.strip()))


def _content_tokens(text: str) -> Set[str]:
    acronyms = {
        m.group(0).lower() for m in re.finditer(r"\b[A-Z][A-Z0-9]{1,4}\b", text)
    }
    return {
        _stem(t)
        for t in re.findall(r"[a-z][a-z\-']{2,}", text.lower())
        if t not in _STOP and t not in acronyms
    }


@dataclass
class ClaimVerdict:
    """One sentence of the answer, and whether the context supports it."""

    text: str
    supported: bool
    # Specifics asserted by the claim that appear nowhere in the context —
    # the actionable part of a failure.
    unsupported_numbers: List[str] = field(default_factory=list)
    unsupported_entities: List[str] = field(default_factory=list)
    overlap: float = 0.0
    reason: str = ""


@dataclass
class GroundednessReport:
    score: float  # 0.0–1.0, share of load-bearing claims that are supported
    label: str  # "supported" | "partial" | "contradicted"
    claims: List[ClaimVerdict] = field(default_factory=list)

    @property
    def unsupported_claims(self) -> List[ClaimVerdict]:
        return [c for c in self.claims if not c.supported]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "score": round(self.score, 3),
            "label": self.label,
            "unsupported_claims": [
                {
                    "text": c.text,
                    "unsupported_numbers": c.unsupported_numbers,
                    "unsupported_entities": c.unsupported_entities,
                    "reason": c.reason,
                }
                for c in self.unsupported_claims
            ],
        }


# A claim with a fabricated specific is unsupported no matter how well the
# rest of its wording overlaps — this is the whole point of the check.
_OVERLAP_SUPPORTED = 0.55
_PARTIAL_FLOOR = 0.60
_SUPPORTED_FLOOR = 0.999


def _context_text(context: Sequence[Any]) -> str:
    """Accept raw strings, chunk dicts, or objects with a ``content`` field."""
    parts: List[str] = []
    for c in context or []:
        if isinstance(c, str):
            parts.append(c)
        elif isinstance(c, dict):
            parts.append(
                str(c.get("content") or c.get("text") or c.get("chunk_text") or "")
            )
        else:
            parts.append(str(getattr(c, "content", "") or getattr(c, "text", "")))
    return "\n".join(p for p in parts if p)


def split_claims(answer: str) -> List[str]:
    """Split an answer into sentence-level claims, dropping empties."""
    return [s.strip() for s in _SENT_SPLIT.split(answer or "") if s.strip()]


def check_claim(
    claim: str, ctx_numbers: Set[str], ctx_entities: Set[str], ctx_tokens: Set[str]
) -> ClaimVerdict:
    """Verdict for one sentence against pre-extracted context features."""
    # An explicit non-answer asserts nothing and cannot be ungrounded.
    if _HEDGE.search(claim):
        return ClaimVerdict(claim, True, overlap=1.0, reason="hedged non-assertion")
    if _CONNECTIVE.match(claim):
        return ClaimVerdict(claim, True, overlap=1.0, reason="discourse connective")

    bad_nums = sorted(n for n in _numbers(claim) if n not in ctx_numbers)
    bad_ents = sorted(e for e in _proper_nouns(claim) if e not in ctx_entities)

    tokens = _content_tokens(claim)
    overlap = (len(tokens & ctx_tokens) / len(tokens)) if tokens else 1.0

    if bad_nums:
        return ClaimVerdict(
            claim,
            False,
            bad_nums,
            bad_ents,
            overlap,
            reason=f"asserts figure(s) absent from context: {', '.join(bad_nums)}",
        )
    if bad_ents:
        return ClaimVerdict(
            claim,
            False,
            bad_nums,
            bad_ents,
            overlap,
            reason=f"names entit(ies) absent from context: {', '.join(bad_ents)}",
        )
    if overlap < _OVERLAP_SUPPORTED:
        return ClaimVerdict(
            claim,
            False,
            bad_nums,
            bad_ents,
            overlap,
            reason=f"low lexical support ({overlap:.0%})",
        )
    return ClaimVerdict(claim, True, overlap=overlap, reason="supported")


def assess(answer: str, context: Sequence[Any]) -> GroundednessReport:
    """Score how well ``context`` supports ``answer``.

    Returns a label alongside the score:
      * ``supported``    — every load-bearing claim is grounded
      * ``partial``      — most are, but at least one is not
      * ``contradicted`` — the answer is largely unsupported by its own sources
    """
    claims = split_claims(answer)
    if not claims:
        return GroundednessReport(score=1.0, label="supported", claims=[])

    ctx = _context_text(context)
    if not ctx.strip():
        # No context at all: anything asserted is unsupported by construction.
        verdicts = [
            ClaimVerdict(c, False, reason="no retrieved context to support this")
            for c in claims
        ]
        # ...except honest non-answers, which are the correct output here.
        for v in verdicts:
            if _HEDGE.search(v.text):
                v.supported, v.reason = True, "hedged non-assertion"
        score = sum(v.supported for v in verdicts) / len(verdicts)
        return GroundednessReport(
            score=score,
            label="supported"
            if score >= _SUPPORTED_FLOOR
            else ("partial" if score >= _PARTIAL_FLOOR else "contradicted"),
            claims=verdicts,
        )

    ctx_numbers = _numbers(ctx)
    ctx_entities = _proper_nouns(ctx)
    ctx_tokens = _content_tokens(ctx)

    verdicts = [check_claim(c, ctx_numbers, ctx_entities, ctx_tokens) for c in claims]
    score = sum(v.supported for v in verdicts) / len(verdicts)
    label = (
        "supported"
        if score >= _SUPPORTED_FLOOR
        else ("partial" if score >= _PARTIAL_FLOOR else "contradicted")
    )
    return GroundednessReport(score=score, label=label, claims=verdicts)


def assess_rag_response(response: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Convenience wrapper for a RAG response dict ({answer, sources}).

    Returns None when there is nothing to assess, so callers can attach the
    result unconditionally without branching.
    """
    answer = response.get("answer") or response.get("response") or ""
    sources: Iterable[Any] = response.get("sources") or response.get("chunks") or []
    if not answer:
        return None
    return assess(answer, list(sources)).to_dict()
