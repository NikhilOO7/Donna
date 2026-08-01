"""Unit tests for the meeting-flow agent (talk-time + decision pace)."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

from apps.api.services.meeting.flow_agent import FlowAgent


def _stats(*pairs):
    total = sum(w for _, w in pairs)
    return [{"speaker": s, "words": w, "share": round(w / total, 3)} for s, w in pairs]


class TestFlowAgent:
    @pytest.mark.asyncio
    async def test_dominance_nudge_when_one_speaker_dominates(self):
        agent = FlowAgent()
        stats = _stats(("Alice", 80), ("Bob", 10), ("Cara", 10))
        with (
            patch.object(
                FlowAgent, "_speaker_stats", new=AsyncMock(return_value=stats)
            ),
            patch.object(FlowAgent, "_broadcast_flow", new=AsyncMock()) as bc,
            patch.object(FlowAgent, "_once", new=AsyncMock(return_value=True)),
        ):
            result = await agent.analyze("m1", utterance_count=25)
        assert result is not None
        assert result["nudge_type"] == "flow"
        assert "Alice" in result["content"]
        bc.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_no_nudge_when_balanced(self):
        agent = FlowAgent()
        stats = _stats(("Alice", 50), ("Bob", 50))
        with (
            patch.object(
                FlowAgent, "_speaker_stats", new=AsyncMock(return_value=stats)
            ),
            patch.object(FlowAgent, "_broadcast_flow", new=AsyncMock()),
            patch.object(FlowAgent, "_once", new=AsyncMock(return_value=True)),
        ):
            result = await agent.analyze("m1", utterance_count=25)
        assert result is None

    @pytest.mark.asyncio
    async def test_no_balance_nudge_for_solo_speaker(self):
        agent = FlowAgent()
        stats = _stats(("Alice", 100))
        with (
            patch.object(
                FlowAgent, "_speaker_stats", new=AsyncMock(return_value=stats)
            ),
            patch.object(FlowAgent, "_broadcast_flow", new=AsyncMock()),
            patch.object(FlowAgent, "_once", new=AsyncMock(return_value=True)),
        ):
            result = await agent.analyze("m1", utterance_count=30)
        assert result is None  # single-speaker rooms aren't "unbalanced"

    @pytest.mark.asyncio
    async def test_no_decision_nudge_after_threshold(self):
        agent = FlowAgent()
        started = datetime.now(timezone.utc) - timedelta(minutes=45)
        with patch.object(FlowAgent, "_once", new=AsyncMock(return_value=True)):
            result = await agent.analyze(
                "m1",
                utterance_count=7,  # not a stats cycle (avoids DB path)
                started_at=started,
                decision_count=0,
            )
        assert result is not None
        assert "no decision" in result["title"]

    @pytest.mark.asyncio
    async def test_no_decision_nudge_suppressed_when_decisions_exist(self):
        agent = FlowAgent()
        started = datetime.now(timezone.utc) - timedelta(minutes=45)
        result = await agent.analyze(
            "m1", utterance_count=7, started_at=started, decision_count=2
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_no_decision_nudge_too_early(self):
        agent = FlowAgent()
        started = datetime.now(timezone.utc) - timedelta(minutes=10)
        result = await agent.analyze(
            "m1", utterance_count=7, started_at=started, decision_count=0
        )
        assert result is None
