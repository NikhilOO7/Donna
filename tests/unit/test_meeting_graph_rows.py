"""
Unit tests for the meeting knowledge-graph row builder.

Verifies that a completed meeting is shaped into the Neo4j node/edge rows that model
decisions, action items, research topics, and the transcript — the graph relationships
the platform claims. Pure function, no live Neo4j required.
"""

from apps.api.services.document.knowledge_graph_service import KnowledgeGraphService


def _rows():
    return KnowledgeGraphService._build_meeting_graph_rows(
        meeting_id="m-1",
        title="Q3 Planning",
        status="completed",
        owner="owner-1",
        decisions=[
            {"decision_text": "Go with vendor B", "owner": "Alice", "status": "open"},
            {"decision": "Ship self-serve onboarding", "deadline": "2026-07-01"},
            {"owner": "Bob"},  # no text → dropped
        ],
        action_items=[
            {"description": "Draft contract", "assignee": "Alice", "priority": "high"},
            {"item": "Write onboarding docs"},  # legacy 'item' key
            {"assignee": "nobody"},  # no description → dropped
        ],
        research_topics=["competitor pricing", "  ", "voice latency"],
        utterance_count=42,
    )


class TestMeetingGraphRows:
    def test_meeting_node(self):
        rows = _rows()
        m = rows["meeting"]
        assert m["id"] == "m-1"
        assert m["title"] == "Q3 Planning"
        assert m["owner_id"] == "owner-1"
        assert m["utterance_count"] == 42

    def test_decisions_drop_empty_and_carry_fields(self):
        rows = _rows()
        decisions = rows["decisions"]
        assert len(decisions) == 2  # third had no text
        assert decisions[0]["text"] == "Go with vendor B"
        assert decisions[0]["owner"] == "Alice"
        assert decisions[1]["text"] == "Ship self-serve onboarding"
        assert decisions[1]["deadline"] == "2026-07-01"
        # IDs are stable and meeting-scoped
        assert decisions[0]["id"] == "m-1:d:0"
        assert all(d["owner_id"] == "owner-1" for d in decisions)

    def test_actions_support_legacy_item_key_and_drop_empty(self):
        rows = _rows()
        actions = rows["actions"]
        assert len(actions) == 2  # third had no description
        assert actions[0]["description"] == "Draft contract"
        assert actions[0]["priority"] == "high"
        assert actions[1]["description"] == "Write onboarding docs"
        assert actions[1]["priority"] == "medium"  # default

    def test_topics_trimmed_and_blank_dropped(self):
        rows = _rows()
        names = [t["name"] for t in rows["topics"]]
        assert names == ["competitor pricing", "voice latency"]
        assert all(t["meeting_id"] == "m-1" for t in rows["topics"])
