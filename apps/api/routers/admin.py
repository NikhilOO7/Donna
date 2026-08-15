"""
Operator endpoints.

Small, deliberately boring surface for the things an on-call engineer needs to
*do* rather than read. Everything here is authenticated; nothing here is
reachable without a logged-in user, because a "just an admin tool" endpoint is
still an endpoint.

The knowledge-graph outbox is the main occupant: `/health` reports that
Postgres and Neo4j disagree, and this is where you act on it once the
underlying cause is fixed.
"""

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.auth import require_user
from apps.api.core.database import get_db
from apps.api.services.document import kg_outbox

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


@router.get("/kg-outbox")
async def kg_outbox_status(
    session: AsyncSession = Depends(get_db),
    _user=Depends(require_user),
) -> Dict[str, Any]:
    """Backlog health for Postgres → Neo4j replication.

    ``graph_diverged`` is the field that matters: it means at least one write
    exhausted its retries, so the graph is *known* to disagree with the system
    of record. That used to be invisible — the pre-outbox code logged
    "KG sync skipped" and moved on.
    """
    stats = await kg_outbox.stats(session)
    return {
        **stats,
        "interpretation": (
            "graph_diverged=true means at least one write permanently failed; "
            "fix the underlying cause, then POST /api/v1/admin/kg-outbox/retry "
            "to replay. pending>0 with a small age is normal — the drainer runs "
            "every 2 minutes."
        ),
    }


@router.post("/kg-outbox/retry")
async def kg_outbox_retry(
    session: AsyncSession = Depends(get_db),
    _user=Depends(require_user),
) -> Dict[str, Any]:
    """Reset permanently-failed outbox entries to pending, so they replay.

    Deliberately manual. Auto-retrying forever would turn a permanent failure
    (bad Cypher, an auth change, a schema mismatch) into an infinite loop that
    hides the cause — the entries stop retrying precisely so somebody looks.
    Run this *after* fixing whatever broke.
    """
    requeued = await kg_outbox.retry_failed(session)
    return {
        "requeued": requeued,
        "note": (
            "entries are back in the queue; the drainer picks them up within "
            "~2 minutes. Watch /health -> kg_outbox.failed to confirm it "
            "returns to 0 rather than climbing straight back."
        ),
    }


@router.post("/kg-outbox/drain")
async def kg_outbox_drain(
    limit: int = 200,
    session: AsyncSession = Depends(get_db),
    _user=Depends(require_user),
) -> Dict[str, Any]:
    """Drain the outbox now instead of waiting for the scheduled run.

    Useful immediately after a Neo4j outage clears, when waiting two minutes
    to find out whether replication recovered is two minutes too long.
    """
    if limit < 1 or limit > 1000:
        raise HTTPException(400, "limit must be between 1 and 1000")
    return await kg_outbox.drain(session, limit=limit)
