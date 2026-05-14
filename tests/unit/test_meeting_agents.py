"""
Tests for the DURING-phase meeting agents and dispatcher.

Focuses on the cheap pre-check / pure-Python paths to avoid hitting
OpenAI or Exa in unit tests:
  • scribe_agent: regex gate
  • fact_check_agent: claim regex + Exa missing → silent no-op
  • context_agent: early-return on short input
"""

import pytest

from apps.api.services.meeting.context_agent import ContextAgent
from apps.api.services.meeting.fact_check_agent import (
    CLAIM_PATTERNS,
    FactCheckAgent,
)
from apps.api.services.meeting.scribe_agent import scribe_agent


class TestScribeAgent:
    """Scribe agent decision detection."""

    @pytest.mark.asyncio
    async def test_returns_none_for_empty_utterances(self):
        result = await scribe_agent.analyze([])
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_no_decision_keywords(self):
        utterances = [
            {"speaker": "A", "text": "hello there"},
            {"speaker": "B", "text": "nice to meet you"},
        ]
        # No decision-pattern words → regex gate short-circuits before any LLM call
        result = await scribe_agent.analyze(utterances)
        assert result is None


class TestContextAgent:
    """Context (RAG) agent gating."""

    @pytest.mark.asyncio
    async def test_returns_none_for_empty(self):
        agent = ContextAgent()
        assert await agent.analyze([]) is None

    @pytest.mark.asyncio
    async def test_returns_none_for_short_query(self):
        agent = ContextAgent()
        # < 20 chars combined → short-circuits before embedder
        assert await agent.analyze([{"text": "hi"}]) is None


class TestFactCheckAgent:
    """Fact-check agent pre-filter and Exa gating."""

    def test_claim_patterns_match_percentages(self):
        assert CLAIM_PATTERNS.search("Market grew 15% last quarter")
        assert CLAIM_PATTERNS.search("Prices increased 8.2%")

    def test_claim_patterns_match_attribution(self):
        assert CLAIM_PATTERNS.search("According to Reuters, the market doubled")
        assert CLAIM_PATTERNS.search("Reports say revenue rose")

    def test_claim_patterns_ignore_chitchat(self):
        assert not CLAIM_PATTERNS.search("hello team, how are you")
        assert not CLAIM_PATTERNS.search("let's start the meeting")

    @pytest.mark.asyncio
    async def test_no_exa_key_returns_none(self, monkeypatch):
        # Without EXA_API_KEY, agent should silently no-op regardless of input
        monkeypatch.setattr(
            "apps.api.services.meeting.fact_check_agent.settings",
            type("S", (), {"exa_api_key": None, "openai_api_key": "x"})(),
        )
        agent = FactCheckAgent()
        result = await agent.analyze(
            [{"speaker": "A", "text": "Market grew 15% last quarter"}]
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_short_utterance_returns_none(self):
        agent = FactCheckAgent()
        # Short text bypasses claim extraction entirely
        result = await agent.analyze([{"text": "yes"}])
        assert result is None
