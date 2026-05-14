"""
End-to-end integration test for the DURING-phase meeting dispatch loop.

Exercises the real ``agent_dispatcher.dispatch`` orchestration with
every external dependency mocked:

  * Five agents (scribe, context, insight, fact-check, kg-query) are
    patched to return canned nudges.
  * ``meeting_service.get_meeting`` returns a synthetic meeting with
    a transcript + research brief.
  * ``meeting_service.add_nudge`` is recorded so we can assert what
    was persisted.
  * ``meeting_hub.broadcast`` is recorded so we can assert each
    persisted nudge was pushed over the WebSocket.

This is the test that would have caught regressions where the
dispatcher silently dropped agents, or where a refactor of
``meeting_service`` broke nudge persistence — the layer above unit
tests, the layer below "requires a running Postgres + Neo4j".
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("REQUIRE_API_KEY", "false")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("REDIS_HOST", "localhost")
os.environ.setdefault("QDRANT_HOST", "localhost")

import pytest

from apps.api.services.meeting.agent_dispatcher import agent_dispatcher

# ---- Test fixtures --------------------------------------------------------


@dataclass
class _FakeTranscript:
    utterances: List[Dict[str, Any]]


@dataclass
class _FakeResearch:
    topics: List[Dict[str, Any]]


@dataclass
class _FakeMeeting:
    transcript: Optional[_FakeTranscript] = None
    research_brief: Optional[_FakeResearch] = None


@dataclass
class _PersistedNudge:
    id: str
    nudge_type: str
    title: str
    content: str
    source_agent: Optional[str]
    source_data: Optional[Dict[str, Any]]
    relevance_score: Optional[float]
    created_at: Any = None

    def __post_init__(self):
        from datetime import datetime, timezone

        self.created_at = datetime.now(timezone.utc)


def _make_canned_nudge(nudge_type: str, title: str, agent: str) -> Dict[str, Any]:
    return {
        "nudge_type": nudge_type,
        "title": title,
        "content": f"Canned content for {nudge_type}",
        "source_agent": agent,
        "source_data": {"agent": agent},
        "relevance_score": 0.8,
    }


# ---- The test --------------------------------------------------------------


class TestMeetingDispatchFlow:
    @pytest.mark.asyncio
    async def test_full_dispatch_loop_persists_and_broadcasts_all_nudges(self):
        meeting_id = str(uuid.uuid4())

        fake_meeting = _FakeMeeting(
            transcript=_FakeTranscript(
                utterances=[
                    {"speaker": "Alice", "text": "Let's pick Beacon Cloud."},
                    {
                        "speaker": "Bob",
                        "text": "Their compliance posture grew 15% last quarter.",
                    },
                ]
            ),
            research_brief=_FakeResearch(
                topics=[{"topic": "compliance posture", "summary": "Beacon leads."}]
            ),
        )

        # Track what add_nudge persisted
        persisted: List[_PersistedNudge] = []

        async def fake_add_nudge(
            session,
            meeting_id,
            nudge_type,
            title,
            content,
            source_agent=None,
            source_data=None,
            relevance_score=None,
        ):
            n = _PersistedNudge(
                id=str(uuid.uuid4()),
                nudge_type=nudge_type,
                title=title,
                content=content,
                source_agent=source_agent,
                source_data=source_data,
                relevance_score=relevance_score,
            )
            persisted.append(n)
            return n

        broadcasts: List[Dict[str, Any]] = []

        async def fake_broadcast(mid: str, payload: Dict[str, Any]):
            broadcasts.append({"meeting_id": mid, "payload": payload})

        # Fake DB session context manager
        fake_session = AsyncMock()
        session_ctx = MagicMock()
        session_ctx.__aenter__ = AsyncMock(return_value=fake_session)
        session_ctx.__aexit__ = AsyncMock(return_value=None)

        with (
            patch(
                "apps.api.services.meeting.agent_dispatcher.AsyncSessionLocal",
                return_value=session_ctx,
            ),
            patch(
                "apps.api.services.meeting.agent_dispatcher.meeting_service"
            ) as mock_ms,
            patch(
                "apps.api.services.meeting.agent_dispatcher.meeting_hub"
            ) as mock_hub,
            patch(
                "apps.api.services.meeting.agent_dispatcher.scribe_agent"
            ) as mock_scribe,
            patch(
                "apps.api.services.meeting.agent_dispatcher.context_agent"
            ) as mock_context,
            patch(
                "apps.api.services.meeting.agent_dispatcher.insight_agent"
            ) as mock_insight,
            patch(
                "apps.api.services.meeting.agent_dispatcher.fact_check_agent"
            ) as mock_fc,
            patch(
                "apps.api.services.meeting.agent_dispatcher.kg_query_agent"
            ) as mock_kg,
        ):
            mock_ms.get_meeting = AsyncMock(return_value=fake_meeting)
            mock_ms.add_nudge = AsyncMock(side_effect=fake_add_nudge)
            mock_hub.broadcast = AsyncMock(side_effect=fake_broadcast)

            mock_scribe.analyze = AsyncMock(
                return_value=_make_canned_nudge(
                    "decision_prompt", "Decision detected", "scribe_agent"
                )
            )
            mock_context.analyze = AsyncMock(
                return_value=_make_canned_nudge(
                    "context", "Relevant from KB", "context_agent"
                )
            )
            mock_insight.analyze = AsyncMock(
                return_value=_make_canned_nudge(
                    "insight", "Research match", "insight_agent"
                )
            )
            mock_fc.analyze = AsyncMock(return_value=None)  # no claim → no nudge
            mock_kg.analyze = AsyncMock(
                return_value=_make_canned_nudge(
                    "knowledge_graph", "Connection found", "kg_query_agent"
                )
            )

            await agent_dispatcher.dispatch(meeting_id)

        # --- Assertions ---

        # All five agents were invoked exactly once
        mock_scribe.analyze.assert_awaited_once()
        mock_context.analyze.assert_awaited_once()
        mock_insight.analyze.assert_awaited_once()
        mock_fc.analyze.assert_awaited_once()
        mock_kg.analyze.assert_awaited_once()

        # Only the 4 agents that returned a nudge resulted in persistence
        assert len(persisted) == 4
        persisted_types = {n.nudge_type for n in persisted}
        assert persisted_types == {
            "decision_prompt",
            "context",
            "insight",
            "knowledge_graph",
        }

        # Every persisted nudge was broadcast over the meeting WebSocket
        assert len(broadcasts) == 4
        for b in broadcasts:
            assert b["meeting_id"] == meeting_id
            assert b["payload"]["type"] == "nudge_created"
            assert b["payload"]["nudge"]["id"]
            assert b["payload"]["nudge"]["type"] in persisted_types

    @pytest.mark.asyncio
    async def test_agent_exception_does_not_break_the_batch(self):
        """If one agent raises, the other four still produce nudges."""
        meeting_id = str(uuid.uuid4())

        fake_meeting = _FakeMeeting(
            transcript=_FakeTranscript(
                utterances=[{"speaker": "A", "text": "Something to discuss here"}]
            ),
            research_brief=None,
        )

        persisted: List[_PersistedNudge] = []

        async def fake_add_nudge(session, meeting_id, **kw):
            n = _PersistedNudge(
                id=str(uuid.uuid4()),
                nudge_type=kw["nudge_type"],
                title=kw["title"],
                content=kw["content"],
                source_agent=kw.get("source_agent"),
                source_data=kw.get("source_data"),
                relevance_score=kw.get("relevance_score"),
            )
            persisted.append(n)
            return n

        fake_session = AsyncMock()
        session_ctx = MagicMock()
        session_ctx.__aenter__ = AsyncMock(return_value=fake_session)
        session_ctx.__aexit__ = AsyncMock(return_value=None)

        with (
            patch(
                "apps.api.services.meeting.agent_dispatcher.AsyncSessionLocal",
                return_value=session_ctx,
            ),
            patch(
                "apps.api.services.meeting.agent_dispatcher.meeting_service"
            ) as mock_ms,
            patch(
                "apps.api.services.meeting.agent_dispatcher.meeting_hub"
            ) as mock_hub,
            patch(
                "apps.api.services.meeting.agent_dispatcher.scribe_agent"
            ) as mock_scribe,
            patch(
                "apps.api.services.meeting.agent_dispatcher.context_agent"
            ) as mock_context,
            patch(
                "apps.api.services.meeting.agent_dispatcher.insight_agent"
            ) as mock_insight,
            patch(
                "apps.api.services.meeting.agent_dispatcher.fact_check_agent"
            ) as mock_fc,
            patch(
                "apps.api.services.meeting.agent_dispatcher.kg_query_agent"
            ) as mock_kg,
        ):
            mock_ms.get_meeting = AsyncMock(return_value=fake_meeting)
            mock_ms.add_nudge = AsyncMock(side_effect=fake_add_nudge)
            mock_hub.broadcast = AsyncMock()

            mock_scribe.analyze = AsyncMock(
                side_effect=RuntimeError("scribe blew up")
            )
            mock_context.analyze = AsyncMock(
                return_value=_make_canned_nudge("context", "C", "context_agent")
            )
            mock_insight.analyze = AsyncMock(
                return_value=_make_canned_nudge("insight", "I", "insight_agent")
            )
            mock_fc.analyze = AsyncMock(return_value=None)
            mock_kg.analyze = AsyncMock(
                return_value=_make_canned_nudge(
                    "knowledge_graph", "K", "kg_query_agent"
                )
            )

            await agent_dispatcher.dispatch(meeting_id)

        # Three non-failing agents that returned nudges → 3 persisted
        assert len(persisted) == 3
        assert {n.nudge_type for n in persisted} == {
            "context",
            "insight",
            "knowledge_graph",
        }

    @pytest.mark.asyncio
    async def test_no_transcript_no_dispatch(self):
        """Empty meeting → dispatcher returns early, agents never run."""
        meeting_id = str(uuid.uuid4())

        fake_meeting = _FakeMeeting(transcript=None)
        fake_session = AsyncMock()
        session_ctx = MagicMock()
        session_ctx.__aenter__ = AsyncMock(return_value=fake_session)
        session_ctx.__aexit__ = AsyncMock(return_value=None)

        with (
            patch(
                "apps.api.services.meeting.agent_dispatcher.AsyncSessionLocal",
                return_value=session_ctx,
            ),
            patch(
                "apps.api.services.meeting.agent_dispatcher.meeting_service"
            ) as mock_ms,
            patch(
                "apps.api.services.meeting.agent_dispatcher.scribe_agent"
            ) as mock_scribe,
            patch(
                "apps.api.services.meeting.agent_dispatcher.context_agent"
            ) as mock_context,
        ):
            mock_ms.get_meeting = AsyncMock(return_value=fake_meeting)
            mock_scribe.analyze = AsyncMock()
            mock_context.analyze = AsyncMock()

            await agent_dispatcher.dispatch(meeting_id)

        mock_scribe.analyze.assert_not_awaited()
        mock_context.analyze.assert_not_awaited()
