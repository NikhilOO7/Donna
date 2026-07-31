"""Regression tests for the enhanced voice agent RAG path (/api/v1/query use_enhanced=True).

The enhanced query path previously crashed with a TypeError whenever the corpus
returned results, because SearchResult dataclasses were subscripted like dicts.
"""

from unittest.mock import AsyncMock, MagicMock

from apps.api.services.document.vector_store import SearchResult
from apps.api.services.voice.enhanced_livekit_service import (
    DocumentIntelligenceVoiceAgent,
)


def _make_agent():
    agent = DocumentIntelligenceVoiceAgent()
    # Inject mocks so _ensure_rag_services() is a no-op
    agent.rag_service = MagicMock()
    agent.vector_store = MagicMock()
    agent.embedding_generator = MagicMock()
    agent.embedding_generator.generate_contextual_embedding = AsyncMock(
        return_value=[0.1] * 8
    )
    return agent


async def test_search_handles_searchresult_dataclasses():
    """search_documents_with_context must read SearchResult attributes, not subscript."""
    agent = _make_agent()
    agent.vector_store.search_with_context = AsyncMock(
        return_value=[
            SearchResult(
                chunk_id="c1",
                document_id="d1",
                content="chunk text",
                score=0.9,
                metadata={"page": 3},
            )
        ]
    )
    agent.vector_store.get_neighboring_chunks = AsyncMock(return_value={})
    agent.vector_store.get_document_info = AsyncMock(return_value={})

    result = await agent.search_documents_with_context(
        query="what is the budget", conversation_id="conv-1"
    )

    assert result["results"], "expected at least one enhanced result"
    first = result["results"][0]
    assert first["chunk_id"] == "c1"
    assert first["document_id"] == "d1"
    assert first["score"] == 0.9
    assert first["metadata"] == {"page": 3}


async def test_process_voice_query_returns_rag_answer_on_hits():
    """process_voice_query should return the RAG answer without crashing on hits."""
    agent = _make_agent()
    agent.rag_service.process_query = AsyncMock(
        return_value={
            "answer": "The budget is $1M.",
            "sources": [{"document_id": "d1", "chunk_id": "c1"}],
        }
    )

    result = await agent.process_voice_query(
        query="what is the budget", conversation_id="conv-1"
    )

    assert result["answer"] == "The budget is $1M."
    assert result["sources"][0]["document_id"] == "d1"
    assert result["conversation_id"] == "conv-1"
