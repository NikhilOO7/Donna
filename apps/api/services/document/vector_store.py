# apps/api/services/document/vector_store.py
"""
Enhanced Vector Store Service with support for contextual embeddings
Manages multi-level context storage and retrieval
"""

import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import numpy as np
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    OptimizersConfigDiff,
    PointStruct,
    VectorParams,
)

from apps.api.core.config import settings
from apps.api.core.connections import get_qdrant_client, get_redis_client

logger = logging.getLogger(__name__)


def generate_point_id(chunk_id: str, context_level: str) -> str:
    """
    Generate a valid UUID for Qdrant point ID from chunk_id and context level.
    Uses UUID v5 (name-based UUID) to ensure deterministic and valid UUIDs.
    """
    # Create a namespace UUID for our application
    namespace = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")  # DNS namespace
    # Combine chunk_id and context_level to create unique name
    name = f"{chunk_id}_{context_level}"
    # Generate UUID v5
    return str(uuid.uuid5(namespace, name))


@dataclass
class SearchResult:
    """Search result with contextual information"""

    chunk_id: str
    document_id: str
    content: str
    score: float
    metadata: Dict[str, Any]
    local_context: Optional[Dict[str, Any]] = None
    document_context: Optional[Dict[str, Any]] = None
    global_context: Optional[Dict[str, Any]] = None


class VectorStoreService:
    """Original vector store service for backward compatibility"""

    def __init__(self):
        self.collection_name = settings.qdrant_collection_name
        self.vector_size = settings.embedding_dimensions

    async def initialize(self):
        """Initialize vector store"""
        client = await get_qdrant_client()

        # Create collection if it doesn't exist
        collections = await client.get_collections()
        if self.collection_name not in [c.name for c in collections.collections]:
            await client.create_collection(
                collection_name=self.collection_name,
                vectors_config=VectorParams(
                    size=self.vector_size, distance=Distance.COSINE
                ),
            )
            logger.info(f"Created collection: {self.collection_name}")

    async def store_embeddings(
        self, document_id: str, embeddings_data: List[Dict[str, Any]]
    ):
        """Store embeddings in vector database"""
        client = await get_qdrant_client()

        points = []
        for data in embeddings_data:
            point = PointStruct(
                id=data["chunk_id"],
                vector=data["embedding"],
                payload={
                    "document_id": document_id,
                    "content": data["content"],
                    "metadata": data.get("metadata", {}),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
            )
            points.append(point)

        # Upsert points
        await client.upsert(collection_name=self.collection_name, points=points)

        logger.info(f"Stored {len(points)} embeddings for document {document_id}")

    async def search(
        self,
        query_embedding: List[float],
        top_k: int = 5,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Search for similar documents"""
        client = await get_qdrant_client()

        # Build filter
        conditions = []
        if filters and filters.get("document_ids"):
            conditions.append(
                FieldCondition(
                    key="document_id",
                    match=MatchValue(value=filters["document_ids"]),
                )
            )
        # Tenant scoping — this collection nests owner under metadata.
        if filters and filters.get("owner_id"):
            conditions.append(
                FieldCondition(
                    key="metadata.owner_id",
                    match=MatchValue(value=str(filters["owner_id"])),
                )
            )
        qdrant_filter = Filter(must=conditions) if conditions else None

        # Search
        results = (
            await client.query_points(
                collection_name=self.collection_name,
                query=query_embedding,
                query_filter=qdrant_filter,
                limit=top_k,
            )
        ).points

        # Format results
        formatted_results = []
        for result in results:
            formatted_results.append(
                {
                    "chunk_id": result.id,
                    "score": result.score,
                    "document_id": result.payload.get("document_id"),
                    "content": result.payload.get("content"),
                    "metadata": result.payload.get("metadata", {}),
                }
            )

        return formatted_results

    async def delete_document(self, document_id: str):
        """Delete all embeddings for a document"""
        client = await get_qdrant_client()

        await client.delete(
            collection_name=self.collection_name,
            points_selector=Filter(
                must=[
                    FieldCondition(
                        key="document_id", match=MatchValue(value=document_id)
                    )
                ]
            ),
        )

        logger.info(f"Deleted embeddings for document {document_id}")


class ModernVectorStore:
    """Enhanced vector store with contextual embeddings support"""

    def __init__(self):
        # Collection names for different context levels
        self.collections = {
            "local": f"{settings.qdrant_collection_name}_local",
            "document": f"{settings.qdrant_collection_name}_document",
            "global": f"{settings.qdrant_collection_name}_global",
            "unified": f"{settings.qdrant_collection_name}_unified",
        }
        # Use standardized embedding dimensions from config
        self.vector_size = settings.embedding_dimensions
        self.cache_ttl = 3600  # 1 hour cache

    async def initialize(self):
        """Initialize all collections"""
        client = await get_qdrant_client()

        # Create collections for each context level
        existing_collections = [
            c.name for c in (await client.get_collections()).collections
        ]

        for context_level, collection_name in self.collections.items():
            if collection_name not in existing_collections:
                await client.create_collection(
                    collection_name=collection_name,
                    vectors_config=VectorParams(
                        size=self.vector_size, distance=Distance.COSINE
                    ),
                    optimizers_config=OptimizersConfigDiff(
                        indexing_threshold=20000, memmap_threshold=50000
                    ),
                )
                logger.info(f"Created collection: {collection_name}")

    async def store_memory_records(
        self,
        meeting_id: str,
        records: List[Dict[str, Any]],
        owner_id: Optional[str] = None,
    ) -> int:
        """Index meeting-memory records alongside document chunks.

        Memory records are single-level by nature, so the same vector is
        written to every collection — retrieval at any context level can
        surface what the team discussed, decided, and committed to.
        Idempotent per (meeting, kind, index): re-summarizing a meeting
        overwrites its memories instead of duplicating them.
        """
        client = await get_qdrant_client()
        points_by_collection: Dict[str, List[PointStruct]] = {
            name: [] for name in self.collections.values()
        }

        stored = 0
        for i, record in enumerate(records):
            vector = record.get("embedding")
            if not vector:
                continue
            metadata = record.get("metadata", {})
            kind = metadata.get("memory_kind", "memory")
            point_id = generate_point_id(f"memory:{meeting_id}:{kind}:{i}", "memory")
            payload = {
                "document_id": f"meeting:{meeting_id}",
                "owner_id": str(owner_id) if owner_id else None,
                "content": record.get("content", ""),
                "metadata": metadata,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            for name in self.collections.values():
                points_by_collection[name].append(
                    PointStruct(id=point_id, vector=vector, payload=payload)
                )
            stored += 1

        for name, points in points_by_collection.items():
            if points:
                await client.upsert(collection_name=name, points=points)

        return stored

    async def store_contextual_embeddings(
        self,
        document_id: str,
        embeddings_data: List[Dict[str, Any]],
        document_structure: Any,
        owner_id: Optional[str] = None,
    ):
        """Store embeddings with contextual information.

        ``owner_id`` is written into every point's payload so retrieval can
        be scoped to a tenant (see ``search_with_context`` filters).
        """
        client = await get_qdrant_client()
        redis_client = await get_redis_client()

        # Prepare points for each context level
        points_by_level = {"local": [], "document": [], "global": [], "unified": []}

        for idx, data in enumerate(embeddings_data):
            chunk_id = data["chunk_id"]
            # Pick the canonical embedding vector; prefer per-level if available
            level_embeddings = data.get("embeddings", {})
            default_vec = data.get("embedding")
            base_payload = {
                "document_id": document_id,
                "owner_id": str(owner_id) if owner_id else None,
                "chunk_index": idx,
                "content": data["content"],
                "metadata": data["metadata"],
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

            # Add structure information
            if document_structure:
                base_payload["document_structure"] = {
                    "title": document_structure.title,
                    "total_chunks": document_structure.total_chunks,
                    "document_type": document_structure.document_type,
                    "section": data["metadata"].get("section_path", []),
                }

            # Local context point
            local_payload = {
                **base_payload,
                "context_level": "local",
                "original_chunk_id": chunk_id,  # Store original for reference
            }
            if "local_context" in data["metadata"]:
                local_payload["local_context"] = data["metadata"]["local_context"]

            points_by_level["local"].append(
                PointStruct(
                    id=generate_point_id(chunk_id, "local"),
                    vector=level_embeddings.get("local") or default_vec,
                    payload=local_payload,
                )
            )

            # Document context point
            doc_payload = {
                **base_payload,
                "context_level": "document",
                "original_chunk_id": chunk_id,
            }
            if "document_context" in data["metadata"]:
                doc_payload["document_context"] = data["metadata"]["document_context"]

            points_by_level["document"].append(
                PointStruct(
                    id=generate_point_id(chunk_id, "document"),
                    vector=level_embeddings.get("document") or default_vec,
                    payload=doc_payload,
                )
            )

            # Global context point
            global_payload = {
                **base_payload,
                "context_level": "global",
                "original_chunk_id": chunk_id,
            }
            if "global_context" in data["metadata"]:
                global_payload["global_context"] = data["metadata"]["global_context"]

            points_by_level["global"].append(
                PointStruct(
                    id=generate_point_id(chunk_id, "global"),
                    vector=level_embeddings.get("global") or default_vec,
                    payload=global_payload,
                )
            )

            # Unified point with all contexts
            unified_payload = {
                **base_payload,
                "context_level": "unified",
                "original_chunk_id": chunk_id,
                "all_contexts": {
                    "local": data["metadata"].get("local_context"),
                    "document": data["metadata"].get("document_context"),
                    "global": data["metadata"].get("global_context"),
                },
            }

            points_by_level["unified"].append(
                PointStruct(
                    id=generate_point_id(chunk_id, "unified"),
                    vector=default_vec,
                    payload=unified_payload,
                )
            )

        # Store points in respective collections
        for context_level, points in points_by_level.items():
            if points:
                await client.upsert(
                    collection_name=self.collections[context_level], points=points
                )
                logger.info(
                    f"Stored {len(points)} embeddings in {context_level} collection"
                )

        # Cache document metadata in Redis
        if redis_client:
            cache_key = f"doc_meta:{document_id}"
            cache_data = {
                "structure": document_structure.__dict__ if document_structure else {},
                "chunk_count": len(embeddings_data),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            await redis_client.setex(cache_key, self.cache_ttl, json.dumps(cache_data))

    async def search_with_context(
        self,
        query_embedding: List[float],
        context_level: str = "local",
        filters: Optional[Dict[str, Any]] = None,
        top_k: int = 5,
    ) -> List[SearchResult]:
        """Search with specific context level"""
        client = await get_qdrant_client()

        # Determine collection to search
        if context_level == "auto":
            # Search all collections and merge results
            return await self._search_multi_context(query_embedding, filters, top_k)

        collection_name = self.collections.get(
            context_level, self.collections["unified"]
        )

        # Build filter
        qdrant_filter = self._build_filter(filters)

        # Search
        results = (
            await client.query_points(
                collection_name=collection_name,
                query=query_embedding,
                query_filter=qdrant_filter,
                limit=top_k,
                with_payload=True,
                with_vectors=False,
            )
        ).points

        # Format results
        search_results = []
        for result in results:
            payload = result.payload

            search_result = SearchResult(
                chunk_id=result.id,
                document_id=payload.get("document_id"),
                content=payload.get("content"),
                score=result.score,
                metadata=payload.get("metadata", {}),
                local_context=payload.get("local_context"),
                document_context=payload.get("document_context"),
                global_context=payload.get("global_context"),
            )

            # Add document structure if available
            if "document_structure" in payload:
                search_result.metadata["document_structure"] = payload[
                    "document_structure"
                ]

            search_results.append(search_result)

        return search_results

    async def _search_multi_context(
        self,
        query_embedding: List[float],
        filters: Optional[Dict[str, Any]],
        top_k: int,
    ) -> List[SearchResult]:
        """Search across multiple context levels and merge results"""
        client = await get_qdrant_client()

        # Search each context level
        all_results = []
        context_weights = {"local": 0.4, "document": 0.35, "global": 0.25}

        for context_level, weight in context_weights.items():
            collection_name = self.collections[context_level]

            try:
                results = (
                    await client.query_points(
                        collection_name=collection_name,
                        query=query_embedding,
                        query_filter=self._build_filter(filters),
                        limit=top_k * 2,  # Get more results for merging
                        with_payload=True,
                    )
                ).points

                # Weight scores by context level
                for result in results:
                    result.score *= weight
                    all_results.append((result, context_level))

            except Exception as e:
                logger.error(f"Search failed for {context_level}: {e}")

        # Sort by weighted score and deduplicate
        all_results.sort(key=lambda x: x[0].score, reverse=True)

        seen_chunks = set()
        final_results = []

        for result, context_level in all_results:
            # Extract base chunk ID (without context suffix)
            base_chunk_id = result.id.rsplit("_", 1)[0]

            if base_chunk_id not in seen_chunks:
                seen_chunks.add(base_chunk_id)

                payload = result.payload
                search_result = SearchResult(
                    chunk_id=base_chunk_id,
                    document_id=payload.get("document_id"),
                    content=payload.get("content"),
                    score=result.score,
                    metadata={
                        **payload.get("metadata", {}),
                        "matched_context_level": context_level,
                    },
                    local_context=payload.get("local_context"),
                    document_context=payload.get("document_context"),
                    global_context=payload.get("global_context"),
                )

                final_results.append(search_result)

                if len(final_results) >= top_k:
                    break

        return final_results

    async def get_neighboring_chunks(
        self, chunk_id: str, window_size: int = 2
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Get neighboring chunks for local context"""
        await get_qdrant_client()
        redis_client = await get_redis_client()

        # Try cache first
        cache_key = f"neighbors:{chunk_id}:{window_size}"
        if redis_client:
            cached = await redis_client.get(cache_key)
            if cached:
                return json.loads(cached)

        # Extract document ID and chunk index from chunk_id
        parts = chunk_id.split("_chunk_")
        if len(parts) != 2:
            return {"before": [], "after": []}

        document_id = parts[0]
        try:
            chunk_index = int(parts[1])
        except ValueError:
            return {"before": [], "after": []}

        # Get chunks before and after
        neighbors = {"before": [], "after": [], "section_path": []}

        # Search for neighboring chunks
        for offset in range(1, window_size + 1):
            # Before
            before_index = chunk_index - offset
            if before_index >= 0:
                before_chunk = await self._get_chunk_by_index(document_id, before_index)
                if before_chunk:
                    neighbors["before"].insert(0, before_chunk)

            # After
            after_index = chunk_index + offset
            after_chunk = await self._get_chunk_by_index(document_id, after_index)
            if after_chunk:
                neighbors["after"].append(after_chunk)

        # Get section path
        current_chunk = await self._get_chunk_by_index(document_id, chunk_index)
        if current_chunk and "metadata" in current_chunk:
            neighbors["section_path"] = current_chunk["metadata"].get(
                "section_path", []
            )

        # Cache results
        if redis_client:
            await redis_client.setex(
                cache_key,
                300,  # 5 minutes
                json.dumps(neighbors),
            )

        return neighbors

    async def _get_chunk_by_index(
        self, document_id: str, chunk_index: int
    ) -> Optional[Dict[str, Any]]:
        """Get a specific chunk by document ID and index"""
        client = await get_qdrant_client()

        # Search in unified collection
        results = (
            await client.query_points(
                collection_name=self.collections["unified"],
                query_filter=Filter(
                    must=[
                        FieldCondition(
                            key="document_id", match=MatchValue(value=document_id)
                        ),
                        FieldCondition(
                            key="chunk_index", match=MatchValue(value=chunk_index)
                        ),
                    ]
                ),
                limit=1,
                with_payload=True,
                with_vectors=False,
            )
        ).points

        if results:
            payload = results[0].payload
            return {
                "chunk_id": results[0].id,
                "content": payload.get("content"),
                "metadata": payload.get("metadata", {}),
            }

        return None

    async def get_document_info(self, document_id: str) -> Dict[str, Any]:
        """Get document metadata and structure"""
        redis_client = await get_redis_client()

        # Check cache
        if redis_client:
            cache_key = f"doc_meta:{document_id}"
            cached = await redis_client.get(cache_key)
            if cached:
                return json.loads(cached)

        # Query from vector store
        client = await get_qdrant_client()

        # Get first chunk to extract document structure
        results = (
            await client.query_points(
                collection_name=self.collections["unified"],
                query_filter=Filter(
                    must=[
                        FieldCondition(
                            key="document_id", match=MatchValue(value=document_id)
                        )
                    ]
                ),
                limit=1,
                with_payload=True,
            )
        ).points

        if results:
            payload = results[0].payload
            doc_structure = payload.get("document_structure", {})

            # Get all chunks to build complete structure
            all_chunks = await client.scroll(
                collection_name=self.collections["unified"],
                scroll_filter=Filter(
                    must=[
                        FieldCondition(
                            key="document_id", match=MatchValue(value=document_id)
                        )
                    ]
                ),
                limit=1000,
            )

            # Extract sections
            sections = set()
            for point in all_chunks[0]:
                section_path = point.payload.get("metadata", {}).get("section_path", [])
                if section_path:
                    sections.add(section_path[0])

            doc_info = {
                "title": doc_structure.get("title", "Unknown"),
                "summary": doc_structure.get("summary", ""),
                "sections": list(sections),
                "metadata": doc_structure,
                "chunk_count": len(all_chunks[0]),
            }

            # Cache results
            if redis_client:
                await redis_client.setex(
                    f"doc_meta:{document_id}", self.cache_ttl, json.dumps(doc_info)
                )

            return doc_info

        return {}

    async def find_related_documents(
        self, document_id: str, query: str, max_related: int = 3
    ) -> List[Dict[str, Any]]:
        """Find documents related to the given document"""
        # This is a simplified implementation
        # In production, this would use a knowledge graph or citation analysis

        client = await get_qdrant_client()

        # Get sample embeddings from current document
        current_doc_chunks = await client.scroll(
            collection_name=self.collections["unified"],
            scroll_filter=Filter(
                must=[
                    FieldCondition(
                        key="document_id", match=MatchValue(value=document_id)
                    )
                ]
            ),
            limit=5,
            with_vectors=True,
        )

        if not current_doc_chunks[0]:
            return []

        # Average embeddings
        embeddings = [point.vector for point in current_doc_chunks[0]]
        avg_embedding = np.mean(embeddings, axis=0).tolist()

        # Search for similar documents, excluding current
        results = (
            await client.query_points(
                collection_name=self.collections["global"],
                query=avg_embedding,
                query_filter=Filter(
                    must_not=[
                        FieldCondition(
                            key="document_id", match=MatchValue(value=document_id)
                        )
                    ]
                ),
                limit=max_related * 3,  # Get more to ensure unique documents
            )
        ).points

        # Aggregate by document
        related_docs = {}
        for result in results:
            doc_id = result.payload.get("document_id")
            if doc_id not in related_docs:
                related_docs[doc_id] = {
                    "document_id": doc_id,
                    "score": result.score,
                    "title": result.payload.get("document_structure", {}).get(
                        "title", "Unknown"
                    ),
                }

        # Sort by score and return top N
        sorted_docs = sorted(
            related_docs.values(), key=lambda x: x["score"], reverse=True
        )

        return sorted_docs[:max_related]

    async def get_document_relationships(
        self, document_id: str
    ) -> Dict[str, List[Any]]:
        """Get relationships between documents"""
        # Simplified implementation
        # In production, this would use a graph database

        relationships = {
            "references": [],  # Documents referenced by this one
            "referenced_by": [],  # Documents that reference this one
            "entities": [],  # Shared entities
            "topics": [],  # Shared topics
        }

        # Get document chunks to extract entities and topics
        client = await get_qdrant_client()

        chunks = await client.scroll(
            collection_name=self.collections["unified"],
            scroll_filter=Filter(
                must=[
                    FieldCondition(
                        key="document_id", match=MatchValue(value=document_id)
                    )
                ]
            ),
            limit=100,
            with_payload=True,
        )

        # Extract entities and keywords
        all_entities = []
        all_keywords = []

        for point in chunks[0]:
            metadata = point.payload.get("metadata", {})
            all_entities.extend(metadata.get("entities", []))
            all_keywords.extend(metadata.get("keywords", []))

        # Deduplicate
        from collections import Counter

        entity_counts = Counter(e["text"] for e in all_entities if "text" in e)
        keyword_counts = Counter(all_keywords)

        relationships["entities"] = [
            {"text": text, "count": count}
            for text, count in entity_counts.most_common(10)
        ]

        relationships["topics"] = [
            {"topic": topic, "count": count}
            for topic, count in keyword_counts.most_common(10)
        ]

        return relationships

    def _build_filter(self, filters: Optional[Dict[str, Any]]) -> Optional[Filter]:
        """Build Qdrant filter from dictionary"""
        if not filters:
            return None

        conditions = []

        if "document_ids" in filters and filters["document_ids"]:
            conditions.append(
                FieldCondition(
                    key="document_id", match=MatchValue(value=filters["document_ids"])
                )
            )

        # Tenant scoping: only match this owner's points.
        if filters.get("owner_id"):
            conditions.append(
                FieldCondition(
                    key="owner_id", match=MatchValue(value=str(filters["owner_id"]))
                )
            )

        if "section" in filters:
            conditions.append(
                FieldCondition(
                    key="metadata.section_path",
                    match=MatchValue(value=filters["section"]),
                )
            )

        if conditions:
            return Filter(must=conditions)

        return None

    async def delete_document(self, document_id: str):
        """Delete all embeddings for a document across all collections"""
        client = await get_qdrant_client()
        redis_client = await get_redis_client()

        # Delete from all collections
        for context_level, collection_name in self.collections.items():
            try:
                await client.delete(
                    collection_name=collection_name,
                    points_selector=Filter(
                        must=[
                            FieldCondition(
                                key="document_id", match=MatchValue(value=document_id)
                            )
                        ]
                    ),
                )
                logger.info(
                    f"Deleted embeddings from {collection_name} for document {document_id}"
                )
            except Exception as e:
                logger.error(f"Failed to delete from {collection_name}: {e}")

        # Clear cache
        if redis_client:
            cache_keys = [f"doc_meta:{document_id}", f"neighbors:*{document_id}*"]
            for pattern in cache_keys:
                keys = await redis_client.keys(pattern)
                if keys:
                    await redis_client.delete(*keys)
