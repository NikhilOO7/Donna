"""Unit tests for the agenda-tracking agent (pure lexical, no LLM)."""

from unittest.mock import AsyncMock, patch

import pytest

from apps.api.services.meeting.agenda_agent import AgendaAgent, _content_tokens, _covers


def _utt(text: str, speaker: str = "A"):
    return {"speaker": speaker, "text": text}


class TestLexicalMatching:
    def test_content_tokens_drop_stopwords(self):
        tokens = _content_tokens("Review the Q3 pricing strategy for launch")
        assert "pricing" in tokens and "strategy" in tokens and "launch" in tokens
        assert "the" not in tokens and "review" not in tokens

    def test_covers_when_most_tokens_present(self):
        window = set(_content_tokens("we talked about pricing strategy today"))
        assert _covers("Pricing strategy", window)

    def test_does_not_cover_unrelated(self):
        window = set(_content_tokens("the weather is nice outside"))
        assert not _covers("Pricing strategy", window)


class TestAgendaAgent:
    @pytest.mark.asyncio
    async def test_marks_item_covered_and_returns_no_nudge(self):
        agent = AgendaAgent()
        with patch.object(
            AgendaAgent, "_persist_and_broadcast", new=AsyncMock()
        ) as persist:
            result = await agent.analyze(
                "m1",
                [_utt("let's dig into the pricing strategy numbers")],
                agenda=[{"title": "Pricing strategy", "status": "pending"}],
                utterance_count=5,
            )
        assert result is None
        persist.assert_awaited_once()
        updated = persist.await_args.args[1]
        assert updated[0]["status"] == "covered"

    @pytest.mark.asyncio
    async def test_uncovered_nudge_after_threshold(self):
        agent = AgendaAgent()
        with (
            patch.object(AgendaAgent, "_persist_and_broadcast", new=AsyncMock()),
            patch.object(
                AgendaAgent,
                "_nudge_cooldown_acquired",
                new=AsyncMock(return_value=True),
            ),
        ):
            result = await agent.analyze(
                "m1",
                [_utt("completely unrelated chatter about lunch options")],
                agenda=[
                    {"title": "Budget approval", "status": "pending"},
                    {"title": "Hiring plan", "status": "covered"},
                ],
                utterance_count=30,
            )
        assert result is not None
        assert result["nudge_type"] == "agenda"
        assert "Budget approval" in result["content"]
        assert result["source_data"]["covered_count"] == 1

    @pytest.mark.asyncio
    async def test_no_nudge_below_utterance_threshold(self):
        agent = AgendaAgent()
        result = await agent.analyze(
            "m1",
            [_utt("unrelated chatter")],
            agenda=[{"title": "Budget approval", "status": "pending"}],
            utterance_count=3,
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_empty_agenda_returns_none(self):
        agent = AgendaAgent()
        result = await agent.analyze("m1", [_utt("hello")], agenda=[])
        assert result is None

    @pytest.mark.asyncio
    async def test_string_items_normalized(self):
        agent = AgendaAgent()
        with patch.object(
            AgendaAgent, "_persist_and_broadcast", new=AsyncMock()
        ) as persist:
            await agent.analyze(
                "m1",
                [_utt("the hiring plan looks solid for engineering")],
                agenda=["Hiring plan"],
                utterance_count=2,
            )
        updated = persist.await_args.args[1]
        assert updated[0] == {"title": "Hiring plan", "status": "covered"}
