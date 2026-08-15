"""
Settings API for customer database connections.

Every endpoint is owner-scoped and returns 404 (not 403) for a connection the
caller does not own — a 403 confirms existence, which is itself a leak.

The password is write-only across this entire surface: it can be set, it can
be replaced, and it is never returned in any response, at any verbosity, ever.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.auth import require_user
from apps.api.core.config import settings
from apps.api.core.crypto import encrypt, encryption_available
from apps.api.core.database import get_db
from apps.api.models.data_connection import (
    SUPPORTED_ENGINES,
    DataConnection,
    DataQueryLog,
)
from apps.api.services.data_connection import guard, indexer, service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/data-connections", tags=["data-connections"])


class ConnectionCreate(BaseModel):
    name: str = Field(..., max_length=120)
    engine: str = "postgresql"
    host: str
    port: int = 5432
    database: str
    username: str
    password: str  # write-only: never echoed back
    ssl_mode: str = "require"


class ConnectionUpdate(BaseModel):
    name: Optional[str] = None
    password: Optional[str] = None
    ssl_mode: Optional[str] = None
    allowed_tables: Optional[List[str]] = None
    is_active: Optional[bool] = None


def _public(conn: DataConnection) -> Dict[str, Any]:
    """Serialise a connection. Deliberately has no password branch at all —
    the safest way to never leak a secret is to have no code path that could."""
    return {
        "id": str(conn.id),
        "name": conn.name,
        "engine": conn.engine,
        "host": conn.host,
        "port": conn.port,
        "database": conn.database,
        "username": conn.username,
        "ssl_mode": conn.ssl_mode,
        "status": conn.status,
        "last_error": conn.last_error,
        "last_verified_at": conn.last_verified_at.isoformat()
        if conn.last_verified_at
        else None,
        "allowed_tables": list(conn.allowed_tables or []),
        "table_count": (conn.schema_profile or {}).get("table_count", 0),
        "last_indexed_at": conn.last_indexed_at.isoformat()
        if conn.last_indexed_at
        else None,
        "indexed_row_count": conn.indexed_row_count,
        "is_active": conn.is_active,
    }


async def _owned(session: AsyncSession, connection_id: str, user) -> DataConnection:
    try:
        cid = UUID(connection_id)
    except ValueError:
        raise HTTPException(400, "Invalid connection id")
    row = await session.execute(select(DataConnection).where(DataConnection.id == cid))
    conn = row.scalar_one_or_none()
    # 404 rather than 403: a 403 confirms the row exists.
    if conn is None or (user is not None and str(conn.owner_id) != str(user.id)):
        raise HTTPException(404, "Connection not found")
    return conn


@router.get("")
async def list_connections(
    session: AsyncSession = Depends(get_db), user=Depends(require_user)
):
    rows = await session.execute(
        select(DataConnection)
        .where(DataConnection.owner_id == user.id)
        .order_by(DataConnection.created_at.desc())
    )
    return {
        "connections": [_public(c) for c in rows.scalars().all()],
        "encryption_ready": encryption_available(),
        "allow_private_hosts": settings.data_connection_allow_private,
    }


@router.post("", status_code=201)
async def create_connection(
    body: ConnectionCreate,
    session: AsyncSession = Depends(get_db),
    user=Depends(require_user),
):
    """Store a connection. Refuses before persisting anything if the host is
    disallowed or credentials cannot be encrypted — a stored-but-unusable
    connection is worse than a clear failure."""
    if body.engine not in SUPPORTED_ENGINES:
        raise HTTPException(
            400, f"Unsupported engine. Supported: {', '.join(SUPPORTED_ENGINES)}"
        )
    if not encryption_available():
        raise HTTPException(
            503,
            "ENCRYPTION_KEY is not configured, so database credentials cannot "
            "be stored securely. Set it and restart before adding a connection.",
        )

    verdict = guard.check_host(
        body.host, allow_private=settings.data_connection_allow_private
    )
    if not verdict.allowed:
        raise HTTPException(400, verdict.reason)

    conn = DataConnection(
        owner_id=user.id,
        name=body.name.strip(),
        engine=body.engine,
        host=body.host.strip(),
        port=body.port,
        database=body.database.strip(),
        username=body.username.strip(),
        password_encrypted=encrypt(body.password),
        ssl_mode=body.ssl_mode,
        allowed_tables=[],  # nothing approved until the customer ticks tables
    )
    session.add(conn)
    await session.commit()
    await session.refresh(conn)
    logger.info(f"[data-connection] created '{conn.name}' for owner {user.id}")
    return _public(conn)


@router.post("/{connection_id}/verify")
async def verify_connection(
    connection_id: str,
    session: AsyncSession = Depends(get_db),
    user=Depends(require_user),
):
    """Connect, prove the account cannot write, and cache the schema."""
    conn = await _owned(session, connection_id, user)
    try:
        result = await service.verify_and_profile(session, conn)
    except Exception as e:
        raise HTTPException(400, str(e)[:400])
    profile = result.pop("profile", {})
    return {
        "connection": _public(conn),
        "check": result,
        # The customer picks from this list; nothing is read until they do.
        "tables": [
            {
                "qualified": t["qualified"],
                "row_estimate": t["row_estimate"],
                "column_count": len(t["columns"]),
                "sensitive_columns": t["sensitive_columns"],
            }
            for t in profile.get("tables", [])
        ],
    }


@router.patch("/{connection_id}")
async def update_connection(
    connection_id: str,
    body: ConnectionUpdate,
    session: AsyncSession = Depends(get_db),
    user=Depends(require_user),
):
    conn = await _owned(session, connection_id, user)
    if body.name is not None:
        conn.name = body.name.strip()
    if body.ssl_mode is not None:
        conn.ssl_mode = body.ssl_mode
    if body.password:
        conn.password_encrypted = encrypt(body.password)
    if body.is_active is not None:
        conn.is_active = body.is_active
    if body.allowed_tables is not None:
        # Only identifiers that exist in the discovered profile may be
        # approved — this stops an arbitrary string reaching query planning.
        known = {t["qualified"] for t in (conn.schema_profile or {}).get("tables", [])}
        requested = set(body.allowed_tables)
        unknown = requested - known
        if unknown:
            raise HTTPException(
                400,
                "These tables are not in the discovered schema: "
                + ", ".join(sorted(unknown)),
            )
        conn.allowed_tables = sorted(requested)
    await session.commit()
    return _public(conn)


@router.post("/{connection_id}/sync")
async def sync_connection(
    connection_id: str,
    session: AsyncSession = Depends(get_db),
    user=Depends(require_user),
):
    """Snapshot approved tables into the vector store for in-meeting use."""
    conn = await _owned(session, connection_id, user)
    if not conn.allowed_tables:
        raise HTTPException(400, "Approve at least one table before syncing.")
    report = await indexer.snapshot_connection(
        conn, session, allow_private=settings.data_connection_allow_private
    )
    return {"connection": _public(conn), **report}


@router.get("/{connection_id}/audit")
async def connection_audit(
    connection_id: str,
    limit: int = 50,
    session: AsyncSession = Depends(get_db),
    user=Depends(require_user),
):
    """Every statement Donna has run against this database.

    Exposed to the customer, not just to operators: "what did you run against
    my database?" should be self-service.
    """
    conn = await _owned(session, connection_id, user)
    rows = await session.execute(
        select(DataQueryLog)
        .where(DataQueryLog.connection_id == conn.id)
        .order_by(DataQueryLog.created_at.desc())
        .limit(min(max(limit, 1), 200))
    )
    return {
        "queries": [
            {
                "purpose": q.purpose,
                "sql": q.sql_text,
                "row_count": q.row_count,
                "duration_ms": q.duration_ms,
                "succeeded": q.succeeded,
                "error": q.error,
                "at": q.created_at.isoformat() if q.created_at else None,
            }
            for q in rows.scalars().all()
        ]
    }


@router.delete("/{connection_id}", status_code=204)
async def delete_connection(
    connection_id: str,
    session: AsyncSession = Depends(get_db),
    user=Depends(require_user),
):
    conn = await _owned(session, connection_id, user)
    await session.delete(conn)
    await session.commit()
    logger.info(f"[data-connection] deleted connection {connection_id}")
