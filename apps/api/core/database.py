# apps/api/core/database.py
"""
MODERNIZED Database Module - SQLAlchemy 2.0 Standards (November 2025)
Key changes: DeclarativeBase, Mapped[], modern async patterns
"""

from typing import AsyncGenerator, Optional
from contextlib import asynccontextmanager
import logging

from sqlalchemy import text, MetaData, event
from sqlalchemy.ext.asyncio import (
    create_async_engine,
    AsyncSession,
    async_sessionmaker,
    AsyncEngine,
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
            "connect_args": {"server_settings": {"application_name": "voice-doc-intelligence"}},
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

# Initialize database
async def init_db():
    """Verify database connectivity and schema.

    Schema evolution is managed by Alembic migrations (see /alembic/).
    Run `alembic upgrade head` to apply pending migrations.
    In development, we still create_all as a convenience fallback.
    """
    try:
        async with engine.begin() as conn:
            await conn.execute(text("CREATE SCHEMA IF NOT EXISTS doc_intel"))
            # In production, rely on Alembic migrations exclusively.
            # create_all is a dev convenience that only creates missing tables.
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Database initialized (run 'alembic upgrade head' for migrations)")
    except Exception as e:
        logger.error(f"Database initialization failed: {e}", exc_info=True)
        raise

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