"""
Memory Agent — the meeting-memory read-back.

When the conversation touches something the team already decided in a past
meeting, surface it: "You've decided this before." Reads the Meeting →
Decision subgraph that the summary pipeline mirrors into Neo4j, matches by
token overlap (LLM-free), and rate-limits itself per meeting.
"""

import logging
import re
import time
from typing import Any, Dict, List, Optional

from apps.api.core.logging import warn_throttled

logger = logging.getLogger(__name__)

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
    "should",
    "would",
    "could",
    "going",
    "let's",
    "lets",
    "meeting",
}

_COOLDOWN_SECONDS = 180  # per meeting
_MIN_OVERLAP = 2  # shared meaningful tokens before we claim a match


def _tokens(text: str) -> set:
    return {
        t
        for t in re.findall(r"[a-z][a-z\-]{3,}", (text or "").lower())
        if t not in _STOPWORDS
    }


class MemoryAgent:
    """Resurface past decisions relevant to the live conversation."""

    def __init__(self):
        self._last_fired: Dict[str, float] = {}

    async def analyze(
        self,
        meeting_id: str,
        utterances: List[Dict[str, Any]],
        owner_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        if not utterances:
            return None

        now = time.time()
        if now - self._last_fired.get(meeting_id, 0) < _COOLDOWN_SECONDS:
            return None

        latest_tokens = _tokens(utterances[-1].get("text", ""))
        if len(latest_tokens) < 2:
            return None

        decisions = await self._past_decisions(meeting_id, owner_id)
        if not decisions:
            return None

        best = None
        best_overlap = 0
        for d in decisions:
            overlap = len(_tokens(d.get("text", "")) & latest_tokens)
            if overlap > best_overlap:
                best_overlap = overlap
                best = d

        if best is None or best_overlap < _MIN_OVERLAP:
            return None

        self._last_fired[meeting_id] = now
        meeting_title = best.get("meeting_title") or "a previous meeting"
        logger.info(
            f"[Memory] past-decision match (overlap={best_overlap}) "
            f"in meeting {meeting_id}"
        )
        return {
            "nudge_type": "context",
            "title": "You've decided this before",
            "content": (
                f'In "{meeting_title}" the team decided: {best.get("text", "")} '
                "Worth confirming whether that still stands before re-litigating."
            ),
            "source_agent": "memory_agent",
            "source_data": {
                "past_meeting_id": best.get("meeting_id"),
                "past_meeting_title": meeting_title,
                "past_decision": best.get("text"),
            },
            "relevance_score": min(0.55 + 0.1 * best_overlap, 0.9),
        }

    async def _past_decisions(
        self, current_meeting_id: str, owner_id: Optional[str]
    ) -> List[Dict[str, Any]]:
        """Decisions from OTHER meetings by this owner (best-effort)."""
        try:
            from apps.api.core.neo4j_client import GLOBAL_OWNER, neo4j_client

            if not neo4j_client.enabled:
                return []
            owner = str(owner_id) if owner_id else GLOBAL_OWNER
            rows = await neo4j_client.execute(
                """
                MATCH (m:Meeting {owner_id: $owner})-[:MADE_DECISION]->(d:Decision)
                WHERE m.id <> $current
                RETURN m.id AS meeting_id, m.title AS meeting_title,
                       d.text AS text
                ORDER BY m.id DESC
                LIMIT 50
                """,
                {"owner": owner, "current": str(current_meeting_id)},
            )
            return [r for r in (rows or []) if r.get("text")]
        except Exception as e:
            warn_throttled(
                logger,
                "memory.recall",
                f"[Memory] decision recall unavailable — past-decision nudges are "
                f"silently not firing: {e}",
            )
            return []


memory_agent = MemoryAgent()
