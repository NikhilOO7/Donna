"""
Analytics & Conversation persistence service.

Writes events to the analytics_events PostgreSQL table and manages
conversation sessions for multi-turn RAG queries.
"""

import logging
import time
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
from uuid import UUID

from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.models.analytics import AnalyticsEvent, ConversationSession

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Analytics Events
# ---------------------------------------------------------------------------

async def track_event(
    session: AsyncSession,
    event_type: str,
    *,
    session_id: Optional[str] = None,
    document_id: Optional[str] = None,
    event_data: Optional[Dict[str, Any]] = None,
    latency_ms: Optional[int] = None,
) -> None:
    """Record an analytics event to PostgreSQL.

    Call this on every query, document upload, voice session, etc.
    Non-blocking: logs errors but does not raise.
    """
    try:
        event = AnalyticsEvent(
            event_type=event_type,
            session_id=session_id,
            document_id=document_id,
            event_data=event_data or {},
            latency_ms=latency_ms,
        )
        session.add(event)
        await session.commit()
    except Exception as e:
        logger.warning(f"Failed to track analytics event: {e}")
        await session.rollback()


async def get_event_stats(
    session: AsyncSession,
    hours: int = 24,
) -> Dict[str, Any]:
    """Get aggregated event statistics for the last N hours."""
    since = datetime.now(timezone.utc).replace(
        hour=datetime.now(timezone.utc).hour - min(hours, 23)
    )

    # Count by event type
    type_query = (
        select(AnalyticsEvent.event_type, func.count().label("count"))
        .where(AnalyticsEvent.created_at >= since)
        .group_by(AnalyticsEvent.event_type)
    )
    result = await session.execute(type_query)
    type_counts = {row.event_type: row.count for row in result}

    # Average latency by event type
    latency_query = (
        select(
            AnalyticsEvent.event_type,
            func.avg(AnalyticsEvent.latency_ms).label("avg_latency"),
            func.percentile_cont(0.95).within_group(AnalyticsEvent.latency_ms).label("p95_latency"),
        )
        .where(AnalyticsEvent.created_at >= since)
        .where(AnalyticsEvent.latency_ms.isnot(None))
        .group_by(AnalyticsEvent.event_type)
    )
    try:
        result = await session.execute(latency_query)
        latencies = {
            row.event_type: {
                "avg_ms": round(row.avg_latency, 1) if row.avg_latency else 0,
                "p95_ms": round(row.p95_latency, 1) if row.p95_latency else 0,
            }
            for row in result
        }
    except Exception:
        latencies = {}

    return {
        "event_counts": type_counts,
        "latencies": latencies,
        "period_hours": hours,
    }


# ---------------------------------------------------------------------------
# Conversation Sessions
# ---------------------------------------------------------------------------

async def get_or_create_conversation(
    session: AsyncSession,
    conversation_id: str,
) -> ConversationSession:
    """Load an existing conversation or create a new one."""
    result = await session.execute(
        select(ConversationSession).where(
            ConversationSession.session_id == conversation_id
        )
    )
    conv = result.scalar_one_or_none()

    if conv is None:
        conv = ConversationSession(
            session_id=conversation_id,
            messages=[],
        )
        session.add(conv)
        await session.flush()

    return conv


async def append_message(
    session: AsyncSession,
    conversation_id: str,
    query: str,
    answer: str,
    metadata: Optional[Dict[str, Any]] = None,
) -> ConversationSession:
    """Append a query/answer pair to a conversation session."""
    conv = await get_or_create_conversation(session, conversation_id)

    messages = list(conv.messages or [])
    messages.append({
        "query": query,
        "answer": answer,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **(metadata or {}),
    })

    # Keep last 20 messages
    if len(messages) > 20:
        messages = messages[-20:]

    conv.messages = messages
    conv.last_activity = datetime.now(timezone.utc)

    await session.commit()
    return conv


async def get_conversation_history(
    session: AsyncSession,
    conversation_id: str,
    last_n: int = 5,
) -> List[Dict[str, Any]]:
    """Get recent messages from a conversation."""
    conv = await get_or_create_conversation(session, conversation_id)
    messages = conv.messages or []
    return messages[-last_n:]
