"""
Context Agent.

Embeds the latest utterance, queries Qdrant for relevant document
chunks (uploaded docs + pre-meeting research), and returns a
`context` nudge when a strong match is found.
"""

import logging
from typing import Any, Dict, List, Optional

from apps.api.services.document.contextual_processor import (
    ContextualEmbeddingGenerator,
)
from apps.api.services.document.vector_store import ModernVectorStore

logger = logging.getLogger(__name__)

MIN_SIMILARITY = 0.55  # Below this, no nudge


class ContextAgent:
    """Surface relevant Knowledge Base content during a meeting."""

    def __init__(self):
        self._embedder: Optional[ContextualEmbeddingGenerator] = None
        self._vector_store: Optional[ModernVectorStore] = None

    def _get_embedder(self) -> ContextualEmbeddingGenerator:
        if self._embedder is None:
            self._embedder = ContextualEmbeddingGenerator()
        return self._embedder

    def _get_vector_store(self) -> ModernVectorStore:
        if self._vector_store is None:
            self._vector_store = ModernVectorStore()
        return self._vector_store

    async def analyze(
        self, recent_utterances: List[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        """Query knowledge base for context relevant to recent discussion."""
        if not recent_utterances:
            return None

        # Build query from last 2-3 utterances (more context = better retrieval)
        query_text = " ".join(u.get("text", "") for u in recent_utterances[-3:]).strip()

        if len(query_text) < 20:
            return None  # too short to be meaningful

        try:
            embedder = self._get_embedder()
            vector_store = self._get_vector_store()

            query_embedding = await embedder.generate_contextual_embedding(
                text=query_text, context_level="document"
            )

            results = await vector_store.search_with_context(
                query_embedding=query_embedding,
                context_level="document",
                top_k=1,
            )
        except Exception as e:
            logger.warning(f"[Context] RAG search failed: {e}")
            return None

        if not results:
            return None

        top = results[0]
        score = getattr(top, "score", 0.0) or 0.0

        if score < MIN_SIMILARITY:
            return None

        content = getattr(top, "content", "") or ""
        snippet = content[:300] + ("..." if len(content) > 300 else "")
        doc_id = getattr(top, "document_id", "unknown")

        logger.info(f"[Context] RAG hit score={score:.2f} doc={doc_id}")

        return {
            "nudge_type": "context",
            "title": "Relevant from Knowledge Base",
            "content": snippet,
            "source_agent": "context_agent",
            "source_data": {
                "document_id": str(doc_id),
                "chunk_id": getattr(top, "chunk_id", None),
                "score": score,
            },
            "relevance_score": min(score, 1.0),
        }


context_agent = ContextAgent()
