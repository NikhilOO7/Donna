"""
Unit tests for vector store services.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from apps.api.core.config import settings


class TestVectorStoreService:
    """Test the original VectorStoreService."""

    def test_vector_size_matches_config(self):
        """VectorStoreService should use config-based dimensions."""
        with patch("apps.api.services.document.vector_store.get_qdrant_client"), \
             patch("apps.api.services.document.vector_store.get_redis_client"):
            from apps.api.services.document.vector_store import VectorStoreService

            service = VectorStoreService()
            assert service.vector_size == settings.embedding_dimensions

    @pytest.mark.asyncio
    async def test_search_returns_formatted_results(self, mock_qdrant_client):
        """search() should return formatted result dicts."""
        with patch(
            "apps.api.services.document.vector_store.get_qdrant_client",
            return_value=mock_qdrant_client,
        ):
            from apps.api.services.document.vector_store import VectorStoreService

            service = VectorStoreService()
            query_embedding = [0.1] * 1536

            results = await service.search(query_embedding=query_embedding, top_k=5)

            assert len(results) == 1
            assert results[0]["score"] == 0.95
            assert results[0]["content"] == "Test content from document"
            assert results[0]["document_id"] == "test-doc-id"


class TestModernVectorStore:
    """Test the ModernVectorStore."""

    def test_vector_size_uses_config(self):
        """ModernVectorStore should use config-based dimensions."""
        with patch("apps.api.services.document.vector_store.get_qdrant_client"), \
             patch("apps.api.services.document.vector_store.get_redis_client"):
            from apps.api.services.document.vector_store import ModernVectorStore

            store = ModernVectorStore()
            assert store.vector_size == settings.embedding_dimensions

    def test_collections_are_named_correctly(self):
        """ModernVectorStore should create 4 context-level collections."""
        with patch("apps.api.services.document.vector_store.get_qdrant_client"), \
             patch("apps.api.services.document.vector_store.get_redis_client"):
            from apps.api.services.document.vector_store import ModernVectorStore

            store = ModernVectorStore()
            assert "local" in store.collections
            assert "document" in store.collections
            assert "global" in store.collections
            assert "unified" in store.collections
