"""
Distributed coordination primitives backed by Redis.

Two primitives the meeting hot-path needs to behave correctly across
*multiple* API replicas:

* ``cooldown_passed(key, ttl)`` — atomic "is this action allowed right
  now?" gate (used by fact-check + KG agents so a claim/connection fires
  once across the whole fleet, not once per replica).
* ``distributed_lock(key)`` — best-effort mutual exclusion (used to
  serialize the agent dispatcher per meeting so overlapping utterances
  can't double-emit nudges).

Both degrade gracefully to process-local state when Redis is
unavailable, so single-process dev/demo keeps working unchanged.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from contextlib import asynccontextmanager
from typing import Dict, Optional

from apps.api.core.connections import get_redis_client
from apps.api.core.logging import warn_throttled

logger = logging.getLogger(__name__)

_KEY_PREFIX = "coord:"

# Process-local fallbacks (used only when Redis is unreachable)
_LOCAL_COOLDOWNS: Dict[str, float] = {}
_LOCAL_LOCKS: Dict[str, asyncio.Lock] = {}
_LOCAL_LOCKS_GUARD = asyncio.Lock()

# Compare-and-delete so we only release a lock we still own.
_UNLOCK_LUA = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
else
    return 0
end
"""


async def _redis():
    try:
        return await get_redis_client()
    except Exception:
        return None


async def cooldown_passed(key: str, ttl_seconds: float) -> bool:
    """Return True if ``key`` is not currently in cooldown, atomically
    claiming it for ``ttl_seconds``. Return False if still cooling down.

    Redis path uses ``SET key 1 NX EX ttl`` (atomic across replicas).
    Fallback path uses a process-local dict with opportunistic pruning.
    """
    full = f"{_KEY_PREFIX}cd:{key}"
    r = await _redis()
    if r is not None:
        try:
            ok = await r.set(full, "1", nx=True, ex=max(1, int(round(ttl_seconds))))
            return bool(ok)
        except Exception as e:
            # Process-local cooldowns are per-replica: the same claim can fire
            # once per replica instead of once overall. Operators need to know.
            warn_throttled(
                logger,
                "coord.cooldown.fallback",
                f"[coord] Redis cooldown failed — falling back to process-local "
                f"state. Cooldowns are no longer shared across replicas: {e}",
            )

    now = time.monotonic()
    last = _LOCAL_COOLDOWNS.get(key)
    if last is not None and now - last < ttl_seconds:
        return False
    _LOCAL_COOLDOWNS[key] = now
    if len(_LOCAL_COOLDOWNS) > 5000:
        cutoff = now - 3600
        for k in [k for k, v in _LOCAL_COOLDOWNS.items() if v < cutoff]:
            _LOCAL_COOLDOWNS.pop(k, None)
    return True


@asynccontextmanager
async def distributed_lock(
    key: str,
    ttl_seconds: float = 30.0,
    wait: bool = True,
    wait_timeout: float = 15.0,
):
    """Best-effort distributed lock. Yields True if acquired, else False.

    The caller decides what to do when it can't acquire (skip vs. proceed
    anyway). Redis path: ``SET NX PX`` + Lua compare-and-del release. Falls
    back to a process-local ``asyncio.Lock`` when Redis is down.
    """
    full = f"{_KEY_PREFIX}lock:{key}"
    token = uuid.uuid4().hex
    r = await _redis()
    acquired = False
    redis_held = False
    local_lock: Optional[asyncio.Lock] = None

    if r is not None:
        deadline = time.monotonic() + (wait_timeout if wait else 0.0)
        while True:
            try:
                ok = await r.set(full, token, nx=True, px=int(ttl_seconds * 1000))
            except Exception as e:
                # The serious one: a process-local lock serializes dispatch
                # only within this replica, so N replicas can run the same
                # meeting's cycle concurrently and double-emit nudges.
                warn_throttled(
                    logger,
                    "coord.lock.fallback",
                    f"[coord] Redis lock error — falling back to a process-local "
                    f"lock. Mutual exclusion no longer holds ACROSS replicas; "
                    f"expect duplicate work if more than one replica is running: {e}",
                )
                r = None
                break
            if ok:
                acquired = True
                redis_held = True
                break
            if not wait or time.monotonic() >= deadline:
                break
            await asyncio.sleep(0.05)

    if r is None:
        async with _LOCAL_LOCKS_GUARD:
            local_lock = _LOCAL_LOCKS.setdefault(key, asyncio.Lock())
        if wait:
            try:
                await asyncio.wait_for(local_lock.acquire(), timeout=wait_timeout)
                acquired = True
            except asyncio.TimeoutError:
                acquired = False
        elif local_lock.locked():
            acquired = False
        else:
            await local_lock.acquire()
            acquired = True

    try:
        yield acquired
    finally:
        if redis_held and r is not None:
            try:
                await r.eval(_UNLOCK_LUA, 1, full, token)
            except Exception:
                pass
        elif local_lock is not None and acquired and local_lock.locked():
            local_lock.release()
