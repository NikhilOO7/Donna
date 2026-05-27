"""
Context Agent.

Multi-modal retrieval against the knowledge base. Pulls top-K candidate
chunks from Qdrant — *including* synthetic chunks the enhanced
document pipeline produced for tables and images — then re-ranks them
with a small element-type weighting so:

* When the recent discussion is data-heavy (numbers, percentages,
  comparatives), table chunks get a small boost over plain text.
* Tables and images surface as a differentiated nudge title so the
  reader knows the AI is citing a structured artifact, not prose.
"""

import logging
import re
from typing import Any, Dict, List, Optional

from apps.api.services.document.contextual_processor import (
    ContextualEmbeddingGenerator,
)
from apps.api.services.document.vector_store import ModernVectorStore

logger = logging.getLogger(__name__)

MIN_SIMILARITY = 0.55  # Below this, no nudge

# How many candidates to pull from Qdrant before re-ranking. 5 is enough
# to almost always include a table/image when one is relevant without
# blowing up the prompt.
TOP_K_CANDIDATES = 5

# Boost factor applied to table/image chunks when the query window
# contains numeric / comparative signal — keeps text-only queries
# from surfacing irrelevant tables.
_DATA_HEAVY_PATTERN = re.compile(
    r"\b(\d+(\.\d+)?\s*%|\$\s*\d|"
    r"grew|increased|decreased|raised|"
    r"more than|less than|compare|comparison|"
    r"how many|how much)\b",
    re.IGNORECASE,
)
_TABLE_BOOST_DATA_HEAVY = 1.15
_TABLE_BOOST_DEFAULT = 1.02
_IMAGE_BOOST_DEFAULT = 1.05


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

            candidates = await vector_store.search_with_context(
                query_embedding=query_embedding,
                context_level="document",
                top_k=TOP_K_CANDIDATES,
            )
        except Exception as e:
            logger.warning(f"[Context] RAG search failed: {e}")
            return None

        if not candidates:
            return None

        # Re-rank: apply element-type weighting + minimum score floor
        data_heavy = bool(_DATA_HEAVY_PATTERN.search(query_text))
        scored: List[Dict[str, Any]] = []
        for c in candidates:
            base_score = float(getattr(c, "score", 0.0) or 0.0)
            if base_score < MIN_SIMILARITY:
                continue
            metadata = getattr(c, "metadata", None) or {}
            element_type = (metadata.get("element_type") or "").lower()

            if element_type == "table":
                weight = _TABLE_BOOST_DATA_HEAVY if data_heavy else _TABLE_BOOST_DEFAULT
            elif element_type == "image":
                weight = _IMAGE_BOOST_DEFAULT
            else:
                weight = 1.0

            scored.append(
                {
                    "result": c,
                    "element_type": element_type or "text",
                    "boosted_score": base_score * weight,
                    "base_score": base_score,
                }
            )

        if not scored:
            return None

        scored.sort(key=lambda x: x["boosted_score"], reverse=True)
        top = scored[0]
        c = top["result"]
        element_type = top["element_type"]
        base_score = top["base_score"]

        content = getattr(c, "content", "") or ""
        # Strip the synthetic-chunk markers the enhanced pipeline prepends
        # to table/image chunks so users never see literal "[TABLE]" text.
        content = content.removeprefix("[TABLE]\n").removeprefix("[IMAGE]\n").lstrip()
        snippet = content[:300] + ("..." if len(content) > 300 else "")
        doc_id = getattr(c, "document_id", "unknown")

        # Differentiated title by source type
        if element_type == "table":
            title = "Relevant data from Knowledge Base"
        elif element_type == "image":
            title = "Relevant chart / figure from Knowledge Base"
        else:
            title = "Relevant from Knowledge Base"

        logger.info(
            f"[Context] RAG hit type={element_type} base={base_score:.2f} "
            f"boosted={top['boosted_score']:.2f} doc={doc_id} "
            f"(candidates={len(candidates)}, data_heavy={data_heavy})"
        )

        return {
            "nudge_type": "context",
            "title": title,
            "content": snippet,
            "source_agent": "context_agent",
            "source_data": {
                "document_id": str(doc_id),
                "chunk_id": getattr(c, "chunk_id", None),
                "element_type": element_type,
                "score": base_score,
                "boosted_score": top["boosted_score"],
            },
            "relevance_score": min(base_score, 1.0),
        }


context_agent = ContextAgent()
