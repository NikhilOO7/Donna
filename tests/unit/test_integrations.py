"""Unit tests for inbound email research (H4) + Google Calendar glue (H5)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import BackgroundTasks, HTTPException

from apps.api.routers.integrations import inbound_email
from apps.api.services.integrations import google_calendar


def _session_returning_user(user):
    session = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = user
    session.execute = AsyncMock(return_value=result)
    return session


class TestInboundEmail:
    @pytest.mark.asyncio
    async def test_rejects_bad_token(self):
        with patch("apps.api.routers.integrations.settings") as mock_settings:
            mock_settings.postmark_inbound_token = "secret"
            with pytest.raises(HTTPException) as exc:
                await inbound_email(
                    {"Subject": "hi"},
                    BackgroundTasks(),
                    token="wrong",
                    session=AsyncMock(),
                )
            assert exc.value.status_code == 401

    @pytest.mark.asyncio
    async def test_503_when_not_configured(self):
        with patch("apps.api.routers.integrations.settings") as mock_settings:
            mock_settings.postmark_inbound_token = None
            with pytest.raises(HTTPException) as exc:
                await inbound_email(
                    {}, BackgroundTasks(), token="", session=AsyncMock()
                )
            assert exc.value.status_code == 503

    @pytest.mark.asyncio
    async def test_unknown_sender_is_ignored_with_200(self):
        with patch("apps.api.routers.integrations.settings") as mock_settings:
            mock_settings.postmark_inbound_token = "secret"
            result = await inbound_email(
                {
                    "FromFull": {"Email": "stranger@nowhere.dev"},
                    "Subject": "Research this",
                    "TextBody": "please",
                },
                BackgroundTasks(),
                token="secret",
                session=_session_returning_user(None),
            )
        assert result == {"status": "ignored", "reason": "unknown_sender"}

    @pytest.mark.asyncio
    async def test_registered_sender_creates_research_meeting(self):
        user = MagicMock()
        user.id = "u-1"
        user.email = "founder@team.dev"

        meeting = MagicMock()
        meeting.id = "m-1"
        meeting.title = "Research: Vendor pricing trends"
        meeting.description = "What changed in Q3?"

        with (
            patch("apps.api.routers.integrations.settings") as mock_settings,
            patch("apps.api.routers.integrations.meeting_service") as mock_ms,
            patch(
                "apps.api.routers.integrations.enqueue",
                new=AsyncMock(return_value=True),
            ) as mock_enqueue,
            patch("apps.api.routers.integrations.email_service") as mock_email,
        ):
            mock_settings.postmark_inbound_token = "secret"
            mock_settings.frontend_url = "http://localhost:3000"
            mock_ms.create_meeting = AsyncMock(return_value=meeting)
            mock_ms.update_meeting_status = AsyncMock()
            mock_email._send = MagicMock(return_value="msg-id")

            result = await inbound_email(
                {
                    "FromFull": {"Email": "Founder@Team.dev"},
                    "Subject": "Vendor pricing trends",
                    "TextBody": "What changed in Q3?",
                },
                BackgroundTasks(),
                token="secret",
                session=_session_returning_user(user),
            )

        assert result["status"] == "accepted"
        assert result["meeting_id"] == "m-1"
        mock_ms.create_meeting.assert_awaited_once()
        kwargs = mock_ms.create_meeting.await_args.kwargs
        assert kwargs["meeting_type"] == "research_request"
        assert kwargs["title"].startswith("Research:")
        mock_enqueue.assert_awaited_once()
        mock_email._send.assert_called_once()  # confirmation email


class TestGoogleState:
    def test_state_roundtrip(self):
        state = google_calendar.sign_state("user-123")
        assert google_calendar.verify_state(state) == "user-123"

    def test_tampered_state_rejected(self):
        state = google_calendar.sign_state("user-123")
        assert google_calendar.verify_state("user-456." + state.split(".")[1]) is None
        assert google_calendar.verify_state("garbage") is None

    def test_event_start_parsing(self):
        assert (
            google_calendar._parse_start(
                {"start": {"dateTime": "2026-08-01T10:00:00+00:00"}}
            )
            is not None
        )
        all_day = google_calendar._parse_start({"start": {"date": "2026-08-01"}})
        assert all_day is not None and all_day.hour == 9
        assert google_calendar._parse_start({"start": {}}) is None
