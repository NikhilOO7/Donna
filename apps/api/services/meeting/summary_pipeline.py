"""
Summary Pipeline.

Background task that aggregates meeting data, generates a structured
summary via GPT-4, and stores it in the database.
"""

import logging
from typing import Any, Callable, Coroutine, Dict, Optional

from apps.api.core.database import AsyncSessionLocal
from apps.api.models.meeting import ActionItem, MeetingSummary
from apps.api.services.meeting.summary_agent import SummaryAgent

logger = logging.getLogger(__name__)


class SummaryPipeline:
    """Orchestrates post-meeting summary generation."""

    def __init__(self):
        self.summary_agent = SummaryAgent()

    async def run(
        self,
        meeting_id: str,
        meeting_title: str,
        description: str,
        transcript_text: str,
        decisions: list,
        action_items: list,
        nudges: list,
        research_summary: str,
        notify: Optional[Callable[[Dict[str, Any]], Coroutine]] = None,
        owner_id: Optional[str] = None,
    ) -> None:
        """Generate and store meeting summary as a background task."""

        async def _notify(data: Dict[str, Any]):
            if notify:
                await notify({"meeting_id": meeting_id, **data})

        async with AsyncSessionLocal() as session:
            try:
                await _notify({"type": "summary_progress", "step": "generating"})

                logger.info(f"[Summary {meeting_id}] Generating summary...")
                result = await self.summary_agent.generate_summary(
                    meeting_title=meeting_title,
                    description=description,
                    transcript_text=transcript_text,
                    decisions=decisions,
                    action_items=action_items,
                    nudges=nudges,
                    research_summary=research_summary,
                    meeting_id=meeting_id,
                )

                await _notify({"type": "summary_progress", "step": "saving"})

                # Store summary
                summary = MeetingSummary(
                    meeting_id=meeting_id,
                    summary_text=result.get("executive_summary", ""),
                    key_insights=result.get("ai_insights_used", []),
                    decisions_summary=result.get("decisions_summary", []),
                )
                session.add(summary)

                # Persist LLM-extracted action items as real rows, deduped
                # against already-logged items (case-insensitive description).
                existing_desc = {
                    (a.get("description") or a.get("item") or "").strip().lower()
                    for a in (action_items or [])
                }
                existing_desc.discard("")
                new_items = 0
                for item in result.get("action_items", []) or []:
                    desc = (item.get("item") or item.get("description") or "").strip()
                    if not desc or desc.lower() in existing_desc:
                        continue
                    existing_desc.add(desc.lower())
                    priority = item.get("priority")
                    if priority not in ("high", "medium", "low"):
                        priority = "medium"
                    assignee = (item.get("assignee") or "").strip()
                    if not assignee or assignee.upper() in ("TBD", "UNASSIGNED"):
                        assignee = None
                    session.add(
                        ActionItem(
                            meeting_id=meeting_id,
                            description=desc,
                            assignee=assignee,
                            priority=priority,
                            status="pending",
                        )
                    )
                    new_items += 1

                await session.commit()
                if new_items:
                    logger.info(
                        f"[Summary {meeting_id}] Persisted {new_items} "
                        "extracted action items"
                    )

                # Mirror the completed meeting into the Neo4j knowledge graph as a
                # typed subgraph (Meeting → Decisions / ActionItems / ResearchTopics /
                # Transcript). Best-effort: a graph outage must not fail the summary.
                try:
                    from apps.api.services.document.knowledge_graph_service import (
                        knowledge_graph_service,
                    )

                    topics = [
                        d.get("decision") or d.get("decision_text") or ""
                        for d in result.get("key_discussion_points", [])
                    ]
                    await knowledge_graph_service.sync_meeting_to_neo4j(
                        meeting_id=meeting_id,
                        title=meeting_title,
                        status="completed",
                        decisions=result.get("decisions_summary", decisions),
                        action_items=result.get("action_items", action_items),
                        research_topics=[t for t in topics if t],
                        utterance_count=len(transcript_text.split())
                        if transcript_text
                        else 0,
                        owner_id=owner_id,
                    )
                except Exception as kg_err:
                    logger.warning(f"[Summary {meeting_id}] KG sync skipped: {kg_err}")

                # Long-term memory: distill this meeting into the vector
                # knowledge base so future meetings, Ask Donna, and the
                # context agent can draw on it — with citations back here.
                try:
                    from apps.api.services.meeting.memory_indexer import (
                        memory_indexer,
                    )

                    utterances = []
                    if transcript_text:
                        utterances = [
                            {
                                "speaker": line.split(":", 1)[0],
                                "text": line.split(":", 1)[1].strip(),
                            }
                            for line in transcript_text.splitlines()
                            if ":" in line
                        ]
                    await memory_indexer.index_meeting(
                        meeting_id=meeting_id,
                        meeting_title=meeting_title,
                        summary_text=result.get("executive_summary", ""),
                        decisions=decisions or result.get("decisions_summary", []),
                        utterances=utterances,
                        owner_id=owner_id,
                    )
                except Exception as mem_err:
                    logger.warning(
                        f"[Summary {meeting_id}] memory indexing skipped: {mem_err}"
                    )

                logger.info(f"[Summary {meeting_id}] Complete")
                await _notify({"type": "summary_completed"})

            except Exception as e:
                logger.error(f"[Summary {meeting_id}] Failed: {e}")
                # Store a failed summary so the UI can show the error
                try:
                    summary = MeetingSummary(
                        meeting_id=meeting_id,
                        summary_text=f"Summary generation failed: {e}",
                        key_insights=[],
                        decisions_summary=[],
                    )
                    session.add(summary)
                    await session.commit()
                except Exception:
                    pass
                await _notify({"type": "summary_failed", "error": str(e)})


summary_pipeline = SummaryPipeline()
