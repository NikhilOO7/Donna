"""
Google Calendar ingestion (H5) — the AUO "kills the cold-start" read path.

Plain-httpx OAuth + Calendar REST (no Google SDK dependency):

    auth URL → user consents → callback stores the refresh token →
    sync pulls the next 7 days of events → each becomes a Donna meeting
    (deduped by external_event_id) → the nightly research cron preps them.

Everything is gated on GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET being set.
"""

import hashlib
import hmac
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.config import settings

logger = logging.getLogger(__name__)

_AUTH_BASE = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN_URL = "https://oauth2.googleapis.com/token"
_EVENTS_URL = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
_SCOPE = "https://www.googleapis.com/auth/calendar.readonly"

_SYNC_WINDOW_DAYS = 7
_MAX_EVENTS_PER_SYNC = 25


def is_configured() -> bool:
    return bool(settings.google_client_id and settings.google_client_secret)


def sign_state(user_id: str) -> str:
    """OAuth ``state`` = user_id.hmac — binds the callback to the user."""
    mac = hmac.new(
        settings.jwt_secret.encode(), user_id.encode(), hashlib.sha256
    ).hexdigest()[:32]
    return f"{user_id}.{mac}"


def verify_state(state: str) -> Optional[str]:
    """Return the user_id if the state signature checks out."""
    if "." not in state:
        return None
    user_id, _mac = state.rsplit(".", 1)
    if hmac.compare_digest(sign_state(user_id), state):
        return user_id
    return None


def build_auth_url(user_id: str) -> str:
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": settings.google_redirect_uri,
        "response_type": "code",
        "scope": _SCOPE,
        "access_type": "offline",  # -> refresh token
        "prompt": "consent",
        "state": sign_state(user_id),
    }
    return f"{_AUTH_BASE}?{urlencode(params)}"


async def exchange_code(code: str) -> Dict[str, Any]:
    """Authorization code → {access_token, refresh_token, ...}."""
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            _TOKEN_URL,
            data={
                "code": code,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "redirect_uri": settings.google_redirect_uri,
                "grant_type": "authorization_code",
            },
        )
    resp.raise_for_status()
    return resp.json()


async def refresh_access_token(refresh_token: str) -> Optional[str]:
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            _TOKEN_URL,
            data={
                "refresh_token": refresh_token,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "grant_type": "refresh_token",
            },
        )
    if resp.status_code != 200:
        logger.warning(f"[GCal] token refresh failed: {resp.text[:200]}")
        return None
    return resp.json().get("access_token")


async def fetch_upcoming_events(access_token: str) -> List[Dict[str, Any]]:
    """Next-N-days events from the primary calendar (expanded, ordered)."""
    now = datetime.now(timezone.utc)
    params = {
        "timeMin": now.isoformat(),
        "timeMax": (now + timedelta(days=_SYNC_WINDOW_DAYS)).isoformat(),
        "singleEvents": "true",
        "orderBy": "startTime",
        "maxResults": str(_MAX_EVENTS_PER_SYNC),
    }
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.get(
            _EVENTS_URL,
            params=params,
            headers={"Authorization": f"Bearer {access_token}"},
        )
    resp.raise_for_status()
    return resp.json().get("items", [])


def _parse_start(event: Dict[str, Any]) -> Optional[datetime]:
    start = event.get("start") or {}
    if start.get("dateTime"):
        try:
            return datetime.fromisoformat(start["dateTime"])
        except ValueError:
            return None
    if start.get("date"):  # all-day
        try:
            return datetime.fromisoformat(start["date"]).replace(
                hour=9, tzinfo=timezone.utc
            )
        except ValueError:
            return None
    return None


async def sync_user_calendar(session: AsyncSession, user) -> Dict[str, Any]:
    """Import upcoming events as Donna meetings. Returns a summary dict."""
    from apps.api.models.meeting import Meeting
    from apps.api.services.meeting.meeting_service import meeting_service

    access_token = await refresh_access_token(user.google_refresh_token)
    if not access_token:
        return {"error": "Google authorization expired — reconnect your calendar"}

    events = await fetch_upcoming_events(access_token)
    created, skipped = 0, 0
    for event in events:
        event_id = event.get("id")
        title = (event.get("summary") or "").strip()
        start = _parse_start(event)
        if not event_id or not title or start is None:
            skipped += 1
            continue
        if event.get("status") == "cancelled":
            skipped += 1
            continue

        existing = (
            await session.execute(
                select(Meeting.id).where(
                    Meeting.external_event_id == event_id,
                    Meeting.owner_id == user.id,
                    Meeting.deleted_at.is_(None),
                )
            )
        ).first()
        if existing:
            skipped += 1
            continue

        attendees = [
            {"email": a.get("email", "").lower()}
            for a in (event.get("attendees") or [])
            if a.get("email") and not a.get("resource")
        ][:20]

        meeting = await meeting_service.create_meeting(
            session,
            title=title[:255],
            description=(event.get("description") or "")[:2000] or None,
            attendees=attendees,
            scheduled_at=start,
            owner_id=user.id,
            meeting_type="calendar_import",
        )
        meeting.external_event_id = event_id
        await session.commit()
        created += 1

    logger.info(f"[GCal] sync for {user.email}: {created} imported, {skipped} skipped")
    return {"created": created, "skipped": skipped, "window_days": _SYNC_WINDOW_DAYS}
