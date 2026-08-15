"""
Scribe Agent.

Watches recent utterances for decision/agreement language and produces
a `decision_prompt` nudge card suggesting the user log the decision.
"""

import logging
import re
from typing import Any, Dict, List, Optional

from apps.api.core import json_parse, llm_provider
from apps.api.core.config import settings
from apps.api.core.resilience import resilient_call

logger = logging.getLogger(__name__)

# Cheap pre-filter — only call GPT when these patterns appear.
# Tuned against evals/datasets/scribe_decisions.jsonl (run: evals.run):
# "we should …" alone proved to be musing, not commitment (precision), and
# "i'll take a look" is not "i'll take the follow-up" — ownership needs an
# object. "consider it done" / "it's settled" are commitments (recall).
DECISION_PATTERNS = re.compile(
    r"\b(let's go with|we decided|we'll go|agreed|the decision is|"
    r"the plan is|(i'll|i will) (take (the|over)|own)|action item|"
    r"going forward|next step is|let's commit|finalize|approved|"
    r"consider it done|it'?s settled|"
    # Commitment framings the original set missed (eval cases sd-32, sd-37).
    r"lock(ing|ed)? (this |it |that )?in|"
    r"shall we (just )?go with|"
    r"are we (all )?(agreed|good with)|"
    r"sign(ing)? off on|"
    r"we're going with)\b",
    re.IGNORECASE,
)

# A retrospective reference to an OLD decision is not a new one. Without this,
# "Last week we decided to use Postgres, just recapping" fires the gate and
# pays for an LLM call to re-log a decision that already exists (eval sd-33).
# Checked against the whole utterance, since the marker can precede or follow.
DECISION_RETROSPECTIVE = re.compile(
    r"\b(last (week|month|time)|previously|earlier|back in \w+|"
    r"just recap|recapping|as (we|you) (decided|agreed)|"
    r"we already (decided|agreed)|to recap|reminder that)\b",
    re.IGNORECASE,
)


def is_decision_language(text: str) -> bool:
    """The scribe's free pre-check: is this a NEW decision worth an LLM call?

    Recall-biased by design — a missed decision costs more than a wasted
    gpt-4o-mini call — but retrospective references are excluded because they
    are pure cost with no new information.
    """
    if not text or not DECISION_PATTERNS.search(text):
        return False
    return not DECISION_RETROSPECTIVE.search(text)


class ScribeAgent:
    """Detect decisions and action items in meeting utterances."""

    def __init__(self):
        self.client = llm_provider.failover_client()

    async def analyze(
        self, recent_utterances: List[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        """Return a nudge dict if a decision is detected, else None."""
        if not recent_utterances:
            return None

        # Pre-filter: cheap regex scan over latest utterance
        latest = recent_utterances[-1].get("text", "")
        if not is_decision_language(latest):
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

        # Verbatim conversation lines that triggered this detection — these
        # become Decision.context when the user logs the decision, so leaders
        # can always see exactly who said what.
        trigger_quotes = [
            {
                "speaker": u.get("speaker", "?"),
                "text": u.get("text", ""),
                "timestamp": u.get("timestamp"),
            }
            for u in recent_utterances[-3:]
            if u.get("text")
        ]

        return {
            "nudge_type": "decision_prompt",
            "title": "Sounds like a decision — want me to log it?",
            "content": result.get("decision_text", ""),
            "source_agent": "scribe_agent",
            "source_data": {
                "owner": result.get("owner"),
                "deadline": result.get("deadline"),
                "confidence": result.get("confidence", 0.7),
                "trigger_quotes": trigger_quotes,
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
            model=settings.model_fast,
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
        return json_parse.loads(content)


scribe_agent = ScribeAgent()
