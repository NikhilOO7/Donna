"""
Customer database connections.

One row per configured read-only connection, owned by a user (tenant). The
password never appears in plaintext here — it is Fernet-encrypted by
``core/crypto.py`` before it reaches the column, so a database backup or a
support engineer with SELECT on this table gets ciphertext.

The schema profile discovered at connect time is cached on the row so the
research pipeline can plan queries without re-introspecting the customer's
database on every meeting.
"""

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID  # noqa: N811
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.core.database import Base

# Only Postgres today: asyncpg is already a dependency and it covers the
# large majority of the target market. The connector is written against a
# driver seam so MySQL is a driver addition, not a redesign.
SUPPORTED_ENGINES = ("postgresql",)

STATUS_UNVERIFIED = "unverified"
STATUS_CONNECTED = "connected"
STATUS_ERROR = "error"


class DataConnection(Base):
    """A read-only connection to a customer's own database."""

    __tablename__ = "data_connections"
    __table_args__ = {"schema": "doc_intel"}

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    # Tenancy: every read is scoped by this, exactly like documents and
    # meetings. A connection is as private as the data it can reach.
    owner_id: Mapped[Optional[UUID]] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("doc_intel.users.id"),
        nullable=True,
        index=True,
    )

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    engine: Mapped[str] = mapped_column(
        String(32), default="postgresql", nullable=False
    )

    host: Mapped[str] = mapped_column(String(255), nullable=False)
    port: Mapped[int] = mapped_column(Integer, default=5432, nullable=False)
    database: Mapped[str] = mapped_column(String(128), nullable=False)
    username: Mapped[str] = mapped_column(String(128), nullable=False)
    # Fernet ciphertext. Never logged, never returned by the API.
    password_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    ssl_mode: Mapped[str] = mapped_column(String(24), default="require", nullable=False)

    # Which tables Donna may read. Empty means "everything discovered".
    # An explicit allowlist is the difference between "connect your database"
    # and "connect the three tables that are relevant to meetings".
    allowed_tables: Mapped[Optional[list]] = mapped_column(JSON, default=list)

    status: Mapped[str] = mapped_column(
        String(24), default=STATUS_UNVERIFIED, nullable=False
    )
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    last_verified_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Cached introspection: {tables: [{schema, name, columns[], row_estimate}]}
    schema_profile: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    last_indexed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    indexed_row_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class DataQueryLog(Base):
    """Audit trail: every statement Donna ran against a customer database.

    Non-negotiable for a feature that reads someone else's production data.
    When a customer asks "what did you run, and when?", the answer has to be a
    query rather than a shrug — and if the SQL generator ever misbehaves, this
    is the only record of what it actually did.
    """

    __tablename__ = "data_query_log"
    __table_args__ = {"schema": "doc_intel"}

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    connection_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("doc_intel.data_connections.id"),
        nullable=False,
        index=True,
    )
    owner_id: Mapped[Optional[UUID]] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=True
    )
    meeting_id: Mapped[Optional[UUID]] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=True
    )
    purpose: Mapped[str] = mapped_column(String(64), nullable=False)
    sql_text: Mapped[str] = mapped_column(Text, nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    succeeded: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
