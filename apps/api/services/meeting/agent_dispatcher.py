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

from apps.api.core.database import AsyncSessionLocal
from apps.api.services.meeting.context_agent import context_agent
from apps.api.services.meeting.fact_check_agent import fact_check_agent
from apps.api.services.meeting.insight_agent import insight_agent
from apps.api.services.meeting.kg_query_agent import kg_query_agent
from apps.api.services.meeting.meeting_service import meeting_service
from apps.api.services.meeting.realtime import meeting_hub
from apps.api.services.meeting.scribe_agent import scribe_agent

logger = logging.getLogger(__name__)


class AgentDispatcher:
    """Orchestrate meeting agents in response to new utterances."""

    async def dispatch(self, meeting_id: str) -> None:
        """Run all agents in parallel for the latest meeting state."""
        try:
            mid = UUID(meeting_id)
        except ValueError:
            logger.warning(f"[Dispatcher] invalid meeting_id: {meeting_id}")
            return

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
                    scribe_agent.analyze(utterances),
                    context_agent.analyze(utterances),
                    insight_agent.analyze(utterances, research_topics),
                    fact_check_agent.analyze(utterances),
                    kg_query_agent.analyze(meeting_id, utterances),
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
