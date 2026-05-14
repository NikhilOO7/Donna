"""
REST endpoints for the Meeting Assistant lifecycle.
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
    WebSocket,
    WebSocketDisconnect,
)
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.auth import verify_api_key
from apps.api.core.database import get_db
from apps.api.models.meeting import (
    ActionItemCreate,
    DecisionCreate,
    MeetingCreate,
)
from apps.api.services.meeting.agent_dispatcher import agent_dispatcher
from apps.api.services.meeting.email_service import email_service
from apps.api.services.meeting.meeting_service import meeting_service
from apps.api.services.meeting.realtime import meeting_hub
from apps.api.services.meeting.summary_pipeline import summary_pipeline
from apps.api.services.research.pipeline import research_pipeline

router = APIRouter(prefix="/api/v1/meetings", tags=["meetings"])


@router.post("/", response_model=dict)
async def create_meeting(
    body: MeetingCreate,
    session: AsyncSession = Depends(get_db),
    _api_key: str = Depends(verify_api_key),
):
    """Create a new meeting."""
    meeting = await meeting_service.create_meeting(
        session,
        title=body.title,
        description=body.description,
        attendees=body.attendees,
        scheduled_at=body.scheduled_at,
    )
    return {
        "id": str(meeting.id),
        "title": meeting.title,
        "status": meeting.status,
        "created_at": meeting.created_at.isoformat(),
    }


@router.get("/")
async def list_meetings(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    status: Optional[str] = None,
    session: AsyncSession = Depends(get_db),
    _api_key: str = Depends(verify_api_key),
):
    """List meetings with optional status filter."""
    meetings = await meeting_service.list_meetings(session, skip, limit, status)
    return {
        "meetings": [
            {
                "id": str(m.id),
                "title": m.title,
                "status": m.status,
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


@router.get("/{meeting_id}")
async def get_meeting(
    meeting_id: str,
    session: AsyncSession = Depends(get_db),
    _api_key: str = Depends(verify_api_key),
):
    """Get a meeting with all related data."""
    try:
        mid = UUID(meeting_id)
    except ValueError:
        raise HTTPException(400, "Invalid meeting ID format")

    meeting = await meeting_service.get_meeting(session, mid)
    if not meeting:
        raise HTTPException(404, "Meeting not found")

    return {
        "id": str(meeting.id),
        "title": meeting.title,
        "description": meeting.description,
        "status": meeting.status,
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
                "relevance_score": n.relevance_score,
                "created_at": n.created_at.isoformat(),
            }
            for n in (meeting.nudges or [])
        ],
        "decisions": [
            {
                "id": str(d.id),
                "decision_text": d.decision_text,
                "owner": d.owner,
                "deadline": d.deadline.isoformat() if d.deadline else None,
                "status": d.status,
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


@router.delete("/{meeting_id}")
async def delete_meeting(
    meeting_id: str,
    session: AsyncSession = Depends(get_db),
    _api_key: str = Depends(verify_api_key),
):
    """Soft-delete a meeting."""
    try:
        mid = UUID(meeting_id)
    except ValueError:
        raise HTTPException(400, "Invalid meeting ID format")

    success = await meeting_service.delete_meeting(session, mid)
    if not success:
        raise HTTPException(500, "Failed to delete meeting")
    return {"message": "Meeting deleted successfully"}


@router.post("/{meeting_id}/decisions")
async def add_decision(
    meeting_id: str,
    body: DecisionCreate,
    session: AsyncSession = Depends(get_db),
    _api_key: str = Depends(verify_api_key),
):
    """Log a decision during a meeting."""
    try:
        mid = UUID(meeting_id)
    except ValueError:
        raise HTTPException(400, "Invalid meeting ID format")

    nudge_id = UUID(body.source_nudge_id) if body.source_nudge_id else None

    decision = await meeting_service.add_decision(
        session,
        meeting_id=mid,
        decision_text=body.decision_text,
        owner=body.owner,
        deadline=body.deadline,
        context=body.context,
        source_nudge_id=nudge_id,
    )
    return {
        "id": str(decision.id),
        "decision_text": decision.decision_text,
        "status": decision.status,
    }


@router.post("/{meeting_id}/action-items")
async def add_action_item(
    meeting_id: str,
    body: ActionItemCreate,
    session: AsyncSession = Depends(get_db),
    _api_key: str = Depends(verify_api_key),
):
    """Log an action item."""
    try:
        mid = UUID(meeting_id)
    except ValueError:
        raise HTTPException(400, "Invalid meeting ID format")

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


# -- Research Endpoints ----------------------------------------------------


@router.post("/{meeting_id}/research")
async def trigger_research(
    meeting_id: str,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_db),
    _api_key: str = Depends(verify_api_key),
):
    """Trigger pre-meeting research pipeline (runs in background)."""
    try:
        mid = UUID(meeting_id)
    except ValueError:
        raise HTTPException(400, "Invalid meeting ID format")

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

    # Run pipeline in background
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
    _api_key: str = Depends(verify_api_key),
):
    """Get research results for a meeting."""
    try:
        mid = UUID(meeting_id)
    except ValueError:
        raise HTTPException(400, "Invalid meeting ID format")

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
    _api_key: str = Depends(verify_api_key),
):
    """Start a live meeting session."""
    try:
        mid = UUID(meeting_id)
    except ValueError:
        raise HTTPException(400, "Invalid meeting ID format")

    success = await meeting_service.update_meeting_status(session, mid, "in_progress")
    if not success:
        raise HTTPException(500, "Failed to start meeting")
    return {"status": "in_progress", "message": "Meeting started"}


@router.post("/{meeting_id}/end")
async def end_meeting(
    meeting_id: str,
    session: AsyncSession = Depends(get_db),
    _api_key: str = Depends(verify_api_key),
):
    """End a live meeting session."""
    try:
        mid = UUID(meeting_id)
    except ValueError:
        raise HTTPException(400, "Invalid meeting ID format")

    success = await meeting_service.update_meeting_status(session, mid, "completed")
    if not success:
        raise HTTPException(500, "Failed to end meeting")
    return {"status": "completed", "message": "Meeting ended"}


@router.get("/{meeting_id}/nudges")
async def get_nudges(
    meeting_id: str,
    session: AsyncSession = Depends(get_db),
    _api_key: str = Depends(verify_api_key),
):
    """Get all nudge cards for a meeting."""
    try:
        mid = UUID(meeting_id)
    except ValueError:
        raise HTTPException(400, "Invalid meeting ID format")

    meeting = await meeting_service.get_meeting(session, mid)
    if not meeting:
        raise HTTPException(404, "Meeting not found")

    return {
        "nudges": [
            {
                "id": str(n.id),
                "type": n.nudge_type,
                "title": n.title,
                "content": n.content,
                "source_agent": n.source_agent,
                "relevance_score": n.relevance_score,
                "created_at": n.created_at.isoformat(),
            }
            for n in (meeting.nudges or [])
        ]
    }


# -- Voice / LiveKit Endpoints ---------------------------------------------


@router.get("/{meeting_id}/voice-token")
async def get_meeting_voice_token(
    meeting_id: str,
    request: Request,
    participant_name: str = Query("user", description="Display name"),
    _api_key: str = Depends(verify_api_key),
):
    """Issue a LiveKit token for the meeting's room (`meeting-{id}`)."""
    try:
        UUID(meeting_id)
    except ValueError:
        raise HTTPException(400, "Invalid meeting ID format")

    services = getattr(request.app.state, "services", None)
    voice = services.voice_service if services else None
    if voice is None:
        raise HTTPException(503, "Voice service not initialized")

    room_name = f"meeting-{meeting_id}"
    try:
        token = await voice.generate_token(
            room_name=room_name, participant_name=participant_name
        )
    except Exception as e:
        raise HTTPException(500, f"Token generation failed: {e}")

    from apps.api.core.config import settings as _s

    return {
        "token": token,
        "url": _s.livekit_url,
        "room_name": room_name,
    }


# -- Transcript / Utterance Endpoints --------------------------------------


@router.post("/{meeting_id}/utterances")
async def add_utterance(
    meeting_id: str,
    body: dict,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_db),
    _api_key: str = Depends(verify_api_key),
):
    """Append an utterance to the meeting transcript and trigger agents.

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

    # Run agent dispatcher in background — does not block the response
    background_tasks.add_task(agent_dispatcher.dispatch, meeting_id)

    return {
        "status": "ok",
        "utterance_count": len(transcript.utterances or []),
    }


@router.websocket("/{meeting_id}/ws")
async def meeting_websocket(websocket: WebSocket, meeting_id: str):
    """Live channel for meeting events (utterances + nudges).

    Frontend subscribes once on meeting open and receives push events,
    eliminating the 5s polling loop.
    """
    try:
        UUID(meeting_id)
    except ValueError:
        await websocket.close(code=4400)
        return

    await meeting_hub.connect(meeting_id, websocket)
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
    _api_key: str = Depends(verify_api_key),
):
    """Get the meeting transcript."""
    try:
        mid = UUID(meeting_id)
    except ValueError:
        raise HTTPException(400, "Invalid meeting ID format")

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
    _api_key: str = Depends(verify_api_key),
):
    """Generate a post-meeting summary (background task)."""
    try:
        mid = UUID(meeting_id)
    except ValueError:
        raise HTTPException(400, "Invalid meeting ID format")

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
        }
        for d in (meeting.decisions or [])
    ]

    nudges_data = [
        {
            "type": n.nudge_type,
            "title": n.title,
            "content": n.content,
        }
        for n in (meeting.nudges or [])
    ]

    research_summary = ""
    if meeting.research_brief and meeting.research_brief.executive_summary:
        research_summary = meeting.research_brief.executive_summary

    background_tasks.add_task(
        summary_pipeline.run,
        meeting_id=meeting_id,
        meeting_title=meeting.title,
        description=meeting.description or "",
        transcript_text=transcript_text,
        decisions=decisions_data,
        action_items=[],
        nudges=nudges_data,
        research_summary=research_summary,
    )

    return {"status": "started", "message": "Summary generation started"}


@router.get("/{meeting_id}/summary")
async def get_summary(
    meeting_id: str,
    session: AsyncSession = Depends(get_db),
    _api_key: str = Depends(verify_api_key),
):
    """Get meeting summary."""
    try:
        mid = UUID(meeting_id)
    except ValueError:
        raise HTTPException(400, "Invalid meeting ID format")

    meeting = await meeting_service.get_meeting(session, mid)
    if not meeting:
        raise HTTPException(404, "Meeting not found")

    if not meeting.summary:
        return {"status": "not_generated", "data": None}

    return {
        "status": "completed",
        "data": {
            "summary_text": meeting.summary.summary_text,
            "key_insights": meeting.summary.key_insights,
            "decisions_summary": meeting.summary.decisions_summary,
            "email_sent_at": meeting.summary.email_sent_at.isoformat()
            if meeting.summary.email_sent_at
            else None,
            "created_at": meeting.summary.created_at.isoformat(),
        },
    }


@router.post("/{meeting_id}/send-summary")
async def send_summary_email(
    meeting_id: str,
    session: AsyncSession = Depends(get_db),
    _api_key: str = Depends(verify_api_key),
):
    """Send meeting summary email to attendees."""
    try:
        mid = UUID(meeting_id)
    except ValueError:
        raise HTTPException(400, "Invalid meeting ID format")

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
        "action_items": [],
        "ai_insights_used": meeting.summary.key_insights,
        "follow_up_recommendations": [],
    }

    postmark_id = await email_service.send_summary_email(
        recipients=recipients,
        meeting_title=meeting.title,
        summary=summary_data,
    )

    if postmark_id:
        await meeting_service.mark_email_sent(session, mid, postmark_id)
        return {
            "status": "sent",
            "message": f"Summary emailed to {len(recipients)} recipients",
            "postmark_id": postmark_id,
        }

    raise HTTPException(500, "Failed to send email")
