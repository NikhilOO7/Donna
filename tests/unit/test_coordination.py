"""
Tests for the distributed coordination primitives (Phase B).

Redis is forced unavailable so we exercise the in-process fallback path
deterministically (no running Redis needed). The Redis path shares the
same semantics — verified separately under load.
"""

import asyncio
import os

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("REDIS_HOST", "localhost")
os.environ.setdefault("QDRANT_HOST", "localhost")

import pytest

import apps.api.core.coordination as coord


@pytest.fixture(autouse=True)
def _force_local(monkeypatch):
    """Force the in-process fallback by making Redis look unavailable."""

    async def _no_redis():
        return None

    monkeypatch.setattr(coord, "_redis", _no_redis)
    # Clear local state between tests
    coord._LOCAL_COOLDOWNS.clear()
    coord._LOCAL_LOCKS.clear()
    yield


class TestCooldown:
    @pytest.mark.asyncio
    async def test_first_call_passes_second_blocked(self):
        assert await coord.cooldown_passed("k1", ttl_seconds=10) is True
        # Immediately again → still cooling down
        assert await coord.cooldown_passed("k1", ttl_seconds=10) is False

    @pytest.mark.asyncio
    async def test_distinct_keys_independent(self):
        assert await coord.cooldown_passed("a", 10) is True
        assert await coord.cooldown_passed("b", 10) is True

    @pytest.mark.asyncio
    async def test_expires_after_ttl(self):
        assert await coord.cooldown_passed("exp", ttl_seconds=0.05) is True
        assert await coord.cooldown_passed("exp", ttl_seconds=0.05) is False
        await asyncio.sleep(0.08)
        assert await coord.cooldown_passed("exp", ttl_seconds=0.05) is True


class TestDistributedLock:
    @pytest.mark.asyncio
    async def test_acquire_and_release(self):
        async with coord.distributed_lock("m1", wait=False) as acquired:
            assert acquired is True
        # After release, can acquire again
        async with coord.distributed_lock("m1", wait=False) as acquired2:
            assert acquired2 is True

    @pytest.mark.asyncio
    async def test_non_waiting_second_acquire_fails_while_held(self):
        async with coord.distributed_lock("m2", wait=False) as a1:
            assert a1 is True
            async with coord.distributed_lock("m2", wait=False) as a2:
                assert a2 is False

    @pytest.mark.asyncio
    async def test_serializes_concurrent_holders(self):
        """Two waiters on the same key must not hold simultaneously."""
        order = []

        async def worker(n):
            async with coord.distributed_lock("shared", wait=True, wait_timeout=2):
                order.append(("enter", n))
                await asyncio.sleep(0.05)
                order.append(("exit", n))

        await asyncio.gather(worker(1), worker(2))

        # Each enter must be immediately followed by its own exit (no interleave)
        assert order[0][0] == "enter"
        assert order[1][0] == "exit"
        assert order[1][1] == order[0][1]
        assert order[2][0] == "enter"
        assert order[3][0] == "exit"
        assert order[3][1] == order[2][1]
