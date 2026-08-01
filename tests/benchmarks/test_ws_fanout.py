"""
J4 — MeetingHub fan-out load sanity.

Benchmarks in-process delivery to a room of 50 sockets (the realistic
ceiling for one meeting) and asserts the latency budget from
docs/ARCHITECTURE.md: WS fan-out < 50ms per broadcast.

Redis is patched out so this measures the hub itself, not the network.
"""

import asyncio
import time
from unittest.mock import AsyncMock, patch

import pytest

from apps.api.services.meeting.realtime import MeetingHub

N_SOCKETS = 50
N_BROADCASTS = 100
BUDGET_MS_PER_BROADCAST = 50.0


class _FakeSocket:
    """Async no-op websocket that counts deliveries."""

    def __init__(self):
        self.received = 0

    async def accept(self):
        pass

    async def send_text(self, _payload: str):
        self.received += 1
        await asyncio.sleep(0)  # yield, like a real send would


@pytest.mark.asyncio
async def test_fanout_50_sockets_meets_latency_budget():
    hub = MeetingHub()
    meeting_id = "bench-meeting"

    sockets = [_FakeSocket() for _ in range(N_SOCKETS)]
    with patch.object(MeetingHub, "_get_redis", new=AsyncMock(return_value=None)):
        for i, ws in enumerate(sockets):
            role = "leader" if i % 2 == 0 else "participant"
            await hub.connect(meeting_id, ws, role=role, my_name=f"p{i}")

        start = time.perf_counter()
        for i in range(N_BROADCASTS):
            await hub.broadcast(
                meeting_id,
                {"type": "utterance_added", "utterance": {"text": f"msg {i}"}},
            )
        elapsed = time.perf_counter() - start

    per_broadcast_ms = (elapsed / N_BROADCASTS) * 1000
    assert per_broadcast_ms < BUDGET_MS_PER_BROADCAST, (
        f"fan-out took {per_broadcast_ms:.2f}ms per broadcast "
        f"(budget {BUDGET_MS_PER_BROADCAST}ms) across {N_SOCKETS} sockets"
    )
    # Non-nudge events reach every role
    assert all(ws.received == N_BROADCASTS for ws in sockets)


@pytest.mark.asyncio
async def test_fanout_respects_participant_privacy_at_scale():
    """Unshared nudges must reach leaders only, even under load."""
    hub = MeetingHub()
    meeting_id = "bench-privacy"

    leaders = [_FakeSocket() for _ in range(10)]
    participants = [_FakeSocket() for _ in range(40)]
    with patch.object(MeetingHub, "_get_redis", new=AsyncMock(return_value=None)):
        for ws in leaders:
            await hub.connect(meeting_id, ws, role="leader")
        for i, ws in enumerate(participants):
            await hub.connect(meeting_id, ws, role="participant", my_name=f"p{i}")

        for _ in range(20):
            await hub.broadcast(
                meeting_id,
                {
                    "type": "nudge_created",
                    "nudge": {"type": "insight", "pinned_at": None},
                },
            )

    assert all(ws.received == 20 for ws in leaders)
    assert all(ws.received == 0 for ws in participants)
