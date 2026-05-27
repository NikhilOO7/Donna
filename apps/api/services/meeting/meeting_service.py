"""
Meeting lifecycle CRUD service.

Manages meetings, decisions, action items, and nudges across all 3 phases.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from apps.api.models.meeting import (
    ActionItem,
    Decision,
    Meeting,
    MeetingTranscript,
    Nudge,
)

logger = logging.getLogger(__name__)


class MeetingService:
    """CRUD operations for the meeting lifecycle."""

    # -- Meetings ----------------------------------------------------------

    async def create_meeting(
        self,
        session: AsyncSession,
        title: str,
        description: Optional[str] = None,
        attendees: Optional[list] = None,
        scheduled_at: Optional[datetime] = None,
        owner_id: Optional[UUID] = None,
    ) -> Meeting:
        try:
            meeting = Meeting(
                title=title,
                description=description,
                attendees=attendees or [],
                scheduled_at=scheduled_at,
                status="scheduled",
                owner_id=owner_id,
            )
            session.add(meeting)
            await session.commit()
            await session.refresh(meeting)
            logger.info(f"Created meeting: {meeting.id} — {title}")
            return meeting
        except Exception as e:
            await session.rollback()
            logger.error(f"Failed to create meeting: {e}")
            raise

    async def get_owner_id(
        self, session: AsyncSession, meeting_id: UUID
    ) -> tuple[bool, Optional[UUID]]:
        """Cheaply fetch (exists, owner_id) without loading the full tree.

        Used by sub-endpoints to enforce row-level isolation without the
        cost of ``get_meeting``'s eager loads (matters on the hot path).
        """
        result = await session.execute(
            select(Meeting.id, Meeting.owner_id).where(
                Meeting.id == meeting_id, Meeting.deleted_at.is_(None)
            )
        )
        row = result.first()
        if row is None:
            return (False, None)
        return (True, row.owner_id)

    async def get_meeting(
        self, session: AsyncSession, meeting_id: UUID
    ) -> Optional[Meeting]:
        try:
            query = (
                select(Meeting)
                .where(Meeting.id == meeting_id, Meeting.deleted_at.is_(None))
                .options(
                    selectinload(Meeting.research_brief),
                    selectinload(Meeting.transcript),
                    selectinload(Meeting.nudges),
                    selectinload(Meeting.decisions).selectinload(Decision.action_items),
                    selectinload(Meeting.action_items),
                    selectinload(Meeting.summary),
                )
            )
            result = await session.execute(query)
            return result.scalar_one_or_none()
        except Exception as e:
            logger.error(f"Failed to get meeting {meeting_id}: {e}")
            return None

    async def list_meetings(
        self,
        session: AsyncSession,
        skip: int = 0,
        limit: int = 50,
        status: Optional[str] = None,
        owner_id: Optional[UUID] = None,
    ) -> List[Meeting]:
        try:
            query = select(Meeting).where(Meeting.deleted_at.is_(None))
            if owner_id is not None:
                query = query.where(Meeting.owner_id == owner_id)
            if status:
                query = query.where(Meeting.status == status)
            query = query.offset(skip).limit(limit).order_by(Meeting.created_at.desc())
            result = await session.execute(query)
            return list(result.scalars().all())
        except Exception as e:
            logger.error(f"Failed to list meetings: {e}")
            return []

    async def update_meeting_status(
        self, session: AsyncSession, meeting_id: UUID, status: str
    ) -> bool:
        try:
            values: Dict[str, Any] = {
                "status": status,
                "updated_at": datetime.now(timezone.utc),
            }
            if status == "in_progress":
                values["started_at"] = datetime.now(timezone.utc)
            elif status in ("completed", "cancelled"):
                values["ended_at"] = datetime.now(timezone.utc)

            await session.execute(
                update(Meeting).where(Meeting.id == meeting_id).values(**values)
            )
            await session.commit()
            logger.info(f"Meeting {meeting_id} → {status}")
            return True
        except Exception as e:
            await session.rollback()
            logger.error(f"Failed to update meeting status: {e}")
            return False

    async def delete_meeting(self, session: AsyncSession, meeting_id: UUID) -> bool:
        try:
            await session.execute(
                update(Meeting)
                .where(Meeting.id == meeting_id)
                .values(deleted_at=datetime.now(timezone.utc))
            )
            await session.commit()
            logger.info(f"Soft-deleted meeting {meeting_id}")
            return True
        except Exception as e:
            await session.rollback()
            logger.error(f"Failed to delete meeting: {e}")
            return False

    # -- Decisions ---------------------------------------------------------

    async def add_decision(
        self,
        session: AsyncSession,
        meeting_id: UUID,
        decision_text: str,
        owner: Optional[str] = None,
        deadline: Optional[datetime] = None,
        context: Optional[str] = None,
        source_nudge_id: Optional[UUID] = None,
    ) -> Decision:
        try:
            decision = Decision(
                meeting_id=meeting_id,
                decision_text=decision_text,
                owner=owner,
                deadline=deadline,
                context=context,
                source_nudge_id=source_nudge_id,
            )
            session.add(decision)
            await session.commit()
            await session.refresh(decision)
            logger.info(f"Decision logged for meeting {meeting_id}")
            return decision
        except Exception as e:
            await session.rollback()
            logger.error(f"Failed to add decision: {e}")
            raise

    # -- Action Items ------------------------------------------------------

    async def add_action_item(
        self,
        session: AsyncSession,
        meeting_id: UUID,
        description: str,
        assignee: Optional[str] = None,
        deadline: Optional[datetime] = None,
        priority: str = "medium",
        decision_id: Optional[UUID] = None,
    ) -> ActionItem:
        try:
            item = ActionItem(
                meeting_id=meeting_id,
                decision_id=decision_id,
                description=description,
                assignee=assignee,
                deadline=deadline,
                priority=priority,
            )
            session.add(item)
            await session.commit()
            await session.refresh(item)
            logger.info(f"Action item added for meeting {meeting_id}")
            return item
        except Exception as e:
            await session.rollback()
            logger.error(f"Failed to add action item: {e}")
            raise

    # -- Nudges ------------------------------------------------------------

    async def add_nudge(
        self,
        session: AsyncSession,
        meeting_id: UUID,
        nudge_type: str,
        title: str,
        content: str,
        source_agent: Optional[str] = None,
        source_data: Optional[dict] = None,
        relevance_score: Optional[float] = None,
    ) -> Nudge:
        try:
            nudge = Nudge(
                meeting_id=meeting_id,
                nudge_type=nudge_type,
                title=title,
                content=content,
                source_agent=source_agent,
                source_data=source_data or {},
                relevance_score=relevance_score,
                shown_at=datetime.now(timezone.utc),
            )
            session.add(nudge)
            await session.commit()
            await session.refresh(nudge)
            logger.info(f"Nudge '{nudge_type}' added for meeting {meeting_id}")
            return nudge
        except Exception as e:
            await session.rollback()
            logger.error(f"Failed to add nudge: {e}")
            raise

    # -- Transcript --------------------------------------------------------

    async def append_utterance(
        self,
        session: AsyncSession,
        meeting_id: UUID,
        speaker: str,
        text: str,
    ) -> MeetingTranscript:
        """Append an utterance to the meeting transcript.

        Creates a MeetingTranscript record if none exists. Updates
        ``utterances`` JSON list and ``full_text``.

        Concurrency: takes a row lock on the parent meeting before the
        read-modify-write so overlapping speakers (manual + voice, or two
        LiveKit participants) can't clobber each other's utterance — the
        classic lost-update race on a JSON list. All appends for a given
        meeting serialize on this lock; utterance volume per meeting is
        low enough that this is the right trade vs. a JSONB migration.
        """
        try:
            # Serialize concurrent appends for this meeting.
            await session.execute(
                select(Meeting.id).where(Meeting.id == meeting_id).with_for_update()
            )

            result = await session.execute(
                select(MeetingTranscript).where(
                    MeetingTranscript.meeting_id == meeting_id
                )
            )
            transcript = result.scalar_one_or_none()

            utterance = {
                "speaker": speaker,
                "text": text,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

            if transcript is None:
                transcript = MeetingTranscript(
                    meeting_id=meeting_id,
                    utterances=[utterance],
                    full_text=f"{speaker}: {text}",
                )
                session.add(transcript)
            else:
                # Re-assign for SQLAlchemy to detect JSON mutation
                new_utterances = list(transcript.utterances or [])
                new_utterances.append(utterance)
                transcript.utterances = new_utterances
                existing = transcript.full_text or ""
                transcript.full_text = (
                    f"{existing}\n{speaker}: {text}"
                    if existing
                    else f"{speaker}: {text}"
                )

            await session.commit()
            await session.refresh(transcript)
            return transcript
        except Exception as e:
            await session.rollback()
            logger.error(f"Failed to append utterance: {e}")
            raise

    async def get_transcript(
        self, session: AsyncSession, meeting_id: UUID
    ) -> Optional[MeetingTranscript]:
        try:
            result = await session.execute(
                select(MeetingTranscript).where(
                    MeetingTranscript.meeting_id == meeting_id
                )
            )
            return result.scalar_one_or_none()
        except Exception as e:
            logger.error(f"Failed to get transcript: {e}")
            return None

    # -- Summary -----------------------------------------------------------

    async def mark_email_sent(
        self, session: AsyncSession, meeting_id: UUID, postmark_id: str
    ) -> bool:
        try:
            from apps.api.models.meeting import MeetingSummary

            result = await session.execute(
                select(MeetingSummary).where(MeetingSummary.meeting_id == meeting_id)
            )
            summary = result.scalar_one_or_none()
            if summary:
                summary.email_sent_at = datetime.now(timezone.utc)
                summary.postmark_id = postmark_id
                await session.commit()
                logger.info(f"Email sent marked for meeting {meeting_id}")
                return True
            return False
        except Exception as e:
            await session.rollback()
            logger.error(f"Failed to mark email sent: {e}")
            return False


meeting_service = MeetingService()
