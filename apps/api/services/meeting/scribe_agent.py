"""
Scribe Agent.

Watches recent utterances for decision/agreement language and produces
a `decision_prompt` nudge card suggesting the user log the decision.
"""

import json
import logging
import re
from typing import Any, Dict, List, Optional

from openai import AsyncOpenAI

from apps.api.core.config import settings
from apps.api.core.resilience import resilient_call

logger = logging.getLogger(__name__)

# Cheap pre-filter — only call GPT when these patterns appear
DECISION_PATTERNS = re.compile(
    r"\b(let's go with|we decided|we'll go|agreed|the decision is|"
    r"the plan is|i'll take|i will take|action item|going forward|"
    r"we should|next step is|let's commit|finalize|approved)\b",
    re.IGNORECASE,
)


class ScribeAgent:
    """Detect decisions and action items in meeting utterances."""

    def __init__(self):
        self.client = AsyncOpenAI(api_key=settings.openai_api_key)

    async def analyze(
        self, recent_utterances: List[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        """Return a nudge dict if a decision is detected, else None."""
        if not recent_utterances:
            return None

        # Pre-filter: cheap regex scan over latest utterance
        latest = recent_utterances[-1].get("text", "")
        if not DECISION_PATTERNS.search(latest):
            return None

        try:
            result = await self._extract_decision(recent_utterances)
        except Exception as e:
            logger.warning(f"[Scribe] extraction failed: {e}")
            return None

        if not result or not result.get("is_decision"):
            return None

        logger.info(
            f"[Scribe] decision detected: {result.get('decision_text', '')[:60]}"
        )

        return {
            "nudge_type": "decision_prompt",
            "title": "Sounds like a decision — want me to log it?",
            "content": result.get("decision_text", ""),
            "source_agent": "scribe_agent",
            "source_data": {
                "owner": result.get("owner"),
                "deadline": result.get("deadline"),
                "confidence": result.get("confidence", 0.7),
            },
            "relevance_score": result.get("confidence", 0.7),
        }

    @resilient_call("openai", max_retries=1, timeout_seconds=10)
    async def _extract_decision(
        self, utterances: List[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        transcript = "\n".join(
            f"{u.get('speaker', '?')}: {u.get('text', '')}" for u in utterances[-5:]
        )

        response = await self.client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You detect formal decisions in meeting transcripts. "
                        "Return JSON ONLY: "
                        '{"is_decision": bool, "decision_text": str|null, '
                        '"owner": str|null, "deadline": str|null, '
                        '"confidence": float}. Only mark is_decision=true when '
                        "a clear commitment or agreement was reached. Casual "
                        '"we should X" without commitment is not a decision.'
                    ),
                },
                {"role": "user", "content": transcript},
            ],
            temperature=0.1,
            max_tokens=300,
        )

        content = response.choices[0].message.content.strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[1].rsplit("```", 1)[0]
        return json.loads(content)


scribe_agent = ScribeAgent()
