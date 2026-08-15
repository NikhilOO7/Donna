"""
Durable background-job queue (Arq over Redis).

The DURING/BEFORE/AFTER pipelines were fire-and-forget FastAPI
BackgroundTasks: exceptions were swallowed, nothing retried, and work in
flight was lost on a crash/restart. This module routes that work through
Arq instead — jobs are persisted in Redis, retried on failure, and
survive process restarts.

``enqueue(name, *args)`` is the single entry point. It returns the job id if
the job was durably enqueued, None otherwise (Redis down / queue disabled) so
the caller can fall back to in-process execution. Gated by
``settings.use_job_queue`` so dev/demo keeps immediate in-process behavior.

Work is split across **two queues by latency class**. Arq has no priority
or fairness model — a single FIFO queue means a 100-document upload batch
occupies every worker slot with 600-second jobs while the live
``dispatch_job`` for an in-progress meeting waits behind it. That inverts
the whole hot/warm/cold design, so the hot path gets its own queue and its
own worker process:

* ``donna:hot``  — ``dispatch_job`` only. Short jobs, latency-critical.
* ``donna:bulk`` — research, summary, document processing. Slow, tolerant.

Each queue needs a worker consuming it (see ``apps/workers/job_worker.py``:
``DispatchWorkerSettings`` and ``WorkerSettings``). ``queue_depths()`` feeds
``/health`` so a queue nobody is draining is visible rather than silent.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from apps.api.core.config import settings

logger = logging.getLogger(__name__)

# Queue names. Arq keys its pending-job sorted set by exactly this string.
QUEUE_HOT = "donna:hot"
QUEUE_BULK = "donna:bulk"

# Latency class per job. Anything unlisted is treated as bulk: a new job is
# assumed slow until someone deliberately promotes it to the hot path.
_QUEUE_BY_JOB: Dict[str, str] = {
    "dispatch_job": QUEUE_HOT,
    "research_job": QUEUE_BULK,
    "summary_job": QUEUE_BULK,
    "process_document_job": QUEUE_BULK,
}

ALL_QUEUES = (QUEUE_HOT, QUEUE_BULK)

# One pool per queue — Arq binds a default queue name to the pool.
_pools: Dict[str, Any] = {}


def queue_for(job_name: str) -> str:
    """The queue a job belongs to. Unknown jobs default to bulk."""
    return _QUEUE_BY_JOB.get(job_name, QUEUE_BULK)


def get_redis_settings():
    """Build Arq RedisSettings from the app's Redis config."""
    from arq.connections import RedisSettings

    return RedisSettings(
        host=settings.redis_host,
        port=settings.redis_port,
        password=settings.redis_password or None,
        database=settings.redis_db,
    )


async def _get_pool(queue_name: str):
    pool = _pools.get(queue_name)
    if pool is not None:
        return pool
    try:
        from arq import create_pool

        pool = await create_pool(get_redis_settings(), default_queue_name=queue_name)
        _pools[queue_name] = pool
        logger.info(f"Arq job queue pool connected (queue={queue_name})")
    except Exception as e:
        logger.warning(f"Arq pool unavailable for queue '{queue_name}': {e}")
        return None
    return pool


async def enqueue(name: str, *args: Any, **kwargs: Any) -> Optional[str]:
    """Enqueue a durable job onto the queue matching its latency class.

    Returns the job id, or None if not enqueued — a None return tells the
    caller to fall back to in-process execution.
    """
    if not settings.use_job_queue:
        return None
    queue_name = queue_for(name)
    pool = await _get_pool(queue_name)
    if pool is None:
        return None
    try:
        job = await pool.enqueue_job(name, *args, _queue_name=queue_name, **kwargs)
        if job is not None:
            logger.info(f"Enqueued job '{name}' (id={job.job_id}, queue={queue_name})")
            return job.job_id
    except Exception as e:
        logger.warning(f"Failed to enqueue job '{name}' on '{queue_name}': {e}")
    return None


async def queue_depths() -> Dict[str, Optional[int]]:
    """Pending job count per queue, for /health.

    A hot queue with a growing depth means no dispatch worker is consuming
    it — the specific silent failure that splitting the queues introduces.
    None means the depth could not be read (Redis down or queue disabled).
    """
    if not settings.use_job_queue:
        return {q: None for q in ALL_QUEUES}
    out: Dict[str, Optional[int]] = {}
    for q in ALL_QUEUES:
        try:
            from apps.api.core.connections import get_redis_client

            redis = await get_redis_client()
            out[q] = int(await redis.zcard(q))
        except Exception:
            out[q] = None
    return out


async def close_pool() -> None:
    for name, pool in list(_pools.items()):
        try:
            await pool.close()
        except Exception:
            pass
        _pools.pop(name, None)
