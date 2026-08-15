#!/usr/bin/env python3
"""
Load and latency harness.

The architecture claimed "< 2s to first insight" and "< 12s for LLM nudges".
Those were *structural* bounds — the agent timeouts guarantee them — but the
number a user experiences also includes the POST, the queue hop, state
loading, persistence and WebSocket delivery, and that chain had never been
timed. Instrumentation for it now exists (`first_nudge_seconds`,
`nudge_end_to_end_seconds`, `dispatch_queue_wait_seconds`); this script is
what puts load through it and reads the result.

It drives the real HTTP API — not the dispatcher in-process — so everything
between "words exist" and "nudge on screen" is included, including the parts
that only misbehave under concurrency.

    # single meeting, 60 utterances
    uv run python scripts/loadtest.py --utterances 60

    # 5 concurrent meetings — the interesting case: per-meeting locks,
    # queue contention, pool pressure
    uv run python scripts/loadtest.py --meetings 5 --utterances 40

    # against a multi-replica stack
    uv run python scripts/loadtest.py --base-url http://localhost:8000 --meetings 10

Reports observed p50/p95/p99 from the server's own histograms, and separately
the client-side POST latency, because a divergence between the two localises
the problem to the network/LB rather than the app.
"""

from __future__ import annotations

import argparse
import asyncio
import random
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

SEED = 20260813

FILLER = [
    "Right, where are we on the integration work?",
    "I looked at the numbers this morning and they seem fine.",
    "That makes sense to me, no objections.",
    "Let me pull up the document and share my screen.",
    "Yeah, the team has been heads down on that this sprint.",
    "Sorry, go ahead — you were saying?",
]
DECISIONS = [
    "Let's go with Acme Systems for the integration.",
    "Agreed, we'll ship the migration on June 1.",
    "Locking this in: Priya owns the rollout.",
]
CLAIMS = [
    "Revenue grew 15% year over year according to their filing.",
    "They raised about fifty million last year.",
    "Churn dropped from 2.1% to 1.4% after the redesign.",
]


def _utterance(rng: random.Random, decision_rate: float, claim_rate: float) -> str:
    r = rng.random()
    if r < decision_rate:
        return rng.choice(DECISIONS)
    if r < decision_rate + claim_rate:
        return rng.choice(CLAIMS)
    return rng.choice(FILLER)


def _pct(values: List[float], p: float) -> float:
    if not values:
        return float("nan")
    s = sorted(values)
    k = max(0, min(len(s) - 1, int(round((p / 100.0) * (len(s) - 1)))))
    return s[k]


async def _scrape_histograms(client, base_url: str) -> Dict[str, Dict[str, float]]:
    """Read the server's own histograms — the authoritative numbers.

    Client-side timing measures the POST only; the server histograms measure
    the whole pipeline through to WS broadcast, which is the claim under test.
    """
    out: Dict[str, Dict[str, float]] = {}
    try:
        resp = await client.get(f"{base_url}/metrics", timeout=10)
        for line in resp.text.splitlines():
            if line.startswith("#") or not line.strip():
                continue
            for metric in (
                "first_nudge_seconds",
                "nudge_end_to_end_seconds",
                "dispatch_queue_wait_seconds",
            ):
                if line.startswith(f"{metric}_sum") or line.startswith(
                    f"{metric}_count"
                ):
                    key = "sum" if "_sum" in line.split("{")[0] else "count"
                    try:
                        value = float(line.rsplit(" ", 1)[1])
                    except (IndexError, ValueError):
                        continue
                    out.setdefault(metric, {})
                    out[metric][key] = out[metric].get(key, 0.0) + value
    except Exception as e:
        print(f"  (could not scrape /metrics: {e})")
    return out


async def run_meeting(
    client,
    base_url: str,
    token: Optional[str],
    index: int,
    n_utterances: int,
    decision_rate: float,
    claim_rate: float,
    pace_ms: int,
) -> Dict[str, Any]:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    rng = random.Random(SEED + index)

    r = await client.post(
        f"{base_url}/api/v1/meetings/",
        json={"title": f"Load test meeting {index}", "description": "loadtest"},
        headers=headers,
        timeout=30,
    )
    if r.status_code >= 400:
        return {"error": f"create failed {r.status_code}: {r.text[:200]}"}
    meeting_id = (r.json() or {}).get("id") or (r.json() or {}).get("meeting_id")
    if not meeting_id:
        return {"error": f"no meeting id in response: {r.text[:200]}"}

    await client.post(
        f"{base_url}/api/v1/meetings/{meeting_id}/start", headers=headers, timeout=30
    )

    post_latencies: List[float] = []
    errors = 0
    for i in range(n_utterances):
        text = _utterance(rng, decision_rate, claim_rate)
        t0 = time.perf_counter()
        try:
            resp = await client.post(
                f"{base_url}/api/v1/meetings/{meeting_id}/utterances",
                json={"speaker": f"Speaker {(i % 3) + 1}", "text": text},
                headers=headers,
                timeout=30,
            )
            post_latencies.append(time.perf_counter() - t0)
            if resp.status_code >= 400:
                errors += 1
        except Exception:
            errors += 1
        if pace_ms:
            # Real speech is paced. Firing flat-out measures a burst, which is
            # a different (and less representative) question.
            await asyncio.sleep(pace_ms / 1000.0)

    return {
        "meeting_id": meeting_id,
        "posted": len(post_latencies),
        "errors": errors,
        "post_latencies": post_latencies,
    }


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base-url", default="http://localhost:8000")
    ap.add_argument("--meetings", type=int, default=1)
    ap.add_argument("--utterances", type=int, default=40)
    ap.add_argument("--decision-rate", type=float, default=0.08)
    ap.add_argument("--claim-rate", type=float, default=0.08)
    ap.add_argument(
        "--pace-ms", type=int, default=250, help="delay between utterances (0 = burst)"
    )
    ap.add_argument("--email", help="login email (omit if REQUIRE_AUTH=false)")
    ap.add_argument("--password")
    ap.add_argument(
        "--settle-seconds",
        type=int,
        default=20,
        help="wait after the last utterance for cycles to finish",
    )
    args = ap.parse_args()

    try:
        import httpx
    except ImportError:
        print("httpx is required: uv add httpx", file=sys.stderr)
        return 2

    async with httpx.AsyncClient() as client:
        # Health first — a load test against a degraded stack measures the
        # degradation, not the system.
        try:
            h = await client.get(f"{args.base_url}/health", timeout=10)
            health = h.json()
            print(f"health: {health.get('status')}")
            for name, state in (health.get("services") or {}).items():
                if isinstance(state, str) and state not in (
                    "healthy",
                    "in_sync",
                    "separate_process",
                ):
                    print(f"  ⚠ {name}: {state}")
        except Exception as e:
            print(f"cannot reach {args.base_url}: {e}", file=sys.stderr)
            return 1

        token = None
        if args.email and args.password:
            r = await client.post(
                f"{args.base_url}/api/v1/auth/login",
                json={"email": args.email, "password": args.password},
                timeout=30,
            )
            if r.status_code >= 400:
                print(f"login failed: {r.status_code} {r.text[:200]}", file=sys.stderr)
                return 1
            token = r.json().get("access_token")

        before = await _scrape_histograms(client, args.base_url)

        total = args.meetings * args.utterances
        print(
            f"\ndriving {args.meetings} meeting(s) x {args.utterances} utterances "
            f"= {total} total, pace={args.pace_ms}ms"
        )
        t0 = time.perf_counter()
        results = await asyncio.gather(
            *[
                run_meeting(
                    client,
                    args.base_url,
                    token,
                    i,
                    args.utterances,
                    args.decision_rate,
                    args.claim_rate,
                    args.pace_ms,
                )
                for i in range(args.meetings)
            ]
        )
        wall = time.perf_counter() - t0

        failed = [r for r in results if r.get("error")]
        for f in failed:
            print(f"  meeting error: {f['error']}")

        print(f"\nwaiting {args.settle_seconds}s for dispatch cycles to finish…")
        await asyncio.sleep(args.settle_seconds)
        after = await _scrape_histograms(client, args.base_url)

        # ---- report -----------------------------------------------------
        posts = [x for r in results for x in r.get("post_latencies", [])]
        errors = sum(r.get("errors", 0) for r in results)

        print("\n" + "=" * 66)
        print("LOAD TEST RESULT")
        print("=" * 66)
        print(f"  meetings              : {args.meetings}")
        print(f"  utterances posted     : {len(posts)}/{total}")
        print(f"  errors                : {errors}")
        print(f"  wall clock            : {wall:.1f}s")
        if posts:
            print("\n  CLIENT-SIDE POST latency (accept path only):")
            print(
                f"    p50 {_pct(posts, 50) * 1000:7.1f}ms   "
                f"p95 {_pct(posts, 95) * 1000:7.1f}ms   "
                f"p99 {_pct(posts, 99) * 1000:7.1f}ms   "
                f"max {max(posts) * 1000:7.1f}ms"
            )
            print(f"    mean {statistics.fmean(posts) * 1000:.1f}ms")

        print("\n  SERVER-SIDE pipeline latency (delta over this run):")
        any_server = False
        for metric in (
            "first_nudge_seconds",
            "nudge_end_to_end_seconds",
            "dispatch_queue_wait_seconds",
        ):
            b, a = before.get(metric, {}), after.get(metric, {})
            dc = a.get("count", 0) - b.get("count", 0)
            ds = a.get("sum", 0.0) - b.get("sum", 0.0)
            if dc > 0:
                any_server = True
                print(f"    {metric:<28} n={int(dc):<5} mean={ds / dc:.2f}s")
            else:
                print(f"    {metric:<28} n=0     (no observations)")
        if not any_server:
            print("      ⚠ No server-side observations. Either no nudges fired")
            print("        (gates closed — expected for filler-only transcripts),")
            print("        or USE_JOB_QUEUE=true with no dispatch-worker running.")
            print("        Check /health -> services.dispatch_queue.")

        print("\n  For exact percentiles, query Prometheus directly:")
        print("    histogram_quantile(0.95, rate(first_nudge_seconds_bucket[5m]))")
        print("=" * 66)

        # SLO check against docs/SLO.md
        fn = after.get("first_nudge_seconds", {})
        fnb = before.get("first_nudge_seconds", {})
        n = fn.get("count", 0) - fnb.get("count", 0)
        if n > 0:
            mean = (fn.get("sum", 0) - fnb.get("sum", 0)) / n
            target = 2.0
            verdict = "WITHIN" if mean <= target else "OVER"
            print(f"\n  SLO first-nudge (<{target}s): mean {mean:.2f}s — {verdict}")
            print("  (mean, not p95 — scrape the bucket series for the real p95)")

        return 1 if failed or errors else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
