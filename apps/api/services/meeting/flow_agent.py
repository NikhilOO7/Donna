"""
Meeting-Flow Agent.

The PDF's "meeting-flow awareness": watches HOW the meeting is going, not
what's being said — talk-time balance per speaker, elapsed time with no
decision logged — and nudges the leader when the room's dynamics need
attention. Streams a ``flow_update`` event so the UI can render a live
talk-time meter.

LLM-free by design: everything derives from utterance metadata that
Postgres aggregates in one query, so it can run on every dispatch cycle.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from apps.api.core.logging import warn_throttled

logger = logging.getLogger(__name__)

# Don't judge the room's balance before it has had a chance to balance.
_MIN_UTTERANCES_FOR_BALANCE = 20
# One speaker holding more than this share of the words is "dominating".
_DOMINANCE_THRESHOLD = 0.65
# Minutes into the meeting after which "no decision yet" is worth raising.
_NO_DECISION_AFTER_MINUTES = 30

_BALANCE_COOLDOWN_SECONDS = 900  # at most one balance nudge / 15 min
# Recompute talk-time every N utterances (the aggregate is one SQL query,
# but there's no need to re-run it on every single sentence).
_STATS_EVERY_N = 5


class FlowAgent:
    """Talk-time balance + decision-pace awareness for live meetings."""

    async def analyze(
        self,
        meeting_id: str,
        utterance_count: int = 0,
        started_at: Optional[datetime] = None,
        decision_count: int = 0,
    ) -> Optional[Dict[str, Any]]:
        if utterance_count <= 0:
            return None

        # Talk-time meter + dominance check (every Nth utterance)
        if utterance_count % _STATS_EVERY_N == 0:
            stats = await self._speaker_stats(meeting_id)
            if stats:
                await self._broadcast_flow(meeting_id, stats)
                nudge = await self._balance_nudge(meeting_id, utterance_count, stats)
                if nudge:
                    return nudge

        # Decision-pace check: long meeting, nothing logged
        if started_at and decision_count == 0:
            now = datetime.now(timezone.utc)
            start = (
                started_at
                if started_at.tzinfo
                else started_at.replace(tzinfo=timezone.utc)
            )
            elapsed_min = (now - start).total_seconds() / 60
            if elapsed_min >= _NO_DECISION_AFTER_MINUTES and await self._once(
                f"flow:nodecision:{meeting_id}"
            ):
                return {
                    "nudge_type": "flow",
                    "title": f"{int(elapsed_min)} minutes in — no decision logged yet",
                    "content": (
                        "The conversation is flowing, but nothing has been "
                        "committed. Worth pausing to lock in a decision or "
                        "an action item?"
                    ),
                    "source_agent": "flow_agent",
                    "source_data": {"elapsed_minutes": int(elapsed_min)},
                    "relevance_score": 0.65,
                }
        return None

    async def _balance_nudge(
        self, meeting_id: str, utterance_count: int, stats: List[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        if utterance_count < _MIN_UTTERANCES_FOR_BALANCE or len(stats) < 2:
            return None
        top = stats[0]
        if top["share"] < _DOMINANCE_THRESHOLD:
            return None
        if not await self._once(
            f"flow:balance:{meeting_id}", ttl=_BALANCE_COOLDOWN_SECONDS
        ):
            return None
        quiet = [s["speaker"] for s in stats[1:] if s["share"] < 0.15][:3]
        content = f"{top['speaker']} has {int(top['share'] * 100)}% of the airtime."
        if quiet:
            content += " Haven't heard much from " + ", ".join(quiet) + "."
        return {
            "nudge_type": "flow",
            "title": "Talk-time is getting one-sided",
            "content": content,
            "source_agent": "flow_agent",
            "source_data": {"talk_time": stats},
            "relevance_score": 0.6,
        }

    @staticmethod
    async def _speaker_stats(meeting_id: str) -> List[Dict[str, Any]]:
        """Per-speaker word share, aggregated inside Postgres.

        Returns [{speaker, words, share}] sorted by share desc. Donna's own
        utterances (Ask-Donna answers logged to the transcript) are excluded.
        """
        try:
            from sqlalchemy import text

            from apps.api.core.database import AsyncSessionLocal

            query = text(
                """
                SELECT u->>'speaker' AS speaker,
                       SUM(GREATEST(1,
                           array_length(regexp_split_to_array(
                               COALESCE(u->>'text', ''), '\\s+'), 1)
                       )) AS words
                FROM doc_intel.meeting_transcripts t,
                     jsonb_array_elements(t.utterances::jsonb) u
                WHERE t.meeting_id = :mid
                  AND COALESCE(u->>'speaker', '') NOT IN ('', 'Donna')
                GROUP BY 1
                """
            )
            async with AsyncSessionLocal() as session:
                rows = (await session.execute(query, {"mid": UUID(meeting_id)})).all()
            total = sum(int(r.words or 0) for r in rows)
            if total <= 0:
                return []
            stats = [
                {
                    "speaker": r.speaker,
                    "words": int(r.words or 0),
                    "share": round(int(r.words or 0) / total, 3),
                }
                for r in rows
            ]
            stats.sort(key=lambda s: s["share"], reverse=True)
            return stats
        except Exception as e:
            logger.warning(f"[Flow] speaker stats failed: {e}")
            return []

    @staticmethod
    async def _broadcast_flow(meeting_id: str, stats: List[Dict[str, Any]]) -> None:
        try:
            from apps.api.services.meeting.realtime import meeting_hub

            await meeting_hub.broadcast(
                meeting_id, {"type": "flow_update", "talk_time": stats}
            )
        except Exception as e:
            warn_throttled(
                logger,
                "flow.broadcast",
                f"[Flow] talk-time broadcast skipped — the meter will not update "
                f"in the UI: {e}",
            )

    @staticmethod
    async def _once(key: str, ttl: int = 6 * 3600) -> bool:
        """True the first time ``key`` is claimed within ``ttl``."""
        try:
            from apps.api.core.connections import get_redis_client

            redis = await get_redis_client()
            return bool(await redis.set(key, "1", nx=True, ex=ttl))
        except Exception:
            return False  # no Redis → suppress rather than spam


flow_agent = FlowAgent()
