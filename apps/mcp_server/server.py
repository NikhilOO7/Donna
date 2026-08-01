"""
Donna MCP Server — the team's meeting intelligence as tools.

Exposes Donna's knowledge base (documents + meeting memories + decisions)
to any MCP client — Claude Desktop, Claude Code, IDEs — over stdio.
Every tool result carries citations, same as the product UI.

Run standalone:

    uv run python -m apps.mcp_server.server

Claude Desktop config (``claude_desktop_config.json``)::

    {
      "mcpServers": {
        "donna": {
          "command": "uv",
          "args": ["run", "python", "-m", "apps.mcp_server.server"],
          "cwd": "/path/to/voice-doc-intelligence",
          "env": {"DONNA_MCP_OWNER_EMAIL": "you@company.com"}
        }
      }
    }

``DONNA_MCP_OWNER_EMAIL`` scopes every tool to that user's workspace
(same row-level isolation as the API). Unset = unscoped dev mode.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import UUID

# Project root + .env loading (same pattern as the workers)
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv  # noqa: E402

env_path = project_root / ".env"
if env_path.exists():
    load_dotenv(env_path)

from mcp.server.fastmcp import FastMCP  # noqa: E402

mcp = FastMCP("donna")

_owner_cache: Dict[str, Optional[str]] = {}
_services: Dict[str, Any] = {}


def _get_embedder():
    if "embedder" not in _services:
        from apps.api.services.document.contextual_processor import (
            ContextualEmbeddingGenerator,
        )

        _services["embedder"] = ContextualEmbeddingGenerator()
    return _services["embedder"]


def _get_store():
    if "store" not in _services:
        from apps.api.services.document.vector_store import ModernVectorStore

        _services["store"] = ModernVectorStore()
    return _services["store"]


def _get_rag():
    if "rag" not in _services:
        # Modern service — the legacy RAGService reads a collection the
        # ingestion pipeline never writes.
        from apps.api.services.rag.rag_service import ModernRAGService

        _services["rag"] = ModernRAGService()
    return _services["rag"]


async def _owner_id() -> Optional[str]:
    """Resolve DONNA_MCP_OWNER_EMAIL to a user id (cached)."""
    email = (os.environ.get("DONNA_MCP_OWNER_EMAIL") or "").strip().lower()
    if not email:
        return None
    if email in _owner_cache:
        return _owner_cache[email]
    try:
        from sqlalchemy import select

        from apps.api.core.database import AsyncSessionLocal
        from apps.api.models.user import User

        async with AsyncSessionLocal() as session:
            user = (
                await session.execute(select(User).where(User.email == email))
            ).scalar_one_or_none()
            _owner_cache[email] = str(user.id) if user else None
    except Exception:
        _owner_cache[email] = None
    return _owner_cache[email]


@mcp.tool()
async def search_knowledge(query: str, limit: int = 5) -> List[Dict[str, Any]]:
    """Search Donna's knowledge base — uploaded documents AND past meeting
    memories (summaries, decisions, extracted facts). Each result includes
    a citation naming exactly where the knowledge came from."""
    from apps.api.services.rag.rag_service import build_citation

    vector = await _get_embedder().generate_contextual_embedding(
        text=query, context_level="document"
    )
    store = _get_store()
    owner = await _owner_id()
    results = await store.search_with_context(
        query_embedding=vector,
        context_level="unified",
        top_k=max(1, min(limit, 20)),
        filters={"owner_id": owner} if owner else None,
    )
    return [
        {
            "content": (r.content or "")[:500],
            "score": round(float(r.score or 0), 3),
            **build_citation(r.metadata or {}),
        }
        for r in results
    ]


@mcp.tool()
async def ask_donna(question: str) -> Dict[str, Any]:
    """Ask Donna a question answered from the team's documents and meeting
    history. Returns the answer plus the cited sources it drew on."""
    result = await _get_rag().process_query(
        query=question, conversation_id="mcp", owner_id=await _owner_id()
    )
    return {
        "answer": result.get("answer", ""),
        "sources": [
            {
                "citation": s.get("citation"),
                "source_type": s.get("source_type"),
                "content": s.get("content"),
            }
            for s in result.get("sources", [])
        ],
    }


@mcp.tool()
async def list_meetings(limit: int = 10) -> List[Dict[str, Any]]:
    """List recent meetings in the workspace with status and type."""
    from apps.api.core.database import AsyncSessionLocal
    from apps.api.services.meeting.meeting_service import meeting_service

    owner = await _owner_id()
    async with AsyncSessionLocal() as session:
        meetings = await meeting_service.list_meetings(
            session,
            limit=max(1, min(limit, 50)),
            owner_id=UUID(owner) if owner else None,
        )
        return [
            {
                "id": str(m.id),
                "title": m.title,
                "status": m.status,
                "meeting_type": m.meeting_type,
                "scheduled_at": m.scheduled_at.isoformat() if m.scheduled_at else None,
            }
            for m in meetings
        ]


@mcp.tool()
async def get_meeting_brief(meeting_id: str) -> Dict[str, Any]:
    """Full brief for one meeting: summary, decisions (with the verbatim
    conversation quotes that triggered them), and action items."""
    from apps.api.core.database import AsyncSessionLocal
    from apps.api.services.meeting.meeting_service import meeting_service

    async with AsyncSessionLocal() as session:
        meeting = await meeting_service.get_meeting(session, UUID(meeting_id))
        if meeting is None:
            return {"error": "Meeting not found"}
        owner = await _owner_id()
        if owner and meeting.owner_id and str(meeting.owner_id) != owner:
            return {"error": "Meeting not found"}
        return {
            "id": str(meeting.id),
            "title": meeting.title,
            "status": meeting.status,
            "meeting_type": meeting.meeting_type,
            "agenda": meeting.agenda or [],
            "summary": meeting.summary.summary_text if meeting.summary else None,
            "decisions": [
                {
                    "decision": d.decision_text,
                    "owner": d.owner,
                    "status": d.status,
                    "conversation_trigger": d.context,
                }
                for d in (meeting.decisions or [])
            ],
            "action_items": [
                {
                    "description": a.description,
                    "assignee": a.assignee,
                    "priority": a.priority,
                    "status": a.status,
                }
                for a in (meeting.action_items or [])
            ],
        }


@mcp.tool()
async def list_decisions(limit: int = 20) -> List[Dict[str, Any]]:
    """Recent decisions across ALL meetings — the team's decision log,
    each citing its meeting and the conversation that triggered it."""
    from sqlalchemy import select

    from apps.api.core.database import AsyncSessionLocal
    from apps.api.models.meeting import Decision, Meeting

    owner = await _owner_id()
    async with AsyncSessionLocal() as session:
        query = (
            select(Decision, Meeting.title)
            .join(Meeting, Meeting.id == Decision.meeting_id)
            .where(Meeting.deleted_at.is_(None))
            .order_by(Decision.created_at.desc())
            .limit(max(1, min(limit, 100)))
        )
        if owner:
            query = query.where(Meeting.owner_id == UUID(owner))
        rows = (await session.execute(query)).all()
        return [
            {
                "decision": d.decision_text,
                "meeting": title,
                "owner": d.owner,
                "status": d.status,
                "conversation_trigger": d.context,
                "decided_at": d.created_at.isoformat() if d.created_at else None,
            }
            for d, title in rows
        ]


if __name__ == "__main__":
    mcp.run()
