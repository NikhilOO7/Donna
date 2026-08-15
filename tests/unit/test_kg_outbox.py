"""
Knowledge-graph outbox tests.

The defect being pinned: Postgres and Neo4j were dual-written with no
reconciliation. A failed sync was logged as "KG sync skipped" and the graph
diverged permanently, invisibly. These tests assert the three properties that
make divergence impossible-or-visible: the intent is recorded, retries are
bounded and idempotent, and a permanent failure surfaces as a state rather
than a log line nobody reads.
"""

from unittest.mock import AsyncMock, patch

import pytest

from apps.api.models.outbox import (
    MAX_ATTEMPTS,
    STATUS_DONE,
    STATUS_FAILED,
    STATUS_PENDING,
    KGOutbox,
)
from apps.api.services.document import kg_outbox


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return self._rows


class _FakeSession:
    """Minimal async session: enough to exercise drain() without a database."""

    def __init__(self, rows=None):
        self.added = []
        self.committed = 0
        self._rows = rows or []

    def add(self, obj):
        self.added.append(obj)

    async def execute(self, *_a, **_k):
        return _FakeResult(self._rows)

    async def commit(self):
        self.committed += 1


def _entry(**kw):
    e = KGOutbox(
        operation=kg_outbox.OP_SYNC_MEETING,
        entity_type="meeting",
        entity_id="m-1",
        payload={"meeting_id": "m-1", "title": "Q2 Vendor Selection"},
        status=STATUS_PENDING,
        attempts=0,
    )
    for k, v in kw.items():
        setattr(e, k, v)
    return e


class TestEnqueue:
    async def test_enqueue_joins_the_callers_transaction(self):
        """It must NOT commit — atomicity with the source data is the point."""
        session = _FakeSession()
        await kg_outbox.enqueue_meeting_sync(
            session,
            meeting_id="m-1",
            title="Q2 Vendor Selection",
            status="completed",
            decisions=[{"decision": "pick Acme"}],
            action_items=[],
        )
        assert len(session.added) == 1
        assert session.committed == 0, (
            "enqueue must not commit; committing separately would reintroduce "
            "the dual-write window this pattern exists to close"
        )

    async def test_payload_is_self_contained(self):
        """Replay must not depend on re-reading mutable state."""
        session = _FakeSession()
        await kg_outbox.enqueue_meeting_sync(
            session,
            meeting_id="m-1",
            title="Q2",
            status="completed",
            decisions=[{"decision": "pick Acme"}],
            action_items=[{"description": "sign"}],
            research_topics=["vendor risk"],
            utterance_count=42,
        )
        p = session.added[0].payload
        assert p["decisions"] == [{"decision": "pick Acme"}]
        assert p["action_items"] == [{"description": "sign"}]
        assert p["research_topics"] == ["vendor risk"]
        assert p["utterance_count"] == 42


class TestDrain:
    async def test_noop_when_neo4j_disabled(self):
        """Neo4j is optional — entries wait rather than erroring."""
        session = _FakeSession([_entry()])
        with patch("apps.api.core.neo4j_client.neo4j_client") as client:
            client.enabled = False
            result = await kg_outbox.drain(session)
        assert result["applied"] == 0
        assert result["neo4j"] == 0

    async def test_successful_entry_marked_done(self):
        entry = _entry()
        session = _FakeSession([entry])
        with patch("apps.api.core.neo4j_client.neo4j_client") as client:
            client.enabled = True
            with patch.object(kg_outbox, "_apply", AsyncMock(return_value=3)):
                result = await kg_outbox.drain(session)
        assert result["applied"] == 1
        assert entry.status == STATUS_DONE
        assert entry.processed_at is not None
        assert entry.last_error is None

    async def test_transient_failure_stays_pending_for_retry(self):
        entry = _entry()
        session = _FakeSession([entry])
        with patch("apps.api.core.neo4j_client.neo4j_client") as client:
            client.enabled = True
            with patch.object(
                kg_outbox, "_apply", AsyncMock(side_effect=RuntimeError("neo4j down"))
            ):
                result = await kg_outbox.drain(session)
        assert result["failed"] == 1
        assert entry.status == STATUS_PENDING, "a transient failure must be retried"
        assert entry.attempts == 1
        assert "neo4j down" in entry.last_error

    async def test_permanent_failure_after_max_attempts(self):
        entry = _entry(attempts=MAX_ATTEMPTS - 1)
        session = _FakeSession([entry])
        with patch("apps.api.core.neo4j_client.neo4j_client") as client:
            client.enabled = True
            with patch.object(
                kg_outbox, "_apply", AsyncMock(side_effect=RuntimeError("bad cypher"))
            ):
                await kg_outbox.drain(session)
        assert entry.status == STATUS_FAILED
        assert entry.attempts == MAX_ATTEMPTS

    async def test_failed_entries_are_kept_not_deleted(self):
        """The row IS the record of divergence — deleting it restores the bug."""
        entry = _entry(attempts=MAX_ATTEMPTS - 1)
        session = _FakeSession([entry])
        with patch("apps.api.core.neo4j_client.neo4j_client") as client:
            client.enabled = True
            with patch.object(
                kg_outbox, "_apply", AsyncMock(side_effect=RuntimeError("x"))
            ):
                await kg_outbox.drain(session)
        assert entry.status == STATUS_FAILED
        assert entry.payload, "payload must survive so the write can be replayed"

    async def test_unknown_operation_is_rejected(self):
        entry = _entry(operation="not_a_real_operation")
        with pytest.raises(ValueError, match="unknown outbox operation"):
            await kg_outbox._apply(entry)
