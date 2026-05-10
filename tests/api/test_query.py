"""
API contract tests for the query/RAG endpoint.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestQueryEndpoint:
    """Tests for POST /api/v1/query"""

    @pytest.mark.asyncio
    async def test_query_returns_200(self, client):
        """Valid query should return 200 with answer."""
        with (
            patch(
                "apps.api.main.get_conversation_history",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch("apps.api.main.append_message", new_callable=AsyncMock),
            patch("apps.api.main.track_event", new_callable=AsyncMock),
            patch(
                "apps.api.main.get_cached_response",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch("apps.api.main.set_cached_response", new_callable=AsyncMock),
        ):
            response = await client.post(
                "/api/v1/query",
                json={
                    "query": "What architecture does the system use?",
                    "use_enhanced": False,
                },
            )

            assert response.status_code == 200
            data = response.json()
            assert "answer" in data
            assert "sources" in data
            assert "conversation_id" in data
            assert len(data["answer"]) > 0

    @pytest.mark.asyncio
    async def test_query_empty_string_rejected(self, client):
        """Empty query should be rejected by validation."""
        response = await client.post(
            "/api/v1/query",
            json={
                "query": "",
            },
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_query_too_long_rejected(self, client):
        """Query exceeding max_length should be rejected."""
        response = await client.post(
            "/api/v1/query",
            json={
                "query": "x" * 2001,
            },
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_query_missing_field(self, client):
        """Missing required query field should return 422."""
        response = await client.post("/api/v1/query", json={})
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_query_with_conversation_id(self, client):
        """Query with conversation_id should load history."""
        with (
            patch(
                "apps.api.main.get_conversation_history",
                new_callable=AsyncMock,
                return_value=[
                    {"query": "previous question", "answer": "previous answer"}
                ],
            ),
            patch("apps.api.main.append_message", new_callable=AsyncMock),
            patch("apps.api.main.track_event", new_callable=AsyncMock),
            patch(
                "apps.api.main.get_cached_response",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch("apps.api.main.set_cached_response", new_callable=AsyncMock),
        ):
            response = await client.post(
                "/api/v1/query",
                json={
                    "query": "Tell me more",
                    "conversation_id": "conv-123",
                    "use_enhanced": False,
                },
            )

            assert response.status_code == 200
            data = response.json()
            assert data["conversation_id"] == "conv-123"

    @pytest.mark.asyncio
    async def test_query_cache_hit_returns_cached(self, client):
        """Cached query should return cached result without calling RAG."""
        cached = {
            "answer": "Cached answer",
            "sources": [],
            "conversation_id": "cached",
            "context_level": "document",
            "metadata": {},
        }

        with patch(
            "apps.api.main.get_cached_response",
            new_callable=AsyncMock,
            return_value=cached,
        ):
            response = await client.post(
                "/api/v1/query",
                json={
                    "query": "cached question",
                    "use_enhanced": False,
                },
            )

            assert response.status_code == 200
            data = response.json()
            assert data["answer"] == "Cached answer"

    @pytest.mark.asyncio
    async def test_query_context_levels(self, client):
        """Different context levels should be accepted."""
        for level in ["local", "document", "global"]:
            with (
                patch(
                    "apps.api.main.get_conversation_history",
                    new_callable=AsyncMock,
                    return_value=[],
                ),
                patch("apps.api.main.append_message", new_callable=AsyncMock),
                patch("apps.api.main.track_event", new_callable=AsyncMock),
                patch(
                    "apps.api.main.get_cached_response",
                    new_callable=AsyncMock,
                    return_value=None,
                ),
                patch("apps.api.main.set_cached_response", new_callable=AsyncMock),
            ):
                response = await client.post(
                    "/api/v1/query",
                    json={
                        "query": "test query",
                        "context_level": level,
                        "use_enhanced": False,
                    },
                )

                assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_query_max_results_validation(self, client):
        """max_results outside bounds should be rejected."""
        response = await client.post(
            "/api/v1/query",
            json={
                "query": "test",
                "max_results": 0,
            },
        )
        assert response.status_code == 422

        response = await client.post(
            "/api/v1/query",
            json={
                "query": "test",
                "max_results": 100,
            },
        )
        assert response.status_code == 422


class TestAnalyticsEndpoints:
    """Tests for analytics endpoints."""

    @pytest.mark.asyncio
    async def test_usage_analytics_returns_200(self, client):
        """Usage analytics should return document stats."""
        with (
            patch(
                "apps.api.services.document.document_service.document_service"
            ) as mock_ds,
            patch(
                "apps.api.main.get_event_stats",
                new_callable=AsyncMock,
                return_value={
                    "event_counts": {},
                    "latencies": {},
                    "period_hours": 24,
                },
            ),
        ):
            mock_stats = MagicMock()
            mock_stats.total_documents = 5
            mock_stats.total_chunks = 50
            mock_stats.total_entities = 100
            mock_stats.processing_status_counts = {"completed": 4, "failed": 1}
            mock_ds.get_document_stats = AsyncMock(return_value=mock_stats)

            response = await client.get("/api/v1/analytics/usage")

            assert response.status_code == 200
            data = response.json()
            assert "documents" in data
            assert data["documents"]["total"] == 5

    @pytest.mark.asyncio
    async def test_performance_analytics_returns_200(self, client):
        """Performance analytics should return latency data."""
        with patch(
            "apps.api.main.get_event_stats",
            new_callable=AsyncMock,
            return_value={
                "event_counts": {"query": 10},
                "latencies": {"query": {"avg_ms": 500, "p95_ms": 1200}},
                "period_hours": 24,
            },
        ):
            response = await client.get("/api/v1/analytics/performance")

            assert response.status_code == 200
            data = response.json()
            assert "average_latencies" in data
            assert "timestamp" in data
