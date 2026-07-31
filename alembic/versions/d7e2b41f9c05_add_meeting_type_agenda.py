"""Add structured meeting_type + agenda to meetings

Revision ID: d7e2b41f9c05
Revises: c4f8a2d91e63
Create Date: 2026-07-31
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d7e2b41f9c05"
down_revision: Union[str, Sequence[str], None] = "c4f8a2d91e63"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "meetings",
        sa.Column("meeting_type", sa.String(120), nullable=True),
        schema="doc_intel",
    )
    op.add_column(
        "meetings",
        sa.Column("agenda", sa.JSON(), nullable=True),
        schema="doc_intel",
    )


def downgrade() -> None:
    op.drop_column("meetings", "agenda", schema="doc_intel")
    op.drop_column("meetings", "meeting_type", schema="doc_intel")
