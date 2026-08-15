"""
Meeting Memory Indexer — Donna's long-term memory.

After every meeting (live or imported), distills the conversation into
memory records and indexes them into the SAME vector space as documents,
so retrieval — Ask Donna, the context agent, research grounding — draws
on everything the team has ever discussed, not just what it uploaded.

Record kinds:

* ``summary``    — the executive summary
* ``decision``   — each decision, with its verbatim conversation trigger
* ``transcript`` — windowed slices of the raw conversation
* ``fact``       — LLM-extracted durable facts/commitments/preferences,
                   each carrying the exact quote it came from

Every record carries a **citation** (meeting title + date + quote) so any
insight built on it can say exactly where the knowledge came from.
All indexing is best-effort: memory must never fail a summary.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_TRANSCRIPT_WINDOW_CHARS = 700
_MAX_FACTS = 10


def build_memory_records(
    meeting_id: str,
    meeting_title: str,
    meeting_date: Optional[str],
    summary_text: str,
    decisions: List[Dict[str, Any]],
    utterances: List[Dict[str, Any]],
    facts: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Shape meeting knowledge into indexable records. Pure → unit-testable."""
    date = meeting_date or datetime.now(timezone.utc).date().isoformat()

    def _meta(kind: str, **extra: Any) -> Dict[str, Any]:
        return {
            "source_type": "meeting_memory",
            "memory_kind": kind,
            "meeting_id": str(meeting_id),
            "meeting_title": meeting_title,
            "meeting_date": date,
            **{k: v for k, v in extra.items() if v},
        }

    records: List[Dict[str, Any]] = []

    if summary_text and not summary_text.startswith("Summary generation failed"):
        records.append(
            {
                "content": f"Summary of meeting '{meeting_title}': {summary_text}",
                "metadata": _meta("summary"),
            }
        )

    for d in decisions or []:
        text = d.get("decision_text") or d.get("decision") or ""
        if not text.strip():
            continue
        parts = [f"Decision in meeting '{meeting_title}': {text}"]
        if d.get("owner") and d["owner"] != "TBD":
            parts.append(f"Owner: {d['owner']}.")
        if d.get("deadline") and str(d["deadline"]) != "TBD":
            parts.append(f"Deadline: {d['deadline']}.")
        records.append(
            {
                "content": " ".join(parts),
                "metadata": _meta("decision", quote=d.get("context")),
            }
        )

    # Transcript windows — keep speaker attribution inside the content
    window: List[str] = []
    window_len = 0
    for u in utterances or []:
        line = f"{u.get('speaker', 'Speaker')}: {u.get('text', '')}"
        window.append(line)
        window_len += len(line)
        if window_len >= _TRANSCRIPT_WINDOW_CHARS:
            records.append(
                {
                    "content": f"From meeting '{meeting_title}':\n" + "\n".join(window),
                    "metadata": _meta("transcript"),
                }
            )
            window, window_len = [], 0
    if window:
        records.append(
            {
                "content": f"From meeting '{meeting_title}':\n" + "\n".join(window),
                "metadata": _meta("transcript"),
            }
        )

    for f in (facts or [])[:_MAX_FACTS]:
        fact = (f.get("fact") or "").strip()
        if not fact:
            continue
        records.append(
            {
                "content": fact,
                "metadata": _meta(
                    "fact", quote=f.get("quote"), speaker=f.get("speaker")
                ),
            }
        )

    return records


class MemoryIndexer:
    """Distill + embed + store meeting knowledge (best-effort)."""

    async def extract_facts(
        self, meeting_title: str, transcript_text: str, summary_text: str
    ) -> List[Dict[str, Any]]:
        """LLM extraction of durable facts worth remembering across meetings."""
        if not transcript_text and not summary_text:
            return []
        try:
            from apps.api.core import json_parse, llm_provider
            from apps.api.core.config import settings

            client = llm_provider.failover_client()
            response = await client.chat.completions.create(
                model=settings.model_fast,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Extract durable, atomic facts from this meeting that "
                            "would be useful to remember in FUTURE meetings — "
                            "commitments, preferences, constraints, numbers, "
                            "relationships. Skip small talk and one-off logistics. "
                            "Each fact must include the verbatim quote it comes "
                            "from. Respond ONLY with JSON:\n"
                            '{"facts": [{"fact": "...", "quote": "...", '
                            '"speaker": "..."}]}'
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            f"Meeting: {meeting_title}\n\n"
                            f"Summary: {summary_text[:1500]}\n\n"
                            f"Transcript:\n{transcript_text[:6000]}"
                        ),
                    },
                ],
                temperature=0.2,
                max_tokens=1200,
            )
            content = (response.choices[0].message.content or "").strip()
            facts = json_parse.loads(content, {}).get("facts", [])
            return facts if isinstance(facts, list) else []
        except Exception as e:
            logger.info(f"[Memory] fact extraction skipped: {e}")
            return []

    async def index_meeting(
        self,
        meeting_id: str,
        meeting_title: str,
        summary_text: str,
        decisions: List[Dict[str, Any]],
        utterances: List[Dict[str, Any]],
        owner_id: Optional[str] = None,
        meeting_date: Optional[str] = None,
    ) -> int:
        """Index a finished meeting into the vector knowledge base."""
        try:
            transcript_text = "\n".join(
                f"{u.get('speaker', 'Speaker')}: {u.get('text', '')}"
                for u in utterances or []
            )
            facts = await self.extract_facts(
                meeting_title, transcript_text, summary_text
            )

            records = build_memory_records(
                meeting_id=meeting_id,
                meeting_title=meeting_title,
                meeting_date=meeting_date,
                summary_text=summary_text,
                decisions=decisions,
                utterances=utterances,
                facts=facts,
            )
            if not records:
                return 0

            from apps.api.services.document.contextual_processor import (
                ContextualEmbeddingGenerator,
            )
            from apps.api.services.document.vector_store import ModernVectorStore

            embedder = ContextualEmbeddingGenerator()
            vectors = await embedder._embed_batch([r["content"] for r in records])
            for record, vector in zip(records, vectors):
                record["embedding"] = vector

            store = ModernVectorStore()
            stored = await store.store_memory_records(
                meeting_id=str(meeting_id), records=records, owner_id=owner_id
            )
            logger.info(
                f"[Memory] indexed meeting {meeting_id}: {stored} records "
                f"({len(facts)} extracted facts)"
            )
            return stored
        except Exception as e:
            logger.warning(f"[Memory] indexing skipped for {meeting_id}: {e}")
            return 0


memory_indexer = MemoryIndexer()
