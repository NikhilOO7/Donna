"""
Activation Agent.

The "YOUR EXPERTISE NEEDED" nudge: when the conversation turns to a topic
that matches a registered participant's expertise, surface a card inviting
them to contribute. Deliberately LLM-free — a token-overlap matcher with a
per-person cooldown — so it adds zero latency and zero cost per utterance.

The nudge contains only the conversational trigger (never internal data);
the participant decides whether to share what they know.
"""

import logging
import re
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Words too generic to signal expertise on their own
_STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "that",
    "this",
    "have",
    "from",
    "will",
    "about",
    "team",
    "work",
    "working",
    "management",
    "general",
    "senior",
}

_COOLDOWN_SECONDS = 240  # per (meeting, person)


def _tokens(text: str) -> set:
    return {
        t for t in re.findall(r"[a-z][a-z\-]{3,}", text.lower()) if t not in _STOPWORDS
    }


class ActivationAgent:
    """Match live conversation against registered participant expertise."""

    def __init__(self):
        # {(meeting_id, person): last_fired_ts} — in-process cooldown is fine:
        # dispatch cycles are serialized per meeting by the distributed lock.
        self._last_fired: Dict[tuple, float] = {}

    async def analyze(
        self,
        utterances: List[Dict[str, Any]],
        attendees: List[Dict[str, Any]],
        meeting_id: str,
    ) -> Optional[Dict[str, Any]]:
        if not utterances or not attendees:
            return None

        latest = utterances[-1]
        latest_text = latest.get("text", "")
        latest_speaker = (latest.get("speaker") or "").strip().lower()
        utterance_tokens = _tokens(latest_text)
        if not utterance_tokens:
            return None

        now = time.time()
        for attendee in attendees:
            name = (attendee.get("name") or "").strip()
            expertise = attendee.get("expertise") or []
            if not name or not expertise:
                continue
            # Don't ping someone about their own remark
            if name.lower() == latest_speaker:
                continue

            key = (meeting_id, name.lower())
            if now - self._last_fired.get(key, 0) < _COOLDOWN_SECONDS:
                continue

            matched = [
                area for area in expertise if _tokens(str(area)) & utterance_tokens
            ]
            if not matched:
                continue

            self._last_fired[key] = now
            logger.info(
                f"[Activation] expertise match: {name} ↔ {matched} "
                f"in meeting {meeting_id}"
            )
            return {
                "nudge_type": "activation",
                "title": f"Your expertise needed: {name}",
                "content": (
                    f"The conversation turned to {matched[0]} — {name}, "
                    "this is your lane. Anything the room should know?"
                ),
                "source_agent": "activation_agent",
                "source_data": {
                    "person": name,
                    "matched_expertise": matched,
                    "conversation_topic": latest_text[:200],
                    "triggered_by": latest.get("speaker"),
                },
                "relevance_score": 0.6,
            }

        return None


activation_agent = ActivationAgent()
