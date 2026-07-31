"""
ORM models for the Donna meeting lifecycle.

Covers all 3 phases:
- BEFORE: ResearchBrief
- DURING: MeetingTranscript, Nudge, Decision, ActionItem
- AFTER:  MeetingSummary

Plus knowledge graph: EntityRelationship, DocumentElement
"""

from datetime import datetime, timezone
from typing import List, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID  # noqa: N811
from sqlalchemy.orm import Mapped, mapped_column, relationship

from apps.api.core.database import Base


def _validate_optional_uuid(value):
    """Coerce empty string → None; reject malformed UUIDs at parse time.

    Without this, a malformed id reaches ``UUID(...)`` in the router and
    raises ValueError → 500. Validating here returns a clean 422 instead,
    and normalizes the value to a canonical UUID string.
    """
    if value is None or value == "":
        return None
    try:
        return str(UUID(str(value)))
    except (ValueError, AttributeError, TypeError):
        raise ValueError("must be a valid UUID")


# ---------------------------------------------------------------------------
# ORM Models
# ---------------------------------------------------------------------------


class Meeting(Base):
    """Core meeting record linking all 3 phases."""

    __tablename__ = "meetings"
    __table_args__ = {"schema": "doc_intel"}

    id: Mapped[str] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    # Owner for per-user row-level isolation. Nullable so existing/demo
    # meetings (created without auth) remain valid; enforced when
    # REQUIRE_AUTH is on.
    owner_id: Mapped[Optional[str]] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("doc_intel.users.id"),
        nullable=True,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    scheduled_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    ended_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    attendees: Mapped[list] = mapped_column(JSON, default=list)
    meeting_type: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    # Shared canvas layout: {nudge_id: {"x": float, "y": float}}
    canvas_positions: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    # Structured agenda: [{"title": str, "status": "pending|covered"}]
    agenda: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="scheduled")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    research_brief: Mapped[Optional["ResearchBrief"]] = relationship(
        back_populates="meeting", uselist=False, cascade="all, delete-orphan"
    )
    transcript: Mapped[Optional["MeetingTranscript"]] = relationship(
        back_populates="meeting", uselist=False, cascade="all, delete-orphan"
    )
    nudges: Mapped[List["Nudge"]] = relationship(
        back_populates="meeting", cascade="all, delete-orphan", lazy="selectin"
    )
    decisions: Mapped[List["Decision"]] = relationship(
        back_populates="meeting", cascade="all, delete-orphan", lazy="selectin"
    )
    action_items: Mapped[List["ActionItem"]] = relationship(
        back_populates="meeting", cascade="all, delete-orphan", lazy="selectin"
    )
    summary: Mapped[Optional["MeetingSummary"]] = relationship(
        back_populates="meeting", uselist=False, cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Meeting(id={self.id}, title='{self.title}', status='{self.status}')>"


class ResearchBrief(Base):
    """Pre-meeting research output (Phase 1)."""

    __tablename__ = "research_briefs"
    __table_args__ = {"schema": "doc_intel"}

    id: Mapped[str] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    meeting_id: Mapped[str] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("doc_intel.meetings.id"),
        nullable=False,
    )
    topics: Mapped[list] = mapped_column(JSON, default=list)
    executive_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(50), default="pending")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    meeting: Mapped["Meeting"] = relationship(back_populates="research_brief")


class MeetingTranscript(Base):
    """Live transcript from during meeting (Phase 2)."""

    __tablename__ = "meeting_transcripts"
    __table_args__ = {"schema": "doc_intel"}

    id: Mapped[str] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    meeting_id: Mapped[str] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("doc_intel.meetings.id"),
        nullable=False,
    )
    utterances: Mapped[list] = mapped_column(JSON, default=list)
    full_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    meeting: Mapped["Meeting"] = relationship(back_populates="transcript")


class Nudge(Base):
    """Real-time nudge card shown during meeting (Phase 2)."""

    __tablename__ = "nudges"
    __table_args__ = {"schema": "doc_intel"}

    id: Mapped[str] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    meeting_id: Mapped[str] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("doc_intel.meetings.id"),
        nullable=False,
    )
    nudge_type: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source_agent: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    source_data: Mapped[dict] = mapped_column(JSON, default=dict)
    relevance_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    shown_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    dismissed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    pinned_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    meeting: Mapped["Meeting"] = relationship(back_populates="nudges")


class MeetingDocument(Base):
    """Join table: documents attached to a meeting (meeting-scoped knowledge)."""

    __tablename__ = "meeting_documents"
    __table_args__ = {"schema": "doc_intel"}

    meeting_id: Mapped[str] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("doc_intel.meetings.id", ondelete="CASCADE"),
        primary_key=True,
    )
    document_id: Mapped[str] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("doc_intel.documents.id", ondelete="CASCADE"),
        primary_key=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class Decision(Base):
    """Decision captured during meeting (Phase 2)."""

    __tablename__ = "decisions"
    __table_args__ = {"schema": "doc_intel"}

    id: Mapped[str] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    meeting_id: Mapped[str] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("doc_intel.meetings.id"),
        nullable=False,
    )
    decision_text: Mapped[str] = mapped_column(Text, nullable=False)
    context: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    owner: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    deadline: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    status: Mapped[str] = mapped_column(String(50), default="pending")
    source_nudge_id: Mapped[Optional[str]] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("doc_intel.nudges.id"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    meeting: Mapped["Meeting"] = relationship(back_populates="decisions")
    source_nudge: Mapped[Optional["Nudge"]] = relationship()
    action_items: Mapped[List["ActionItem"]] = relationship(
        back_populates="decision", cascade="all, delete-orphan", lazy="selectin"
    )


class ActionItem(Base):
    """Action item derived from a decision."""

    __tablename__ = "action_items"
    __table_args__ = {"schema": "doc_intel"}

    id: Mapped[str] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    meeting_id: Mapped[str] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("doc_intel.meetings.id"),
        nullable=False,
    )
    decision_id: Mapped[Optional[str]] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("doc_intel.decisions.id"),
        nullable=True,
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)
    assignee: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    deadline: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    priority: Mapped[str] = mapped_column(String(20), default="medium")
    status: Mapped[str] = mapped_column(String(50), default="open")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    meeting: Mapped["Meeting"] = relationship(back_populates="action_items")
    decision: Mapped[Optional["Decision"]] = relationship(back_populates="action_items")


class MeetingSummary(Base):
    """Post-meeting summary (Phase 3)."""

    __tablename__ = "meeting_summaries"
    __table_args__ = {"schema": "doc_intel"}

    id: Mapped[str] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    meeting_id: Mapped[str] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("doc_intel.meetings.id"),
        nullable=False,
    )
    summary_text: Mapped[str] = mapped_column(Text, nullable=False)
    key_insights: Mapped[list] = mapped_column(JSON, default=list)
    decisions_summary: Mapped[list] = mapped_column(JSON, default=list)
    email_sent_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    postmark_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    meeting: Mapped["Meeting"] = relationship(back_populates="summary")


# ---------------------------------------------------------------------------
# Knowledge Graph Models
# ---------------------------------------------------------------------------


class EntityRelationship(Base):
    """Edge in the knowledge graph between two entities."""

    __tablename__ = "entity_relationships"
    __table_args__ = {"schema": "doc_intel"}

    id: Mapped[str] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    source_entity_id: Mapped[str] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("doc_intel.entities.id"),
        nullable=False,
    )
    target_entity_id: Mapped[str] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("doc_intel.entities.id"),
        nullable=False,
    )
    relationship_type: Mapped[str] = mapped_column(String(100), nullable=False)
    confidence_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    extraction_method: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    context: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    document_id: Mapped[Optional[str]] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("doc_intel.documents.id"),
        nullable=True,
    )
    meeting_id: Mapped[Optional[str]] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("doc_intel.meetings.id"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class DocumentElement(Base):
    """Extracted element from a document (table, image, chart)."""

    __tablename__ = "document_elements"
    __table_args__ = {"schema": "doc_intel"}

    id: Mapped[str] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    document_id: Mapped[str] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("doc_intel.documents.id"),
        nullable=False,
    )
    chunk_id: Mapped[Optional[str]] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("doc_intel.document_chunks.id"),
        nullable=True,
    )
    element_type: Mapped[str] = mapped_column(String(50), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    raw_data: Mapped[dict] = mapped_column(JSON, default=dict)
    caption: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    page_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    position_index: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    embedding_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


# ---------------------------------------------------------------------------
# Pydantic Schemas (API Request/Response)
# ---------------------------------------------------------------------------


class MeetingCreate(BaseModel):
    """Request to create a meeting."""

    model_config = ConfigDict(str_strip_whitespace=True)

    title: str = Field(..., min_length=1, max_length=500)
    description: Optional[str] = None
    scheduled_at: Optional[datetime] = None
    attendees: list = Field(default_factory=list)
    meeting_type: Optional[str] = Field(default=None, max_length=120)
    agenda: list = Field(default_factory=list)


class MeetingResponse(BaseModel):
    """Meeting response with related data counts."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    description: Optional[str] = None
    scheduled_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    attendees: list = []
    status: str
    created_at: datetime
    nudge_count: int = 0
    decision_count: int = 0
    has_research: bool = False
    has_summary: bool = False


class DecisionCreate(BaseModel):
    """Request to log a decision."""

    model_config = ConfigDict(str_strip_whitespace=True)

    decision_text: str = Field(..., min_length=1)
    context: Optional[str] = None
    owner: Optional[str] = None
    deadline: Optional[datetime] = None
    source_nudge_id: Optional[str] = None

    _validate_nudge_id = field_validator("source_nudge_id")(_validate_optional_uuid)


class ActionItemCreate(BaseModel):
    """Request to log an action item."""

    model_config = ConfigDict(str_strip_whitespace=True)

    description: str = Field(..., min_length=1)
    assignee: Optional[str] = None
    deadline: Optional[datetime] = None
    priority: str = Field(default="medium")
    decision_id: Optional[str] = None

    _validate_decision_id = field_validator("decision_id")(_validate_optional_uuid)
