"""
Summary Pipeline.

Background task that aggregates meeting data, generates a structured
summary via GPT-4, and stores it in the database.
"""

import logging
from typing import Any, Callable, Coroutine, Dict, Optional

from apps.api.core.database import AsyncSessionLocal
from apps.api.models.meeting import MeetingSummary
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
                await session.commit()

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
