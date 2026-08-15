#!/usr/bin/env python3
"""
Characterize what a meeting-hour actually costs.

The meter has always worked per meeting; what was missing was a
*representative* figure, so "a meeting-hour costs roughly X" stayed an
argument from mechanism rather than a fact. This script produces the fact.

It replays a transcript through the real dispatcher against a real meeting,
then reads the per-agent cost breakdown out of the Redis meter. Because it
uses the production path, the numbers include the gates: most utterances cost
nothing, which is the whole economic thesis and the thing an estimate from
call-counts would get wrong.

    # against a running stack, with a real transcript
    uv run python scripts/characterize-cost.py --transcript sample.txt

    # or synthesize a meeting of a given shape
    uv run python scripts/characterize-cost.py --utterances 120 --decision-rate 0.1

Honest caveat, printed with the result: a scripted transcript is unusually
decision-dense, which inflates exactly the agents that cost money. Treat the
output as an UPPER bound unless the transcript is genuinely representative.
"""

from __future__ import annotations

import argparse
import asyncio
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

# Deterministic by default so two runs are comparable.
SEED = 1234

FILLER = [
    "Right, so where are we on the integration work?",
    "I looked at the numbers this morning and they seem fine.",
    "Can you hear me okay? My connection is a bit flaky.",
    "That makes sense to me, no objections here.",
    "Let me pull up the document and share my screen.",
    "I think we covered that in the last session.",
    "Sorry, go ahead, you were saying?",
    "Yeah, the team has been heads down on that this sprint.",
]
DECISIONS = [
    "Let's go with Acme Systems for the integration work.",
    "Agreed, we'll ship the migration on June 1.",
    "The decision is to postpone the rewrite until Q3.",
    "I'll take the vendor evaluation and report back Friday.",
]
CLAIMS = [
    "Their platform is the fastest on the market right now.",
    "Revenue grew 15% year over year according to their filing.",
    "They raised a Series B of about fifty million last year.",
    "Churn dropped from 2.1% to 1.4% after the redesign.",
]


def synthesize(n: int, decision_rate: float, claim_rate: float) -> list[str]:
    rng = random.Random(SEED)
    out = []
    for _ in range(n):
        r = rng.random()
        if r < decision_rate:
            out.append(rng.choice(DECISIONS))
        elif r < decision_rate + claim_rate:
            out.append(rng.choice(CLAIMS))
        else:
            out.append(rng.choice(FILLER))
    return out


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--transcript", help="file with one utterance per line")
    ap.add_argument(
        "--utterances",
        type=int,
        default=120,
        help="synthesized utterance count (~1hr of speech)",
    )
    ap.add_argument("--decision-rate", type=float, default=0.06)
    ap.add_argument("--claim-rate", type=float, default=0.06)
    ap.add_argument("--meeting-id", help="existing meeting id; created if omitted")
    args = ap.parse_args()

    if args.transcript:
        lines = [
            ln.strip()
            for ln in Path(args.transcript).read_text().splitlines()
            if ln.strip()
        ]
        source = f"transcript {args.transcript}"
    else:
        lines = synthesize(args.utterances, args.decision_rate, args.claim_rate)
        source = (
            f"synthesized n={args.utterances} "
            f"decisions={args.decision_rate:.0%} claims={args.claim_rate:.0%}"
        )

    from apps.api.core.database import AsyncSessionLocal
    from apps.api.core.llm_meter import get_cost
    from apps.api.services.meeting.agent_dispatcher import agent_dispatcher
    from apps.api.services.meeting.meeting_service import meeting_service

    meeting_id = args.meeting_id
    if not meeting_id:
        async with AsyncSessionLocal() as session:
            meeting = await meeting_service.create_meeting(
                session, title="Cost characterization run", description=""
            )
            meeting_id = str(meeting.id)
        print(f"created meeting {meeting_id}")

    print(f"replaying {len(lines)} utterances ({source})…")
    from uuid import UUID

    for i, text in enumerate(lines, 1):
        async with AsyncSessionLocal() as session:
            await meeting_service.append_utterance(
                session=session,
                meeting_id=UUID(meeting_id),
                speaker=f"Speaker {(i % 3) + 1}",
                text=text,
            )
        await agent_dispatcher.dispatch(meeting_id)
        if i % 20 == 0:
            print(f"  {i}/{len(lines)}")

    cost = await get_cost(meeting_id)

    print("\n" + "=" * 62)
    print(f"COST CHARACTERIZATION — meeting {meeting_id}")
    print("=" * 62)
    print(f"  utterances replayed : {len(lines)}")
    print(f"  LLM calls           : {cost.get('calls', 0)}")
    print(f"  total tokens        : {cost.get('total_tokens', 0):,}")
    print(f"  estimated cost      : ${cost.get('estimated_usd', 0.0):.4f}")
    calls = cost.get("calls", 0) or 0
    print(f"  calls per utterance : {calls / max(1, len(lines)):.2f}")
    print(
        f"  cost per utterance  : ${cost.get('estimated_usd', 0.0) / max(1, len(lines)):.5f}"
    )
    print(
        f"  price table         : {cost.get('price_table_version')} "
        f"(current={cost.get('price_table_current')})"
    )
    if cost.get("unpriced_calls"):
        print(
            f"  ⚠ unpriced calls    : {cost['unpriced_calls']} (billed at gpt-4o fallback)"
        )

    by_agent = cost.get("by_agent") or {}
    if by_agent:
        print("\n  tokens by agent:")
        for agent, tokens in sorted(by_agent.items(), key=lambda kv: -kv[1]):
            share = tokens / max(1, cost.get("total_tokens", 1))
            print(f"    {agent:<14} {tokens:>8,}  {share:>5.1%}")

    print("\n  CAVEAT: a scripted transcript is unusually decision-dense, which")
    print("  inflates exactly the agents that cost money. Treat this as an UPPER")
    print("  bound unless the transcript is genuinely representative of real use.")
    print("=" * 62)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
