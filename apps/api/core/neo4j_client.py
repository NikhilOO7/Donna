"""
Async Neo4j driver singleton.

Owns the connection pool, schema bootstrap (uniqueness constraints +
indices), and a small ``execute`` helper that hides session
boilerplate. The full app is happy without Neo4j running — every
caller goes through ``execute()`` which short-circuits to ``None``
when ``settings.neo4j_enabled`` is off or the driver can't connect.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

from apps.api.core.config import settings

logger = logging.getLogger(__name__)


# ---- Schema bootstrap ------------------------------------------------------
# MERGE on (Entity {id}) gives us free deduplication: a relationship_agent
# call that emits the same source/target pair from two different chunks
# updates the existing edge instead of creating a duplicate.
# Dedup + tenancy key is (normalized, type, owner_id): same entity within a
# tenant collapses to one node, but different tenants get separate nodes.
# owner_id uses the "__global__" sentinel when unset (auth off / demo).
_BOOTSTRAP_CYPHER = [
    "CREATE CONSTRAINT entity_id_unique IF NOT EXISTS "
    "FOR (e:Entity) REQUIRE e.id IS UNIQUE",
    "CREATE CONSTRAINT entity_norm_type_owner_unique IF NOT EXISTS "
    "FOR (e:Entity) REQUIRE (e.normalized, e.type, e.owner_id) IS UNIQUE",
    "CREATE INDEX entity_type IF NOT EXISTS FOR (e:Entity) ON (e.type)",
    "CREATE INDEX entity_document IF NOT EXISTS FOR (e:Entity) ON (e.document_id)",
    "CREATE INDEX entity_owner IF NOT EXISTS FOR (e:Entity) ON (e.owner_id)",
    "CREATE INDEX entity_label IF NOT EXISTS FOR (e:Entity) ON (e.label)",
]

# Sentinel owner for entities with no tenant (auth off / demo data).
GLOBAL_OWNER = "__global__"


class Neo4jClient:
    """Lazy async wrapper around the Neo4j driver."""

    def __init__(self) -> None:
        self._driver = None
        self._lock = asyncio.Lock()
        self._ready = False
        self._unavailable = False

    @property
    def enabled(self) -> bool:
        return settings.neo4j_enabled and not self._unavailable

    async def _connect(self) -> None:
        """Connect + verify + bootstrap. Caller must hold the lock."""
        from neo4j import AsyncGraphDatabase

        try:
            driver = AsyncGraphDatabase.driver(
                settings.neo4j_uri,
                auth=(settings.neo4j_user, settings.neo4j_password),
                max_connection_pool_size=20,
            )
            await driver.verify_connectivity()
            self._driver = driver
            await self._bootstrap_schema()
            self._ready = True
            logger.info(f"[Neo4j] connected to {settings.neo4j_uri}")
        except Exception as e:
            self._unavailable = True
            logger.warning(
                f"[Neo4j] unavailable, falling back to PostgreSQL-only mode: {e}"
            )

    async def _bootstrap_schema(self) -> None:
        if not self._driver:
            return
        async with self._driver.session(database=settings.neo4j_database) as session:
            for cy in _BOOTSTRAP_CYPHER:
                try:
                    await session.run(cy)
                except Exception as e:
                    logger.debug(f"[Neo4j] bootstrap warning ({cy[:40]}...): {e}")

    async def ensure_ready(self) -> bool:
        if self._unavailable or not settings.neo4j_enabled:
            return False
        if self._ready:
            return True
        async with self._lock:
            if self._ready or self._unavailable:
                return self._ready
            await self._connect()
        return self._ready

    async def execute(
        self,
        cypher: str,
        parameters: Optional[Dict[str, Any]] = None,
        write: bool = False,
    ) -> Optional[List[Dict[str, Any]]]:
        """Run a Cypher statement. Returns None if Neo4j is unavailable."""
        if not await self.ensure_ready():
            return None
        try:
            async with self._driver.session(
                database=settings.neo4j_database
            ) as session:
                if write:
                    result = await session.run(cypher, parameters or {})
                    records = [r.data() async for r in result]
                    await result.consume()
                    return records
                result = await session.run(cypher, parameters or {})
                return [r.data() async for r in result]
        except Exception as e:
            logger.warning(f"[Neo4j] query failed ({cypher[:60]}...): {e}")
            return None

    async def close(self) -> None:
        if self._driver:
            try:
                await self._driver.close()
            except Exception:
                pass
            self._driver = None
            self._ready = False


neo4j_client = Neo4jClient()
