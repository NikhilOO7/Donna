"""
Durable background-job queue (Arq over Redis).

The DURING/BEFORE/AFTER pipelines were fire-and-forget FastAPI
BackgroundTasks: exceptions were swallowed, nothing retried, and work in
flight was lost on a crash/restart. This module routes that work through
Arq instead — jobs are persisted in Redis, retried on failure, and
survive process restarts.

``enqueue(name, *args)`` is the single entry point. It returns True if the
job was durably enqueued, False otherwise (Redis down / queue disabled) so
the caller can fall back to in-process execution. Gated by
``settings.use_job_queue`` so dev/demo keeps immediate in-process behavior.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from apps.api.core.config import settings

logger = logging.getLogger(__name__)

_pool = None


def get_redis_settings():
    """Build Arq RedisSettings from the app's Redis config."""
    from arq.connections import RedisSettings

    return RedisSettings(
        host=settings.redis_host,
        port=settings.redis_port,
        password=settings.redis_password or None,
        database=settings.redis_db,
    )


async def _get_pool():
    global _pool
    if _pool is not None:
        return _pool
    try:
        from arq import create_pool

        _pool = await create_pool(get_redis_settings())
        logger.info("Arq job queue pool connected")
    except Exception as e:
        logger.warning(f"Arq pool unavailable: {e}")
        _pool = None
    return _pool


async def enqueue(name: str, *args: Any, **kwargs: Any) -> Optional[str]:
    """Enqueue a durable job. Returns the job id, or None if not enqueued.

    A None return tells the caller to fall back to in-process execution.
    """
    if not settings.use_job_queue:
        return None
    pool = await _get_pool()
    if pool is None:
        return None
    try:
        job = await pool.enqueue_job(name, *args, **kwargs)
        if job is not None:
            logger.info(f"Enqueued job '{name}' (id={job.job_id})")
            return job.job_id
    except Exception as e:
        logger.warning(f"Failed to enqueue job '{name}': {e}")
    return None


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        try:
            await _pool.close()
        except Exception:
            pass
        _pool = None
