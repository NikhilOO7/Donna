"""
Meeting lifecycle CRUD service.

Manages meetings, decisions, action items, and nudges across all 3 phases.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import cast, func, literal, or_, select, update
from sqlalchemy.dialects.postgresql import JSONB, JSONPATH
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

    @staticmethod
    def parse_transcript_text(text: str) -> List[Dict[str, str]]:
        """Parse a pasted/uploaded transcript into speaker-attributed utterances.

        Handles the common shapes:
        - "Name: what they said"
        - "[00:12:34] Name: what they said" / "(12:34) Name: ..."
        - WebVTT / SRT (headers, cue numbers, and timestamp lines stripped)
        - bare lines (appended to the previous speaker's utterance)
        """
        import re

        ts_line = re.compile(
            r"^\s*(\d+\s*$|WEBVTT|\d{1,2}:\d{2}(:\d{2})?[.,]?\d*\s*-->\s*.*)",
            re.IGNORECASE,
        )
        leading_ts = re.compile(r"^\s*[\[(]?\d{1,2}:\d{2}(:\d{2})?[\])]?\s*")
        speaker_line = re.compile(r"^([A-Za-z][\w .'\-]{0,60}?)\s*:\s+(.+)$")

        utterances: List[Dict[str, str]] = []
        for raw in (text or "").splitlines():
            line = raw.strip()
            if not line or ts_line.match(line):
                continue
            line = leading_ts.sub("", line).strip()
            if not line:
                continue

            m = speaker_line.match(line)
            if m:
                utterances.append(
                    {"speaker": m.group(1).strip(), "text": m.group(2).strip()}
                )
            elif utterances:
                # Continuation of the previous utterance
                utterances[-1]["text"] += " " + line
            else:
                utterances.append({"speaker": "Speaker", "text": line})

        return [u for u in utterances if u["text"]]

    @staticmethod
    def normalize_attendees(attendees: Optional[list]) -> list:
        """Lowercase attendee emails so invited-member lookups match reliably."""
        out = []
        for a in attendees or []:
            if not isinstance(a, dict):
                continue
            entry = dict(a)
            if entry.get("email"):
                entry["email"] = str(entry["email"]).strip().lower()
            out.append(entry)
        return out

    async def create_meeting(
        self,
        session: AsyncSession,
        title: str,
        description: Optional[str] = None,
        attendees: Optional[list] = None,
        scheduled_at: Optional[datetime] = None,
        owner_id: Optional[UUID] = None,
        meeting_type: Optional[str] = None,
        agenda: Optional[list] = None,
    ) -> Meeting:
        try:
            agenda_items = [
                {
                    "title": str(a.get("title") if isinstance(a, dict) else a)[:300],
                    "status": "pending",
                }
                for a in (agenda or [])
                if str(a.get("title") if isinstance(a, dict) else a).strip()
            ][:12]
            meeting = Meeting(
                title=title,
                description=description,
                attendees=self.normalize_attendees(attendees),
                scheduled_at=scheduled_at,
                status="scheduled",
                owner_id=owner_id,
                meeting_type=(meeting_type or None),
                agenda=agenda_items,
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

    async def get_access_row(
        self, session: AsyncSession, meeting_id: UUID
    ) -> tuple[bool, Optional[UUID], list]:
        """Cheaply fetch (exists, owner_id, attendees) for access decisions."""
        result = await session.execute(
            select(Meeting.id, Meeting.owner_id, Meeting.attendees).where(
                Meeting.id == meeting_id, Meeting.deleted_at.is_(None)
            )
        )
        row = result.first()
        if row is None:
            return (False, None, [])
        return (True, row.owner_id, row.attendees or [])

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

    async def get_dispatch_state(
        self, session: AsyncSession, meeting_id: UUID
    ) -> Optional[Dict[str, Any]]:
        """Slim state for the agent dispatcher's hot path.

        Loads ONLY what the meeting agents need — transcript utterances,
        research topics, owner, attendees, attached document ids — via
        targeted selects instead of ``get_meeting``'s full eager tree
        (nudges, decisions, action items, summary). On a long meeting the
        difference is dozens of rows per utterance.
        """
        try:
            from apps.api.models.meeting import MeetingDocument, ResearchBrief

            row = (
                await session.execute(
                    select(
                        Meeting.owner_id,
                        Meeting.attendees,
                        Meeting.agenda,
                        Meeting.started_at,
                    ).where(Meeting.id == meeting_id, Meeting.deleted_at.is_(None))
                )
            ).first()
            if row is None:
                return None

            decision_count = (
                await session.execute(
                    select(func.count())
                    .select_from(Decision)
                    .where(Decision.meeting_id == meeting_id)
                )
            ).scalar_one()

            # Only the recent window leaves Postgres — agents look at the
            # last few utterances, and shipping a 2-hour meeting's full
            # JSON array on every dispatch cycle scales with meeting
            # length. Lax jsonpath handles arrays shorter than the window.
            t_row = (
                await session.execute(
                    select(
                        func.jsonb_path_query_array(
                            cast(MeetingTranscript.utterances, JSONB),
                            cast(literal("$[last-11 to last]"), JSONPATH),
                        ),
                        func.jsonb_array_length(
                            cast(MeetingTranscript.utterances, JSONB)
                        ),
                    ).where(MeetingTranscript.meeting_id == meeting_id)
                )
            ).first()
            transcript = t_row[0] if t_row else None
            utterance_count = int(t_row[1] or 0) if t_row else 0

            # Newest-first + first(), not scalar_one_or_none(): meetings
            # researched before the pipeline reused a single row can have
            # several completed briefs, and scalar_one_or_none() raises on
            # more than one rather than picking the current answer.
            topics = (
                (
                    await session.execute(
                        select(ResearchBrief.topics)
                        .where(
                            ResearchBrief.meeting_id == meeting_id,
                            ResearchBrief.status == "completed",
                        )
                        .order_by(ResearchBrief.created_at.desc())
                    )
                )
                .scalars()
                .first()
            )

            doc_rows = await session.execute(
                select(MeetingDocument.document_id).where(
                    MeetingDocument.meeting_id == meeting_id
                )
            )

            attendees = row.attendees if isinstance(row.attendees, list) else []
            return {
                "owner_id": str(row.owner_id) if row.owner_id else None,
                "attendees": attendees,
                "agenda": row.agenda if isinstance(row.agenda, list) else [],
                "started_at": row.started_at,
                "decision_count": int(decision_count or 0),
                "utterances": list(transcript or []),
                "utterance_count": utterance_count,
                "research_topics": list(topics or []),
                "attached_doc_ids": {str(r[0]) for r in doc_rows.all()},
            }
        except Exception as e:
            logger.error(f"Failed to load dispatch state: {e}")
            return None

    async def list_meetings(
        self,
        session: AsyncSession,
        skip: int = 0,
        limit: int = 50,
        status: Optional[str] = None,
        owner_id: Optional[UUID] = None,
        member_email: Optional[str] = None,
    ) -> List[Meeting]:
        """List meetings the user owns — plus, when ``member_email`` is given,
        meetings they were invited to (email present in attendees)."""
        try:
            query = select(Meeting).where(Meeting.deleted_at.is_(None))
            if owner_id is not None:
                conds = [Meeting.owner_id == owner_id]
                if member_email:
                    conds.append(
                        cast(Meeting.attendees, JSONB).contains(
                            [{"email": member_email.lower()}]
                        )
                    )
                query = query.where(or_(*conds))
            if status:
                query = query.where(Meeting.status == status)
            query = query.offset(skip).limit(limit).order_by(Meeting.created_at.desc())
            result = await session.execute(query)
            return list(result.scalars().all())
        except Exception as e:
            logger.error(f"Failed to list meetings: {e}")
            return []

    async def update_attendees(
        self, session: AsyncSession, meeting_id: UUID, attendees: List[Dict[str, Any]]
    ) -> bool:
        """Replace the meeting's attendee list (voice-setup registration)."""
        try:
            await session.execute(
                update(Meeting)
                .where(Meeting.id == meeting_id)
                .values(attendees=attendees, updated_at=datetime.now(timezone.utc))
            )
            await session.commit()
            logger.info(
                f"Meeting {meeting_id} attendees updated ({len(attendees)} entries)"
            )
            return True
        except Exception as e:
            await session.rollback()
            logger.error(f"Failed to update attendees: {e}")
            return False

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

    async def set_decision_status(
        self, session: AsyncSession, meeting_id: UUID, decision_id: UUID, status: str
    ) -> bool:
        """Move a decision through its lifecycle (pending → in_progress → done)."""
        try:
            result = await session.execute(
                update(Decision)
                .where(Decision.id == decision_id, Decision.meeting_id == meeting_id)
                .values(status=status)
            )
            await session.commit()
            return bool(result.rowcount)
        except Exception as e:
            await session.rollback()
            logger.error(f"Failed to update decision status: {e}")
            raise

    async def set_action_item_status(
        self, session: AsyncSession, meeting_id: UUID, item_id: UUID, status: str
    ) -> bool:
        """Move an action item through its lifecycle (open → in_progress → done)."""
        try:
            result = await session.execute(
                update(ActionItem)
                .where(ActionItem.id == item_id, ActionItem.meeting_id == meeting_id)
                .values(status=status)
            )
            await session.commit()
            return bool(result.rowcount)
        except Exception as e:
            await session.rollback()
            logger.error(f"Failed to update action item status: {e}")
            raise

    async def list_open_action_items(
        self, session: AsyncSession, owner_id: Optional[UUID], limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Cross-meeting open items — the dashboard's "what's still owed" view."""
        try:
            query = (
                select(ActionItem, Meeting.title)
                .join(Meeting, Meeting.id == ActionItem.meeting_id)
                .where(ActionItem.status != "done", Meeting.deleted_at.is_(None))
                .order_by(
                    ActionItem.deadline.asc().nulls_last(),
                    ActionItem.created_at.desc(),
                )
                .limit(limit)
            )
            if owner_id:
                query = query.where(Meeting.owner_id == owner_id)
            rows = (await session.execute(query)).all()
            return [
                {
                    "id": str(item.id),
                    "meeting_id": str(item.meeting_id),
                    "meeting_title": title,
                    "description": item.description,
                    "assignee": item.assignee,
                    "deadline": item.deadline.isoformat() if item.deadline else None,
                    "priority": item.priority,
                    "status": item.status,
                }
                for item, title in rows
            ]
        except Exception as e:
            logger.error(f"Failed to list open action items: {e}")
            return []

    # -- Nudges ------------------------------------------------------------

    @staticmethod
    def _nudge_fingerprint(
        nudge_type: str, content: str, dedupe_key: Optional[str] = None
    ) -> str:
        """Identity of a nudge, for suppressing repeats.

        Retrieval agents re-run every dispatch cycle, and a document chunk
        relevant to the last utterance is usually still relevant to the next.
        Scores drift between runs, so identity is the type plus the normalized
        text — never the score.

        ``dedupe_key`` exists because that is not always the right identity.
        An LLM-generated answer is worded differently each time it is produced,
        so two answers to the *same question* hash differently and both survive
        — the user asks once and Donna replies twice, slightly differently,
        which is worse than either reply alone. Agents that know their own
        stable identity (the reply agent knows it is the question) pass it here.
        """
        import hashlib
        import re

        basis = dedupe_key if dedupe_key else content
        normalized = re.sub(r"\s+", " ", (basis or "").strip().lower())
        return hashlib.sha256(f"{nudge_type}|{normalized}".encode()).hexdigest()[:32]

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
        dedupe_window_s: int = 900,
    ) -> Optional[Nudge]:
        """Persist a nudge, or return None if it repeats a recent one.

        Without this, a finding that stays relevant is re-inserted every cycle:
        one real insight became nine cards saying the same thing at 58–80%
        confidence. The panel then buries the second genuine finding under
        repeats of the first, which is worse than showing nothing — the user
        stops reading it.

        Deliberately scoped per meeting and windowed rather than permanent: if
        a risk resurfaces half an hour later in a different part of the
        conversation, that IS worth raising again.
        """
        try:
            fingerprint = self._nudge_fingerprint(
                nudge_type, content, (source_data or {}).get("dedupe_key")
            )
            cutoff = datetime.now(timezone.utc) - timedelta(seconds=dedupe_window_s)
            existing = (
                await session.execute(
                    select(Nudge.id).where(
                        Nudge.meeting_id == meeting_id,
                        Nudge.nudge_type == nudge_type,
                        Nudge.created_at >= cutoff,
                        cast(Nudge.source_data, JSONB)["fingerprint"].astext
                        == fingerprint,
                    )
                )
            ).first()
            if existing is not None:
                logger.debug(
                    f"Nudge '{nudge_type}' suppressed as duplicate for {meeting_id}"
                )
                return None

            source_data = dict(source_data or {})
            source_data["fingerprint"] = fingerprint

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

    async def set_nudge_feedback(
        self,
        session: AsyncSession,
        meeting_id: UUID,
        nudge_id: UUID,
        *,
        dismissed: Optional[bool] = None,
        pinned: Optional[bool] = None,
    ) -> Optional[Nudge]:
        """Set/clear dismissed_at or pinned_at on a nudge.

        Scoped by meeting_id so a nudge can only be modified through its
        own (owner-checked) meeting.
        """
        try:
            result = await session.execute(
                select(Nudge).where(
                    Nudge.id == nudge_id, Nudge.meeting_id == meeting_id
                )
            )
            nudge = result.scalar_one_or_none()
            if nudge is None:
                return None

            now = datetime.now(timezone.utc)
            if dismissed is not None:
                nudge.dismissed_at = now if dismissed else None
            if pinned is not None:
                nudge.pinned_at = now if pinned else None

            await session.commit()
            await session.refresh(nudge)
            return nudge
        except Exception as e:
            await session.rollback()
            logger.error(f"Failed to set nudge feedback: {e}")
            raise

    # -- Transcript --------------------------------------------------------

    async def set_transcript(
        self,
        session: AsyncSession,
        meeting_id: UUID,
        utterances: List[Dict[str, str]],
    ) -> MeetingTranscript:
        """Create the meeting's transcript wholesale (transcript import)."""
        try:
            full_text = "\n".join(
                f"{u.get('speaker', 'Speaker')}: {u.get('text', '')}"
                for u in utterances
            )
            transcript = MeetingTranscript(
                meeting_id=meeting_id,
                utterances=utterances,
                full_text=full_text,
            )
            session.add(transcript)
            await session.commit()
            await session.refresh(transcript)
            logger.info(
                f"Imported transcript for meeting {meeting_id} "
                f"({len(utterances)} utterances)"
            )
            return transcript
        except Exception as e:
            await session.rollback()
            logger.error(f"Failed to import transcript: {e}")
            raise

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
