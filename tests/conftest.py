"""
Shared test fixtures for the Voice Document Intelligence test suite.
"""

import asyncio
import os
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from typing import AsyncGenerator

# Set test environment before importing app code
os.environ["APP_ENV"] = "test"
os.environ["POSTGRES_HOST"] = "localhost"
os.environ["REDIS_HOST"] = "localhost"
os.environ["QDRANT_HOST"] = "localhost"
os.environ["REQUIRE_API_KEY"] = "false"

from httpx import AsyncClient, ASGITransport


@pytest.fixture(scope="session")
def event_loop():
    """Create a session-scoped event loop."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def mock_openai_client():
    """Mock OpenAI client for embedding and chat tests."""
    client = MagicMock()

    # Mock embeddings
    mock_embedding_response = MagicMock()
    mock_embedding_data = MagicMock()
    mock_embedding_data.embedding = [0.1] * 1536
    mock_embedding_response.data = [mock_embedding_data]
    client.embeddings.create.return_value = mock_embedding_response

    # Mock chat completions
    mock_chat_response = MagicMock()
    mock_choice = MagicMock()
    mock_choice.message.content = '{"intent_type": "factual", "key_entities": [], "query_complexity": "simple"}'
    mock_chat_response.choices = [mock_choice]
    client.chat.completions.create.return_value = mock_chat_response

    return client


@pytest.fixture
def mock_async_openai_client():
    """Mock AsyncOpenAI client."""
    client = AsyncMock()

    # Mock embeddings
    mock_embedding_response = MagicMock()
    mock_embedding_data = MagicMock()
    mock_embedding_data.embedding = [0.1] * 1536
    mock_embedding_response.data = [mock_embedding_data]
    client.embeddings.create.return_value = mock_embedding_response

    # Mock chat completions
    mock_chat_response = MagicMock()
    mock_choice = MagicMock()
    mock_choice.message.content = "This is a test answer based on the document context."
    mock_chat_response.choices = [mock_choice]
    client.chat.completions.create.return_value = mock_chat_response

    return client


@pytest.fixture
def mock_qdrant_client():
    """Mock Qdrant client for vector store tests."""
    client = AsyncMock()

    # Mock get_collections
    mock_collections = MagicMock()
    mock_collections.collections = []
    client.get_collections.return_value = mock_collections

    # Mock create_collection
    client.create_collection.return_value = True

    # Mock upsert
    client.upsert.return_value = True

    # Mock search
    mock_result = MagicMock()
    mock_result.id = "test-chunk-id"
    mock_result.score = 0.95
    mock_result.payload = {
        "document_id": "test-doc-id",
        "content": "Test content from document",
        "metadata": {"section": "Introduction"},
    }
    client.search.return_value = [mock_result]

    return client


@pytest.fixture
def mock_redis_client():
    """Mock Redis client."""
    client = AsyncMock()
    client.ping.return_value = True
    client.get.return_value = None
    client.set.return_value = True
    return client


@pytest.fixture
def sample_document_content():
    """Sample document text for testing."""
    return """
    # Test Document: Software Architecture

    ## Introduction
    This document describes the architecture of a modern software system.

    ## Components
    The system consists of three main components:
    1. Frontend - React-based web application
    2. Backend - FastAPI Python server
    3. Database - PostgreSQL for persistent storage

    ## Security
    All API endpoints are protected with API key authentication.
    Data is encrypted at rest and in transit.
    """


@pytest.fixture
def sample_chunks():
    """Sample document chunks for testing."""
    return [
        {
            "content": "This document describes the architecture of a modern software system.",
            "chunk_index": 0,
            "metadata": {"section": "Introduction", "word_count": 10},
        },
        {
            "content": "The system consists of three main components: Frontend, Backend, Database.",
            "chunk_index": 1,
            "metadata": {"section": "Components", "word_count": 10},
        },
        {
            "content": "All API endpoints are protected with API key authentication.",
            "chunk_index": 2,
            "metadata": {"section": "Security", "word_count": 9},
        },
    ]
