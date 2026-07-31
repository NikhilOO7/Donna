"""Unit tests for the ActivationAgent (expertise ↔ conversation matching)."""

from apps.api.services.meeting.activation_agent import ActivationAgent


def _utt(speaker: str, text: str) -> dict:
    return {"speaker": speaker, "text": text}


async def test_matches_expertise_and_builds_nudge():
    agent = ActivationAgent()
    attendees = [
        {"name": "Sarah", "expertise": ["cushioning systems", "materials testing"]}
    ]
    utterances = [
        _utt("Mike", "What do we think about the cushioning performance numbers?")
    ]

    nudge = await agent.analyze(utterances, attendees, meeting_id="m1")

    assert nudge is not None
    assert nudge["nudge_type"] == "activation"
    assert "Sarah" in nudge["title"]
    assert nudge["source_data"]["person"] == "Sarah"
    assert "cushioning systems" in nudge["source_data"]["matched_expertise"]
    assert nudge["source_data"]["triggered_by"] == "Mike"


async def test_no_match_returns_none():
    agent = ActivationAgent()
    attendees = [{"name": "Sarah", "expertise": ["supply chain"]}]
    utterances = [_utt("Mike", "Let's review the marketing copy for the launch page.")]

    assert await agent.analyze(utterances, attendees, meeting_id="m1") is None


async def test_does_not_ping_speaker_about_own_remark():
    agent = ActivationAgent()
    attendees = [{"name": "Sarah", "expertise": ["cushioning systems"]}]
    utterances = [_utt("Sarah", "The cushioning tests came back this morning.")]

    assert await agent.analyze(utterances, attendees, meeting_id="m1") is None


async def test_cooldown_prevents_repeat_fires():
    agent = ActivationAgent()
    attendees = [{"name": "Sarah", "expertise": ["cushioning systems"]}]
    utterances = [_utt("Mike", "Back to cushioning again — thoughts?")]

    first = await agent.analyze(utterances, attendees, meeting_id="m1")
    second = await agent.analyze(utterances, attendees, meeting_id="m1")

    assert first is not None
    assert second is None


async def test_attendees_without_expertise_are_ignored():
    agent = ActivationAgent()
    attendees = [{"name": "Bob"}, {"email": "no-name@co.com", "expertise": ["pricing"]}]
    utterances = [_utt("Mike", "The pricing discussion is next.")]

    assert await agent.analyze(utterances, attendees, meeting_id="m1") is None
