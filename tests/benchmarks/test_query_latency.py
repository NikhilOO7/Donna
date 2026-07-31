"""
Benchmark: full RAG query pipeline latency.

Measures overhead of the query pipeline (embedding + search + answer
generation) with mocked external services.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.benchmarks.conftest import BenchmarkResult, timer


@pytest.fixture
def mock_services():
    # OpenAI
    mock_openai = MagicMock()
    embed_resp = MagicMock()
    embed_data = MagicMock()
    embed_data.embedding = [0.1] * 1536
    embed_resp.data = [embed_data]
    mock_openai.embeddings.create.return_value = embed_resp

    chat_resp = MagicMock()
    choice = MagicMock()
    choice.message.content = "The system uses microservices architecture."
    chat_resp.choices = [choice]
    mock_openai.chat.completions.create.return_value = chat_resp

    # Qdrant
    mock_qdrant = AsyncMock()
    search_result = MagicMock()
    search_result.id = "chunk-001"
    search_result.score = 0.9
    search_result.payload = {
        "document_id": "doc-1",
        "content": "Microservices architecture with FastAPI.",
        "metadata": {},
    }
    mock_qdrant.search.return_value = [search_result]

    return {"openai": mock_openai, "qdrant": mock_qdrant}


class TestQueryPipelineBenchmark:
    @pytest.mark.asyncio
    async def test_full_query_latency(self, mock_services):
        """Full RAG query should complete in <100ms (mocked)."""
        with (
            patch(
                "apps.api.services.rag.rag_service.OpenAI",
                return_value=mock_services["openai"],
            ),
            patch(
                "apps.api.services.document.vector_store.get_qdrant_client",
                return_value=mock_services["qdrant"],
            ),
            patch(
                "apps.api.services.document.embeddings.OpenAI",
                return_value=mock_services["openai"],
            ),
        ):
            from apps.api.services.rag.rag_service import RAGService

            service = RAGService()
            service.client = mock_services["openai"]
            service.embedding_service.client = mock_services["openai"]

            result = BenchmarkResult("full_rag_query")

            for _ in range(10):
                with timer(result):
                    await service.process_query("What architecture does it use?")

            print(f"\n  {result}")
            assert result.mean_ms < 100, (
                f"Mean latency {result.mean_ms:.1f}ms exceeds 100ms"
            )
