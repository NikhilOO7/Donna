"""
ORM models for analytics events and conversation sessions.
Maps to the analytics_events and conversation_sessions tables in doc_intel schema.
"""

from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
from uuid import uuid4

from sqlalchemy import String, Integer, DateTime, JSON, ForeignKey, Text, ARRAY
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.core.database import Base


class AnalyticsEvent(Base):
    """Tracks system usage events (queries, uploads, voice sessions)."""

    __tablename__ = "analytics_events"
    __table_args__ = {"schema": "doc_intel"}

    id: Mapped[str] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    session_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    document_id: Mapped[Optional[str]] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("doc_intel.documents.id"),
        nullable=True,
    )
    event_data: Mapped[dict] = mapped_column(JSON, default=dict)
    latency_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class ConversationSession(Base):
    """Persists conversation history for multi-turn RAG queries."""

    __tablename__ = "conversation_sessions"
    __table_args__ = {"schema": "doc_intel"}

    id: Mapped[str] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    session_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    participant_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    messages: Mapped[list] = mapped_column(JSON, default=list)
    current_documents: Mapped[Optional[list]] = mapped_column(
        ARRAY(PostgreSQLUUID(as_uuid=True)), nullable=True
    )
    action_items: Mapped[list] = mapped_column(JSON, default=list)
    decisions: Mapped[list] = mapped_column(JSON, default=list)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    ended_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_activity: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
