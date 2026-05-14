"""
Research Pipeline Orchestrator.

Runs the 4-agent research pipeline:
  Topic Extraction → Search (parallel) → Validation → Synthesis

Updates ResearchBrief status and sends WebSocket progress notifications.
"""

import asyncio
import logging
from typing import Any, Callable, Coroutine, Dict, Optional

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
                # Create research brief record
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

                # Step 4: Synthesize
                logger.info(f"[Research {meeting_id}] Synthesizing...")
                synthesis = await self.synthesis_agent.synthesize(
                    topics=topics,
                    validated_sources=validated_sources,
                    meeting_title=title,
                )

                # Build topics data for storage
                topics_data = []
                for topic_info in topics:
                    topic_name = topic_info["topic"]
                    topics_data.append(
                        {
                            "topic": topic_name,
                            "rationale": topic_info.get("rationale", ""),
                            "sources": [
                                {
                                    "url": s.get("url", ""),
                                    "title": s.get("title", ""),
                                    "excerpt": s.get("excerpt", ""),
                                    "tier": s.get("tier", 3),
                                    "credibility_score": s.get("credibility_score", 0),
                                }
                                for s in validated_sources.get(topic_name, [])
                            ],
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
