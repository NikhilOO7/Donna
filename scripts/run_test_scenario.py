#!/usr/bin/env python3
"""
Drive the test corpus + meeting scenario end to end, and SCORE the result.

The difference from scripts/seed_meeting_demo.py: this one knows what is
supposed to happen. Each utterance in meeting_scenario.json declares which
agents it should trigger, so the output is a pass/fail per expectation rather
than a pile of nudges to read. It also checks the negative case — the
retrospective "last month we decided" line that must NOT produce a decision.

    # everything: upload corpus, run meeting, score
    uv run python scripts/run_test_scenario.py

    # skip ingestion if the corpus is already uploaded
    uv run python scripts/run_test_scenario.py --skip-upload

    # include the 35-page scanned PDF to exercise OCR (slow)
    uv run python scripts/run_test_scenario.py --include-scanned

Exit code is non-zero if a `must_fire` expectation was missed or the negative
case fired, so this is usable as a smoke test in a pipeline.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

SCENARIO = Path(__file__).parent / "meeting_scenario.json"
SCANNED_PDF = ROOT / "Donna - You are AUO, a proactive meeting collaborator.pdf"

C_OK, C_BAD, C_WARN, C_DIM, C_OFF = (
    "\033[32m",
    "\033[31m",
    "\033[33m",
    "\033[2m",
    "\033[0m",
)


def ok(m):
    print(f"  {C_OK}✓{C_OFF} {m}")


def bad(m):
    print(f"  {C_BAD}✗{C_OFF} {m}")


def warn(m):
    print(f"  {C_WARN}!{C_OFF} {m}")


def dim(m):
    print(f"  {C_DIM}{m}{C_OFF}")


class Runner:
    def __init__(self, base_url: str, token: Optional[str]):
        self.base = base_url.rstrip("/")
        self.headers = {"Authorization": f"Bearer {token}"} if token else {}
        self.client = None

    async def preflight(self) -> Dict[str, Any]:
        """A scenario run against a degraded stack measures the degradation."""
        r = await self.client.get(f"{self.base}/health", timeout=15)
        h = r.json()
        print(f"\nhealth: {h.get('status')}")
        for name, state in (h.get("services") or {}).items():
            if isinstance(state, str) and state not in (
                "healthy",
                "in_sync",
                "separate_process",
            ):
                warn(f"{name}: {state}")
            elif isinstance(state, dict) and state.get("status") != "healthy":
                warn(f"{name}: {state}")
        return h

    async def upload(self, paths: List[Path], meeting_id: Optional[str] = None):
        print("\n1. Ingesting corpus")
        doc_ids = []
        for p in paths:
            if not p.exists():
                bad(f"missing: {p}")
                continue
            with open(p, "rb") as fh:
                files = {"file": (p.name, fh, "application/octet-stream")}
                data = {"meeting_id": meeting_id} if meeting_id else {}
                try:
                    r = await self.client.post(
                        f"{self.base}/api/v1/documents/upload",
                        files=files,
                        data=data,
                        headers=self.headers,
                        timeout=180,
                    )
                except Exception as e:
                    bad(f"{p.name}: {e}")
                    continue
            if r.status_code >= 400:
                bad(f"{p.name}: {r.status_code} {r.text[:140]}")
                continue
            body = r.json()
            did = body.get("document_id") or body.get("id")
            doc_ids.append(did)
            ok(f"{p.name} → {body.get('processing_status', 'accepted')}")
        return doc_ids

    async def wait_for_processing(self, doc_ids: List[str], timeout: int = 300):
        """Processing is a cold path; querying before it finishes measures nothing."""
        print("\n2. Waiting for processing to complete")
        deadline = time.time() + timeout
        pending = set(filter(None, doc_ids))
        while pending and time.time() < deadline:
            for did in list(pending):
                try:
                    r = await self.client.get(
                        f"{self.base}/api/v1/documents/{did}",
                        headers=self.headers,
                        timeout=30,
                    )
                    st = (r.json() or {}).get("processing_status")
                    if st == "completed":
                        pending.discard(did)
                        ok(f"{did[:8]}… completed")
                    elif st == "failed":
                        pending.discard(did)
                        bad(f"{did[:8]}… FAILED")
                except Exception:
                    pass
            if pending:
                await asyncio.sleep(4)
        if pending:
            warn(f"{len(pending)} document(s) still processing after {timeout}s")

    async def create_meeting(self, spec: Dict[str, Any]) -> Optional[str]:
        print("\n3. Creating meeting")
        r = await self.client.post(
            f"{self.base}/api/v1/meetings/",
            json={
                "title": spec["title"],
                "description": spec["description"],
                "meeting_type": spec.get("meeting_type"),
                "agenda": spec.get("agenda"),
                "attendees": spec.get("attendees"),
            },
            headers=self.headers,
            timeout=60,
        )
        if r.status_code >= 400:
            bad(f"create failed: {r.status_code} {r.text[:200]}")
            return None
        mid = (r.json() or {}).get("id") or (r.json() or {}).get("meeting_id")
        ok(f"meeting {mid}")
        ok(
            f"{len(spec.get('agenda') or [])} agenda items, "
            f"{len(spec.get('attendees') or [])} attendees with expertise"
        )
        await self.client.post(
            f"{self.base}/api/v1/meetings/{mid}/start",
            headers=self.headers,
            timeout=30,
        )
        return mid

    async def research(self, mid: str, spec: Dict[str, Any]) -> bool:
        """Run the pre-meeting research pipeline so the insight agent has topics.

        Without a brief, insight has nothing to match against and correctly
        stays silent — so this is what makes that agent reachable at all.
        """
        print("\n3b. Pre-meeting research (for the insight agent)")
        try:
            r = await self.client.post(
                f"{self.base}/api/v1/meetings/{mid}/research",
                json={"title": spec["title"], "description": spec["description"]},
                headers=self.headers,
                timeout=300,
            )
        except Exception as e:
            warn(f"research call failed: {e}")
            return False
        if r.status_code >= 400:
            warn(f"research: {r.status_code} {r.text[:140]} (EXA_API_KEY set?)")
            return False
        # Poll until the brief completes — insight can't match a brief that
        # is still being written.
        deadline = time.time() + 240
        while time.time() < deadline:
            try:
                g = await self.client.get(
                    f"{self.base}/api/v1/meetings/{mid}/research",
                    headers=self.headers,
                    timeout=30,
                )
                body = g.json() if g.status_code < 400 else {}
                status = (body or {}).get("status")
                if status == "completed":
                    topics = (body or {}).get("topics") or []
                    ok(f"brief ready — {len(topics)} topic(s)")
                    return True
                if status == "failed":
                    warn("research failed")
                    return False
            except Exception:
                pass
            await asyncio.sleep(5)
        warn("research did not complete in time")
        return False

    async def run_transcript(
        self, mid: str, transcript: List[Dict[str, Any]], settle: float
    ) -> List[Dict[str, Any]]:
        print(f"\n4. Streaming {len(transcript)} utterances")
        seen: List[Dict[str, Any]] = []
        for i, turn in enumerate(transcript, 1):
            before = len(seen)
            r = await self.client.post(
                f"{self.base}/api/v1/meetings/{mid}/utterances",
                json={"speaker": turn["speaker"], "text": turn["text"]},
                headers=self.headers,
                timeout=60,
            )
            if r.status_code >= 400:
                bad(f"utterance {i}: {r.status_code} {r.text[:120]}")
                continue
            await asyncio.sleep(settle)
            seen = await self.fetch_nudges(mid)
            new = seen[before:]
            label = f"{i:>2}. {turn['speaker']:<14} {turn['text'][:56]}…"
            if new:
                agents = sorted({n.get("type") or n.get("nudge_type") for n in new})
                print(f"  {label}  {C_OK}→ {', '.join(a for a in agents if a)}{C_OFF}")
            else:
                print(f"  {label}  {C_DIM}→ —{C_OFF}")
            turn["_fired"] = sorted(
                {n.get("type") or n.get("nudge_type") for n in new if n}
            )
        return seen

    async def fetch_nudges(self, mid: str) -> List[Dict[str, Any]]:
        try:
            r = await self.client.get(
                f"{self.base}/api/v1/meetings/{mid}/nudges",
                headers=self.headers,
                timeout=30,
            )
            return (r.json() or {}).get("nudges", []) if r.status_code < 400 else []
        except Exception:
            return []

    async def finish(self, mid: str) -> Dict[str, Any]:
        print("\n5. Ending meeting + summary")
        await self.client.post(
            f"{self.base}/api/v1/meetings/{mid}/end", headers=self.headers, timeout=60
        )
        try:
            r = await self.client.post(
                f"{self.base}/api/v1/meetings/{mid}/summarize",
                headers=self.headers,
                timeout=240,
            )
            if r.status_code < 400:
                ok("summary generated")
            else:
                warn(f"summary: {r.status_code} {r.text[:120]}")
        except Exception as e:
            warn(f"summary failed: {e}")
        out = {}
        for name, path in (
            ("cost", f"/api/v1/meetings/{mid}/cost"),
            ("summary", f"/api/v1/meetings/{mid}/summary"),
        ):
            try:
                r = await self.client.get(
                    f"{self.base}{path}", headers=self.headers, timeout=60
                )
                if r.status_code < 400:
                    out[name] = r.json()
            except Exception:
                pass
        return out


def score(
    scenario: Dict[str, Any],
    nudges: List[Dict[str, Any]],
    ran: Optional[Dict[str, bool]] = None,
) -> int:
    """Compare what fired against what the scenario said should fire."""
    print("\n" + "=" * 72)
    print("SCORECARD")
    print("=" * 72)

    fired_types = {n.get("type") or n.get("nudge_type") for n in nudges}
    fired_types.discard(None)
    by_agent: Dict[str, int] = {}
    for n in nudges:
        t = n.get("type") or n.get("nudge_type")
        if t:
            by_agent[t] = by_agent.get(t, 0) + 1

    print(f"\n  {len(nudges)} nudge(s) total")
    for a, c in sorted(by_agent.items(), key=lambda kv: -kv[1]):
        print(f"    {a:<18} {c}")

    failures = 0
    a = scenario["assertions"]

    print("\n  Required:")
    for agent in a["must_fire"]:
        if agent in fired_types:
            ok(f"{agent} fired")
        else:
            bad(f"{agent} did NOT fire — this is a failure")
            failures += 1

    ran = ran or {}
    print("\n  Conditional (depend on config):")
    for key, need, gate in (
        ("should_fire_with_documents", "documents ingested", "documents"),
        ("should_fire_with_exa_key", "EXA_API_KEY", None),
        ("should_fire_with_neo4j", "Neo4j reachable", None),
        ("should_fire_with_research", "--research and EXA_API_KEY", "research"),
    ):
        for agent in a.get(key, []):
            if agent in fired_types:
                ok(f"{agent} fired")
            elif gate and ran.get(gate) is False:
                # Not exercised this run — silence is correct, not suspicious.
                dim(f"{agent} not exercised (no {gate} this run)")
            else:
                warn(f"{agent} silent — expected only if: {need}")

    # Negative case: the retrospective decision must not have produced a nudge.
    print("\n  Negative case (must NOT fire):")
    retro = [
        t
        for t in scenario["transcript"]
        if not t.get("expect") and "recap" in t["text"].lower()
    ]
    for t in retro:
        if "decision_prompt" in (t.get("_fired") or []) or "scribe" in (
            t.get("_fired") or []
        ):
            bad(
                "retrospective 'we decided' produced a decision nudge — "
                "the retrospective-exclusion fix has regressed"
            )
            failures += 1
        else:
            ok("retrospective reference correctly ignored")

    # Groundedness: any fact_check that was checked against its own sources.
    fc = [n for n in nudges if (n.get("type") or n.get("nudge_type")) == "fact_check"]
    if fc:
        print("\n  Fact-check groundedness (ADR-013):")
        for n in fc:
            g = (n.get("source_data") or {}).get("groundedness")
            rel = n.get("relevance_score")
            if g is None:
                dim("no groundedness report attached")
            elif g.get("label") == "supported":
                ok(f"explanation grounded (score {g.get('score')}), relevance {rel}")
            else:
                ok(
                    f"explanation {g.get('label')} → relevance capped at {rel} "
                    f"(< 0.8, so shown but never spoken)"
                )

    print("\n" + "=" * 72)
    if failures:
        print(f"{C_BAD}FAILED{C_OFF} — {failures} required expectation(s) missed")
    else:
        print(f"{C_OK}PASSED{C_OFF} — every required expectation met")
    print("=" * 72)
    return 1 if failures else 0


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base-url", default="http://localhost:8000")
    ap.add_argument("--email")
    ap.add_argument("--password")
    ap.add_argument("--skip-upload", action="store_true")
    ap.add_argument(
        "--research",
        action="store_true",
        help="run pre-meeting research first so the insight agent is reachable "
        "(needs EXA_API_KEY)",
    )
    ap.add_argument(
        "--include-scanned",
        action="store_true",
        help="also upload the 35-page image-only PDF (slow OCR path)",
    )
    ap.add_argument(
        "--settle",
        type=float,
        default=3.0,
        help="seconds to wait after each utterance for agents",
    )
    args = ap.parse_args()

    try:
        import httpx
    except ImportError:
        print("httpx required: uv add httpx", file=sys.stderr)
        return 2

    scenario = json.loads(SCENARIO.read_text())

    async with httpx.AsyncClient(follow_redirects=True) as client:
        token = None
        if args.email and args.password:
            r = await client.post(
                f"{args.base_url}/api/v1/auth/login",
                json={"email": args.email, "password": args.password},
                timeout=30,
            )
            if r.status_code >= 400:
                print(f"login failed: {r.text[:200]}", file=sys.stderr)
                return 1
            token = r.json().get("access_token")

        runner = Runner(args.base_url, token)
        runner.client = client

        try:
            await runner.preflight()
        except Exception as e:
            print(f"cannot reach {args.base_url}: {e}", file=sys.stderr)
            print("start it with ./run.sh (option 1) or:", file=sys.stderr)
            print("  uv run uvicorn apps.api.main:app --reload", file=sys.stderr)
            return 1

        mid = await runner.create_meeting(scenario["meeting"])
        if not mid:
            return 1

        if not args.skip_upload:
            paths = [ROOT / p for p in scenario["documents"]]
            if args.include_scanned and SCANNED_PDF.exists():
                paths.append(SCANNED_PDF)
                dim("including the 35-page scanned PDF — OCR will take minutes")
            doc_ids = await runner.upload(paths, meeting_id=mid)
            await runner.wait_for_processing(doc_ids)
        else:
            dim("skipping upload (--skip-upload)")

        ran = {"research": False, "documents": not args.skip_upload}
        if args.research:
            ran["research"] = await runner.research(mid, scenario["meeting"])

        nudges = await runner.run_transcript(mid, scenario["transcript"], args.settle)
        result = await runner.finish(mid)

        cost = result.get("cost") or {}
        if cost.get("calls"):
            print(
                f"\n  cost: ${cost.get('estimated_usd', 0):.4f} across "
                f"{cost['calls']} LLM call(s), {cost.get('total_tokens', 0):,} tokens"
            )
            for agent, tok in sorted(
                (cost.get("by_agent") or {}).items(), key=lambda kv: -kv[1]
            ):
                print(f"    {agent:<16} {tok:>7,} tokens")

        code = score(scenario, nudges, ran)
        print(f"\n  Open it: {args.base_url.replace('8000', '3000')}/meetings/{mid}")
        return code


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
