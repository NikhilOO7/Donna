"""
Alembic environment configuration for async SQLAlchemy.

Uses the application's database URL from config and the ORM Base
to auto-detect schema changes.
"""

import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# Import application models so Alembic can detect them
from apps.api.core.config import settings
from apps.api.core.database import Base
from apps.api.models.analytics import AnalyticsEvent, ConversationSession  # noqa: F401

# Import all models to register them with Base.metadata
from apps.api.models.document import (  # noqa: F401
    ContextualEmbedding,
    Document,
    DocumentChunk,
    Entity,
)
from apps.api.models.meeting import (  # noqa: F401
    ActionItem,
    Decision,
    DocumentElement,
    EntityRelationship,
    Meeting,
    MeetingSummary,
    MeetingTranscript,
    Nudge,
    ResearchBrief,
)
from apps.api.models.user import User  # noqa: F401

config = context.config

# Set the database URL from application config
config.set_main_option("sqlalchemy.url", settings.database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# All application tables live in the `doc_intel` schema. Alembic's
# autogenerate/compare defaults to the search-path (public) schema only,
# so without these it can't "see" existing doc_intel tables and reports
# false drift. We enable schema reflection and restrict comparison to
# our own schema (+ the alembic_version bookkeeping table).
TARGET_SCHEMA = "doc_intel"


def _include_name(name, type_, parent_names):
    """Restrict autogenerate to the doc_intel schema so reflected system
    schemas (public, information_schema, …) don't produce spurious diffs."""
    if type_ == "schema":
        return name == TARGET_SCHEMA
    return True


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (generate SQL without connecting)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_schemas=True,
        include_name=_include_name,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_schemas=True,
        include_name=_include_name,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run migrations in 'online' mode with async engine."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
