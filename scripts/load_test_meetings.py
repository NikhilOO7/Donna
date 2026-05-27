#!/usr/bin/env python3
"""
Basic load test for the DURING-phase meeting hot path.

Drives N concurrent meetings, each with M "speakers" posting utterances
simultaneously, against a running backend. Validates two things the
Phase A/B work targets:

  1. **No lost utterances** — every posted utterance survives the
     concurrent JSON-append (the row-lock race fix).
  2. **Latency stays sane** — reports p50/p95/p99 for the
     ``POST /utterances`` endpoint under concurrency.

Usage:
    uv run python scripts/load_test_meetings.py \
        --base-url http://localhost:8000 --meetings 10 --speakers 4 --turns 5

The backend (and Postgres) must be running. Agent dispatch runs in the
background, so utterance POSTs should stay fast regardless of agent work.
"""

from __future__ import annotations

import argparse
import asyncio
import statistics
import time
from typing import List

import httpx


async def _create_meeting(client: httpx.AsyncClient, idx: int) -> str | None:
    r = await client.post(
        "/api/v1/meetings/",
        json={
            "title": f"Load test meeting {idx}",
            "description": "Concurrency load test",
            "attendees": [f"spk{i}" for i in range(4)],
        },
    )
    if r.status_code not in (200, 201):
        print(f"  ✗ create meeting {idx} failed: {r.status_code} {r.text[:120]}")
        return None
    data = r.json()
    mid = data.get("id") or data.get("meeting_id")
    if mid:
        await client.post(f"/api/v1/meetings/{mid}/start")
    return mid


async def _run_meeting(
    client: httpx.AsyncClient,
    meeting_id: str,
    speakers: int,
    turns: int,
    latencies: List[float],
) -> int:
    """Fire speakers×turns utterances with overlap; return count sent."""
    sent = 0

    async def speaker(s: int):
        nonlocal sent
        for t in range(turns):
            payload = {"speaker": f"spk{s}", "text": f"s{s} turn {t} ({meeting_id[:8]})"}
            start = time.monotonic()
            try:
                r = await client.post(
                    f"/api/v1/meetings/{meeting_id}/utterances", json=payload
                )
                latencies.append((time.monotonic() - start) * 1000)
                if r.status_code == 200:
                    sent += 1
            except Exception as e:
                print(f"  ✗ utterance error: {e}")
            await asyncio.sleep(0.01)  # slight stagger → realistic overlap

    await asyncio.gather(*(speaker(s) for s in range(speakers)))
    return sent


async def _verify_no_loss(
    client: httpx.AsyncClient, meeting_id: str, expected: int
) -> tuple[int, bool]:
    # Give background work a moment, then read the transcript back.
    await asyncio.sleep(1.0)
    r = await client.get(f"/api/v1/meetings/{meeting_id}/transcript")
    if r.status_code != 200:
        return 0, False
    got = len(r.json().get("utterances", []))
    return got, got == expected


async def main():
    parser = argparse.ArgumentParser(description="Meeting hot-path load test")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--meetings", type=int, default=10)
    parser.add_argument("--speakers", type=int, default=4)
    parser.add_argument("--turns", type=int, default=5)
    args = parser.parse_args()

    expected_per_meeting = args.speakers * args.turns
    latencies: List[float] = []

    async with httpx.AsyncClient(base_url=args.base_url, timeout=30.0) as client:
        print(
            f"Creating {args.meetings} meetings "
            f"({args.speakers} speakers × {args.turns} turns each)..."
        )
        meeting_ids = await asyncio.gather(
            *(_create_meeting(client, i) for i in range(args.meetings))
        )
        meeting_ids = [m for m in meeting_ids if m]
        if not meeting_ids:
            print("✗ No meetings created — is the backend running?")
            return

        print(f"Driving {len(meeting_ids)} meetings concurrently...")
        t0 = time.monotonic()
        sent_counts = await asyncio.gather(
            *(
                _run_meeting(client, m, args.speakers, args.turns, latencies)
                for m in meeting_ids
            )
        )
        elapsed = time.monotonic() - t0

        print("Verifying no utterances were lost...")
        results = await asyncio.gather(
            *(_verify_no_loss(client, m, expected_per_meeting) for m in meeting_ids)
        )

        total_sent = sum(sent_counts)
        losses = [
            (mid, got)
            for mid, (got, ok) in zip(meeting_ids, results)
            if not ok
        ]

        # -- Report --
        print("\n" + "=" * 60)
        print("LOAD TEST REPORT")
        print("=" * 60)
        print(f"Meetings:            {len(meeting_ids)}")
        print(f"Utterances sent:     {total_sent}")
        print(f"Wall time:           {elapsed:.2f}s")
        print(f"Throughput:          {total_sent / elapsed:.1f} utterances/s")
        if latencies:
            latencies.sort()
            print("POST /utterances latency (ms):")
            print(f"  p50: {statistics.median(latencies):.1f}")
            print(f"  p95: {latencies[int(len(latencies) * 0.95)]:.1f}")
            print(f"  p99: {latencies[int(len(latencies) * 0.99)]:.1f}")
            print(f"  max: {latencies[-1]:.1f}")
        if losses:
            print(f"\n✗ LOST UTTERANCES in {len(losses)} meeting(s):")
            for mid, got in losses[:5]:
                print(f"    {mid[:8]}: expected {expected_per_meeting}, got {got}")
            print("  → indicates a lost-update race regression")
        else:
            print(f"\n✓ No utterances lost — all {len(meeting_ids)} meetings intact")
        print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
