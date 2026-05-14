#!/usr/bin/env python3
"""
End-to-end Meeting Assistant demo seeder.

Walks the full lifecycle against a running API:
  1. Upload a sample knowledge-base document (PDF if --pdf is given,
     otherwise plain text — note: text won't exercise the layout/
     table/image agents)
  2. Create a meeting with a topic that overlaps the document
  3. Trigger pre-meeting research (if EXA_API_KEY is set)
  4. Start the meeting
  5. Stream a scripted set of utterances — agents fire after each one
  6. Wait for nudges to accumulate
  7. End the meeting + generate the post-meeting summary
  8. Print a final report with counts + sample nudges

Usage:
    uv run python scripts/seed_meeting_demo.py [--base-url http://localhost:8000]
    uv run python scripts/seed_meeting_demo.py --pdf path/to/file.pdf

Optional --skip-research suppresses the Exa call.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from typing import Any, Dict, List, Optional

import httpx

SAMPLE_DOC = {
    "filename": "vendor_evaluation.txt",
    "content": (
        "Vendor Evaluation Summary — Q2 Procurement\n"
        "\n"
        "Three vendors were assessed for the new search infrastructure:\n"
        "  • Vendor A (Acme Search) — strong query latency, weaker support SLAs.\n"
        "  • Vendor B (Beacon Cloud) — best-in-class compliance posture, mid-tier latency.\n"
        "  • Vendor C (CoreScale) — lowest annual cost but limited multi-region coverage.\n"
        "\n"
        "Acme's CEO, Jane Calder, has historically partnered with Beacon Cloud on\n"
        "joint compliance certifications. CoreScale spun out of Beacon in 2022.\n"
        "\n"
        "Recommendation: Vendor B aligns with our compliance roadmap and offers an\n"
        "acceptable latency / cost tradeoff. Final selection requires sign-off from\n"
        "the platform team by end of Q2.\n"
    ),
}

UTTERANCES = [
    ("Alice",   "Let's kick off the vendor selection review. We need to pick between Acme, Beacon, and CoreScale."),
    ("Bob",     "Our research shows Beacon's compliance posture is the strongest of the three."),
    ("Alice",   "Right — and CoreScale spun out of Beacon back in 2022, so there's lineage there."),
    ("Charlie", "Acme's CEO Jane Calder has co-certified with Beacon before, that's notable."),
    ("Bob",     "Latency-wise Acme is fastest but their support SLAs are weak."),
    ("Alice",   "Given the compliance roadmap pressure, let's go with Vendor B — Beacon Cloud."),
    ("Charlie", "Agreed. I'll take the action item to draft the contract by end of Q2."),
]


class DemoRunner:
    def __init__(
        self,
        base_url: str,
        skip_research: bool = False,
        pdf_path: Optional[str] = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.skip_research = skip_research
        self.pdf_path = pdf_path
        self.client = httpx.AsyncClient(base_url=self.base_url, timeout=120.0)

    async def close(self):
        await self.client.aclose()

    # ----- helpers ----------------------------------------------------

    async def _wait_until_ready(self, doc_id: str, timeout_s: int = 60) -> bool:
        start = time.monotonic()
        while time.monotonic() - start < timeout_s:
            r = await self.client.get(f"/api/v1/documents/{doc_id}")
            if r.status_code == 200 and r.json().get("processing_status") == "completed":
                return True
            await asyncio.sleep(1.5)
        return False

    async def _print_step(self, label: str):
        print(f"\n── {label} " + "─" * max(0, 60 - len(label)))

    # ----- pipeline steps --------------------------------------------

    async def upload_kb_doc(self) -> Optional[str]:
        await self._print_step("1. Uploading knowledge-base document")
        if self.pdf_path:
            from pathlib import Path

            p = Path(self.pdf_path)
            if not p.exists():
                print(f"  ✗ PDF not found: {self.pdf_path}")
                return None
            print(f"  → uploading PDF: {p.name}")
            with p.open("rb") as fh:
                files = {"file": (p.name, fh.read(), "application/pdf")}
        else:
            print("  → uploading synthetic text document (no table/image agents)")
            files = {
                "file": (SAMPLE_DOC["filename"], SAMPLE_DOC["content"], "text/plain")
            }
        r = await self.client.post("/api/v1/documents/upload", files=files)
        if r.status_code != 200:
            print(f"  ✗ Upload failed: {r.status_code} {r.text[:200]}")
            return None
        doc_id = r.json().get("document_id") or r.json().get("id")
        print(f"  ✓ document_id={doc_id}")

        if doc_id:
            print("  ⏳ waiting for processing to complete...")
            ok = await self._wait_until_ready(doc_id)
            print(f"  {'✓' if ok else '⚠'} processing {'complete' if ok else 'still running'}")
        return doc_id

    async def fetch_kg_stats(self, doc_id: str):
        await self._print_step("1a. Knowledge graph extraction")
        kg = (await self.client.get(f"/api/v1/documents/{doc_id}/knowledge-graph")).json()
        el = (await self.client.get(f"/api/v1/documents/{doc_id}/elements")).json()
        print(
            f"  ✓ {kg.get('node_count', 0)} entities, "
            f"{kg.get('edge_count', 0)} relationships, "
            f"{el.get('count', 0)} document elements (tables/images)"
        )

    async def create_meeting(self) -> Optional[str]:
        await self._print_step("2. Creating meeting")
        payload = {
            "title": "Q2 Vendor Selection Review",
            "description": (
                "Decide between Acme Search, Beacon Cloud, and CoreScale for "
                "our new search infrastructure. Compliance posture, latency, "
                "and Q2 budget are key constraints."
            ),
            "attendees": ["Alice", "Bob", "Charlie"],
        }
        r = await self.client.post("/api/v1/meetings/", json=payload)
        if r.status_code not in (200, 201):
            print(f"  ✗ Create failed: {r.status_code} {r.text[:200]}")
            return None
        meeting_id = r.json().get("id") or r.json().get("meeting_id")
        print(f"  ✓ meeting_id={meeting_id}")
        return meeting_id

    async def trigger_research(self, meeting_id: str):
        if self.skip_research:
            print("  ↷ (skipping research — --skip-research)")
            return
        await self._print_step("3. Triggering pre-meeting research")
        r = await self.client.post(f"/api/v1/meetings/{meeting_id}/research")
        print(f"  ✓ research triggered ({r.status_code})")
        # Poll for up to 60s
        for _ in range(40):
            await asyncio.sleep(1.5)
            m = (await self.client.get(f"/api/v1/meetings/{meeting_id}")).json()
            status = m.get("research", {}).get("status")
            if status in ("completed", "failed"):
                print(f"  ✓ research status: {status}")
                if status == "completed":
                    topics = m.get("research", {}).get("topics", [])
                    print(f"    {len(topics)} research topics extracted")
                return

    async def start_meeting(self, meeting_id: str):
        await self._print_step("4. Starting meeting")
        r = await self.client.post(f"/api/v1/meetings/{meeting_id}/start")
        print(f"  ✓ status={r.status_code}")

    async def stream_utterances(self, meeting_id: str):
        await self._print_step("5. Streaming scripted utterances")
        for speaker, text in UTTERANCES:
            r = await self.client.post(
                f"/api/v1/meetings/{meeting_id}/utterances",
                json={"speaker": speaker, "text": text},
            )
            mark = "✓" if r.status_code == 200 else "✗"
            print(f"  {mark} {speaker}: {text[:60]}{'…' if len(text) > 60 else ''}")
            # Give agents time to fire before next utterance
            await asyncio.sleep(2.0)

        print("  ⏳ waiting 4s for trailing agents...")
        await asyncio.sleep(4.0)

    async def end_meeting(self, meeting_id: str):
        await self._print_step("6. Ending meeting")
        r = await self.client.post(f"/api/v1/meetings/{meeting_id}/end")
        print(f"  ✓ status={r.status_code}")

    async def generate_summary(self, meeting_id: str):
        await self._print_step("7. Generating post-meeting summary")
        r = await self.client.post(f"/api/v1/meetings/{meeting_id}/summarize")
        print(f"  ✓ summary triggered ({r.status_code})")
        for _ in range(30):
            await asyncio.sleep(1.5)
            m = (await self.client.get(f"/api/v1/meetings/{meeting_id}")).json()
            if m.get("summary"):
                print("  ✓ summary ready")
                return

    async def final_report(self, meeting_id: str):
        await self._print_step("8. Final report")
        m = (await self.client.get(f"/api/v1/meetings/{meeting_id}")).json()
        nudges: List[Dict[str, Any]] = m.get("nudges") or []
        decisions: List[Dict[str, Any]] = m.get("decisions") or []
        summary = m.get("summary") or {}

        print(f"  Nudges generated: {len(nudges)}")
        types: Dict[str, int] = {}
        for n in nudges:
            types[n.get("type") or n.get("nudge_type") or "?"] = (
                types.get(n.get("type") or n.get("nudge_type") or "?", 0) + 1
            )
        for k, v in types.items():
            print(f"    {k}: {v}")

        print(f"  Decisions: {len(decisions)}")
        print(f"  Summary text length: {len(summary.get('summary_text', '') or '')} chars")

        if nudges:
            print("\n  Top 3 nudges:")
            for n in nudges[:3]:
                print(
                    f"   • [{n.get('type') or n.get('nudge_type')}] "
                    f"{n.get('title', '')}"
                )

    async def run(self):
        doc_id = await self.upload_kb_doc()
        if doc_id:
            await self.fetch_kg_stats(doc_id)

        meeting_id = await self.create_meeting()
        if not meeting_id:
            print("  ✗ Cannot continue without a meeting")
            return

        await self.trigger_research(meeting_id)
        await self.start_meeting(meeting_id)
        await self.stream_utterances(meeting_id)
        await self.end_meeting(meeting_id)
        await self.generate_summary(meeting_id)
        await self.final_report(meeting_id)

        print("\n✓ Demo run complete.")
        print(f"  Open the UI at http://localhost:3000 to view meeting {meeting_id}")


async def main():
    parser = argparse.ArgumentParser(description="Seed an end-to-end meeting demo")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--skip-research", action="store_true")
    parser.add_argument(
        "--pdf",
        help="Path to a PDF to upload (exercises layout/table/image agents). "
        "If omitted, a synthetic text doc is used.",
    )
    args = parser.parse_args()

    runner = DemoRunner(
        base_url=args.base_url,
        skip_research=args.skip_research,
        pdf_path=args.pdf,
    )
    try:
        await runner.run()
    except Exception as e:
        print(f"\n✗ Demo run errored: {e}")
        sys.exit(1)
    finally:
        await runner.close()


if __name__ == "__main__":
    asyncio.run(main())
