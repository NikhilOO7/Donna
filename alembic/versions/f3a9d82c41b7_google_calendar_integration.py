"""google calendar integration: user refresh token + meeting external event id

Revision ID: f3a9d82c41b7
Revises: e9a1c53b7f21
Create Date: 2026-07-31
"""

import sqlalchemy as sa
from alembic import op

revision = "f3a9d82c41b7"
down_revision = "e9a1c53b7f21"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("google_refresh_token", sa.String(512), nullable=True),
        schema="doc_intel",
    )
    op.add_column(
        "meetings",
        sa.Column("external_event_id", sa.String(255), nullable=True),
        schema="doc_intel",
    )
    op.create_index(
        "ix_meetings_external_event_id",
        "meetings",
        ["external_event_id"],
        schema="doc_intel",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_meetings_external_event_id", table_name="meetings", schema="doc_intel"
    )
    op.drop_column("meetings", "external_event_id", schema="doc_intel")
    op.drop_column("users", "google_refresh_token", schema="doc_intel")
