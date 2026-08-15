"""
Knowledge-graph outbox: enqueue, drain, observe.

Usage — enqueue inside the transaction that writes the source data, so the
intent to sync is committed atomically with the thing being synced:

    async with AsyncSessionLocal() as session:
        ...write the summary rows...
        await kg_outbox.enqueue_meeting_sync(session, meeting_id=..., ...)
        await session.commit()

The caller may then opportunistically drain so the happy path stays fast.
If that drain fails, the row is still there and the periodic drainer picks
it up — which is the entire point.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.models.outbox import (
    MAX_ATTEMPTS,
    STATUS_DONE,
    STATUS_FAILED,
    STATUS_PENDING,
    KGOutbox,
)

logger = logging.getLogger(__name__)

OP_SYNC_MEETING = "sync_meeting"


async def enqueue_meeting_sync(
    session: AsyncSession,
    *,
    meeting_id: str,
    title: str,
    status: str,
    decisions: List[Dict[str, Any]],
    action_items: List[Dict[str, Any]],
    research_topics: Optional[List[str]] = None,
    utterance_count: int = 0,
    owner_id: Optional[str] = None,
) -> None:
    """Record the intent to mirror a meeting into Neo4j.

    Does NOT commit — it joins the caller's transaction on purpose. That is
    what makes the outbox atomic with the data it describes.
    """
    session.add(
        KGOutbox(
            operation=OP_SYNC_MEETING,
            entity_type="meeting",
            entity_id=str(meeting_id),
            owner_id=owner_id,
            payload={
                "meeting_id": str(meeting_id),
                "title": title,
                "status": status,
                "decisions": decisions or [],
                "action_items": action_items or [],
                "research_topics": research_topics or [],
                "utterance_count": utterance_count,
                "owner_id": str(owner_id) if owner_id else None,
            },
        )
    )


async def _apply(entry: KGOutbox) -> int:
    """Apply one outbox entry to Neo4j. Raises on failure."""
    if entry.operation != OP_SYNC_MEETING:
        raise ValueError(f"unknown outbox operation '{entry.operation}'")

    from apps.api.services.document.knowledge_graph_service import (
        knowledge_graph_service,
    )

    p = entry.payload or {}
    # The underlying Cypher uses MERGE, so re-applying an entry converges
    # rather than duplicating — which is what makes retry safe.
    return await knowledge_graph_service.sync_meeting_to_neo4j(
        meeting_id=p["meeting_id"],
        title=p.get("title") or "",
        status=p.get("status") or "completed",
        decisions=p.get("decisions") or [],
        action_items=p.get("action_items") or [],
        research_topics=p.get("research_topics") or [],
        utterance_count=p.get("utterance_count") or 0,
        owner_id=p.get("owner_id"),
    )


async def drain(session: AsyncSession, limit: int = 50) -> Dict[str, int]:
    """Apply pending entries to Neo4j. Returns {applied, failed, skipped}.

    Rows are claimed with ``FOR UPDATE SKIP LOCKED`` so several drainers can
    run concurrently without processing the same entry twice.
    """
    from apps.api.core.neo4j_client import neo4j_client

    if not neo4j_client.enabled:
        # Not an error: Neo4j is optional. Entries wait, and the health
        # endpoint reports the backlog so the wait is visible.
        return {"applied": 0, "failed": 0, "skipped": 0, "neo4j": 0}

    rows = (
        (
            await session.execute(
                select(KGOutbox)
                .where(KGOutbox.status == STATUS_PENDING)
                .order_by(KGOutbox.created_at)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        )
        .scalars()
        .all()
    )

    applied = failed = 0
    for entry in rows:
        entry.attempts += 1
        try:
            await _apply(entry)
            entry.status = STATUS_DONE
            entry.processed_at = datetime.now(timezone.utc)
            entry.last_error = None
            applied += 1
        except Exception as e:
            entry.last_error = str(e)[:1000]
            if entry.attempts >= MAX_ATTEMPTS:
                # Terminal for the drainer, but deliberately KEPT: the row is
                # the record of what diverged. Deleting it would restore
                # exactly the silent-divergence bug the outbox exists to fix.
                entry.status = STATUS_FAILED
                logger.error(
                    f"[kg-outbox] entry {entry.id} ({entry.entity_type} "
                    f"{entry.entity_id}) FAILED permanently after "
                    f"{entry.attempts} attempts: {e}"
                )
            else:
                logger.warning(
                    f"[kg-outbox] entry {entry.id} attempt {entry.attempts} "
                    f"failed, will retry: {e}"
                )
            failed += 1

    await session.commit()
    if applied or failed:
        logger.info(f"[kg-outbox] drained: {applied} applied, {failed} failed")

    # Refresh the gauges after every drain so alerting reflects reality even
    # when nothing is calling /health.
    try:
        await stats(session)
    except Exception:
        pass

    return {"applied": applied, "failed": failed, "skipped": 0, "neo4j": 1}


async def stats(session: AsyncSession) -> Dict[str, Any]:
    """Backlog health: how far behind is the graph, and is anything stuck?"""
    pending = (
        await session.execute(
            select(func.count())
            .select_from(KGOutbox)
            .where(KGOutbox.status == STATUS_PENDING)
        )
    ).scalar_one()
    failed = (
        await session.execute(
            select(func.count())
            .select_from(KGOutbox)
            .where(KGOutbox.status == STATUS_FAILED)
        )
    ).scalar_one()
    oldest = (
        await session.execute(
            select(func.min(KGOutbox.created_at)).where(
                KGOutbox.status == STATUS_PENDING
            )
        )
    ).scalar_one_or_none()

    lag = None
    if oldest is not None:
        if oldest.tzinfo is None:
            oldest = oldest.replace(tzinfo=timezone.utc)
        lag = round((datetime.now(timezone.utc) - oldest).total_seconds(), 1)

    # Publish for alerting. Reading stats is the only place that knows these
    # numbers, and both /health and the periodic drainer call it — so the
    # gauges stay fresh without a separate collector.
    try:
        from apps.api.core.metrics import (
            KG_OUTBOX_FAILED,
            KG_OUTBOX_OLDEST_PENDING,
            KG_OUTBOX_PENDING,
        )

        KG_OUTBOX_PENDING.set(int(pending))
        KG_OUTBOX_FAILED.set(int(failed))
        KG_OUTBOX_OLDEST_PENDING.set(lag if lag is not None else 0.0)
    except Exception:
        pass  # metrics must never break the thing they measure

    return {
        "pending": int(pending),
        "failed": int(failed),
        "oldest_pending_age_seconds": lag,
        # Failed entries mean the graph is KNOWN to disagree with Postgres.
        # That is a real, actionable state, not a warning to scroll past.
        "graph_diverged": int(failed) > 0,
    }


async def retry_failed(session: AsyncSession) -> int:
    """Reset permanently-failed entries to pending (operator action).

    Used after fixing whatever broke — a Neo4j auth change, a schema issue —
    to replay the divergence rather than accepting it.
    """
    result = await session.execute(
        update(KGOutbox)
        .where(KGOutbox.status == STATUS_FAILED)
        .values(status=STATUS_PENDING, attempts=0, last_error=None)
    )
    await session.commit()
    return int(result.rowcount or 0)
