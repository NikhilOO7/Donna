"""
Tests for the MeetingHub WebSocket fan-out.

Uses a fake WebSocket so no network or app fixture is required.
"""

from typing import List
from unittest.mock import AsyncMock

import pytest

from apps.api.services.meeting.realtime import MeetingHub


class _FakeWS:
    """Minimal WebSocket-like object that records send_text calls."""

    def __init__(self, fail_after: int | None = None):
        self.accept = AsyncMock()
        self.sent: List[str] = []
        self.fail_after = fail_after

    async def send_text(self, text: str):
        if self.fail_after is not None and len(self.sent) >= self.fail_after:
            raise RuntimeError("fake socket closed")
        self.sent.append(text)


class TestMeetingHub:
    @pytest.mark.asyncio
    async def test_broadcast_with_no_subscribers_is_noop(self):
        hub = MeetingHub()
        await hub.broadcast("mid", {"type": "test"})  # must not raise

    @pytest.mark.asyncio
    async def test_subscribe_and_receive(self):
        hub = MeetingHub()
        ws = _FakeWS()
        await hub.connect("m1", ws)
        await hub.broadcast("m1", {"type": "nudge_created", "x": 1})
        assert len(ws.sent) == 1
        assert '"nudge_created"' in ws.sent[0]
        await hub.disconnect("m1", ws)

    @pytest.mark.asyncio
    async def test_broadcast_only_to_matching_meeting(self):
        hub = MeetingHub()
        a, b = _FakeWS(), _FakeWS()
        await hub.connect("m1", a)
        await hub.connect("m2", b)
        await hub.broadcast("m1", {"type": "x"})
        assert len(a.sent) == 1
        assert len(b.sent) == 0

    @pytest.mark.asyncio
    async def test_dead_socket_is_dropped(self):
        hub = MeetingHub()
        bad = _FakeWS(fail_after=0)  # fails on first send
        good = _FakeWS()
        await hub.connect("m1", bad)
        await hub.connect("m1", good)

        await hub.broadcast("m1", {"type": "x"})
        # Good socket received it; bad socket was removed
        assert len(good.sent) == 1
        # Second broadcast: only the good socket should remain
        await hub.broadcast("m1", {"type": "y"})
        assert len(good.sent) == 2
