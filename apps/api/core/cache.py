"""
Redis-backed cache for RAG query results.

Caches query responses by SHA-256 hash of the query string.
TTL-based expiration with cache invalidation on document changes.
"""

import base64
import hashlib
import json
import logging
import struct
from typing import Any, Dict, Optional

from apps.api.core.connections import get_redis_client
from apps.api.core.logging import warn_throttled
from apps.api.core.metrics import CACHE_HITS, CACHE_MISSES

logger = logging.getLogger(__name__)

CACHE_PREFIX = "rag:query:"
DEFAULT_TTL = 300  # 5 minutes

EMBED_PREFIX = "emb:q:"
# Embeddings are deterministic for a given model + text, so they can live
# far longer than RAG responses (which go stale when documents change).
EMBED_TTL = 60 * 60 * 24


def _cache_key(
    query: str, context_level: str = "document", owner_id: Optional[str] = None
) -> str:
    """Generate a deterministic cache key from owner + query + context level.

    ``owner_id`` MUST be part of the key: retrieval is tenant-scoped, so
    the same query returns different answers for different owners.
    """
    raw = f"{owner_id or 'global'}:{query.strip().lower()}:{context_level}"
    return CACHE_PREFIX + hashlib.sha256(raw.encode()).hexdigest()[:16]


async def get_cached_response(
    query: str, context_level: str = "document", owner_id: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """Look up a cached RAG response. Returns None on miss."""
    try:
        redis = await get_redis_client()
        if redis is None:
            return None

        key = _cache_key(query, context_level, owner_id)
        raw = await redis.get(key)
        if raw is None:
            CACHE_MISSES.labels(cache_name="rag_query").inc()
            return None

        CACHE_HITS.labels(cache_name="rag_query").inc()
        return json.loads(raw)

    except Exception as e:
        warn_throttled(
            logger,
            "cache.rag.get",
            f"RAG response cache unavailable — serving uncached (full cost per "
            f"query) until Redis recovers: {e}",
        )
        return None


async def set_cached_response(
    query: str,
    context_level: str,
    response: Dict[str, Any],
    ttl: int = DEFAULT_TTL,
    owner_id: Optional[str] = None,
) -> None:
    """Store a RAG response in cache."""
    try:
        redis = await get_redis_client()
        if redis is None:
            return

        key = _cache_key(query, context_level, owner_id)
        await redis.set(key, json.dumps(response, default=str), ex=ttl)

    except Exception as e:
        warn_throttled(logger, "cache.rag.set", f"RAG response cache write failed: {e}")


def _embed_key(text: str, model: str) -> str:
    raw = f"{model}:{text}"
    return EMBED_PREFIX + hashlib.sha256(raw.encode()).hexdigest()[:24]


def _pack_vector(vector: list) -> str:
    """float32 + base64: ~4x smaller than a JSON float list, and Redis is
    configured with decode_responses=True so values must stay text."""
    return base64.b64encode(struct.pack(f"<{len(vector)}f", *vector)).decode("ascii")


def _unpack_vector(raw: str) -> list:
    if raw.startswith("["):  # legacy JSON entry from before packing
        return json.loads(raw)
    buf = base64.b64decode(raw)
    return list(struct.unpack(f"<{len(buf) // 4}f", buf))


async def get_cached_embedding(text: str, model: str) -> Optional[list]:
    """Look up a cached embedding vector. Returns None on miss."""
    try:
        redis = await get_redis_client()
        if redis is None:
            return None

        raw = await redis.get(_embed_key(text, model))
        if raw is None:
            CACHE_MISSES.labels(cache_name="embedding").inc()
            return None

        CACHE_HITS.labels(cache_name="embedding").inc()
        return _unpack_vector(raw)

    except Exception as e:
        warn_throttled(
            logger,
            "cache.embed.get",
            f"Embedding cache unavailable — re-embedding every query at full "
            f"OpenAI cost until Redis recovers: {e}",
        )
        return None


async def set_cached_embedding(text: str, model: str, vector: list) -> None:
    """Store an embedding vector in cache."""
    try:
        redis = await get_redis_client()
        if redis is None:
            return

        await redis.set(_embed_key(text, model), _pack_vector(vector), ex=EMBED_TTL)

    except Exception as e:
        warn_throttled(logger, "cache.embed.set", f"Embedding cache write failed: {e}")


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
        warn_throttled(
            logger,
            "cache.invalidate",
            f"RAG cache invalidation FAILED — stale answers may be served after a "
            f"document change: {e}",
        )
