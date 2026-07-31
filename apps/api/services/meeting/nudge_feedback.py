"""
Nudge feedback learning (v1 heuristic).

Records the leader's pin/dismiss behavior per nudge type and mutes nudge
types the leader has consistently rejected. Redis-backed; every operation
degrades to a no-op when Redis is unavailable, so learning can never break
the dispatch path.

Rule: a nudge type is suppressed for an owner once it has been dismissed
at least ``SUPPRESS_AFTER`` times with zero pins. A single pin un-mutes it.
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)

SUPPRESS_AFTER = 8


def _key(owner_key: str, nudge_type: str, action: str) -> str:
    return f"nudgefb:{owner_key}:{nudge_type}:{action}"


def _owner_key(owner_id: Optional[str]) -> str:
    return str(owner_id) if owner_id else "global"


async def record(owner_id: Optional[str], nudge_type: str, action: str) -> None:
    """Record a pin/dismiss. ``action`` ∈ {'pinned', 'dismissed'}."""
    try:
        from apps.api.core.connections import get_redis_client

        redis = await get_redis_client()
        await redis.incr(_key(_owner_key(owner_id), nudge_type, action))
    except Exception:
        pass  # learning is best-effort


async def should_suppress(owner_id: Optional[str], nudge_type: str) -> bool:
    """True when this owner has learned-muted this nudge type."""
    try:
        from apps.api.core.connections import get_redis_client

        redis = await get_redis_client()
        ok = _owner_key(owner_id)
        dismissed = int(await redis.get(_key(ok, nudge_type, "dismissed")) or 0)
        if dismissed < SUPPRESS_AFTER:
            return False
        pinned = int(await redis.get(_key(ok, nudge_type, "pinned")) or 0)
        if pinned == 0:
            logger.info(
                f"[NudgeFeedback] suppressing '{nudge_type}' for {ok} "
                f"(dismissed={dismissed}, pinned=0)"
            )
            return True
        return False
    except Exception:
        return False
