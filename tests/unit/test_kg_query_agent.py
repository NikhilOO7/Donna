"""
Tests for the KGQueryAgent — the agent that traverses Neo4j during meetings.

These tests focus on the behavior we can verify without a live Neo4j:
  • The phrase extractor heuristic
  • The "Neo4j unavailable → silent no-op" path
"""

import pytest

from apps.api.services.meeting.kg_query_agent import KGQueryAgent


class TestPhraseExtraction:
    def test_extracts_simple_proper_noun(self):
        out = KGQueryAgent._extract_candidate_phrases(
            "Let's go with Acme for the search infrastructure."
        )
        assert "acme" in out

    def test_extracts_multi_word_phrase(self):
        out = KGQueryAgent._extract_candidate_phrases(
            "Beacon Cloud has the strongest compliance posture."
        )
        assert "beacon cloud" in out

    def test_ignores_stopwords(self):
        out = KGQueryAgent._extract_candidate_phrases("Team AI is here")
        assert "team" not in out
        assert "ai" not in out

    def test_handles_empty(self):
        assert KGQueryAgent._extract_candidate_phrases("") == set()

    def test_spacy_catches_lowercase_entities(self):
        """spaCy NER should catch entities even when they're not
        capitalized — the headline upgrade over the regex extractor."""
        out = KGQueryAgent._extract_candidate_phrases(
            "we should compare beacon cloud with acme search before signing"
        )
        # We don't require an exact label match (spaCy can be quirky),
        # but at least one of the multi-word lowercase phrases should
        # surface as a candidate.
        joined = " | ".join(out)
        assert (
            "beacon cloud" in joined
            or "acme search" in joined
            or "beacon" in out
            or "acme" in out
        ), f"spaCy missed lowercase entities; extracted: {out}"


class TestKGQueryAgent:
    @pytest.mark.asyncio
    async def test_no_neo4j_returns_none(self, monkeypatch):
        # Force the Neo4j client to look disabled regardless of config
        class _FakeClient:
            enabled = False

        monkeypatch.setattr(
            "apps.api.services.meeting.kg_query_agent.neo4j_client", _FakeClient()
        )
        agent = KGQueryAgent()
        result = await agent.analyze(
            "meeting-id",
            [{"speaker": "A", "text": "Let's go with Beacon Cloud"}],
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_no_proper_nouns_returns_none(self, monkeypatch):
        class _FakeClient:
            enabled = True

            async def execute(self, *a, **k):
                return None

        monkeypatch.setattr(
            "apps.api.services.meeting.kg_query_agent.neo4j_client", _FakeClient()
        )
        agent = KGQueryAgent()
        # No capitalized words → no candidate phrases → early return
        result = await agent.analyze(
            "mid",
            [{"speaker": "A", "text": "let's start the conversation now please"}],
        )
        assert result is None
