"""
Integration test for the utterance-append race fix (Phase A #1 / Phase B).

Exercises the REAL ``meeting_service.append_utterance`` against a live
Postgres with many concurrent writers (simulating overlapping speakers).
Asserts that every utterance survives — i.e. the per-meeting row lock
eliminates the lost-update race on the JSON utterances list.

Skips cleanly when no Postgres is reachable (so the default unit run and
Docker-less environments aren't affected). In CI the test job's Postgres
service makes this run for real.
"""

import asyncio
import os
import uuid

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("REDIS_HOST", "localhost")
os.environ.setdefault("QDRANT_HOST", "localhost")

import pytest
from sqlalchemy import delete, text

from apps.api.core.database import AsyncSessionLocal, Base, engine
from apps.api.models.meeting import Meeting, MeetingTranscript
from apps.api.models.user import User  # noqa: F401 — register FK target for create_all
from apps.api.services.meeting.meeting_service import meeting_service


async def _postgres_reachable() -> bool:
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


@pytest.mark.asyncio
async def test_concurrent_appends_lose_no_utterances():
    if not await _postgres_reachable():
        pytest.skip("Postgres not reachable — skipping DB integration test")

    # Ensure schema + tables exist (idempotent).
    async with engine.begin() as conn:
        await conn.execute(text("CREATE SCHEMA IF NOT EXISTS doc_intel"))
        await conn.run_sync(Base.metadata.create_all)

    meeting_id = uuid.uuid4()

    # Create the meeting row the appends will lock on.
    async with AsyncSessionLocal() as session:
        session.add(
            Meeting(
                id=meeting_id,
                title="Concurrency test",
                attendees=[],
                status="in_progress",
            )
        )
        await session.commit()

    n = 40  # concurrent overlapping "speakers"

    async def append_one(i: int):
        # Each writer uses its own session, like separate requests/tasks do.
        async with AsyncSessionLocal() as s:
            await meeting_service.append_utterance(
                session=s,
                meeting_id=meeting_id,
                speaker=f"spk{i % 4}",
                text=f"utterance number {i}",
            )

    try:
        await asyncio.gather(*(append_one(i) for i in range(n)))

        # Verify: exactly n utterances survived (no lost updates).
        async with AsyncSessionLocal() as s:
            transcript = await meeting_service.get_transcript(s, meeting_id)
            assert transcript is not None
            utterances = transcript.utterances or []
            assert len(utterances) == n, (
                f"expected {n} utterances, found {len(utterances)} "
                "— lost-update race regression"
            )
            # All unique texts present (no overwrites)
            texts = {u["text"] for u in utterances}
            assert len(texts) == n
    finally:
        # Cleanup test rows
        async with AsyncSessionLocal() as s:
            await s.execute(
                delete(MeetingTranscript).where(
                    MeetingTranscript.meeting_id == meeting_id
                )
            )
            await s.execute(delete(Meeting).where(Meeting.id == meeting_id))
            await s.commit()
