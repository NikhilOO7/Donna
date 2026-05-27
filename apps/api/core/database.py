# apps/api/core/database.py
"""
MODERNIZED Database Module - SQLAlchemy 2.0 Standards (November 2025)
Key changes: DeclarativeBase, Mapped[], modern async patterns
"""

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional

from sqlalchemy import MetaData, event, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

from .config import settings

logger = logging.getLogger(__name__)

# SQLAlchemy 2.0 metadata with naming convention
metadata = MetaData(
    naming_convention={
        "ix": "ix_%(column_0_label)s",
        "uq": "uq_%(table_name)s_%(column_0_name)s",
        "ck": "ck_%(table_name)s_%(constraint_name)s",
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        "pk": "pk_%(table_name)s",
    }
)


# Modern SQLAlchemy 2.0 Base class (NOT declarative_base())
class Base(DeclarativeBase):
    """SQLAlchemy 2.0 declarative base - use Mapped[] and mapped_column()"""

    metadata = metadata
    __allow_unmapped__ = False  # Enforce type safety


# Global engine instance
engine: Optional[AsyncEngine] = None


def create_engine_instance() -> AsyncEngine:
    """Create modern async engine with SQLAlchemy 2.0 best practices"""
    global engine
    if engine is None:
        # For async engines, don't specify poolclass (uses AsyncAdaptedQueuePool by default)
        # Only use NullPool in production if needed
        engine_kwargs = {
            "echo": settings.debug,
            "pool_pre_ping": True,
            "pool_size": 10 if not settings.is_production else 20,
            "max_overflow": 20 if not settings.is_production else 40,
            "pool_recycle": 3600,
            "connect_args": {
                "server_settings": {"application_name": "voice-doc-intelligence"}
            },
        }

        # Only add NullPool in production if explicitly needed
        if settings.is_production:
            engine_kwargs["poolclass"] = NullPool

        engine = create_async_engine(settings.postgres_url, **engine_kwargs)

        @event.listens_for(engine.sync_engine, "connect")
        def receive_connect(dbapi_conn, connection_record):
            logger.debug("Database connection established")

        logger.info("✅ Async database engine created (SQLAlchemy 2.0)")
    return engine


# Create session factory
engine = create_engine_instance()
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)


# Dependency for FastAPI
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency for database sessions (SQLAlchemy 2.0 pattern)"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception as e:
            await session.rollback()
            logger.error(f"Database session error: {e}", exc_info=True)
            raise
        finally:
            await session.close()


# Context manager for manual usage
@asynccontextmanager
async def get_db_context() -> AsyncGenerator[AsyncSession, None]:
    """Context manager for database sessions outside of FastAPI"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


def _alembic_upgrade_head_sync() -> None:
    """Run `alembic upgrade head` programmatically (sync; call in a thread)."""
    from pathlib import Path

    from alembic.config import Config

    from alembic import command

    # database.py → apps/api/core/database.py; repo root is parents[3]
    repo_root = Path(__file__).resolve().parents[3]
    cfg = Config(str(repo_root / "alembic.ini"))
    cfg.set_main_option("script_location", str(repo_root / "alembic"))
    command.upgrade(cfg, "head")


# Initialize database
async def init_db():
    """Verify database connectivity. The schema is owned exclusively by
    Alembic migrations — no implicit ``create_all`` (which silently drifts
    from migration history and races across replicas).

    Apply migrations with ``alembic upgrade head`` as a pre-deploy job, or
    set ``RUN_MIGRATIONS_ON_STARTUP=true`` for local/dev convenience.
    """
    try:
        # Connectivity check only.
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        logger.info("Database connectivity verified")
    except Exception as e:
        logger.error(f"Database connectivity check failed: {e}", exc_info=True)
        raise

    if settings.run_migrations_on_startup:
        try:
            import asyncio

            await asyncio.to_thread(_alembic_upgrade_head_sync)
            logger.info("Migrations applied (alembic upgrade head)")
        except Exception as e:
            logger.error(f"Auto-migration failed: {e}", exc_info=True)
            raise
    else:
        logger.info(
            "Schema managed by Alembic — run 'alembic upgrade head' "
            "(or set RUN_MIGRATIONS_ON_STARTUP=true)"
        )


# Cleanup
async def close_db() -> None:
    """Gracefully close database connections"""
    global engine
    if engine is not None:
        await engine.dispose()
        logger.info("✅ Database connections closed")


# Health check
async def check_db_health() -> bool:
    """Check database health"""
    try:
        async with get_db_context() as session:
            await session.execute(text("SELECT 1"))
        return True
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        return False
