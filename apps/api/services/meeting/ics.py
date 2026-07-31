"""
iCalendar (.ics) generation — no external deps, RFC 5545 subset.

Two products: the meeting itself as a VEVENT (for invites), and
action-item deadlines as all-day VEVENTs (attached to summary emails so
follow-ups land on people's calendars).
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional


def _escape(text: str) -> str:
    return (
        str(text)
        .replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\n", "\\n")
    )


def _fmt(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _wrap(events: List[str]) -> str:
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Donna//Meeting Intelligence//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        *events,
        "END:VCALENDAR",
    ]
    return "\r\n".join(lines) + "\r\n"


def build_meeting_event(
    meeting_id: str,
    title: str,
    scheduled_at: datetime,
    duration_minutes: int = 60,
    description: Optional[str] = None,
    url: Optional[str] = None,
) -> str:
    """One VEVENT for the meeting itself — used by invite emails."""
    stamp = scheduled_at if scheduled_at.tzinfo else scheduled_at
    event = [
        "BEGIN:VEVENT",
        f"UID:donna-meeting-{meeting_id}@donna.app",
        f"DTSTAMP:{_fmt(stamp)}",
        f"DTSTART:{_fmt(scheduled_at)}",
        f"DTEND:{_fmt(scheduled_at + timedelta(minutes=duration_minutes))}",
        f"SUMMARY:{_escape(title)}",
    ]
    if description:
        event.append(f"DESCRIPTION:{_escape(description[:900])}")
    if url:
        event.append(f"URL:{_escape(url)}")
    event.append("END:VEVENT")
    return _wrap(event)


def build_action_items_calendar(
    meeting_id: str,
    meeting_title: str,
    action_items: List[Dict[str, Any]],
) -> Optional[str]:
    """All-day VEVENTs for action-item deadlines. None if nothing has one."""
    events: List[str] = []
    now = datetime.now(timezone.utc)
    for i, item in enumerate(action_items):
        deadline = item.get("deadline")
        if isinstance(deadline, str):
            try:
                deadline = datetime.fromisoformat(deadline)
            except ValueError:
                continue
        if not isinstance(deadline, datetime):
            continue
        title = item.get("description") or item.get("item") or "Action item"
        assignee = item.get("assignee")
        summary = f"[{meeting_title}] {title}"
        if assignee:
            summary += f" — {assignee}"
        events.extend(
            [
                "BEGIN:VEVENT",
                f"UID:donna-action-{meeting_id}-{i}@donna.app",
                f"DTSTAMP:{_fmt(now)}",
                f"DTSTART;VALUE=DATE:{deadline.strftime('%Y%m%d')}",
                f"SUMMARY:{_escape(summary[:200])}",
                f"DESCRIPTION:{_escape(f'Action item from meeting: {meeting_title}')}",
                "END:VEVENT",
            ]
        )
    if not events:
        return None
    return _wrap(events)
