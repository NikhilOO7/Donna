"""
Agent Dispatcher.

After each utterance, fans out to the meeting-time agents
(scribe, context, insight) in parallel. Persists any nudge
they produce. Designed to run as a FastAPI background task —
does not block the API response.
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional
from uuid import UUID

from apps.api.core.config import settings
from apps.api.core.coordination import distributed_lock
from apps.api.core.database import AsyncSessionLocal
from apps.api.core.tracing import get_tracer
from apps.api.services.meeting.context_agent import context_agent
from apps.api.services.meeting.fact_check_agent import fact_check_agent
from apps.api.services.meeting.insight_agent import insight_agent
from apps.api.services.meeting.kg_query_agent import kg_query_agent
from apps.api.services.meeting.meeting_service import meeting_service
from apps.api.services.meeting.realtime import meeting_hub
from apps.api.services.meeting.scribe_agent import scribe_agent

logger = logging.getLogger(__name__)


async def _traced(span_name: str, coro):
    """Run an agent coroutine inside an OTel span (no-op when tracing off).

    Gives per-agent latency in traces — the building block for a
    per-agent latency dashboard.
    """
    if not settings.enable_tracing:
        return await coro
    tracer = get_tracer("meeting.agents")
    if tracer is None:
        return await coro
    with tracer.start_as_current_span(span_name):
        return await coro


class AgentDispatcher:
    """Orchestrate meeting agents in response to new utterances."""

    async def dispatch(self, meeting_id: str) -> None:
        """Run all agents in parallel for the latest meeting state.

        Serialized per meeting via a distributed lock: overlapping
        utterances (common with voice) can't run two dispatch cycles
        concurrently and double-emit the same nudge. Each cycle reads
        fresh committed state, so serializing also guarantees the latest
        utterance is always analyzed.
        """
        try:
            mid = UUID(meeting_id)
        except ValueError:
            logger.warning(f"[Dispatcher] invalid meeting_id: {meeting_id}")
            return

        async with distributed_lock(
            f"dispatch:{meeting_id}", ttl_seconds=30.0, wait=True, wait_timeout=20.0
        ) as acquired:
            if not acquired:
                logger.info(
                    f"[Dispatcher] meeting {meeting_id}: lock busy, skipping "
                    "(in-progress cycle will cover latest state)"
                )
                return
            await self._dispatch_locked(meeting_id, mid)

    async def _dispatch_locked(self, meeting_id: str, mid: UUID) -> None:
        async with AsyncSessionLocal() as session:
            try:
                # Pull fresh state for this dispatch cycle
                meeting = await meeting_service.get_meeting(session, mid)
                if not meeting or not meeting.transcript:
                    return

                utterances: List[Dict[str, Any]] = list(
                    meeting.transcript.utterances or []
                )
                if not utterances:
                    return

                research_topics = (
                    meeting.research_brief.topics
                    if meeting.research_brief and meeting.research_brief.topics
                    else []
                )

                # Run agents in parallel — each returns Optional[nudge dict]
                results = await asyncio.gather(
                    _traced("agent.scribe", scribe_agent.analyze(utterances)),
                    _traced("agent.context", context_agent.analyze(utterances)),
                    _traced(
                        "agent.insight",
                        insight_agent.analyze(utterances, research_topics),
                    ),
                    _traced(
                        "agent.fact_check",
                        fact_check_agent.analyze(utterances, meeting_id=meeting_id),
                    ),
                    _traced(
                        "agent.kg_query",
                        kg_query_agent.analyze(meeting_id, utterances),
                    ),
                    return_exceptions=True,
                )

                # Persist non-empty nudges. Filter out exceptions and Nones.
                created = 0
                for r in results:
                    if isinstance(r, Exception):
                        logger.warning(f"[Dispatcher] agent error: {r}")
                        continue
                    nudge: Optional[Dict[str, Any]] = r
                    if not nudge:
                        continue

                    try:
                        persisted = await meeting_service.add_nudge(
                            session=session,
                            meeting_id=mid,
                            nudge_type=nudge["nudge_type"],
                            title=nudge["title"],
                            content=nudge["content"],
                            source_agent=nudge.get("source_agent"),
                            source_data=nudge.get("source_data"),
                            relevance_score=nudge.get("relevance_score"),
                        )
                        created += 1
                        # Push to any connected WebSocket clients
                        await meeting_hub.broadcast(
                            meeting_id,
                            {
                                "type": "nudge_created",
                                "nudge": {
                                    "id": str(persisted.id),
                                    "type": persisted.nudge_type,
                                    "title": persisted.title,
                                    "content": persisted.content,
                                    "source_agent": persisted.source_agent,
                                    "source_data": persisted.source_data,
                                    "relevance_score": persisted.relevance_score,
                                    "created_at": persisted.created_at.isoformat()
                                    if persisted.created_at
                                    else None,
                                },
                            },
                        )
                    except Exception as e:
                        logger.warning(f"[Dispatcher] failed to persist nudge: {e}")

                if created:
                    logger.info(
                        f"[Dispatcher] meeting {meeting_id}: {created} nudge(s) created"
                    )

            except Exception as e:
                logger.error(f"[Dispatcher] failed for meeting {meeting_id}: {e}")


agent_dispatcher = AgentDispatcher()
