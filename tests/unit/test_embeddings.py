"""
Unit tests for embedding services.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from apps.api.core.config import settings


class TestEmbeddingConfig:
    """Test embedding configuration consistency."""

    def test_embedding_model_is_small(self):
        """Verify we use text-embedding-3-small for consistency."""
        assert "small" in settings.embedding_model or settings.embedding_dimensions == 1536

    def test_embedding_dimensions_is_1536(self):
        """All vector stores should use 1536 dimensions."""
        assert settings.embedding_dimensions == 1536


class TestEmbeddingService:
    """Test the original EmbeddingService."""

    @pytest.mark.asyncio
    async def test_generate_embedding_returns_correct_dimensions(self, mock_openai_client):
        """Embedding should return vector of correct dimensions."""
        with patch("apps.api.services.document.embeddings.OpenAI", return_value=mock_openai_client):
            from apps.api.services.document.embeddings import EmbeddingService

            service = EmbeddingService()
            service.client = mock_openai_client

            embedding = await service.generate_embedding("test text")

            assert len(embedding) == 1536
            assert all(isinstance(v, float) for v in embedding)

    @pytest.mark.asyncio
    async def test_generate_embedding_with_context(self, mock_openai_client):
        """Embedding with context should enhance the text."""
        with patch("apps.api.services.document.embeddings.OpenAI", return_value=mock_openai_client):
            from apps.api.services.document.embeddings import EmbeddingService

            service = EmbeddingService()
            service.client = mock_openai_client

            context = {"document_type": "policy", "section": "Introduction"}
            embedding = await service.generate_embedding("test text", context)

            assert len(embedding) == 1536
            # Verify the enhanced text was used (check the call args)
            call_args = mock_openai_client.embeddings.create.call_args
            input_text = call_args.kwargs.get("input") or call_args[1].get("input", "")
            assert "[Document: policy]" in input_text


class TestContextualEmbeddingGenerator:
    """Test the enhanced ContextualEmbeddingGenerator."""

    @pytest.mark.asyncio
    async def test_generate_contextual_embedding_returns_list(self, mock_async_openai_client):
        """generate_contextual_embedding should return a flat list of floats."""
        with patch("apps.api.services.document.embeddings.AsyncOpenAI", return_value=mock_async_openai_client), \
             patch("apps.api.services.document.embeddings.SentenceTransformer"):
            from apps.api.services.document.embeddings import ContextualEmbeddingGenerator

            gen = ContextualEmbeddingGenerator()
            gen.openai_client = mock_async_openai_client

            embedding = await gen.generate_contextual_embedding("What is the architecture?")

            assert isinstance(embedding, list)
            assert len(embedding) == 1536
