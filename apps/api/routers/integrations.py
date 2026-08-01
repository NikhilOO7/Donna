"""
External integrations: inbound email research (H4) + Google Calendar (H5).

Inbound email — the PDF's ``research@donna.app`` flow:
    Postmark inbound webhook → verify sender is a registered user →
    create a research-request meeting from the subject/body → enqueue the
    research pipeline → confirmation email with the meeting link.

Google Calendar — the cold-start killer:
    OAuth consent → refresh token stored on the user → sync imports the
    next 7 days of events as Donna meetings (deduped), which the nightly
    research cron then preps automatically.
"""

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.auth import require_user
from apps.api.core.config import settings
from apps.api.core.database import get_db
from apps.api.core.jobs import enqueue
from apps.api.models.user import User
from apps.api.services.integrations import google_calendar
from apps.api.services.meeting.email_service import email_service
from apps.api.services.meeting.meeting_service import meeting_service
from apps.api.services.research.pipeline import research_pipeline

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/integrations", tags=["integrations"])


# -- H4: inbound email research ---------------------------------------------


@router.post("/email/inbound")
async def inbound_email(
    payload: dict,
    background_tasks: BackgroundTasks,
    token: str = Query(default=""),
    session: AsyncSession = Depends(get_db),
):
    """Postmark inbound webhook — email a question, get a research brief.

    Configure Postmark's inbound stream to POST here with
    ``?token=$POSTMARK_INBOUND_TOKEN``. Always answers 200 to Postmark
    (a 4xx/5xx would make it retry spam forever); rejected mail is
    acknowledged and dropped.
    """
    if not settings.postmark_inbound_token:
        raise HTTPException(503, "Inbound email not configured")
    if token != settings.postmark_inbound_token:
        raise HTTPException(401, "Bad inbound token")

    sender = (
        ((payload.get("FromFull") or {}).get("Email") or payload.get("From") or "")
        .strip()
        .lower()
    )
    subject = (payload.get("Subject") or "").strip()
    body = (payload.get("StrippedTextReply") or payload.get("TextBody") or "").strip()

    if not sender or not (subject or body):
        return {"status": "ignored", "reason": "empty"}

    # Only registered users may commission research by email
    user = (
        await session.execute(select(User).where(User.email == sender))
    ).scalar_one_or_none()
    if user is None:
        logger.info(f"[Inbound] dropped mail from unregistered sender {sender}")
        return {"status": "ignored", "reason": "unknown_sender"}

    title = subject[:255] or (body[:80] + "…")
    urgent = any(w in subject.lower() for w in ("urgent", "asap", "today"))

    meeting = await meeting_service.create_meeting(
        session,
        title=f"Research: {title}"
        if not title.lower().startswith("research")
        else title,
        description=body[:2000] or subject,
        owner_id=user.id,
        meeting_type="research_request",
    )
    await meeting_service.update_meeting_status(session, meeting.id, "researching")

    if not await enqueue(
        "research_job", str(meeting.id), meeting.title, meeting.description or ""
    ):
        background_tasks.add_task(
            research_pipeline.run,
            meeting_id=str(meeting.id),
            title=meeting.title,
            description=meeting.description or "",
        )

    meeting_url = f"{settings.frontend_url}/meetings/{meeting.id}"
    email_service._send(
        [sender],
        f"On it — researching: {title}"[:120],
        (
            f"<html><body style='font-family:sans-serif'>"
            f"<p>Donna here. I've started researching:</p>"
            f"<blockquote>{title}</blockquote>"
            f"<p>{'Marked urgent — running now. ' if urgent else ''}"
            f"Your brief will be ready shortly at "
            f"<a href='{meeting_url}'>your Donna workspace</a>.</p>"
            f"</body></html>"
        ),
    )
    logger.info(f"[Inbound] research request from {sender} → meeting {meeting.id}")
    return {"status": "accepted", "meeting_id": str(meeting.id)}


# -- H5: Google Calendar -----------------------------------------------------


@router.get("/google/status")
async def google_status(current_user=Depends(require_user)):
    """Is Google Calendar configured server-side and connected by this user?"""
    return {
        "configured": google_calendar.is_configured(),
        "connected": bool(
            current_user and getattr(current_user, "google_refresh_token", None)
        ),
    }


@router.get("/google/auth-url")
async def google_auth_url(current_user=Depends(require_user)):
    """The consent URL to send the browser to."""
    if not google_calendar.is_configured():
        raise HTTPException(503, "Google Calendar integration not configured")
    if current_user is None:
        raise HTTPException(401, "Sign in first")
    return {"url": google_calendar.build_auth_url(str(current_user.id))}


@router.get("/google/callback")
async def google_callback(
    code: str = Query(default=""),
    state: str = Query(default=""),
    error: str = Query(default=""),
    session: AsyncSession = Depends(get_db),
):
    """OAuth redirect target — stores the refresh token, bounces to the app."""
    dest = f"{settings.frontend_url}/dashboard"
    if error or not code:
        return RedirectResponse(f"{dest}?google=denied")
    if not google_calendar.is_configured():
        raise HTTPException(503, "Google Calendar integration not configured")

    user_id = google_calendar.verify_state(state)
    if user_id is None:
        raise HTTPException(400, "Bad state")

    try:
        tokens = await google_calendar.exchange_code(code)
    except Exception as e:
        logger.warning(f"[GCal] code exchange failed: {e}")
        return RedirectResponse(f"{dest}?google=error")

    refresh = tokens.get("refresh_token")
    if not refresh:
        return RedirectResponse(f"{dest}?google=no_refresh_token")

    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(404, "User not found")
    user.google_refresh_token = refresh
    await session.commit()
    return RedirectResponse(f"{dest}?google=connected")


@router.post("/google/sync")
async def google_sync(
    session: AsyncSession = Depends(get_db),
    current_user=Depends(require_user),
):
    """Import upcoming calendar events as Donna meetings."""
    if not google_calendar.is_configured():
        raise HTTPException(503, "Google Calendar integration not configured")
    if current_user is None or not getattr(current_user, "google_refresh_token", None):
        raise HTTPException(400, "Google Calendar not connected — authorize first")

    result = await google_calendar.sync_user_calendar(session, current_user)
    if "error" in result:
        raise HTTPException(400, result["error"])
    return result
