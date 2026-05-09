"""
API contract tests for the health and metrics endpoints.
"""

import pytest


class TestHealthEndpoint:
    """Tests for GET /health"""

    @pytest.mark.asyncio
    async def test_health_returns_200(self, client):
        response = await client.get("/health")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_health_has_required_fields(self, client):
        response = await client.get("/health")
        data = response.json()
        assert "status" in data
        assert "services" in data
        assert "version" in data
        assert "timestamp" in data

    @pytest.mark.asyncio
    async def test_health_includes_circuit_breakers(self, client):
        response = await client.get("/health")
        data = response.json()
        assert "circuit_breakers" in data
        assert isinstance(data["circuit_breakers"], dict)

    @pytest.mark.asyncio
    async def test_health_status_is_valid(self, client):
        response = await client.get("/health")
        data = response.json()
        assert data["status"] in ("healthy", "degraded", "unhealthy")

    @pytest.mark.asyncio
    async def test_health_services_has_core_services(self, client):
        response = await client.get("/health")
        services = response.json()["services"]
        assert "database" in services
        assert "redis" in services
        assert "qdrant" in services

    @pytest.mark.asyncio
    async def test_health_no_auth_required(self, client):
        """Health endpoint should be accessible without API key."""
        response = await client.get("/health")
        assert response.status_code == 200


class TestMetricsEndpoint:
    """Tests for GET /metrics"""

    @pytest.mark.asyncio
    async def test_metrics_returns_200(self, client):
        response = await client.get("/metrics")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_metrics_returns_prometheus_format(self, client):
        response = await client.get("/metrics")
        content = response.text
        # Prometheus format contains HELP and TYPE directives
        assert "http_requests_total" in content or "HELP" in content

    @pytest.mark.asyncio
    async def test_metrics_no_auth_required(self, client):
        response = await client.get("/metrics")
        assert response.status_code == 200


class TestDemoEndpoint:
    """Tests for GET /api/v1/test/demo"""

    @pytest.mark.asyncio
    async def test_demo_returns_200(self, client):
        response = await client.get("/api/v1/test/demo")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_demo_has_features(self, client):
        response = await client.get("/api/v1/test/demo")
        data = response.json()
        assert "features" in data or "message" in data
