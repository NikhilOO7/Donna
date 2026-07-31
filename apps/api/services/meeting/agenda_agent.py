"""
Agenda-Tracking Agent.

The PDF's "agenda tracking nudges": watches the conversation against the
meeting's structured agenda ([{"title", "status"}] on Meeting.agenda),
marks items covered as they're discussed, streams progress to the room,
and nudges when the meeting is running long with items still uncovered.

Deliberately LLM-free: pure lexical matching over the recent utterance
window. It runs on every dispatch cycle, so it must cost nothing.
"""

import logging
import re
from typing import Any, Dict, List, Optional
from uuid import UUID

logger = logging.getLogger(__name__)

# Fraction of an item title's content words that must appear in the recent
# conversation window before the item counts as covered.
_COVERAGE_THRESHOLD = 0.6

# Don't suggest "you still have uncovered items" before the meeting has
# actually gotten going, and never more than once per cooldown window.
_MIN_UTTERANCES_FOR_NUDGE = 20
_NUDGE_COOLDOWN_SECONDS = 600

_STOPWORDS = frozenset(
    "a an and are as at be but by for from has have i in is it of on or "
    "our that the their this to was we what when which who will with you "
    "your review discuss align confirm update plan next new item".split()
)

_TOKEN_RE = re.compile(r"[a-z0-9']+")


def _content_tokens(text: str) -> List[str]:
    return [
        t for t in _TOKEN_RE.findall(text.lower()) if t not in _STOPWORDS and len(t) > 2
    ]


def _covers(title: str, window_tokens: set) -> bool:
    tokens = _content_tokens(title)
    if not tokens:
        return False
    hits = sum(1 for t in tokens if t in window_tokens)
    return hits / len(tokens) >= _COVERAGE_THRESHOLD


class AgendaAgent:
    """Track structured-agenda coverage from the live transcript."""

    async def analyze(
        self,
        meeting_id: str,
        recent_utterances: List[Dict[str, Any]],
        agenda: Optional[List[Dict[str, Any]]],
        utterance_count: int = 0,
    ) -> Optional[Dict[str, Any]]:
        """Update coverage; return an "uncovered items" nudge when due."""
        if not agenda or not recent_utterances:
            return None

        window_text = " ".join(
            u.get("text", "") for u in recent_utterances[-8:] if u.get("text")
        )
        window_tokens = set(_content_tokens(window_text))
        if not window_tokens:
            return None

        newly_covered: List[str] = []
        updated: List[Dict[str, Any]] = []
        for item in agenda:
            entry = dict(item) if isinstance(item, dict) else {"title": str(item)}
            title = str(entry.get("title", "")).strip()
            status = entry.get("status", "pending")
            if title and status != "covered" and _covers(title, window_tokens):
                entry["status"] = "covered"
                newly_covered.append(title)
            updated.append(entry)

        if newly_covered:
            await self._persist_and_broadcast(meeting_id, updated)

        pending = [
            str(i.get("title", "")) for i in updated if i.get("status") != "covered"
        ]
        if (
            pending
            and not newly_covered
            and utterance_count >= _MIN_UTTERANCES_FOR_NUDGE
            and await self._nudge_cooldown_acquired(meeting_id)
        ):
            covered_n = len(updated) - len(pending)
            return {
                "nudge_type": "agenda",
                "title": f"Agenda check — {covered_n}/{len(updated)} items covered",
                "content": "Not yet discussed: " + " · ".join(pending[:4]),
                "source_agent": "agenda_agent",
                "source_data": {"pending_items": pending, "covered_count": covered_n},
                "relevance_score": 0.6,
            }
        return None

    @staticmethod
    async def _persist_and_broadcast(
        meeting_id: str, agenda: List[Dict[str, Any]]
    ) -> None:
        """Write updated statuses and stream progress to the room."""
        try:
            from sqlalchemy import update

            from apps.api.core.database import AsyncSessionLocal
            from apps.api.models.meeting import Meeting
            from apps.api.services.meeting.realtime import meeting_hub

            async with AsyncSessionLocal() as session:
                await session.execute(
                    update(Meeting)
                    .where(Meeting.id == UUID(meeting_id))
                    .values(agenda=agenda)
                )
                await session.commit()

            covered = sum(1 for i in agenda if i.get("status") == "covered")
            await meeting_hub.broadcast(
                meeting_id,
                {
                    "type": "agenda_progress",
                    "agenda": agenda,
                    "covered": covered,
                    "total": len(agenda),
                },
            )
            logger.info(
                f"[Agenda] meeting {meeting_id}: {covered}/{len(agenda)} covered"
            )
        except Exception as e:
            logger.warning(f"[Agenda] persist/broadcast failed: {e}")

    @staticmethod
    async def _nudge_cooldown_acquired(meeting_id: str) -> bool:
        try:
            from apps.api.core.connections import get_redis_client

            redis = await get_redis_client()
            return bool(
                await redis.set(
                    f"agenda:nudge:{meeting_id}",
                    "1",
                    nx=True,
                    ex=_NUDGE_COOLDOWN_SECONDS,
                )
            )
        except Exception:
            return False  # no Redis → skip the reminder rather than spam


agenda_agent = AgendaAgent()
