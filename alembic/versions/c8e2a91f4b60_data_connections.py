"""data_connections + data_query_log: read-only customer database access

Lets a company connect Donna to their own database so meetings have a factual
base even when nobody uploaded a document. Credentials are Fernet-encrypted in
the application layer, so this table holds ciphertext only.

data_query_log is an audit trail: every statement Donna runs against a
customer database, successful or not. Non-negotiable for a feature that reads
someone else's production data.

Revision ID: c8e2a91f4b60
Revises: b4d1f7a2c8e3
Create Date: 2026-08-14
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "c8e2a91f4b60"
down_revision = "b4d1f7a2c8e3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "data_connections",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "owner_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("doc_intel.users.id"),
            nullable=True,
        ),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("engine", sa.String(32), nullable=False, server_default="postgresql"),
        sa.Column("host", sa.String(255), nullable=False),
        sa.Column("port", sa.Integer(), nullable=False, server_default="5432"),
        sa.Column("database", sa.String(128), nullable=False),
        sa.Column("username", sa.String(128), nullable=False),
        # Fernet ciphertext — never plaintext, never logged, never returned.
        sa.Column("password_encrypted", sa.Text(), nullable=False),
        sa.Column("ssl_mode", sa.String(24), nullable=False, server_default="require"),
        sa.Column(
            "allowed_tables",
            postgresql.JSON(astext_type=sa.Text()),
            nullable=True,
            server_default=sa.text("'[]'::json"),
        ),
        sa.Column("status", sa.String(24), nullable=False, server_default="unverified"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "schema_profile", postgresql.JSON(astext_type=sa.Text()), nullable=True
        ),
        sa.Column("last_indexed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "indexed_row_count", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        schema="doc_intel",
    )
    op.create_index(
        "ix_doc_intel_data_connections_owner_id",
        "data_connections",
        ["owner_id"],
        schema="doc_intel",
    )

    op.create_table(
        "data_query_log",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "connection_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("doc_intel.data_connections.id"),
            nullable=False,
        ),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("meeting_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("purpose", sa.String(64), nullable=False),
        sa.Column("sql_text", sa.Text(), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("duration_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "succeeded", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        schema="doc_intel",
    )
    op.create_index(
        "ix_doc_intel_data_query_log_connection_id",
        "data_query_log",
        ["connection_id"],
        schema="doc_intel",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_doc_intel_data_query_log_connection_id",
        table_name="data_query_log",
        schema="doc_intel",
    )
    op.drop_table("data_query_log", schema="doc_intel")
    op.drop_index(
        "ix_doc_intel_data_connections_owner_id",
        table_name="data_connections",
        schema="doc_intel",
    )
    op.drop_table("data_connections", schema="doc_intel")
