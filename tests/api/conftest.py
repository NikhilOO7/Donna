"""
Shared fixtures for API contract tests.

Uses httpx AsyncClient with ASGITransport to test FastAPI endpoints
without starting a real server. External services are mocked.
"""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest_asyncio

# Set test env before importing app
os.environ["APP_ENV"] = "test"
os.environ["REQUIRE_API_KEY"] = "false"
os.environ["LOG_FORMAT"] = "console"
os.environ["POSTGRES_HOST"] = "localhost"
os.environ["REDIS_HOST"] = "localhost"
os.environ["REDIS_PASSWORD"] = ""
os.environ["QDRANT_HOST"] = "localhost"

from httpx import ASGITransport, AsyncClient


@pytest_asyncio.fixture
async def mock_lifespan_services():
    """Mock all external services that lifespan() initializes."""
    # Mock database init
    with (
        patch("apps.api.main.init_db", new_callable=AsyncMock),
        patch("apps.api.main.init_redis", new_callable=AsyncMock),
        patch("apps.api.main.init_qdrant", new_callable=AsyncMock),
        patch("apps.api.main.init_storage", new_callable=AsyncMock),
        patch(
            "apps.api.main.check_db_health",
            new_callable=AsyncMock,
            return_value=True,
        ),
        patch("apps.api.main.get_redis_client", new_callable=AsyncMock) as mock_redis,
        patch("apps.api.main.get_qdrant_client", new_callable=AsyncMock) as mock_qdrant,
        patch("apps.api.main.get_storage_service") as mock_storage,
        patch("apps.api.main.get_db") as mock_get_db,
    ):
        # Mock Redis ping
        redis_client = AsyncMock()
        redis_client.ping.return_value = True
        redis_client.get.return_value = None
        redis_client.set.return_value = True
        redis_client.scan.return_value = (0, [])
        mock_redis.return_value = redis_client

        # Mock Qdrant
        qdrant_client = AsyncMock()
        mock_collections = MagicMock()
        mock_collections.collections = []
        qdrant_client.get_collections.return_value = mock_collections
        mock_qdrant.return_value = qdrant_client

        # Mock storage
        storage = MagicMock()
        storage.store_file = AsyncMock(
            return_value={
                "file_path": "/tmp/test.pdf",
                "storage_type": "local",
                "content_type": "application/pdf",
            }
        )
        mock_storage.return_value = storage

        # Mock DB session
        mock_session = AsyncMock()
        mock_session.commit = AsyncMock()
        mock_session.rollback = AsyncMock()
        mock_session.close = AsyncMock()

        async def fake_get_db():
            yield mock_session

        mock_get_db.side_effect = fake_get_db

        yield {
            "redis": redis_client,
            "qdrant": qdrant_client,
            "storage": storage,
            "session": mock_session,
        }


@pytest_asyncio.fixture
async def client(mock_lifespan_services):
    """Create an httpx AsyncClient bound to the FastAPI app."""
    from apps.api.core.dependencies import ServiceContainer
    from apps.api.core.rate_limit import limiter
    from apps.api.main import app

    # Disable rate limiting in tests
    limiter.enabled = False

    # Set up a mocked ServiceContainer on app.state so endpoints
    # that use DI (e.g. query_documents) can access services.
    mock_rag = MagicMock()
    mock_rag.process_query = AsyncMock(
        return_value={
            "answer": "Mocked answer from DI.",
            "sources": [],
            "conversation_id": "test",
        }
    )

    app.state.services = ServiceContainer(
        rag_service=mock_rag,
        modern_rag_service=mock_rag,
        voice_service=MagicMock(),
        enhanced_voice_service=MagicMock(sessions=[]),
        embedding_service=MagicMock(),
        vector_store=MagicMock(),
        modern_vector_store=MagicMock(),
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
