"""
Integration test for the end-to-end RAG pipeline.
Tests: Upload -> Chunk -> Embed -> Store in Qdrant -> Query -> Answer

These tests use mocked external services (OpenAI, Qdrant) to validate
the data flow without requiring live API keys or running infrastructure.
"""

import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def mock_services():
    """Set up all mocked services for the RAG pipeline."""
    # Mock OpenAI (sync client for EmbeddingService, RAGService)
    mock_openai = MagicMock()
    mock_embedding_resp = MagicMock()
    mock_embedding_data = MagicMock()
    mock_embedding_data.embedding = [0.1] * 1536
    mock_embedding_resp.data = [mock_embedding_data]
    mock_openai.embeddings.create.return_value = mock_embedding_resp

    mock_chat_resp = MagicMock()
    mock_choice = MagicMock()
    mock_choice.message.content = (
        "Based on the document, the architecture uses microservices."
    )
    mock_chat_resp.choices = [mock_choice]
    mock_openai.chat.completions.create.return_value = mock_chat_resp

    # Mock Qdrant
    mock_qdrant = AsyncMock()
    mock_collections = MagicMock()
    mock_collections.collections = []
    mock_qdrant.get_collections.return_value = mock_collections
    mock_qdrant.create_collection.return_value = True
    mock_qdrant.upsert.return_value = True

    # Mock search results
    mock_search_result = MagicMock()
    mock_search_result.id = "chunk-001"
    mock_search_result.score = 0.92
    mock_search_result.payload = {
        "document_id": "test-doc-id",
        "content": "The system uses a microservices architecture with FastAPI backend.",
        "metadata": {"section": "Architecture", "word_count": 9},
    }
    mock_qdrant.search.return_value = [mock_search_result]

    return {
        "openai": mock_openai,
        "qdrant": mock_qdrant,
    }


class TestRAGPipelineFlow:
    """Validate the complete RAG data flow with mocked services."""

    @pytest.mark.asyncio
    async def test_embedding_service_generates_correct_dimensions(self, mock_services):
        """Step 1: EmbeddingService generates 1536-dim vectors."""
        with patch(
            "apps.api.services.document.embeddings.OpenAI",
            return_value=mock_services["openai"],
        ):
            from apps.api.services.document.embeddings import EmbeddingService

            service = EmbeddingService()
            service.client = mock_services["openai"]

            embedding = await service.generate_embedding("test document chunk")

            assert len(embedding) == 1536
            mock_services["openai"].embeddings.create.assert_called_once()

    @pytest.mark.asyncio
    async def test_vector_store_stores_and_searches(self, mock_services):
        """Step 2: VectorStoreService stores embeddings and retrieves them."""
        with patch(
            "apps.api.services.document.vector_store.get_qdrant_client",
            return_value=mock_services["qdrant"],
        ):
            from apps.api.services.document.vector_store import VectorStoreService

            store = VectorStoreService()

            # Store embeddings
            embeddings_data = [
                {
                    "chunk_id": "chunk-001",
                    "embedding": [0.1] * 1536,
                    "content": "The system uses microservices architecture.",
                    "metadata": {"section": "Architecture"},
                }
            ]
            await store.store_embeddings("test-doc-id", embeddings_data)
            mock_services["qdrant"].upsert.assert_called_once()

            # Search
            query_embedding = [0.2] * 1536
            results = await store.search(query_embedding=query_embedding, top_k=5)

            assert len(results) == 1
            assert results[0]["score"] == 0.92
            assert "microservices" in results[0]["content"]

    @pytest.mark.asyncio
    async def test_rag_service_produces_answer_with_sources(self, mock_services):
        """Step 3: RAGService generates an answer from search results."""
        with (
            patch(
                "apps.api.services.rag.llamaindex_service.OpenAI",
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
            from apps.api.services.rag.llamaindex_service import RAGService

            service = RAGService()
            service.client = mock_services["openai"]
            service.embedding_service.client = mock_services["openai"]

            result = await service.process_query(
                "What architecture does the system use?"
            )

            assert "answer" in result
            assert "sources" in result
            assert len(result["answer"]) > 0
            assert result["conversation_id"] is not None

    @pytest.mark.asyncio
    async def test_full_pipeline_upload_to_query(
        self, mock_services, sample_document_content
    ):
        """Step 4: Full pipeline - process document then query it."""
        with (
            patch(
                "apps.api.services.document.embeddings.OpenAI",
                return_value=mock_services["openai"],
            ),
            patch(
                "apps.api.services.document.vector_store.get_qdrant_client",
                return_value=mock_services["qdrant"],
            ),
            patch(
                "apps.api.services.rag.llamaindex_service.OpenAI",
                return_value=mock_services["openai"],
            ),
        ):
            from apps.api.services.document.embeddings import EmbeddingService
            from apps.api.services.document.processor import DocumentProcessor
            from apps.api.services.document.vector_store import VectorStoreService
            from apps.api.services.rag.llamaindex_service import RAGService

            # 1. Process document into chunks - write to temp file first
            processor = DocumentProcessor()
            processor.client = mock_services["openai"]

            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".txt", delete=False
            ) as f:
                f.write(sample_document_content)
                temp_path = f.name

            try:
                chunks = await processor.process_document(temp_path)
            finally:
                os.unlink(temp_path)

            assert len(chunks) > 0, "Document should produce at least 1 chunk"

            # 2. Generate embeddings for chunks
            embedding_service = EmbeddingService()
            embedding_service.client = mock_services["openai"]

            embeddings_data = []
            for i, chunk in enumerate(chunks):
                embedding = await embedding_service.generate_embedding(chunk["content"])
                embeddings_data.append(
                    {
                        "chunk_id": f"chunk-{i}",
                        "embedding": embedding,
                        "content": chunk["content"],
                        "metadata": chunk.get("metadata", {}),
                    }
                )

            assert len(embeddings_data) == len(chunks)
            assert all(len(e["embedding"]) == 1536 for e in embeddings_data)

            # 3. Store in vector store
            store = VectorStoreService()
            await store.store_embeddings("test-doc-id", embeddings_data)

            # 4. Query and get answer
            rag = RAGService()
            rag.client = mock_services["openai"]
            rag.embedding_service.client = mock_services["openai"]

            result = await rag.process_query("What components does the system have?")

            assert result["answer"], "RAG should produce a non-empty answer"
            assert "sources" in result
            assert result["conversation_id"]


class TestRAGEdgeCases:
    """Test error handling and edge cases in the RAG pipeline."""

    @pytest.mark.asyncio
    async def test_empty_query_still_returns_response(self, mock_services):
        """RAGService should handle empty search results gracefully."""
        # Configure search to return empty
        mock_services["qdrant"].search.return_value = []

        with (
            patch(
                "apps.api.services.rag.llamaindex_service.OpenAI",
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
            from apps.api.services.rag.llamaindex_service import RAGService

            service = RAGService()
            service.client = mock_services["openai"]
            service.embedding_service.client = mock_services["openai"]

            result = await service.process_query("nonexistent topic xyz")

            assert "answer" in result
            assert (
                "couldn't find" in result["answer"].lower() or len(result["answer"]) > 0
            )

    @pytest.mark.asyncio
    async def test_conversation_history_maintained(self, mock_services):
        """RAGService should maintain conversation context across queries."""
        with (
            patch(
                "apps.api.services.rag.llamaindex_service.OpenAI",
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
            from apps.api.services.rag.llamaindex_service import RAGService

            service = RAGService()
            service.client = mock_services["openai"]
            service.embedding_service.client = mock_services["openai"]

            # First query
            result1 = await service.process_query(
                "What is the architecture?", conversation_id="test-conv"
            )
            # Second query same conversation
            result2 = await service.process_query(
                "Tell me more about it", conversation_id="test-conv"
            )

            assert result1["conversation_id"] == "test-conv"
            assert result2["conversation_id"] == "test-conv"
            assert "test-conv" in service.conversation_history
            assert len(service.conversation_history["test-conv"]) == 2
