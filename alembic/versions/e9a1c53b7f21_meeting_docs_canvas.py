"""Meeting-scoped documents + shared canvas positions

Revision ID: e9a1c53b7f21
Revises: d7e2b41f9c05
Create Date: 2026-07-31
"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e9a1c53b7f21"
down_revision: Union[str, Sequence[str], None] = "d7e2b41f9c05"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "meeting_documents",
        sa.Column("meeting_id", UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["meeting_id"], ["doc_intel.meetings.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["document_id"], ["doc_intel.documents.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("meeting_id", "document_id"),
        schema="doc_intel",
    )
    # Shared canvas: {nudge_id: {"x": float, "y": float}}
    op.add_column(
        "meetings",
        sa.Column("canvas_positions", sa.JSON(), nullable=True),
        schema="doc_intel",
    )


def downgrade() -> None:
    op.drop_column("meetings", "canvas_positions", schema="doc_intel")
    op.drop_table("meeting_documents", schema="doc_intel")
