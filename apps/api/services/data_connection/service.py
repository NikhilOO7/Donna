"""
Orchestration for customer data connections.

Every path into a customer's database goes through here, for one reason: this
is where the audit log is written. A query that bypasses this module is a
query nobody can account for later, which for a feature that reads someone
else's production data is not acceptable.

Responsibilities:
  * decrypt credentials into a short-lived spec (never persisted, never logged)
  * run queries through the guards
  * record every attempt — successful or not — to ``data_query_log``
  * expose the two consumption paths:
      ``gather_for_meeting``   cold path, agenda-driven, used by research
      ``answer_data_question`` explicit user ask, used by the assistant
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.config import settings
from apps.api.core.crypto import decrypt
from apps.api.models.data_connection import (
    STATUS_CONNECTED,
    STATUS_ERROR,
    DataConnection,
    DataQueryLog,
)
from apps.api.services.data_connection import connector, introspect, planner

logger = logging.getLogger(__name__)


def spec_for(conn: DataConnection) -> connector.ConnectionSpec:
    """Build a short-lived connection spec. The plaintext never leaves this scope."""
    return connector.ConnectionSpec(
        host=conn.host,
        port=conn.port,
        database=conn.database,
        username=conn.username,
        password=decrypt(conn.password_encrypted),
        ssl_mode=conn.ssl_mode,
        engine=conn.engine,
        allowed_tables=list(conn.allowed_tables or []),
        connection_id=str(conn.id),
    )


async def get_active_connection(
    session: AsyncSession, owner_id: Optional[UUID]
) -> Optional[DataConnection]:
    """The owner's active, verified connection — or None.

    Owner-scoped: a connection is exactly as private as the database it can
    reach, so this filter is the same tenancy boundary as documents and
    meetings.
    """
    if owner_id is None:
        return None
    row = await session.execute(
        select(DataConnection)
        .where(
            DataConnection.owner_id == owner_id,
            DataConnection.is_active.is_(True),
            DataConnection.status == STATUS_CONNECTED,
        )
        .order_by(DataConnection.updated_at.desc())
        .limit(1)
    )
    return row.scalar_one_or_none()


async def _audit(
    session: AsyncSession,
    conn: DataConnection,
    *,
    purpose: str,
    sql: str,
    row_count: int = 0,
    duration_ms: int = 0,
    succeeded: bool = True,
    error: Optional[str] = None,
    meeting_id: Optional[str] = None,
) -> None:
    """Record one statement. Best-effort — auditing must not break the read.

    Note the asymmetry: a failed audit write is logged loudly, because an
    unaudited query is the thing this table exists to prevent.
    """
    try:
        session.add(
            DataQueryLog(
                connection_id=conn.id,
                owner_id=conn.owner_id,
                meeting_id=UUID(meeting_id) if meeting_id else None,
                purpose=purpose,
                sql_text=sql[:8000],
                row_count=row_count,
                duration_ms=duration_ms,
                succeeded=succeeded,
                error=(error or "")[:2000] or None,
            )
        )
        await session.commit()
    except Exception as e:
        logger.error(
            f"[data-connection] FAILED TO AUDIT a query against connection "
            f"{conn.id} — the read happened but is unrecorded: {e}"
        )


async def run_audited(
    session: AsyncSession,
    conn: DataConnection,
    sql: str,
    *,
    purpose: str,
    meeting_id: Optional[str] = None,
) -> Optional[connector.QueryResult]:
    """Execute one guarded query and record it. Returns None on any refusal."""
    spec = spec_for(conn)
    started = time.perf_counter()
    try:
        result = await connector.run_query(
            spec,
            sql,
            allow_private=settings.data_connection_allow_private,
            max_rows=settings.data_connection_max_rows,
            purpose=purpose,
        )
        await _audit(
            session,
            conn,
            purpose=purpose,
            sql=sql,
            row_count=result.row_count,
            duration_ms=result.duration_ms,
            succeeded=True,
            meeting_id=meeting_id,
        )
        return result
    except Exception as e:
        await _audit(
            session,
            conn,
            purpose=purpose,
            sql=sql,
            duration_ms=int((time.perf_counter() - started) * 1000),
            succeeded=False,
            error=str(e),
            meeting_id=meeting_id,
        )
        logger.warning(f"[data-connection] query refused/failed ({purpose}): {e}")
        return None


async def verify_and_profile(
    session: AsyncSession, conn: DataConnection
) -> Dict[str, Any]:
    """Test the connection, prove it is read-only, and cache the schema."""
    spec = spec_for(conn)
    try:
        info = await connector.verify(
            spec, allow_private=settings.data_connection_allow_private
        )
        profile = await introspect.introspect(
            spec, allow_private=settings.data_connection_allow_private
        )
        conn.status = STATUS_CONNECTED
        conn.last_error = None
        conn.last_verified_at = datetime.now(timezone.utc)
        conn.schema_profile = profile
        await session.commit()
        return {**info, "tables_discovered": profile["table_count"], "profile": profile}
    except Exception as e:
        conn.status = STATUS_ERROR
        conn.last_error = str(e)[:2000]
        await session.commit()
        raise


async def gather_for_meeting(
    session: AsyncSession,
    owner_id: Optional[UUID],
    *,
    title: str,
    agenda: List[str],
    meeting_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """COLD PATH: agenda → planned queries → findings for the research brief.

    This is where live querying belongs. Pre-meeting work is minutes-tolerant,
    the plan is auditable after the fact, and nobody is waiting on it during a
    conversation.
    """
    conn = await get_active_connection(session, owner_id)
    if conn is None or not conn.allowed_tables:
        # No connection, or connected but nothing approved yet. Approving
        # nothing is a valid state — it means "read none of my data".
        return []

    schema_text = introspect.schema_prompt(
        conn.schema_profile or {}, list(conn.allowed_tables or [])
    )
    plans = await planner.query_planner.plan(
        schema_prompt_text=schema_text,
        topic=title,
        agenda=agenda,
        allowed_tables=list(conn.allowed_tables or []),
    )

    findings: List[Dict[str, Any]] = []
    for p in plans:
        result = await run_audited(
            session, conn, p["sql"], purpose="meeting_prep", meeting_id=meeting_id
        )
        summary = planner.summarize_results(p["question"], result)
        if summary:
            summary["source"] = f"{conn.name} (your database)"
            summary["sql"] = p["sql"]  # shown in the UI: no black boxes
            findings.append(summary)

    logger.info(
        f"[data-connection] meeting prep produced {len(findings)} finding(s) "
        f"from {len(plans)} planned quer(ies)"
    )
    return findings


async def answer_data_question(
    session: AsyncSession,
    owner_id: Optional[UUID],
    question: str,
    *,
    meeting_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """EXPLICIT ASK: a user asked a data question, so a live query is warranted.

    User-initiated, one query, and the result is attributed to their database
    so nobody mistakes it for a document citation.
    """
    conn = await get_active_connection(session, owner_id)
    if conn is None or not conn.allowed_tables:
        return None

    schema_text = introspect.schema_prompt(
        conn.schema_profile or {}, list(conn.allowed_tables or [])
    )
    plans = await planner.query_planner.plan(
        schema_prompt_text=schema_text,
        topic=question,
        agenda=[question],
        allowed_tables=list(conn.allowed_tables or []),
    )
    if not plans:
        return None

    result = await run_audited(
        session, conn, plans[0]["sql"], purpose="user_question", meeting_id=meeting_id
    )
    summary = planner.summarize_results(plans[0]["question"], result)
    if summary:
        summary["source"] = f"{conn.name} (your database)"
        summary["sql"] = plans[0]["sql"]
    return summary
