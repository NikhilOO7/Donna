"""Align external_event_id index with the metadata naming convention

Pre-existing drift, unrelated to the outbox: migration f3a9d82c41b7 created
the index as ``ix_meetings_external_event_id``, but ``Base.metadata`` declares
``"ix": "ix_%(column_0_label)s"`` and the table is schema-qualified, so
SQLAlchemy expects ``ix_doc_intel_meetings_external_event_id``.

The consequence was not cosmetic: ``alembic check`` reported a permanent
"remove_index / add_index" diff, so the CI drift gate could never pass. A gate
that is always red is a gate nobody reads — and the whole point of that step is
to catch a model change shipped without a migration.

Renamed rather than dropped-and-recreated: a rename is a catalog operation, so
the index stays available and the table is never left unindexed.

Revision ID: b4d1f7a2c8e3
Revises: a1c7e4b90d52
Create Date: 2026-08-13
"""

from alembic import op

revision = "b4d1f7a2c8e3"
down_revision = "a1c7e4b90d52"
branch_labels = None
depends_on = None

_OLD = "ix_meetings_external_event_id"
_NEW = "ix_doc_intel_meetings_external_event_id"


def upgrade() -> None:
    # IF EXISTS: databases created after the naming convention was applied may
    # already carry the correct name, and this must be a no-op there.
    op.execute(f"ALTER INDEX IF EXISTS doc_intel.{_OLD} RENAME TO {_NEW}")


def downgrade() -> None:
    op.execute(f"ALTER INDEX IF EXISTS doc_intel.{_NEW} RENAME TO {_OLD}")
