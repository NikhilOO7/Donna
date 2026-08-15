"""
Research Pipeline Orchestrator.

Runs the 4-agent research pipeline:
  Topic Extraction → Search (parallel) → Validation → Synthesis

Updates ResearchBrief status and sends WebSocket progress notifications.
"""

import asyncio
import logging
from typing import Any, Callable, Coroutine, Dict, Optional

from sqlalchemy import select

from apps.api.core.database import AsyncSessionLocal
from apps.api.models.meeting import ResearchBrief
from apps.api.services.research.search_agent import SearchAgent
from apps.api.services.research.synthesis_agent import SynthesisAgent
from apps.api.services.research.topic_agent import TopicAgent
from apps.api.services.research.validation_agent import ValidationAgent

logger = logging.getLogger(__name__)


class ResearchPipeline:
    """Orchestrates the pre-meeting research workflow."""

    def __init__(self):
        self.topic_agent = TopicAgent()
        self.search_agent = SearchAgent()
        self.validation_agent = ValidationAgent()
        self.synthesis_agent = SynthesisAgent()

    @staticmethod
    async def _meeting_owner(session, meeting_id: str):
        """Owner of the meeting — the tenancy key for any data-connection read."""
        from sqlalchemy import select as _select

        from apps.api.models.meeting import Meeting

        row = await session.execute(
            _select(Meeting.owner_id).where(Meeting.id == meeting_id)
        )
        return row.scalar_one_or_none()

    @staticmethod
    async def _meeting_agenda(session, meeting_id: str):
        """Agenda item titles, which are what the query planner reasons over."""
        from sqlalchemy import select as _select

        from apps.api.models.meeting import Meeting

        row = await session.execute(
            _select(Meeting.agenda).where(Meeting.id == meeting_id)
        )
        agenda = row.scalar_one_or_none() or []
        return [
            a.get("title") for a in agenda if isinstance(a, dict) and a.get("title")
        ]

    async def run(
        self,
        meeting_id: str,
        title: str,
        description: str,
        notify: Optional[Callable[[Dict[str, Any]], Coroutine]] = None,
    ) -> None:
        """Execute the full research pipeline as a background task.

        Args:
            meeting_id: Meeting UUID string.
            title: Meeting title.
            description: Meeting description / brief.
            notify: Optional async callback for WebSocket notifications.
        """

        async def _notify(data: Dict[str, Any]):
            if notify:
                await notify({"meeting_id": meeting_id, **data})

        async with AsyncSessionLocal() as session:
            try:
                # Reuse the meeting's existing brief rather than inserting a
                # new one per run. Meeting.research_brief is declared
                # uselist=False, so a second row makes the relationship
                # ambiguous and SQLAlchemy returns an arbitrary one — in
                # practice the oldest. A re-run would then succeed while the UI
                # kept rendering the original failure forever, which looks
                # exactly like "the retry button does nothing".
                existing = (
                    (
                        await session.execute(
                            select(ResearchBrief)
                            .where(ResearchBrief.meeting_id == meeting_id)
                            .order_by(ResearchBrief.created_at.desc())
                        )
                    )
                    .scalars()
                    .first()
                )

                if existing:
                    brief = existing
                    brief.status = "researching"
                    brief.executive_summary = None
                    brief.topics = []
                    brief.source_count = 0
                else:
                    brief = ResearchBrief(meeting_id=meeting_id, status="researching")
                    session.add(brief)
                await session.commit()
                await session.refresh(brief)
                brief_id = brief.id

                await _notify(
                    {"type": "research_progress", "step": "extracting_topics"}
                )

                # Step 1: Extract topics
                logger.info(f"[Research {meeting_id}] Extracting topics...")
                topics = await self.topic_agent.extract_topics(title, description)
                if not topics:
                    await self._fail(session, brief_id, "No topics extracted")
                    await _notify(
                        {"type": "research_failed", "error": "No topics extracted"}
                    )
                    return

                await _notify(
                    {
                        "type": "research_progress",
                        "step": "searching",
                        "topic_count": len(topics),
                    }
                )

                # Step 2: Search (parallel per topic)
                logger.info(
                    f"[Research {meeting_id}] Searching {len(topics)} topics..."
                )
                search_tasks = [
                    self.search_agent.search_topic(
                        topic=t["topic"],
                        queries=t.get("search_queries", [t["topic"]]),
                    )
                    for t in topics
                ]
                search_results_list = await asyncio.gather(
                    *search_tasks, return_exceptions=True
                )

                # Map topic → results
                topic_sources: Dict[str, list] = {}
                total_sources = 0
                for topic_info, results in zip(topics, search_results_list):
                    if isinstance(results, Exception):
                        logger.warning(
                            f"Search failed for {topic_info['topic']}: {results}"
                        )
                        topic_sources[topic_info["topic"]] = []
                    else:
                        topic_sources[topic_info["topic"]] = results
                        total_sources += len(results)

                await _notify(
                    {
                        "type": "research_progress",
                        "step": "validating",
                        "source_count": total_sources,
                    }
                )

                # Step 3: Validate sources per topic
                logger.info(
                    f"[Research {meeting_id}] Validating {total_sources} sources..."
                )
                validated_sources: Dict[str, list] = {}
                for topic_name, sources in topic_sources.items():
                    validated = await self.validation_agent.validate_sources(
                        sources, top_n=5
                    )
                    validated_sources[topic_name] = validated

                validated_count = sum(len(v) for v in validated_sources.values())

                await _notify(
                    {
                        "type": "research_progress",
                        "step": "synthesizing",
                        "validated_count": validated_count,
                    }
                )

                # Step 3b: The customer's own database.
                #
                # This is the step that makes research useful when nobody
                # uploaded a document. Web sources describe the world; the
                # company's own data describes THEIR situation, which is what
                # an agenda item like "review vendor spend" actually needs.
                #
                # Cold path by design: agenda -> planned SQL -> guards ->
                # their database. Minutes-tolerant, fully audited, and never
                # on the critical path of a live conversation.
                db_findings = []
                try:
                    from apps.api.services.data_connection import (
                        service as data_service,
                    )

                    owner_id = await self._meeting_owner(session, meeting_id)
                    agenda_items = await self._meeting_agenda(session, meeting_id)
                    db_findings = await data_service.gather_for_meeting(
                        session,
                        owner_id,
                        title=title,
                        agenda=agenda_items or [t["topic"] for t in topics],
                        meeting_id=meeting_id,
                    )
                    if db_findings:
                        await _notify(
                            {
                                "type": "research_progress",
                                "step": "queried_your_database",
                                "finding_count": len(db_findings),
                            }
                        )
                except Exception as e:
                    # A database that is down, misconfigured or revoked must
                    # degrade the brief, never fail it.
                    logger.warning(
                        f"[Research {meeting_id}] customer database step skipped: {e}"
                    )

                # Step 4: Synthesize
                logger.info(f"[Research {meeting_id}] Synthesizing...")
                synthesis = await self.synthesis_agent.synthesize(
                    topics=topics,
                    validated_sources=validated_sources,
                    meeting_title=title,
                    meeting_id=meeting_id,
                )
                if db_findings:
                    # Attached rather than merged into `key_findings`: data
                    # from the customer's own systems is a different kind of
                    # evidence than a web source, and the UI should be able to
                    # say so (and show the exact SQL that produced it).
                    synthesis["database_findings"] = db_findings

                # Build topics data for storage. The synthesis agent's key
                # findings are attached to the topic whose sources back them
                # (matched by source URL); unmatched findings and data gaps go
                # into a synthetic cross-topic entry so nothing is dropped.
                all_findings = synthesis.get("key_findings", []) or []
                matched_idx: set = set()

                topics_data = []
                for topic_info in topics:
                    topic_name = topic_info["topic"]
                    t_sources = validated_sources.get(topic_name, [])
                    topic_urls = {s.get("url", "") for s in t_sources if s.get("url")}

                    topic_findings = []
                    for i, f in enumerate(all_findings):
                        if f.get("source_url") and f["source_url"] in topic_urls:
                            topic_findings.append(f)
                            matched_idx.add(i)

                    topics_data.append(
                        {
                            "topic": topic_name,
                            "rationale": topic_info.get("rationale", ""),
                            "key_findings": topic_findings,
                            "sources": [
                                {
                                    "url": s.get("url", ""),
                                    "title": s.get("title", ""),
                                    "excerpt": s.get("excerpt", ""),
                                    "tier": s.get("tier", 3),
                                    "credibility_score": s.get("credibility_score", 0),
                                }
                                for s in t_sources
                            ],
                        }
                    )

                unmatched = [
                    f for i, f in enumerate(all_findings) if i not in matched_idx
                ]
                data_gaps = synthesis.get("data_gaps", []) or []
                suggested = synthesis.get("suggested_topics", []) or []
                if unmatched or data_gaps or suggested:
                    topics_data.append(
                        {
                            "topic": "Cross-topic findings",
                            "rationale": "Findings that draw on multiple sources, plus data limitations.",
                            "key_findings": unmatched,
                            "data_gaps": data_gaps,
                            # H7 blind spots: adjacent topics the user didn't
                            # ask about but the sources suggest watching.
                            "suggested_topics": suggested,
                            "sources": [],
                        }
                    )

                # Update brief in DB
                brief = await session.get(ResearchBrief, brief_id)
                if brief:
                    brief.topics = topics_data
                    brief.executive_summary = synthesis.get("executive_summary", "")
                    brief.source_count = validated_count
                    brief.status = "completed"
                    await session.commit()

                logger.info(
                    f"[Research {meeting_id}] Complete: {validated_count} sources, "
                    f"{len(synthesis.get('key_findings', []))} findings"
                )

                await _notify({"type": "research_completed"})

            except Exception as e:
                logger.error(f"[Research {meeting_id}] Pipeline failed: {e}")
                try:
                    await self._fail(session, brief_id, str(e))
                except Exception:
                    pass
                await _notify({"type": "research_failed", "error": str(e)})

    async def _fail(self, session, brief_id, error: str):
        brief = await session.get(ResearchBrief, brief_id)
        if brief:
            brief.status = "failed"
            brief.executive_summary = f"Research failed: {error}"
            await session.commit()


research_pipeline = ResearchPipeline()
