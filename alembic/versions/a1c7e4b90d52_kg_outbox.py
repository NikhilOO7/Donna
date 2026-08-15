"""kg_outbox: transactional outbox for Neo4j writes

Postgres and Neo4j were dual-written with no reconciliation: a failed sync
was caught, logged as "KG sync skipped", and the graph fell permanently
behind the system of record with nothing detecting or replaying it. This
table makes the intent to sync commit atomically with the data it describes.

Revision ID: a1c7e4b90d52
Revises: f3a9d82c41b7
Create Date: 2026-08-13
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "a1c7e4b90d52"
down_revision = "f3a9d82c41b7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "kg_outbox",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("operation", sa.String(64), nullable=False),
        sa.Column("entity_type", sa.String(32), nullable=False),
        sa.Column("entity_id", sa.String(64), nullable=False),
        sa.Column(
            "payload",
            postgresql.JSON(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::json"),
        ),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "status", sa.String(16), nullable=False, server_default="pending"
        ),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        schema="doc_intel",
    )
    # The drainer's hot query: pending rows, oldest first.
    op.create_index(
        "ix_kg_outbox_status_created",
        "kg_outbox",
        ["status", "created_at"],
        schema="doc_intel",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_kg_outbox_status_created", table_name="kg_outbox", schema="doc_intel"
    )
    op.drop_table("kg_outbox", schema="doc_intel")
