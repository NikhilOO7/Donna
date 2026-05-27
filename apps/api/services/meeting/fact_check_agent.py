"""
Fact-Check Agent.

When a verifiable claim appears in the transcript (e.g. "market grew 15%",
"competitor raised prices 8%"), this agent uses Exa to fetch fresh sources
and GPT-4o-mini to compare the original claim against the source data.
Emits a ``fact_check`` nudge when the claim is contradicted or unverified.

Pre-filtered: only utterances with claim-like patterns (numbers,
percentages, comparatives, attributions) trigger the LLM path.
Silently no-ops when ``EXA_API_KEY`` is not configured.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from typing import Any, Dict, List, Optional

from openai import AsyncOpenAI

from apps.api.core.config import settings
from apps.api.core.coordination import cooldown_passed
from apps.api.core.resilience import resilient_call
from apps.api.services.research.search_agent import SearchAgent

logger = logging.getLogger(__name__)

# Anti-spam: don't re-emit the same claim within N seconds, and cap
# fact-check nudges to one per ~45s window per meeting. Cooldown state
# lives in Redis (shared across replicas) via core.coordination, falling
# back to process-local when Redis is down.
_CLAIM_COOLDOWN_S = 300.0
_PER_MEETING_MIN_GAP_S = 45.0

# Pre-filter: only run LLM extraction if utterance looks claim-like.
# - percentage / numeric increase: "8%", "15 percent", "$3.2B"
# - comparative: "more than", "less than", "doubled", "raised"
# - attribution: "according to", "reports say", "research shows"
CLAIM_PATTERNS = re.compile(
    r"\b(\d+(\.\d+)?\s*%|\$\s*\d|"
    r"grew|increased|decreased|dropped|raised|rose|fell|"
    r"more than|less than|doubled|tripled|"
    r"according to|reports? (say|show)|research (shows|found)|"
    r"market (size|share|cap))\b",
    re.IGNORECASE,
)


class FactCheckAgent:
    """Verify factual claims in transcript via Exa + GPT-4o-mini."""

    def __init__(self):
        self.client = AsyncOpenAI(api_key=settings.openai_api_key)
        self.search_agent = SearchAgent()

    async def analyze(
        self,
        recent_utterances: List[Dict[str, Any]],
        meeting_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Return a fact_check nudge if a verifiable claim is contradicted.

        Cooldowns are Redis-backed (shared across replicas): at most one
        fact-check attempt per ``_PER_MEETING_MIN_GAP_S`` per meeting, and
        the same claim isn't re-verified within ``_CLAIM_COOLDOWN_S``.
        """
        if not settings.exa_api_key or not recent_utterances:
            return None

        latest = recent_utterances[-1]
        text = (latest.get("text") or "").strip()
        if len(text) < 20:
            return None

        # Pre-filter — cheap regex gate before any LLM call
        if not CLAIM_PATTERNS.search(text):
            return None

        scope = meeting_id or "global"

        # Per-meeting throttle — atomically claim the window so the fleet
        # runs at most one fact-check attempt per gap, not one per replica.
        if not await cooldown_passed(
            f"factcheck:meeting:{scope}", _PER_MEETING_MIN_GAP_S
        ):
            return None

        claim = await self._extract_claim(text)
        if not claim:
            return None

        # Per-claim cooldown — never re-verify the same claim within 5 min
        claim_hash = hashlib.sha1(claim.lower().encode()).hexdigest()[:16]
        if not await cooldown_passed(
            f"factcheck:claim:{scope}:{claim_hash}", _CLAIM_COOLDOWN_S
        ):
            return None

        sources = await self.search_agent.search_topic(
            topic=claim, queries=[claim], max_results=3
        )
        if not sources:
            return None

        verdict = await self._verdict(claim, sources)
        if not verdict:
            return None

        status = (verdict.get("status") or "").lower()
        # Only nudge when contradicted or partially supported — supported
        # claims aren't interesting to surface.
        if status not in ("contradicted", "partial", "unverified"):
            return None

        top = sources[0]
        return {
            "nudge_type": "fact_check",
            "title": f"Fact-check: {status.title()}",
            "content": (
                f"Claim: \"{claim}\"\n\n"
                f"{verdict.get('explanation', '')}\n\n"
                f"Source: {top.get('title') or top.get('url')}"
            ),
            "source_agent": "fact_check_agent",
            "source_data": {
                "claim": claim,
                "status": status,
                "source_url": top.get("url"),
                "source_title": top.get("title"),
                "explanation": verdict.get("explanation"),
            },
            "relevance_score": float(verdict.get("confidence") or 0.7),
        }

    # ------------------------------------------------------------------

    @resilient_call("openai", max_retries=2, timeout_seconds=10)
    async def _extract_claim(self, utterance: str) -> Optional[str]:
        """Use GPT-4o-mini to extract a single verifiable claim, if present."""
        try:
            response = await self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Extract a single verifiable factual claim from the "
                            "given utterance. A claim is a statement that can be "
                            "checked against external data (e.g. a statistic, a "
                            "company action, a measurable comparison). Respond "
                            "with ONLY the claim as a plain sentence, or the "
                            "literal string NONE if no checkable claim exists."
                        ),
                    },
                    {"role": "user", "content": utterance},
                ],
                temperature=0.0,
                max_tokens=80,
            )
            out = (response.choices[0].message.content or "").strip()
            if not out or out.upper() == "NONE" or len(out) < 10:
                return None
            return out
        except Exception as e:
            logger.warning(f"[FactCheck] claim extraction failed: {e}")
            return None

    @resilient_call("openai", max_retries=2, timeout_seconds=15)
    async def _verdict(
        self, claim: str, sources: List[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        """Compare claim against retrieved sources, return JSON verdict."""
        # Trim source texts to keep prompt small
        source_blob = "\n\n".join(
            f"[{i + 1}] {s.get('title', '')}\n{(s.get('text') or '')[:500]}"
            for i, s in enumerate(sources[:3])
        )
        try:
            response = await self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a fact-checker. Given a claim and 1-3 web "
                            "sources, determine whether the sources SUPPORT, "
                            "CONTRADICT, PARTIALLY support, or are UNVERIFIED "
                            "for the claim. Respond ONLY with a JSON object: "
                            '{"status": "supported"|"contradicted"|"partial"|"unverified", '
                            '"confidence": 0.0-1.0, "explanation": "one sentence"}.'
                        ),
                    },
                    {
                        "role": "user",
                        "content": f"CLAIM:\n{claim}\n\nSOURCES:\n{source_blob}",
                    },
                ],
                temperature=0.1,
                max_tokens=200,
                response_format={"type": "json_object"},
            )
            return json.loads(response.choices[0].message.content or "{}")
        except Exception as e:
            logger.warning(f"[FactCheck] verdict failed: {e}")
            return None


fact_check_agent = FactCheckAgent()
