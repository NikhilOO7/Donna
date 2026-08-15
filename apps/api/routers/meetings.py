"""
REST endpoints for the Donna meeting lifecycle.
"""

from typing import Optional
from uuid import UUID

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Query,
    Request,
    Response,
    WebSocket,
    WebSocketDisconnect,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.auth import get_service_or_user, require_user
from apps.api.core.config import settings
from apps.api.core.database import get_db
from apps.api.core.jobs import enqueue
from apps.api.models.meeting import (
    ActionItemCreate,
    DecisionCreate,
    Meeting,
    MeetingCreate,
    Nudge,
)
from apps.api.services.analytics_service import track_event
from apps.api.services.meeting.agent_dispatcher import agent_dispatcher
from apps.api.services.meeting.email_service import email_service
from apps.api.services.meeting.ics import (
    build_action_items_calendar,
    build_meeting_event,
)
from apps.api.services.meeting.meeting_service import meeting_service
from apps.api.services.meeting.realtime import meeting_hub
from apps.api.services.meeting.summary_pipeline import summary_pipeline
from apps.api.services.research.pipeline import research_pipeline

router = APIRouter(prefix="/api/v1/meetings", tags=["meetings"])


def _check_owner_id(owner_id, current_user) -> None:
    """Core row-level-isolation rule given a raw owner_id.

    No-op when the meeting has no owner (legacy/demo data) or when no user
    is present (auth disabled). When a user IS present and the meeting is
    owned by someone else, 404 (not 403 — don't reveal existence).
    """
    if current_user is None:
        return
    if owner_id is not None and str(owner_id) != str(current_user.id):
        raise HTTPException(404, "Meeting not found")


def _check_owner(meeting, current_user) -> None:
    """Ownership check against a loaded Meeting object."""
    _check_owner_id(getattr(meeting, "owner_id", None), current_user)


async def require_owned_meeting(
    meeting_id: str,
    session: AsyncSession = Depends(get_db),
    current_user=Depends(require_user),
) -> UUID:
    """Dependency: validate the meeting id, enforce ownership, return the UUID.

    Cheap (owner_id-only lookup) so it's safe on the hot path. Use on
    sub-endpoints that mutate a meeting (leader-only actions).
    """
    try:
        mid = UUID(meeting_id)
    except ValueError:
        raise HTTPException(400, "Invalid meeting ID format")
    exists, owner_id = await meeting_service.get_owner_id(session, mid)
    if not exists:
        raise HTTPException(404, "Meeting not found")
    _check_owner_id(owner_id, current_user)
    return mid


# -- Multiplayer access (leader = owner, participant = invited attendee) ----


def _attendee_entry_for(attendees: list, current_user) -> Optional[dict]:
    """The attendee entry matching the user's email, if any."""
    if current_user is None:
        return None
    email = (getattr(current_user, "email", "") or "").lower()
    if not email:
        return None
    for a in attendees or []:
        if isinstance(a, dict) and (a.get("email") or "").lower() == email:
            return a
    return None


# Labels that mean "whoever is looking at this", which is exactly what a
# shared transcript must never store.
_VIEWER_RELATIVE_SPEAKERS = {"you", "me", "myself", "self", "speaker"}


def _display_name_for(attendees: list, current_user) -> Optional[str]:
    """The name this user should be attributed by in a shared transcript.

    Falls back past the attendee list to the account itself, because the
    meeting *owner* is usually not in their own attendee list — which left
    ``my_name`` null for the one person guaranteed to be in the meeting. The
    client's fallback for a null name was the literal string "You", and that
    got persisted as the speaker.

    Storing "You" is not merely untidy: it is viewer-relative data written into
    a shared record. Every other attendee reading that transcript, and every
    recipient of the summary email, sees "You" referring to someone who is not
    them. Attribution in a shared artifact has to be absolute.
    """
    entry = _attendee_entry_for(attendees, current_user)
    if entry and (entry.get("name") or "").strip():
        return entry["name"].strip()
    if current_user is None:
        return None
    full_name = (getattr(current_user, "full_name", "") or "").strip()
    if full_name:
        return full_name
    email = (getattr(current_user, "email", "") or "").strip()
    if email:
        # Better a recognisable handle than a pronoun.
        return email.split("@")[0]
    return None


def _role_of(owner_id, attendees: list, current_user) -> Optional[str]:
    """'leader' | 'participant' | None (no access).

    With auth off (no user) or a legacy unowned meeting, callers get full
    access so existing single-player/demo flows keep working.
    """
    if current_user is None or owner_id is None:
        return "leader"
    if str(owner_id) == str(current_user.id):
        return "leader"
    if _attendee_entry_for(attendees, current_user) is not None:
        return "participant"
    return None


class MeetingAccess:
    """Resolved access for a meeting request."""

    def __init__(
        self,
        mid: UUID,
        role: str,
        my_name: Optional[str],
        my_email: Optional[str] = None,
    ):
        self.mid = mid
        self.role = role
        self.my_name = my_name
        self.my_email = my_email


async def require_meeting_access(
    meeting_id: str,
    session: AsyncSession = Depends(get_db),
    current_user=Depends(require_user),
) -> MeetingAccess:
    """Dependency: allow the meeting's leader OR an invited participant."""
    try:
        mid = UUID(meeting_id)
    except ValueError:
        raise HTTPException(400, "Invalid meeting ID format")
    exists, owner_id, attendees = await meeting_service.get_access_row(session, mid)
    if not exists:
        raise HTTPException(404, "Meeting not found")
    role = _role_of(owner_id, attendees, current_user)
    if role is None:
        raise HTTPException(404, "Meeting not found")
    entry = _attendee_entry_for(attendees, current_user)
    return MeetingAccess(
        mid,
        role,
        (entry or {}).get("name"),
        getattr(current_user, "email", None),
    )


def _visible_nudges(
    nudges: list,
    role: str,
    my_name: Optional[str],
    my_email: Optional[str] = None,
) -> list:
    """Server-side nudge visibility (REST twin of MeetingHub._visible_to).

    Leaders see everything. Participants see the shared board — nudges the
    leader pinned — plus activation nudges addressed to them personally.

    Addressing is by **email**; display names are not identities. Name
    matching remains only as a fallback for nudges persisted before
    ``person_email`` was recorded.
    """
    if role == "leader":
        return list(nudges or [])
    out = []
    for n in nudges or []:
        if n.dismissed_at is not None:
            continue
        if n.pinned_at is not None:
            out.append(n)
        elif n.nudge_type == "activation":
            source = n.source_data or {}
            person_email = (source.get("person_email") or "").lower()
            if person_email:
                if my_email and person_email == my_email.lower():
                    out.append(n)
            elif my_name:
                # Legacy nudge with no email recorded.
                person = (source.get("person") or "").lower()
                if person == my_name.lower():
                    out.append(n)
    return out


async def _voice_nudges_enabled(meeting_id: str) -> bool:
    try:
        from apps.api.core.connections import get_redis_client

        redis = await get_redis_client()
        return (await redis.get(f"voice_nudges:{meeting_id}")) == "1"
    except Exception:
        return False


@router.post("/prep")
async def prep_meeting(
    body: dict,
    current_user=Depends(require_user),
):
    """Structured meeting prep from free-form input (Smart Fill / conversational setup).

    Body: ``{"input": str, "current": {prep JSON from a previous call}?}``
    Returns the Donna prep contract:
    ``{role, meeting_type, meeting_goal, agenda_items, risks_or_tensions, confidence_notes}``
    """
    from apps.api.services.meeting.prep_agent import prep_agent

    user_input = (body.get("input") or "").strip()
    if not user_input:
        raise HTTPException(400, "Field 'input' is required")
    if len(user_input) > 4000:
        raise HTTPException(400, "Input too long (max 4000 chars)")

    current = body.get("current")
    if current is not None and not isinstance(current, dict):
        raise HTTPException(400, "Field 'current' must be an object")

    try:
        return await prep_agent.generate(user_input, current=current)
    except Exception as e:
        raise HTTPException(502, f"Prep generation failed: {e}")


@router.post("/import-transcript")
async def import_transcript(
    body: dict,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_db),
    current_user=Depends(require_user),
):
    """Analyze an existing meeting transcript (Upload Transcript setup mode).

    Body: ``{"transcript_text": str, "title": str?, "meeting_type": str?}``

    Parses the transcript into speaker-attributed utterances, creates a
    completed meeting owned by the caller, and generates the summary
    (decisions, action items, insights) in the background.
    """
    text = (body.get("transcript_text") or "").strip()
    if len(text) < 50:
        raise HTTPException(400, "Transcript is too short — paste at least a few lines")
    if len(text) > 500_000:
        raise HTTPException(400, "Transcript too large (max 500KB)")

    utterances = meeting_service.parse_transcript_text(text)
    if not utterances:
        raise HTTPException(400, "Could not parse any utterances from the transcript")

    title = (body.get("title") or "").strip()[:300] or "Imported meeting"
    meeting_type = (body.get("meeting_type") or "").strip()[:120] or None

    meeting = await meeting_service.create_meeting(
        session,
        title=title,
        description="Imported from transcript",
        owner_id=current_user.id if current_user else None,
        meeting_type=meeting_type,
    )
    mid = meeting.id

    await meeting_service.set_transcript(session, mid, utterances)
    # Imported meetings arrive already finished
    await meeting_service.update_meeting_status(session, mid, "in_progress")
    await meeting_service.update_meeting_status(session, mid, "completed")

    # Auto-generate the summary from the imported transcript
    transcript_text = "\n".join(f"{u['speaker']}: {u['text']}" for u in utterances)
    if not await enqueue(
        "summary_job",
        str(mid),
        title,
        "Imported from transcript",
        transcript_text,
        [],
        [],
        [],
        "",
    ):
        background_tasks.add_task(
            summary_pipeline.run,
            meeting_id=str(mid),
            meeting_title=title,
            description="Imported from transcript",
            transcript_text=transcript_text,
            decisions=[],
            action_items=[],
            nudges=[],
            research_summary="",
            owner_id=str(current_user.id) if current_user else None,
        )

    return {
        "id": str(mid),
        "title": title,
        "utterance_count": len(utterances),
        "status": "completed",
        "summary": "generating",
    }


@router.post("/", response_model=dict)
async def create_meeting(
    body: MeetingCreate,
    session: AsyncSession = Depends(get_db),
    current_user=Depends(require_user),
):
    """Create a new meeting (owned by the authenticated user, if any)."""
    meeting = await meeting_service.create_meeting(
        session,
        title=body.title,
        description=body.description,
        attendees=body.attendees,
        scheduled_at=body.scheduled_at,
        owner_id=current_user.id if current_user else None,
        meeting_type=body.meeting_type,
        agenda=body.agenda,
    )
    # Capture before track_event — its commit expires the ORM object
    response = {
        "id": str(meeting.id),
        "title": meeting.title,
        "status": meeting.status,
        "created_at": meeting.created_at.isoformat(),
    }
    await track_event(
        session,
        event_type="meeting_created",
        session_id=response["id"],
        event_data={
            "owner_id": str(current_user.id) if current_user else None,
            "meeting_type": body.meeting_type,
        },
    )
    return response


@router.get("/")
async def list_meetings(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    status: Optional[str] = None,
    session: AsyncSession = Depends(get_db),
    current_user=Depends(require_user),
):
    """List the user's meetings — owned plus those they're invited to."""
    owner_id = current_user.id if current_user else None
    member_email = getattr(current_user, "email", None) if current_user else None
    meetings = await meeting_service.list_meetings(
        session, skip, limit, status, owner_id=owner_id, member_email=member_email
    )
    return {
        "meetings": [
            {
                "id": str(m.id),
                "title": m.title,
                "status": m.status,
                "my_role": _role_of(
                    getattr(m, "owner_id", None), m.attendees or [], current_user
                ),
                "meeting_type": m.meeting_type,
                "scheduled_at": m.scheduled_at.isoformat() if m.scheduled_at else None,
                "started_at": m.started_at.isoformat() if m.started_at else None,
                "ended_at": m.ended_at.isoformat() if m.ended_at else None,
                "attendees": m.attendees,
                "created_at": m.created_at.isoformat(),
            }
            for m in meetings
        ],
        "total": len(meetings),
        "skip": skip,
        "limit": limit,
    }


@router.get("/open-items")
async def list_open_items(
    limit: int = Query(50, ge=1, le=100),
    session: AsyncSession = Depends(get_db),
    current_user=Depends(require_user),
):
    """Cross-meeting open action items — the dashboard "what's still owed" view."""
    items = await meeting_service.list_open_action_items(
        session, current_user.id if current_user else None, limit=limit
    )
    return {"items": items, "total": len(items)}


@router.get("/nudge-acceptance")
async def nudge_acceptance(
    days: int = 30,
    session: AsyncSession = Depends(get_db),
    current_user=Depends(require_user),
):
    """Per-agent nudge acceptance — which agents are actually worth running.

    The data to answer this has always existed (``pinned_at`` / ``dismissed_at``
    are timestamps, not booleans) but nothing queried it, so the product's
    central question went unanswered while two agents and an entire datastore
    were justified by an untested hypothesis.

    Definitions, stated because "acceptance rate" is ambiguous:
      * **pinned**    — the leader promoted it to the shared board. Strong positive.
      * **dismissed** — explicitly rejected. Strong negative.
      * **ignored**   — neither. Weak signal: possibly unread, not necessarily bad.
      * ``acceptance_rate = pinned / (pinned + dismissed)`` — deliberately
        excludes ignored, so it measures "when someone acted, did they keep it?"
      * ``engagement_rate = (pinned + dismissed) / total`` — how often a nudge
        provoked any action at all. A high acceptance rate on a tiny engagement
        rate is not a win; it is a rounding error.
    """
    from datetime import datetime, timedelta, timezone

    since = datetime.now(timezone.utc) - timedelta(days=max(1, days))

    rows = (
        await session.execute(
            select(
                Nudge.nudge_type,
                Nudge.source_agent,
                func.count().label("total"),
                func.count(Nudge.pinned_at).label("pinned"),
                func.count(Nudge.dismissed_at).label("dismissed"),
                func.avg(Nudge.relevance_score).label("avg_relevance"),
            )
            .join(Meeting, Meeting.id == Nudge.meeting_id)
            .where(
                Nudge.created_at >= since,
                Meeting.deleted_at.is_(None),
                # Owner-scoped: this is per-user behaviour, not global truth.
                Meeting.owner_id == current_user.id
                if current_user is not None
                else Meeting.owner_id.is_(None),
            )
            .group_by(Nudge.nudge_type, Nudge.source_agent)
            .order_by(func.count().desc())
        )
    ).all()

    agents = []
    for r in rows:
        acted = (r.pinned or 0) + (r.dismissed or 0)
        total = r.total or 0
        agents.append(
            {
                "nudge_type": r.nudge_type,
                "source_agent": r.source_agent,
                "total": total,
                "pinned": r.pinned or 0,
                "dismissed": r.dismissed or 0,
                "ignored": total - acted,
                "acceptance_rate": round((r.pinned or 0) / acted, 3) if acted else None,
                "engagement_rate": round(acted / total, 3) if total else None,
                "avg_relevance": round(float(r.avg_relevance), 3)
                if r.avg_relevance is not None
                else None,
                # Enough signal to act on? Below this, the rate is noise.
                "sufficient_data": acted >= 20,
            }
        )

    totals_acted = sum(a["pinned"] + a["dismissed"] for a in agents)
    return {
        "window_days": days,
        "since": since.isoformat(),
        "total_nudges": sum(a["total"] for a in agents),
        "overall_acceptance_rate": (
            round(sum(a["pinned"] for a in agents) / totals_acted, 3)
            if totals_acted
            else None
        ),
        "agents": agents,
        "note": (
            "acceptance_rate excludes ignored nudges; sufficient_data marks rows "
            "with >=20 explicit actions. Rows below that threshold should not "
            "drive keep/kill decisions."
        ),
    }


@router.get("/{meeting_id}")
async def get_meeting(
    meeting_id: str,
    session: AsyncSession = Depends(get_db),
    current_user=Depends(require_user),
):
    """Get a meeting with all related data (owner-scoped)."""
    try:
        mid = UUID(meeting_id)
    except ValueError:
        raise HTTPException(400, "Invalid meeting ID format")

    meeting = await meeting_service.get_meeting(session, mid)
    if not meeting:
        raise HTTPException(404, "Meeting not found")
    role = _role_of(
        getattr(meeting, "owner_id", None), meeting.attendees or [], current_user
    )
    if role is None:
        raise HTTPException(404, "Meeting not found")
    my_name = _display_name_for(meeting.attendees or [], current_user)
    nudges = _visible_nudges(
        meeting.nudges or [],
        role,
        my_name,
        getattr(current_user, "email", None),
    )

    return {
        "id": str(meeting.id),
        "title": meeting.title,
        "description": meeting.description,
        "status": meeting.status,
        "my_role": role,
        "my_name": my_name,
        "meeting_type": meeting.meeting_type,
        "agenda": meeting.agenda or [],
        "canvas_positions": meeting.canvas_positions or {},
        "voice_nudges_enabled": await _voice_nudges_enabled(str(meeting.id)),
        "scheduled_at": meeting.scheduled_at.isoformat()
        if meeting.scheduled_at
        else None,
        "started_at": meeting.started_at.isoformat() if meeting.started_at else None,
        "ended_at": meeting.ended_at.isoformat() if meeting.ended_at else None,
        "attendees": meeting.attendees,
        "created_at": meeting.created_at.isoformat(),
        "research": {
            "status": meeting.research_brief.status,
            "source_count": meeting.research_brief.source_count,
            "executive_summary": meeting.research_brief.executive_summary,
            "topics": meeting.research_brief.topics,
        }
        if meeting.research_brief
        else None,
        "transcript": {
            "utterance_count": len(meeting.transcript.utterances or []),
            "utterances": meeting.transcript.utterances or [],
        }
        if meeting.transcript
        else None,
        "nudges": [
            {
                "id": str(n.id),
                "type": n.nudge_type,
                "title": n.title,
                "content": n.content,
                "source_agent": n.source_agent,
                "source_data": n.source_data or {},
                "relevance_score": n.relevance_score,
                "dismissed_at": n.dismissed_at.isoformat() if n.dismissed_at else None,
                "pinned_at": n.pinned_at.isoformat() if n.pinned_at else None,
                "created_at": n.created_at.isoformat(),
            }
            for n in nudges
        ],
        "decisions": [
            {
                "id": str(d.id),
                "decision_text": d.decision_text,
                "owner": d.owner,
                "deadline": d.deadline.isoformat() if d.deadline else None,
                "status": d.status,
                "context": d.context,
                "source_nudge_id": str(d.source_nudge_id)
                if d.source_nudge_id
                else None,
                "action_items": [
                    {
                        "id": str(a.id),
                        "description": a.description,
                        "assignee": a.assignee,
                        "priority": a.priority,
                        "status": a.status,
                    }
                    for a in (d.action_items or [])
                ],
            }
            for d in (meeting.decisions or [])
        ],
        "action_items": [
            {
                "id": str(a.id),
                "description": a.description,
                "assignee": a.assignee,
                "priority": a.priority,
                "status": a.status,
                "decision_id": str(a.decision_id) if a.decision_id else None,
            }
            for a in (meeting.action_items or [])
        ],
        "summary": {
            "summary_text": meeting.summary.summary_text,
            "key_insights": meeting.summary.key_insights,
            "email_sent_at": meeting.summary.email_sent_at.isoformat()
            if meeting.summary.email_sent_at
            else None,
        }
        if meeting.summary
        else None,
    }


@router.patch("/{meeting_id}")
async def update_meeting(
    meeting_id: str,
    body: dict,
    session: AsyncSession = Depends(get_db),
    mid: UUID = Depends(require_owned_meeting),
):
    """Update meeting attendees (voice-setup participant registration).

    Body: ``{"attendees": [{"name": str?, "email": str?, "voice_registered": bool?}]}``
    """
    attendees = body.get("attendees")
    if not isinstance(attendees, list):
        raise HTTPException(400, "Field 'attendees' (list) is required")
    if len(attendees) > 50:
        raise HTTPException(400, "Too many attendees (max 50)")

    cleaned = []
    for a in attendees:
        if not isinstance(a, dict):
            continue
        name = str(a.get("name") or "").strip()[:120]
        email = str(a.get("email") or "").strip().lower()[:320]
        if not name and not email:
            continue
        entry: dict = {}
        if name:
            entry["name"] = name
        if email:
            entry["email"] = email
        if a.get("voice_registered"):
            entry["voice_registered"] = True
        expertise = a.get("expertise")
        if isinstance(expertise, list):
            areas = [str(x).strip()[:60] for x in expertise if str(x).strip()][:8]
            if areas:
                entry["expertise"] = areas
        cleaned.append(entry)

    if not await meeting_service.update_attendees(session, mid, cleaned):
        raise HTTPException(500, "Failed to update attendees")
    return {"id": str(mid), "attendees": cleaned}


# -- Meeting-scoped documents (D4) ------------------------------------------


@router.get("/{meeting_id}/documents")
async def list_meeting_documents(
    meeting_id: str,
    session: AsyncSession = Depends(get_db),
    access: MeetingAccess = Depends(require_meeting_access),
):
    """Documents attached to this meeting (leader or participant)."""
    from apps.api.models.document import Document
    from apps.api.models.meeting import MeetingDocument

    rows = await session.execute(
        select(Document)
        .join(MeetingDocument, MeetingDocument.document_id == Document.id)
        .where(
            MeetingDocument.meeting_id == access.mid,
            Document.deleted_at.is_(None),
        )
    )
    return {
        "documents": [
            {
                "id": str(d.id),
                "filename": d.filename,
                "processing_status": d.processing_status,
            }
            for d in rows.scalars().all()
        ]
    }


@router.post("/{meeting_id}/documents/{document_id}")
async def attach_meeting_document(
    meeting_id: str,
    document_id: str,
    session: AsyncSession = Depends(get_db),
    mid: UUID = Depends(require_owned_meeting),
    current_user=Depends(require_user),
):
    """Attach one of your documents to this meeting (leader-only)."""
    from apps.api.models.document import Document
    from apps.api.models.meeting import MeetingDocument

    try:
        did = UUID(document_id)
    except ValueError:
        raise HTTPException(400, "Invalid document ID format")

    doc = (
        await session.execute(
            select(Document).where(Document.id == did, Document.deleted_at.is_(None))
        )
    ).scalar_one_or_none()
    if doc is None:
        raise HTTPException(404, "Document not found")
    if (
        current_user is not None
        and doc.owner_id is not None
        and str(doc.owner_id) != str(current_user.id)
    ):
        raise HTTPException(404, "Document not found")

    existing = await session.get(MeetingDocument, (mid, did))
    if existing is None:
        session.add(MeetingDocument(meeting_id=mid, document_id=did))
        await session.commit()
    return {"meeting_id": str(mid), "document_id": str(did), "attached": True}


@router.delete("/{meeting_id}/documents/{document_id}")
async def detach_meeting_document(
    meeting_id: str,
    document_id: str,
    session: AsyncSession = Depends(get_db),
    mid: UUID = Depends(require_owned_meeting),
):
    """Detach a document from this meeting (leader-only)."""
    from apps.api.models.meeting import MeetingDocument

    try:
        did = UUID(document_id)
    except ValueError:
        raise HTTPException(400, "Invalid document ID format")

    row = await session.get(MeetingDocument, (mid, did))
    if row is not None:
        await session.delete(row)
        await session.commit()
    return {"meeting_id": str(mid), "document_id": str(did), "attached": False}


# -- Shared canvas (synced spatial layout) ----------------------------------


@router.patch("/{meeting_id}/canvas")
async def update_canvas(
    meeting_id: str,
    body: dict,
    session: AsyncSession = Depends(get_db),
    mid: UUID = Depends(require_owned_meeting),
):
    """Persist the shared canvas layout (leader-only).

    Body: ``{"positions": {nudge_id: {"x": float, "y": float}}}``
    """
    from sqlalchemy import update as sa_update

    from apps.api.models.meeting import Meeting

    positions = body.get("positions")
    if not isinstance(positions, dict) or len(positions) > 500:
        raise HTTPException(400, "Field 'positions' (object, max 500) is required")

    cleaned = {}
    for k, v in positions.items():
        if isinstance(v, dict) and "x" in v and "y" in v:
            try:
                cleaned[str(k)[:64]] = {
                    "x": round(float(v["x"]), 1),
                    "y": round(float(v["y"]), 1),
                }
            except (TypeError, ValueError):
                continue

    await session.execute(
        sa_update(Meeting).where(Meeting.id == mid).values(canvas_positions=cleaned)
    )
    await session.commit()
    await meeting_hub.broadcast(
        meeting_id, {"type": "canvas_updated", "positions": cleaned}
    )
    return {"positions": cleaned}


@router.post("/{meeting_id}/voice-nudges")
async def toggle_voice_nudges(
    meeting_id: str,
    body: dict,
    mid: UUID = Depends(require_owned_meeting),
):
    """Enable/disable spoken nudges for this meeting (leader-only).

    Body: ``{"enabled": bool}``. High-relevance fact-checks and decision
    prompts are spoken aloud by the voice worker when enabled.
    """
    from apps.api.core.connections import get_redis_client

    enabled = bool(body.get("enabled"))
    try:
        redis = await get_redis_client()
        key = f"voice_nudges:{mid}"
        if enabled:
            await redis.set(key, "1", ex=60 * 60 * 24)
        else:
            await redis.delete(key)
    except Exception:
        raise HTTPException(503, "Voice nudge toggle unavailable (Redis down)")
    return {"enabled": enabled}


@router.get("/{meeting_id}/cost")
async def get_meeting_cost(
    meeting_id: str,
    mid: UUID = Depends(require_owned_meeting),
):
    """Per-meeting LLM usage + estimated cost (leader-only)."""
    from apps.api.core.llm_meter import get_cost

    return await get_cost(str(mid))


@router.delete("/{meeting_id}")
async def delete_meeting(
    meeting_id: str,
    session: AsyncSession = Depends(get_db),
    current_user=Depends(require_user),
):
    """Soft-delete a meeting (owner-scoped)."""
    try:
        mid = UUID(meeting_id)
    except ValueError:
        raise HTTPException(400, "Invalid meeting ID format")

    meeting = await meeting_service.get_meeting(session, mid)
    if not meeting:
        raise HTTPException(404, "Meeting not found")
    _check_owner(meeting, current_user)

    success = await meeting_service.delete_meeting(session, mid)
    if not success:
        raise HTTPException(500, "Failed to delete meeting")
    return {"message": "Meeting deleted successfully"}


@router.post("/{meeting_id}/decisions")
async def add_decision(
    meeting_id: str,
    body: DecisionCreate,
    session: AsyncSession = Depends(get_db),
    mid: UUID = Depends(require_owned_meeting),
):
    """Log a decision during a meeting (owner-scoped)."""
    nudge_id = UUID(body.source_nudge_id) if body.source_nudge_id else None

    # When logging from a scribe nudge, capture the verbatim conversation
    # lines that triggered the detection as the decision's context — so the
    # summary can always show who said what.
    context = body.context
    owner = body.owner
    if nudge_id and not context:
        nudge_row = (
            await session.execute(
                select(Nudge).where(Nudge.id == nudge_id, Nudge.meeting_id == mid)
            )
        ).scalar_one_or_none()
        if nudge_row and nudge_row.source_data:
            quotes = nudge_row.source_data.get("trigger_quotes") or []
            if quotes:
                context = "\n".join(
                    f'{q.get("speaker", "?")}: "{q.get("text", "")}"'
                    for q in quotes
                    if q.get("text")
                )
            if not owner:
                owner = nudge_row.source_data.get("owner")

    decision = await meeting_service.add_decision(
        session,
        meeting_id=mid,
        decision_text=body.decision_text,
        owner=owner,
        deadline=body.deadline,
        context=context,
        source_nudge_id=nudge_id,
    )
    response = {
        "id": str(decision.id),
        "decision_text": decision.decision_text,
        "status": decision.status,
    }
    if nudge_id:
        await track_event(
            session,
            event_type="nudge_accepted",
            session_id=str(mid),
            event_data={"decision_id": response["id"]},
        )
    return response


@router.post("/{meeting_id}/action-items")
async def add_action_item(
    meeting_id: str,
    body: ActionItemCreate,
    session: AsyncSession = Depends(get_db),
    mid: UUID = Depends(require_owned_meeting),
):
    """Log an action item (owner-scoped)."""
    dec_id = UUID(body.decision_id) if body.decision_id else None

    item = await meeting_service.add_action_item(
        session,
        meeting_id=mid,
        description=body.description,
        assignee=body.assignee,
        deadline=body.deadline,
        priority=body.priority,
        decision_id=dec_id,
    )
    return {
        "id": str(item.id),
        "description": item.description,
        "status": item.status,
    }


_DECISION_STATUSES = {"pending", "in_progress", "done"}
_ACTION_STATUSES = {"open", "in_progress", "done"}


@router.patch("/{meeting_id}/decisions/{decision_id}")
async def update_decision_status(
    meeting_id: str,
    decision_id: str,
    body: dict,
    session: AsyncSession = Depends(get_db),
    mid: UUID = Depends(require_owned_meeting),
):
    """Move a decision through its lifecycle (leader only)."""
    status = str(body.get("status", "")).strip()
    if status not in _DECISION_STATUSES:
        raise HTTPException(422, f"status must be one of {sorted(_DECISION_STATUSES)}")
    ok = await meeting_service.set_decision_status(
        session, mid, UUID(decision_id), status
    )
    if not ok:
        raise HTTPException(404, "Decision not found")
    return {"id": decision_id, "status": status}


@router.patch("/{meeting_id}/action-items/{item_id}")
async def update_action_item_status(
    meeting_id: str,
    item_id: str,
    body: dict,
    session: AsyncSession = Depends(get_db),
    mid: UUID = Depends(require_owned_meeting),
):
    """Move an action item through its lifecycle (leader only)."""
    status = str(body.get("status", "")).strip()
    if status not in _ACTION_STATUSES:
        raise HTTPException(422, f"status must be one of {sorted(_ACTION_STATUSES)}")
    ok = await meeting_service.set_action_item_status(
        session, mid, UUID(item_id), status
    )
    if not ok:
        raise HTTPException(404, "Action item not found")
    return {"id": item_id, "status": status}


# -- Research Endpoints ----------------------------------------------------


@router.post("/{meeting_id}/research")
async def trigger_research(
    meeting_id: str,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_db),
    mid: UUID = Depends(require_owned_meeting),
):
    """Trigger pre-meeting research pipeline (owner-scoped, runs in background)."""
    meeting = await meeting_service.get_meeting(session, mid)
    if not meeting:
        raise HTTPException(404, "Meeting not found")

    # Don't re-run if already researching or completed
    if meeting.research_brief and meeting.research_brief.status in (
        "researching",
        "completed",
    ):
        return {
            "status": meeting.research_brief.status,
            "message": f"Research already {meeting.research_brief.status}",
        }

    # Update meeting status
    await meeting_service.update_meeting_status(session, mid, "researching")

    # Durable queue if enabled, else in-process background task
    if not await enqueue(
        "research_job", meeting_id, meeting.title, meeting.description or ""
    ):
        background_tasks.add_task(
            research_pipeline.run,
            meeting_id=meeting_id,
            title=meeting.title,
            description=meeting.description or "",
        )

    return {"status": "started", "message": "Research pipeline started"}


@router.get("/{meeting_id}/research")
async def get_research(
    meeting_id: str,
    session: AsyncSession = Depends(get_db),
    access: MeetingAccess = Depends(require_meeting_access),
):
    """Get research results for a meeting (leader or participant)."""
    mid = access.mid
    meeting = await meeting_service.get_meeting(session, mid)
    if not meeting:
        raise HTTPException(404, "Meeting not found")

    if not meeting.research_brief:
        return {"status": "not_started", "data": None}

    brief = meeting.research_brief
    return {
        "status": brief.status,
        "data": {
            "topics": brief.topics,
            "executive_summary": brief.executive_summary,
            "source_count": brief.source_count,
            "created_at": brief.created_at.isoformat(),
        },
    }


# -- Meeting Lifecycle Endpoints -------------------------------------------


@router.post("/{meeting_id}/start")
async def start_meeting(
    meeting_id: str,
    session: AsyncSession = Depends(get_db),
    current_user=Depends(require_user),
):
    """Start a live meeting session (owner-scoped)."""
    try:
        mid = UUID(meeting_id)
    except ValueError:
        raise HTTPException(400, "Invalid meeting ID format")

    meeting = await meeting_service.get_meeting(session, mid)
    if not meeting:
        raise HTTPException(404, "Meeting not found")
    _check_owner(meeting, current_user)

    success = await meeting_service.update_meeting_status(session, mid, "in_progress")
    if not success:
        raise HTTPException(500, "Failed to start meeting")
    return {"status": "in_progress", "message": "Meeting started"}


@router.post("/{meeting_id}/end")
async def end_meeting(
    meeting_id: str,
    session: AsyncSession = Depends(get_db),
    current_user=Depends(require_user),
):
    """End a live meeting session (owner-scoped)."""
    try:
        mid = UUID(meeting_id)
    except ValueError:
        raise HTTPException(400, "Invalid meeting ID format")

    meeting = await meeting_service.get_meeting(session, mid)
    if not meeting:
        raise HTTPException(404, "Meeting not found")
    _check_owner(meeting, current_user)

    success = await meeting_service.update_meeting_status(session, mid, "completed")
    if not success:
        raise HTTPException(500, "Failed to end meeting")
    return {"status": "completed", "message": "Meeting ended"}


@router.get("/{meeting_id}/nudges")
async def get_nudges(
    meeting_id: str,
    session: AsyncSession = Depends(get_db),
    access: MeetingAccess = Depends(require_meeting_access),
):
    """Get nudge cards (leader: all; participant: shared board + own activations)."""
    mid = access.mid
    meeting = await meeting_service.get_meeting(session, mid)
    if not meeting:
        raise HTTPException(404, "Meeting not found")

    visible = _visible_nudges(
        meeting.nudges or [], access.role, access.my_name, access.my_email
    )
    return {
        "nudges": [
            {
                "id": str(n.id),
                "type": n.nudge_type,
                "title": n.title,
                "content": n.content,
                "source_agent": n.source_agent,
                "source_data": n.source_data or {},
                "relevance_score": n.relevance_score,
                "dismissed_at": n.dismissed_at.isoformat() if n.dismissed_at else None,
                "pinned_at": n.pinned_at.isoformat() if n.pinned_at else None,
                "created_at": n.created_at.isoformat(),
            }
            for n in visible
        ]
    }


@router.get("/{meeting_id}/nudges/{nudge_id}/thread")
async def get_nudge_thread(
    meeting_id: str,
    nudge_id: str,
    session: AsyncSession = Depends(get_db),
    access: MeetingAccess = Depends(require_meeting_access),
):
    """One insight, in full, with the others belonging to the same thread.

    A card is a glance; this is the read. It returns the untruncated passage
    plus the related nudges, so a finding can be examined without hunting
    through a flat reverse-chronological list for the two other cards that
    happen to be about the same thing.

    Relatedness is computed from what we actually know rather than a second
    embedding pass on the hot path:

      * same source document — different passages from one document are
        almost always the same thread of discussion
      * shared salient terms — vendor names, figures, people
      * temporal proximity — nudges raised in the same few minutes were
        responding to the same part of the conversation

    The scores are heuristic and deliberately shown to no one; they only order
    the list.
    """
    mid = access.mid
    meeting = await meeting_service.get_meeting(session, mid)
    if not meeting:
        raise HTTPException(404, "Meeting not found")

    visible = _visible_nudges(
        meeting.nudges or [], access.role, access.my_name, access.my_email
    )
    target = next((n for n in visible if str(n.id) == nudge_id), None)
    if target is None:
        raise HTTPException(404, "Insight not found")

    related = _related_nudges(target, visible)
    return {
        "nudge": _nudge_detail(target),
        "related": [_nudge_detail(n) for n in related],
    }


def _nudge_detail(n) -> dict:
    """Serialize a nudge with its full passage restored."""
    data = n.source_data or {}
    return {
        "id": str(n.id),
        "type": n.nudge_type,
        "title": n.title,
        "content": n.content,
        # The card's text is a 300-char snippet. This is what was actually
        # retrieved, so the detail view doesn't end mid-sentence.
        "full_content": data.get("full_content") or n.content,
        "source_agent": n.source_agent,
        "source_data": data,
        "relevance_score": n.relevance_score,
        "dismissed_at": n.dismissed_at.isoformat() if n.dismissed_at else None,
        "pinned_at": n.pinned_at.isoformat() if n.pinned_at else None,
        "created_at": n.created_at.isoformat(),
    }


# Words too common to indicate that two insights are about the same thing.
_THREAD_STOPWORDS = frozenset(
    """the a an and or but if then than that this these those of to in on at by for
    with from as is are was were be been being have has had do does did will would
    should could can may might must not no yes it its we our you your they their
    i me my he she his her them us who whom which what when where why how""".split()
)


def _salient_terms(text: str) -> set:
    """Terms that plausibly identify a topic: names, figures, domain nouns."""
    import re as _re

    tokens = _re.findall(r"[A-Za-z][\w'-]{2,}|\$?\d[\d,.]*%?", (text or "").lower())
    return {t for t in tokens if t not in _THREAD_STOPWORDS}


def _related_nudges(target, candidates: list, limit: int = 8) -> list:
    """Rank the other nudges by how likely they belong to the same thread."""
    from datetime import timedelta as _timedelta

    t_data = target.source_data or {}
    t_doc = str(t_data.get("document_id") or "") or None
    t_terms = _salient_terms(f"{target.title} {target.content}")
    t_time = target.created_at

    scored = []
    for n in candidates:
        if str(n.id) == str(target.id) or n.dismissed_at is not None:
            continue
        score = 0.0
        data = n.source_data or {}

        if t_doc and str(data.get("document_id") or "") == t_doc:
            score += 3.0

        terms = _salient_terms(f"{n.title} {n.content}")
        overlap = len(t_terms & terms)
        if overlap:
            # Normalized so a long passage doesn't dominate purely by length.
            score += 2.0 * (overlap / max(6, min(len(t_terms), len(terms))))

        if t_time and n.created_at:
            gap = abs((n.created_at - t_time).total_seconds())
            if gap <= _timedelta(minutes=5).total_seconds():
                score += 1.0
            elif gap <= _timedelta(minutes=15).total_seconds():
                score += 0.5

        # A reply is an answer to a question about this moment — worth keeping
        # near whatever prompted it.
        if n.nudge_type == "reply":
            score += 0.5

        if score > 0.75:
            scored.append((score, n))

    scored.sort(key=lambda x: (-x[0], x[1].created_at))
    return [n for _, n in scored[:limit]]


@router.post("/{meeting_id}/nudges/{nudge_id}/dismiss")
async def dismiss_nudge(
    meeting_id: str,
    nudge_id: str,
    session: AsyncSession = Depends(get_db),
    mid: UUID = Depends(require_owned_meeting),
):
    """Dismiss a nudge (persisted — feeds relevance learning later)."""
    try:
        nid = UUID(nudge_id)
    except ValueError:
        raise HTTPException(400, "Invalid nudge ID format")

    nudge = await meeting_service.set_nudge_feedback(session, mid, nid, dismissed=True)
    if nudge is None:
        raise HTTPException(404, "Nudge not found")

    from apps.api.services.meeting.nudge_feedback import record as record_feedback

    response = {"id": str(nudge.id), "dismissed_at": nudge.dismissed_at.isoformat()}
    nudge_type = nudge.nudge_type

    _, owner_id = await meeting_service.get_owner_id(session, mid)
    await record_feedback(str(owner_id) if owner_id else None, nudge_type, "dismissed")
    await track_event(
        session,
        event_type="nudge_dismissed",
        session_id=str(mid),
        event_data={"nudge_type": nudge_type},
    )
    return response


@router.post("/{meeting_id}/nudges/{nudge_id}/pin")
async def pin_nudge(
    meeting_id: str,
    nudge_id: str,
    session: AsyncSession = Depends(get_db),
    mid: UUID = Depends(require_owned_meeting),
):
    """Toggle pin on a nudge (pinned insights get prominence in the summary)."""
    try:
        nid = UUID(nudge_id)
    except ValueError:
        raise HTTPException(400, "Invalid nudge ID format")

    meeting = await meeting_service.get_meeting(session, mid)
    current = next((n for n in (meeting.nudges or []) if str(n.id) == str(nid)), None)
    if current is None:
        raise HTTPException(404, "Nudge not found")

    pinning = current.pinned_at is None
    nudge = await meeting_service.set_nudge_feedback(session, mid, nid, pinned=pinning)
    response = {
        "id": str(nudge.id),
        "pinned_at": nudge.pinned_at.isoformat() if nudge.pinned_at else None,
    }
    nudge_type = nudge.nudge_type
    if pinning:
        from apps.api.services.meeting.nudge_feedback import (
            record as record_feedback,
        )

        _, owner_id = await meeting_service.get_owner_id(session, mid)
        await record_feedback(str(owner_id) if owner_id else None, nudge_type, "pinned")
        await track_event(
            session,
            event_type="nudge_pinned",
            session_id=str(mid),
            event_data={"nudge_type": nudge_type},
        )
    return response


# -- Voice / LiveKit Endpoints ---------------------------------------------


@router.get("/{meeting_id}/voice-token")
async def get_meeting_voice_token(
    meeting_id: str,
    request: Request,
    participant_name: str = Query("user", description="Display name"),
    conference: bool = Query(
        False, description="Shared-mic room: enable acoustic diarization"
    ),
    _access: MeetingAccess = Depends(require_meeting_access),
):
    """Issue a LiveKit token for the meeting's room (leader or participant)."""
    services = getattr(request.app.state, "services", None)
    voice = services.voice_service if services else None
    if voice is None:
        raise HTTPException(503, "Voice service not initialized")

    room_name = f"meeting-{meeting_id}"
    try:
        token = await voice.generate_token(
            room_name=room_name,
            participant_name=participant_name,
            attributes={"conference": "1"} if conference else None,
        )
    except Exception as e:
        raise HTTPException(500, f"Token generation failed: {e}")

    from apps.api.core.config import settings as _s

    return {
        "token": token,
        "url": _s.livekit_client_url,
        "room_name": room_name,
    }


@router.post("/{meeting_id}/speak")
async def speak_in_meeting(
    meeting_id: str,
    body: dict,
    session: AsyncSession = Depends(get_db),
    principal=Depends(get_service_or_user),
):
    """Send text to be spoken aloud by the meeting voice worker.

    Callable by service (API key) or a meeting owner (user JWT).
    Publishes the text on the Redis channel ``meeting:{id}:speak``.
    The LiveKit-side worker subscribes, synthesizes via Cartesia, and
    pushes the audio back into the room. No-op (503) when Redis is
    not configured.
    """
    import json as _json

    from apps.api.core.connections import get_redis_client

    try:
        mid = UUID(meeting_id)
    except ValueError:
        raise HTTPException(400, "Invalid meeting ID format")

    # Owner check when a user (not the service key) is calling.
    if principal is not None:
        exists, owner_id = await meeting_service.get_owner_id(session, mid)
        if not exists:
            raise HTTPException(404, "Meeting not found")
        _check_owner_id(owner_id, principal)

    text = (body.get("text") or "").strip()
    if not text:
        raise HTTPException(400, "Field 'text' is required")
    if len(text) > 600:
        raise HTTPException(400, "Text too long (max 600 chars)")

    redis = await get_redis_client()
    if redis is None:
        raise HTTPException(503, "Redis unavailable — TTS pipeline disabled")

    channel = f"meeting:{meeting_id}:speak"
    try:
        delivered = await redis.publish(channel, _json.dumps({"text": text}))
    except Exception as e:
        raise HTTPException(500, f"Publish failed: {e}")

    return {
        "status": "queued",
        "channel": channel,
        "subscribers": int(delivered),
        "text_length": len(text),
    }


# -- Transcript / Utterance Endpoints --------------------------------------


@router.post("/{meeting_id}/utterances")
async def add_utterance(
    meeting_id: str,
    body: dict,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_db),
    principal=Depends(get_service_or_user),
):
    """Append an utterance to the meeting transcript and trigger agents.

    Callable by the voice worker (service API key) or the browser (user
    JWT). When a user calls it, ownership is enforced.

    Body: {"speaker": str, "text": str}
    """
    try:
        mid = UUID(meeting_id)
    except ValueError:
        raise HTTPException(400, "Invalid meeting ID format")

    speaker = (body.get("speaker") or "").strip() or "Speaker"
    text = (body.get("text") or "").strip()
    if not text:
        raise HTTPException(400, "Utterance text is required")

    meeting = await meeting_service.get_meeting(session, mid)
    if not meeting:
        raise HTTPException(404, "Meeting not found")
    # Leaders and invited participants may speak; unknown users may not.
    if (
        _role_of(getattr(meeting, "owner_id", None), meeting.attendees or [], principal)
        is None
    ):
        raise HTTPException(404, "Meeting not found")

    # The transcript is a shared record, so the speaker label must mean the
    # same thing to everyone who reads it. A client that sends a
    # viewer-relative placeholder gets overridden with the caller's real name —
    # the server knows who is authenticated and the browser may not.
    if speaker.lower() in _VIEWER_RELATIVE_SPEAKERS:
        resolved = _display_name_for(meeting.attendees or [], principal)
        if resolved:
            speaker = resolved

    transcript = await meeting_service.append_utterance(
        session=session,
        meeting_id=mid,
        speaker=speaker,
        text=text,
    )

    # Live-push the new utterance to any connected WebSocket clients
    await meeting_hub.broadcast(
        meeting_id,
        {
            "type": "utterance_added",
            "utterance": {"speaker": speaker, "text": text},
            "utterance_count": len(transcript.utterances or []),
        },
    )

    # Start the end-to-end clock here: this is the first moment the system
    # knows these words exist. Everything downstream (queue hop, state load,
    # fan-out, persistence, WS delivery) is latency the user experiences, and
    # none of it was previously measured — only the agent budgets were.
    import time as _time

    accepted_at = _time.time()
    try:
        from apps.api.core.connections import get_redis_client

        redis = await get_redis_client()
        # Short TTL: this is a stopwatch, not state. If the cycle takes longer
        # than this the measurement is lost, which is the correct trade — a
        # stale start time would report a fictional latency.
        await redis.set(f"utt:accepted:{meeting_id}", str(accepted_at), ex=120)
    except Exception:
        pass  # timing is best-effort; never let it cost an utterance

    # Run agent dispatcher: durable queue if enabled, else in-process.
    if not await enqueue("dispatch_job", meeting_id):
        background_tasks.add_task(agent_dispatcher.dispatch, meeting_id)

    return {
        "status": "ok",
        "utterance_count": len(transcript.utterances or []),
    }


@router.websocket("/{meeting_id}/ws")
async def meeting_websocket(
    websocket: WebSocket, meeting_id: str, token: Optional[str] = Query(None)
):
    """Live channel for meeting events (utterances + nudges).

    Frontend subscribes once on meeting open and receives push events,
    eliminating the 5s polling loop. When ``REQUIRE_AUTH`` is on, a JWT
    must be supplied via the ``token`` query param and the user must be
    the meeting's leader or an invited participant.
    """
    try:
        mid = UUID(meeting_id)
    except ValueError:
        await websocket.close(code=4400)
        return

    from apps.api.core.config import settings

    ws_role = "leader"
    ws_name: Optional[str] = None
    ws_email: Optional[str] = None
    if settings.require_auth:
        from apps.api.core.database import AsyncSessionLocal
        from apps.api.core.security import decode_access_token
        from apps.api.models.user import User

        claims = decode_access_token(token or "")
        if not claims or not claims.get("sub"):
            await websocket.close(code=4401)
            return
        async with AsyncSessionLocal() as session:
            try:
                user = await session.get(User, UUID(claims["sub"]))
            except (ValueError, TypeError):
                user = None
            if user is None or not user.is_active:
                await websocket.close(code=4401)
                return
            exists, owner_id, attendees = await meeting_service.get_access_row(
                session, mid
            )
            role = _role_of(owner_id, attendees, user) if exists else None
            if role is None:
                await websocket.close(code=4403)
                return
            ws_role = role
            ws_name = _display_name_for(attendees, user)
            # The authenticated email, not the attendee entry's — this is the
            # identity activation nudges are addressed to.
            ws_email = getattr(user, "email", None)

    await meeting_hub.connect(
        meeting_id,
        websocket,
        role=ws_role,
        my_name=ws_name,
        my_email=ws_email,
    )
    try:
        # Keep the socket alive — client may send pings or be passive.
        while True:
            msg = await websocket.receive_text()
            if msg == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        await meeting_hub.disconnect(meeting_id, websocket)


@router.get("/{meeting_id}/transcript")
async def get_transcript(
    meeting_id: str,
    session: AsyncSession = Depends(get_db),
    access: MeetingAccess = Depends(require_meeting_access),
):
    """Get the meeting transcript (leader or participant)."""
    mid = access.mid
    transcript = await meeting_service.get_transcript(session, mid)
    if not transcript:
        return {"utterances": [], "full_text": ""}

    return {
        "utterances": transcript.utterances or [],
        "full_text": transcript.full_text or "",
    }


# -- Summary Endpoints -----------------------------------------------------


@router.post("/{meeting_id}/summarize")
async def generate_summary(
    meeting_id: str,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_db),
    mid: UUID = Depends(require_owned_meeting),
):
    """Generate a post-meeting summary (owner-scoped, background task)."""
    meeting = await meeting_service.get_meeting(session, mid)
    if not meeting:
        raise HTTPException(404, "Meeting not found")

    if meeting.summary:
        return {"status": "already_exists", "message": "Summary already generated"}

    # Gather meeting data for the summary agent
    transcript_text = ""
    if meeting.transcript:
        transcript_text = meeting.transcript.full_text or ""

    decisions_data = [
        {
            "decision_text": d.decision_text,
            "owner": d.owner,
            "deadline": d.deadline.isoformat() if d.deadline else None,
            "status": d.status,
            "context": d.context,
        }
        for d in (meeting.decisions or [])
    ]

    # Dismissed nudges are excluded (the user said they weren't relevant);
    # pinned nudges sort first and are flagged for prominence in the summary.
    nudges_data = sorted(
        (
            {
                "type": n.nudge_type,
                "title": n.title,
                "content": n.content,
                "pinned": n.pinned_at is not None,
            }
            for n in (meeting.nudges or [])
            if n.dismissed_at is None
        ),
        key=lambda n: not n["pinned"],
    )

    action_items_data = [
        {
            "description": a.description,
            "assignee": a.assignee,
            "priority": a.priority,
            "status": a.status,
        }
        for a in (meeting.action_items or [])
    ]

    research_summary = ""
    if meeting.research_brief and meeting.research_brief.executive_summary:
        research_summary = meeting.research_brief.executive_summary

    if not await enqueue(
        "summary_job",
        meeting_id,
        meeting.title,
        meeting.description or "",
        transcript_text,
        decisions_data,
        action_items_data,
        nudges_data,
        research_summary,
    ):
        background_tasks.add_task(
            summary_pipeline.run,
            meeting_id=meeting_id,
            meeting_title=meeting.title,
            description=meeting.description or "",
            transcript_text=transcript_text,
            decisions=decisions_data,
            action_items=action_items_data,
            nudges=nudges_data,
            research_summary=research_summary,
        )

    return {"status": "started", "message": "Summary generation started"}


@router.get("/{meeting_id}/summary")
async def get_summary(
    meeting_id: str,
    session: AsyncSession = Depends(get_db),
    access: MeetingAccess = Depends(require_meeting_access),
):
    """Get meeting summary (leader or participant)."""
    mid = access.mid
    meeting = await meeting_service.get_meeting(session, mid)
    if not meeting:
        raise HTTPException(404, "Meeting not found")

    if not meeting.summary:
        return {"status": "not_generated", "data": None}

    summary_response = {
        "status": "completed",
        "data": {
            "summary_text": meeting.summary.summary_text,
            "key_insights": meeting.summary.key_insights,
            "decisions_summary": meeting.summary.decisions_summary,
            "action_items": [
                {
                    "id": str(a.id),
                    "description": a.description,
                    "assignee": a.assignee,
                    "priority": a.priority,
                    "status": a.status,
                    "decision_id": str(a.decision_id) if a.decision_id else None,
                }
                for a in (meeting.action_items or [])
            ],
            "email_sent_at": meeting.summary.email_sent_at.isoformat()
            if meeting.summary.email_sent_at
            else None,
            "created_at": meeting.summary.created_at.isoformat(),
        },
    }
    await track_event(
        session,
        event_type="summary_viewed",
        session_id=str(mid),
        event_data={"role": access.role},
    )
    return summary_response


@router.post("/{meeting_id}/send-summary")
async def send_summary_email(
    meeting_id: str,
    session: AsyncSession = Depends(get_db),
    mid: UUID = Depends(require_owned_meeting),
):
    """Send meeting summary email to attendees (owner-scoped)."""
    meeting = await meeting_service.get_meeting(session, mid)
    if not meeting:
        raise HTTPException(404, "Meeting not found")

    if not meeting.summary:
        raise HTTPException(400, "No summary to send — generate one first")

    recipients = [a.get("email") for a in (meeting.attendees or []) if a.get("email")]
    if not recipients:
        raise HTTPException(400, "No attendee email addresses configured")

    summary_data = {
        "executive_summary": meeting.summary.summary_text,
        "decisions_summary": meeting.summary.decisions_summary,
        "action_items": [
            {
                "item": a.description,
                "assignee": a.assignee,
                "priority": a.priority,
            }
            for a in (meeting.action_items or [])
        ],
        "ai_insights_used": meeting.summary.key_insights,
        "follow_up_recommendations": [],
    }

    # Deadlined action items ride along as calendar events (.ics)
    ics = build_action_items_calendar(
        str(mid),
        meeting.title,
        [
            {
                "description": a.description,
                "assignee": a.assignee,
                "deadline": a.deadline,
            }
            for a in (meeting.action_items or [])
        ],
    )

    postmark_id = await email_service.send_summary_email(
        recipients=recipients,
        meeting_title=meeting.title,
        summary=summary_data,
        ics_attachment=ics,
    )

    if postmark_id:
        await meeting_service.mark_email_sent(session, mid, postmark_id)
        return {
            "status": "sent",
            "message": f"Summary emailed to {len(recipients)} recipients",
            "postmark_id": postmark_id,
        }

    raise HTTPException(500, "Failed to send email")


@router.get("/{meeting_id}/calendar.ics")
async def download_calendar(
    meeting_id: str,
    session: AsyncSession = Depends(get_db),
    access: MeetingAccess = Depends(require_meeting_access),
):
    """Download the meeting (or its action-item deadlines) as an .ics file."""
    meeting = await meeting_service.get_meeting(session, access.mid)
    if not meeting:
        raise HTTPException(404, "Meeting not found")

    ics = None
    if meeting.status == "completed":
        ics = build_action_items_calendar(
            meeting_id,
            meeting.title,
            [
                {
                    "description": a.description,
                    "assignee": a.assignee,
                    "deadline": a.deadline,
                }
                for a in (meeting.action_items or [])
            ],
        )
    if ics is None and meeting.scheduled_at:
        ics = build_meeting_event(
            meeting_id,
            meeting.title,
            meeting.scheduled_at,
            description=meeting.description,
            url=f"{settings.frontend_url}/meetings/{meeting_id}",
        )
    if ics is None:
        raise HTTPException(400, "Nothing to export — no schedule or deadlines")
    return Response(
        content=ics,
        media_type="text/calendar",
        headers={"Content-Disposition": 'attachment; filename="donna-meeting.ics"'},
    )


@router.post("/{meeting_id}/invite")
async def send_invites(
    meeting_id: str,
    session: AsyncSession = Depends(get_db),
    mid: UUID = Depends(require_owned_meeting),
):
    """Email every attendee an invite with the meeting link (+ .ics)."""
    meeting = await meeting_service.get_meeting(session, mid)
    if not meeting:
        raise HTTPException(404, "Meeting not found")
    recipients = [a.get("email") for a in (meeting.attendees or []) if a.get("email")]
    if not recipients:
        raise HTTPException(400, "No attendee email addresses configured")

    meeting_url = f"{settings.frontend_url}/meetings/{meeting_id}"
    ics = (
        build_meeting_event(
            meeting_id,
            meeting.title,
            meeting.scheduled_at,
            description=meeting.description,
            url=meeting_url,
        )
        if meeting.scheduled_at
        else None
    )
    sent = await email_service.send_invite_email(
        recipients=recipients,
        meeting_title=meeting.title,
        meeting_url=meeting_url,
        scheduled_label=(
            meeting.scheduled_at.strftime("%b %d, %Y at %H:%M UTC")
            if meeting.scheduled_at
            else None
        ),
        agenda_titles=[str(i.get("title", i)) for i in (meeting.agenda or []) if i],
        ics_attachment=ics,
    )
    if not sent:
        raise HTTPException(500, "Failed to send invites")
    return {"status": "sent", "recipients": len(recipients)}


@router.post("/{meeting_id}/send-preread")
async def send_preread(
    meeting_id: str,
    session: AsyncSession = Depends(get_db),
    mid: UUID = Depends(require_owned_meeting),
):
    """Email attendees the pre-read: goal + agenda + tiered research findings."""
    meeting = await meeting_service.get_meeting(session, mid)
    if not meeting:
        raise HTTPException(404, "Meeting not found")
    recipients = [a.get("email") for a in (meeting.attendees or []) if a.get("email")]
    if not recipients:
        raise HTTPException(400, "No attendee email addresses configured")

    findings = []
    brief = meeting.research_brief
    for t in (brief.topics if brief and isinstance(brief.topics, list) else [])[:6]:
        if not isinstance(t, dict):
            continue
        sources = t.get("sources") or []
        findings.append(
            {
                "topic": t.get("topic", ""),
                "summary": t.get("summary") or t.get("synthesis", ""),
                "source_url": (
                    sources[0].get("url")
                    if sources and isinstance(sources[0], dict)
                    else None
                ),
            }
        )

    sent = await email_service.send_preread_email(
        recipients=recipients,
        meeting_title=meeting.title,
        meeting_goal=meeting.description,
        agenda_titles=[str(i.get("title", i)) for i in (meeting.agenda or []) if i],
        findings=findings,
    )
    if not sent:
        raise HTTPException(500, "Failed to send pre-read")
    await track_event(
        session,
        event_type="preread_sent",
        session_id=meeting_id,
        event_data={"recipients": len(recipients)},
    )
    return {"status": "sent", "recipients": len(recipients)}


@router.post("/{meeting_id}/send-followups")
async def send_followups(
    meeting_id: str,
    session: AsyncSession = Depends(get_db),
    mid: UUID = Depends(require_owned_meeting),
):
    """Per-assignee action-item emails ("You own 3 items from …")."""
    meeting = await meeting_service.get_meeting(session, mid)
    if not meeting:
        raise HTTPException(404, "Meeting not found")

    # Resolve assignee names to attendee emails; emails pass through as-is.
    email_by_name = {
        str(a.get("name", "")).lower(): a.get("email")
        for a in (meeting.attendees or [])
        if a.get("email")
    }
    assignments: dict = {}
    for item in meeting.action_items or []:
        if item.status == "done" or not item.assignee:
            continue
        key = item.assignee.strip()
        email = key if "@" in key else email_by_name.get(key.lower())
        if not email:
            continue
        assignments.setdefault(email, []).append(
            {
                "description": item.description,
                "deadline": item.deadline.isoformat() if item.deadline else None,
                "priority": item.priority,
            }
        )
    if not assignments:
        raise HTTPException(400, "No emailable assignees with open items")

    sent = await email_service.send_assignee_followups(assignments, meeting.title)
    return {"status": "sent", "emails": sent}


# -- Knowledge Graph + In-Meeting Query ------------------------------------


@router.get("/{meeting_id}/knowledge-graph")
async def get_meeting_knowledge_graph(
    meeting_id: str,
    session: AsyncSession = Depends(get_db),
    mid: UUID = Depends(require_owned_meeting),
):
    """Return the meeting-context knowledge graph (owner-scoped).

    Builds the subgraph of knowledge-base entities that are actually
    referenced in this meeting — entities whose label appears in the
    transcript or research topics — plus their 1-hop neighbours. This
    is the graph the Context / KG agents reason over during the meeting,
    so the UI can visualize "what the AI knows about this conversation".

    Returns ``{nodes, edges, mentioned}`` where ``mentioned`` flags the
    entities the meeting actually surfaced. Empty graph (not an error)
    when Neo4j is unavailable or nothing matches.
    """
    from apps.api.core.neo4j_client import neo4j_client
    from apps.api.services.meeting.kg_query_agent import KGQueryAgent

    meeting = await meeting_service.get_meeting(session, mid)
    if not meeting:
        raise HTTPException(404, "Meeting not found")

    if not neo4j_client.enabled:
        return {
            "meeting_id": meeting_id,
            "node_count": 0,
            "edge_count": 0,
            "nodes": [],
            "edges": [],
            "mentioned": [],
            "source": "unavailable",
        }

    # Gather text the meeting has produced: transcript + research topics
    corpus_parts: list[str] = []
    if meeting.transcript and meeting.transcript.full_text:
        corpus_parts.append(meeting.transcript.full_text)
    if meeting.research_brief and meeting.research_brief.topics:
        for t in meeting.research_brief.topics:
            if isinstance(t, dict):
                corpus_parts.append(f"{t.get('topic', '')} {t.get('summary', '')}")
    corpus = " ".join(corpus_parts).strip()

    candidates = KGQueryAgent._extract_candidate_phrases(corpus) if corpus else set()
    if not candidates:
        return {
            "meeting_id": meeting_id,
            "node_count": 0,
            "edge_count": 0,
            "nodes": [],
            "edges": [],
            "mentioned": [],
            "source": "neo4j",
        }

    # Tenant scope (GLOBAL_OWNER sentinel when the meeting has no owner)
    from apps.api.core.neo4j_client import GLOBAL_OWNER

    owner = (
        str(meeting.owner_id) if getattr(meeting, "owner_id", None) else GLOBAL_OWNER
    )

    # Anchor entities (mentioned) + their 1-hop neighbourhood, owner-scoped
    cypher = """
    MATCH (a:Entity {owner_id: $owner})
    WHERE a.normalized IN $candidates
    OPTIONAL MATCH (a)-[r:REL]-(b:Entity {owner_id: $owner})
    RETURN
        collect(DISTINCT {id: a.id, label: a.label, type: a.type,
                          normalized: a.normalized, mentioned: true}) AS anchors,
        collect(DISTINCT CASE WHEN b IS NOT NULL THEN
            {id: b.id, label: b.label, type: b.type,
             normalized: b.normalized, mentioned: false} END) AS neighbours,
        collect(DISTINCT CASE WHEN b IS NOT NULL THEN
            {source_norm: a.normalized, source_type: a.type,
             target_norm: b.normalized, target_type: b.type,
             relationship: r.type, confidence: r.confidence,
             context: r.context} END) AS rels
    """
    result = await neo4j_client.execute(
        cypher, {"candidates": list(candidates), "owner": owner}
    )
    if not result or not result[0].get("anchors"):
        return {
            "meeting_id": meeting_id,
            "node_count": 0,
            "edge_count": 0,
            "nodes": [],
            "edges": [],
            "mentioned": [],
            "source": "neo4j",
        }

    row = result[0]
    # Merge anchors + neighbours, dedupe by (normalized, type), anchors win
    node_by_key: dict = {}
    for n in row.get("neighbours") or []:
        if n:
            node_by_key[(n["normalized"], n["type"])] = n
    for n in row.get("anchors") or []:
        if n:
            node_by_key[(n["normalized"], n["type"])] = n  # mentioned=true wins

    nodes = list(node_by_key.values())
    id_by_key = {(n["normalized"], n["type"]): n["id"] for n in nodes}

    edges = []
    seen_edges = set()
    for r in row.get("rels") or []:
        if not r:
            continue
        s = id_by_key.get((r["source_norm"], r["source_type"]))
        t = id_by_key.get((r["target_norm"], r["target_type"]))
        if not s or not t:
            continue
        ekey = (s, t, r.get("relationship"))
        if ekey in seen_edges:
            continue
        seen_edges.add(ekey)
        edges.append(
            {
                "source": s,
                "target": t,
                "relationship": (r.get("relationship") or "").lower(),
                "confidence": r.get("confidence"),
                "context": r.get("context"),
            }
        )

    mentioned = [n["label"] for n in nodes if n.get("mentioned")]
    return {
        "meeting_id": meeting_id,
        "node_count": len(nodes),
        "edge_count": len(edges),
        "nodes": nodes,
        "edges": edges,
        "mentioned": mentioned,
        "source": "neo4j",
    }


@router.post("/{meeting_id}/query")
async def query_meeting_context(
    meeting_id: str,
    body: dict,
    request: Request,
    session: AsyncSession = Depends(get_db),
    access: MeetingAccess = Depends(require_meeting_access),
):
    """Manual RAG query during a meeting (leader or participant).

    Lets a participant ask the knowledge base a question mid-meeting
    (e.g. "what did we decide about pricing last quarter?"). Runs the
    same RAG service the Context Agent uses and returns an
    answer + sources. The query + answer are appended to the transcript
    so they appear in the post-meeting summary.

    Body: ``{"query": str, "record": bool = true}``
    """
    mid = access.mid
    query_text = (body.get("query") or "").strip()
    if not query_text:
        raise HTTPException(400, "Field 'query' is required")

    meeting = await meeting_service.get_meeting(session, mid)
    if not meeting:
        raise HTTPException(404, "Meeting not found")

    services = getattr(request.app.state, "services", None)
    # Modern service only: it searches the 4 collections the ingestion
    # pipeline actually writes. The legacy RAGService reads the base
    # collection, which nothing populates — every query 404'd on Qdrant.
    rag = getattr(services, "modern_rag_service", None) if services else None
    if rag is None:
        raise HTTPException(503, "RAG service not initialized")

    # Scope retrieval to the meeting owner's knowledge base (tenant isolation)
    meeting_owner = (
        await session.execute(select(Meeting.owner_id).where(Meeting.id == access.mid))
    ).scalar_one_or_none()

    try:
        result = await rag.process_query(
            query=query_text,
            conversation_id=f"meeting-{meeting_id}",
            owner_id=str(meeting_owner) if meeting_owner else None,
        )
    except Exception as e:
        raise HTTPException(500, f"Query failed: {e}")

    answer = result.get("answer", "")
    sources = result.get("sources", [])

    # Record the Q&A into the transcript so AFTER-phase summary sees it
    if body.get("record", True) and answer:
        try:
            await meeting_service.append_utterance(
                session=session,
                meeting_id=mid,
                speaker="Donna",
                text=f"Q: {query_text}\nA: {answer}",
            )
        except Exception:
            pass  # non-fatal — the answer is still returned

    return {
        "meeting_id": meeting_id,
        "query": query_text,
        "answer": answer,
        "sources": sources,
        "confidence": result.get("confidence"),
    }
