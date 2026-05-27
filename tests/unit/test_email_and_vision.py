"""
Tests for the gap-fill work:
  * Email summary renders from the Jinja2 template (Gap 5)
  * Image agent gates the GPT-4o Vision call on config (Gap 2)
"""

import os

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("REDIS_HOST", "localhost")
os.environ.setdefault("QDRANT_HOST", "localhost")

import pytest

from apps.api.services.document.image_agent import ImageAgent
from apps.api.services.meeting.email_service import email_service


class TestEmailTemplate:
    def test_renders_full_summary(self):
        html = email_service._render_html(
            "Q2 Vendor Review",
            {
                "executive_summary": "We selected Beacon Cloud.",
                "decisions_summary": [
                    {"decision": "Go with Beacon", "owner": "Alice", "deadline": "Q2"}
                ],
                "action_items": [
                    {
                        "item": "Draft contract",
                        "assignee": "Charlie",
                        "priority": "high",
                    }
                ],
                "ai_insights_used": [{"insight": "Compliance edge", "impact": "high"}],
                "follow_up_recommendations": ["Schedule kickoff"],
            },
        )
        assert "Q2 Vendor Review" in html
        assert "Beacon Cloud" in html
        assert "Draft contract" in html
        assert "Compliance edge" in html
        assert "Schedule kickoff" in html
        assert html.strip().startswith("<!DOCTYPE html>")

    def test_renders_minimal_summary(self):
        # Empty optional sections must not break rendering
        html = email_service._render_html(
            "Empty Meeting", {"executive_summary": "Nothing decided."}
        )
        assert "Empty Meeting" in html
        assert "Nothing decided." in html
        # No decisions table when there are no decisions
        assert "Decisions</h2>" not in html

    def test_autoescape_prevents_injection(self):
        html = email_service._render_html(
            "Test", {"executive_summary": "<script>alert(1)</script>"}
        )
        # Jinja2 autoescape should neutralize the raw tag
        assert "<script>alert(1)</script>" not in html
        assert "&lt;script&gt;" in html


class TestImageAgentVisionGating:
    @pytest.mark.asyncio
    async def test_no_images_returns_empty(self):
        agent = ImageAgent()
        assert await agent.process_images([]) == []

    @pytest.mark.asyncio
    async def test_vision_skipped_without_openai_key(self, monkeypatch):
        # No OpenAI key → _get_client returns None → vision returns ""
        monkeypatch.setattr(
            "apps.api.services.document.image_agent.settings",
            type("S", (), {"openai_api_key": None})(),
        )
        agent = ImageAgent()
        result = await agent._describe_with_vision(b"\x89PNG fake", "some ocr", 1)
        assert result == ""
