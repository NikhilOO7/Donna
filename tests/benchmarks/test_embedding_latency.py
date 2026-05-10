"""
Benchmark: embedding generation latency.

Uses mocked OpenAI to measure the overhead of the EmbeddingService
wrapper (serialization, caching, context enhancement) without
waiting on real API calls.
"""

from unittest.mock import MagicMock, patch

import pytest

from tests.benchmarks.conftest import BenchmarkResult, timer


@pytest.fixture
def mock_openai():
    client = MagicMock()
    resp = MagicMock()
    data = MagicMock()
    data.embedding = [0.01] * 1536
    resp.data = [data]
    client.embeddings.create.return_value = resp
    return client


class TestEmbeddingBenchmark:
    @pytest.mark.asyncio
    async def test_single_embedding_latency(self, mock_openai):
        """Single embedding call should complete in <50ms (mocked)."""
        with patch(
            "apps.api.services.document.embeddings.OpenAI", return_value=mock_openai
        ):
            from apps.api.services.document.embeddings import EmbeddingService

            service = EmbeddingService()
            service.client = mock_openai

            result = BenchmarkResult("single_embedding")

            for _ in range(20):
                with timer(result):
                    await service.generate_embedding(
                        "benchmark text for embedding generation"
                    )

            print(f"\n  {result}")
            assert result.mean_ms < 50, (
                f"Mean latency {result.mean_ms:.1f}ms exceeds 50ms"
            )

    @pytest.mark.asyncio
    async def test_batch_embedding_latency(self, mock_openai):
        """Batch of 10 sequential embeddings should complete in <500ms (mocked)."""
        with patch(
            "apps.api.services.document.embeddings.OpenAI", return_value=mock_openai
        ):
            from apps.api.services.document.embeddings import EmbeddingService

            service = EmbeddingService()
            service.client = mock_openai

            texts = [f"benchmark text chunk {i}" for i in range(10)]
            result = BenchmarkResult("batch_embedding_10")

            for _ in range(5):
                with timer(result):
                    for text in texts:
                        await service.generate_embedding(text)

            print(f"\n  {result}")
            assert result.mean_ms < 500, (
                f"Mean latency {result.mean_ms:.1f}ms exceeds 500ms"
            )
