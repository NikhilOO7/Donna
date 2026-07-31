"""Unit tests for the meeting PrepAgent (the structured prep contract)."""

import json
from unittest.mock import AsyncMock, MagicMock

from apps.api.services.meeting.prep_agent import PrepAgent


def _mock_completion(payload: dict) -> MagicMock:
    completion = MagicMock()
    completion.choices = [MagicMock()]
    completion.choices[0].message.content = json.dumps(payload)
    return completion


def _make_agent(payload: dict) -> PrepAgent:
    agent = PrepAgent()
    agent.client = MagicMock()
    agent.client.chat.completions.create = AsyncMock(
        return_value=_mock_completion(payload)
    )
    return agent


async def test_generate_returns_full_contract():
    agent = _make_agent(
        {
            "role": "Product Designer",
            "meeting_type": "Engineering Sync",
            "meeting_goal": "Ensure component ships on time",
            "agenda_items": ["Review handoff", "Discuss blockers"],
            "risks_or_tensions": ["Timeline slip"],
            "confidence_notes": "Inferred from keywords",
        }
    )

    result = await agent.generate("prepping a session with the engineers")

    assert result["role"] == "Product Designer"
    assert result["meeting_type"] == "Engineering Sync"
    assert result["meeting_goal"] == "Ensure component ships on time"
    assert result["agenda_items"] == ["Review handoff", "Discuss blockers"]
    assert result["risks_or_tensions"] == ["Timeline slip"]
    assert result["confidence_notes"] == "Inferred from keywords"


async def test_generate_normalizes_missing_and_bad_fields():
    agent = _make_agent(
        {
            "role": None,
            "meeting_goal": "  Lock pricing  ",
            "agenda_items": "not-a-list",
            "risks_or_tensions": ["", "  Real risk  ", 42],
        }
    )

    result = await agent.generate("pricing sync")

    assert result["role"] == ""
    assert result["meeting_type"] == ""
    assert result["meeting_goal"] == "Lock pricing"
    assert result["agenda_items"] == []
    assert result["risks_or_tensions"] == ["Real risk", "42"]
    assert result["confidence_notes"] == ""


async def test_generate_passes_current_prep_for_refinement():
    agent = _make_agent(
        {
            "role": "PM",
            "meeting_type": "Strategy Planning",
            "meeting_goal": "Updated goal",
            "agenda_items": ["A"],
            "risks_or_tensions": [],
            "confidence_notes": "Refined",
        }
    )
    current = {"meeting_goal": "Old goal", "agenda_items": ["Old item"]}

    await agent.generate("also invite finance", current=current)

    call = agent.client.chat.completions.create.call_args
    user_msg = call.kwargs["messages"][1]["content"]
    assert "Old goal" in user_msg
    assert "also invite finance" in user_msg
