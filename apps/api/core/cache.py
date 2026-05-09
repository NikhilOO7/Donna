"""
Redis-backed cache for RAG query results.

Caches query responses by SHA-256 hash of the query string.
TTL-based expiration with cache invalidation on document changes.
"""

import hashlib
import json
import logging
from typing import Optional, Dict, Any

from apps.api.core.connections import get_redis_client
from apps.api.core.metrics import CACHE_HITS, CACHE_MISSES

logger = logging.getLogger(__name__)

CACHE_PREFIX = "rag:query:"
DEFAULT_TTL = 300  # 5 minutes


def _cache_key(query: str, context_level: str = "document") -> str:
    """Generate a deterministic cache key from query + context level."""
    raw = f"{query.strip().lower()}:{context_level}"
    return CACHE_PREFIX + hashlib.sha256(raw.encode()).hexdigest()[:16]


async def get_cached_response(query: str, context_level: str = "document") -> Optional[Dict[str, Any]]:
    """Look up a cached RAG response. Returns None on miss."""
    try:
        redis = await get_redis_client()
        if redis is None:
            return None

        key = _cache_key(query, context_level)
        raw = await redis.get(key)
        if raw is None:
            CACHE_MISSES.labels(cache_name="rag_query").inc()
            return None

        CACHE_HITS.labels(cache_name="rag_query").inc()
        return json.loads(raw)

    except Exception as e:
        logger.debug(f"Cache lookup failed: {e}")
        return None


async def set_cached_response(
    query: str,
    context_level: str,
    response: Dict[str, Any],
    ttl: int = DEFAULT_TTL,
) -> None:
    """Store a RAG response in cache."""
    try:
        redis = await get_redis_client()
        if redis is None:
            return

        key = _cache_key(query, context_level)
        await redis.set(key, json.dumps(response, default=str), ex=ttl)

    except Exception as e:
        logger.debug(f"Cache store failed: {e}")


async def invalidate_document_cache() -> None:
    """Invalidate all RAG query caches (call on document upload/delete)."""
    try:
        redis = await get_redis_client()
        if redis is None:
            return

        # Scan and delete all rag query keys
        cursor = 0
        while True:
            cursor, keys = await redis.scan(cursor, match=f"{CACHE_PREFIX}*", count=100)
            if keys:
                await redis.delete(*keys)
            if cursor == 0:
                break

        logger.info("RAG query cache invalidated")

    except Exception as e:
        logger.debug(f"Cache invalidation failed: {e}")
