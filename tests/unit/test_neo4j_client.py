"""
Tests for the Neo4j client wrapper.

We can't spin up Neo4j in unit tests, so these verify the graceful
degradation path: when the driver can't connect, every public method
returns ``None`` and the surface API never raises.
"""

import pytest

from apps.api.core.neo4j_client import Neo4jClient


class TestNeo4jClientFallback:
    @pytest.mark.asyncio
    async def test_disabled_short_circuits_execute(self, monkeypatch):
        client = Neo4jClient()
        client._unavailable = True  # simulate prior connect failure

        result = await client.execute("MATCH (n) RETURN n LIMIT 1")
        assert result is None
        assert client.enabled is False

    @pytest.mark.asyncio
    async def test_neo4j_disabled_setting_short_circuits(self, monkeypatch):
        monkeypatch.setattr(
            "apps.api.core.neo4j_client.settings",
            type(
                "S",
                (),
                {
                    "neo4j_enabled": False,
                    "neo4j_uri": "bolt://nowhere:7687",
                    "neo4j_user": "neo4j",
                    "neo4j_password": "x",
                    "neo4j_database": "neo4j",
                },
            )(),
        )
        client = Neo4jClient()
        result = await client.execute("RETURN 1")
        assert result is None
        assert await client.ensure_ready() is False

    @pytest.mark.asyncio
    async def test_unreachable_uri_marks_unavailable(self, monkeypatch):
        # Use a bolt URI that will fail fast — driver should mark the client
        # unavailable and the next execute() returns None without raising.
        monkeypatch.setattr(
            "apps.api.core.neo4j_client.settings",
            type(
                "S",
                (),
                {
                    "neo4j_enabled": True,
                    "neo4j_uri": "bolt://127.0.0.1:1",  # invalid port
                    "neo4j_user": "neo4j",
                    "neo4j_password": "x",
                    "neo4j_database": "neo4j",
                },
            )(),
        )
        client = Neo4jClient()
        result = await client.execute("RETURN 1")
        assert result is None
        assert client._unavailable is True
