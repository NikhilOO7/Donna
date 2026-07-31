"""Add dismissed_at / pinned_at to nudges (feedback capture)

Revision ID: c4f8a2d91e63
Revises: dffb6e8d861f
Create Date: 2026-07-30
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c4f8a2d91e63"
down_revision: Union[str, Sequence[str], None] = "dffb6e8d861f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "nudges",
        sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True),
        schema="doc_intel",
    )
    op.add_column(
        "nudges",
        sa.Column("pinned_at", sa.DateTime(timezone=True), nullable=True),
        schema="doc_intel",
    )


def downgrade() -> None:
    op.drop_column("nudges", "pinned_at", schema="doc_intel")
    op.drop_column("nudges", "dismissed_at", schema="doc_intel")
