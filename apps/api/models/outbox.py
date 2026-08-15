"""
Transactional outbox for knowledge-graph writes.

The problem this solves: Postgres and Neo4j were dual-written with no
reconciliation. A summary would commit to Postgres, the Neo4j sync would
throw, the exception was caught and logged as "KG sync skipped", and the
graph fell permanently behind the system of record. Nothing detected the
divergence and nothing replayed it — so the memory agent would quietly stop
recalling decisions that demonstrably existed in Postgres.

The outbox pattern fixes the ordering: the intent to write to Neo4j is
committed **inside the same Postgres transaction** as the data it describes.
Either both land or neither does. A drainer then applies pending rows to
Neo4j with retries and idempotent Cypher (MERGE, not CREATE), so replay is
safe and the graph converges.

Neo4j remains optional (invariant 6): with it disabled or unreachable, rows
simply accumulate as pending and drain when it returns. The queue depth and
the age of the oldest pending row are exposed on ``/health`` so "the graph is
behind" is an observable state rather than a silent one.
"""

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID  # noqa: N811
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.core.database import Base

# Terminal and non-terminal states. 'failed' is terminal only in the sense
# that the automatic drainer stops picking it up — it stays in the table as a
# record of what diverged, because a silently dropped row is the bug this
# whole module exists to prevent.
STATUS_PENDING = "pending"
STATUS_DONE = "done"
STATUS_FAILED = "failed"

MAX_ATTEMPTS = 5


class KGOutbox(Base):
    """One pending knowledge-graph write, committed with its source data."""

    __tablename__ = "kg_outbox"
    __table_args__ = (
        # The drainer's hot query: pending rows, oldest first.
        Index("ix_kg_outbox_status_created", "status", "created_at"),
        {"schema": "doc_intel"},
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    # What kind of write this is — dispatched by the drainer.
    operation: Mapped[str] = mapped_column(String(64), nullable=False)
    # The subject, so a divergence can be traced to a meeting or document.
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(64), nullable=False)
    # Everything the operation needs, so replay never re-reads mutable state
    # and therefore never applies a *different* write than the one intended.
    payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    owner_id: Mapped[Optional[UUID]] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=True
    )

    status: Mapped[str] = mapped_column(
        String(16), default=STATUS_PENDING, nullable=False
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    processed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
