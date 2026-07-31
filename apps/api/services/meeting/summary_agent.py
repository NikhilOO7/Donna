"""
Summary Agent.

Generates a structured meeting summary from transcript, decisions,
nudges, and pre-meeting research using GPT-4.
"""

import json
import logging
from typing import Any, Dict, List

from openai import AsyncOpenAI

from apps.api.core.config import settings
from apps.api.core.persona import DONNA_PERSONA
from apps.api.core.resilience import resilient_call

logger = logging.getLogger(__name__)


class SummaryAgent:
    """Generate post-meeting summary from meeting data."""

    def __init__(self):
        self.client = AsyncOpenAI(api_key=settings.openai_api_key)

    @resilient_call("openai", max_retries=2, timeout_seconds=60)
    async def generate_summary(
        self,
        meeting_title: str,
        description: str,
        transcript_text: str,
        decisions: List[Dict[str, Any]],
        action_items: List[Dict[str, Any]],
        nudges: List[Dict[str, Any]],
        research_summary: str,
        meeting_id: str | None = None,
    ) -> Dict[str, Any]:
        """Generate structured meeting summary.

        Returns:
            {
                executive_summary: str,
                key_discussion_points: [{point, context}],
                decisions_summary: [{decision, owner, deadline}],
                action_items: [{item, assignee, priority}],
                ai_insights_used: [{insight, impact}],
                follow_up_recommendations: [str]
            }
        """
        # Build context
        context_parts = [f"# Meeting: {meeting_title}"]

        if description:
            context_parts.append(f"\n## Agenda\n{description}")

        if research_summary:
            context_parts.append(
                f"\n## Pre-Meeting Research\n{research_summary[:2000]}"
            )

        if transcript_text:
            context_parts.append(f"\n## Transcript\n{transcript_text[:4000]}")
        else:
            context_parts.append(
                "\n## Transcript\n(No transcript recorded — meeting may "
                "have been text-only or transcript was not captured)"
            )

        if decisions:
            dec_lines = []
            for d in decisions:
                dec_lines.append(
                    f"- {d.get('decision_text', '')} "
                    f"(Owner: {d.get('owner', 'TBD')}, "
                    f"Deadline: {d.get('deadline', 'TBD')})"
                )
                if d.get("context"):
                    quoted = "\n".join(
                        f"    > {line}" for line in d["context"].splitlines()
                    )
                    dec_lines.append(f"  Conversation trigger:\n{quoted}")
            context_parts.append("\n## Decisions Made\n" + "\n".join(dec_lines))

        if action_items:
            items_text = "\n".join(
                f"- {a.get('description') or a.get('item', '')} "
                f"(Assignee: {a.get('assignee') or 'TBD'}, "
                f"Priority: {a.get('priority') or 'medium'})"
                for a in action_items
            )
            context_parts.append(f"\n## Action Items Already Logged\n{items_text}")

        if nudges:
            nudge_text = "\n".join(
                f"- {'⭐ ' if n.get('pinned') else ''}"
                f"[{n.get('type', 'insight')}] {n.get('title', '')}: "
                f"{n.get('content', '')[:200]}"
                for n in nudges[:10]
            )
            context_parts.append(
                f"\n## AI Insights Surfaced During Meeting\n{nudge_text}"
            )

        context = "\n".join(context_parts)

        response = await self.client.chat.completions.create(
            model=settings.model_smart,
            messages=[
                {
                    "role": "system",
                    "content": (
                        DONNA_PERSONA + "\n\n"
                        "You're writing the post-meeting summary you always have ready "
                        "before anyone asks. Synthesize everything — transcript, your "
                        "research, the decisions, the nudges you surfaced — into a "
                        "crisp, actionable report. Write the executive_summary in your "
                        "voice: direct, warm, a step ahead.\n\n"
                        "Nudges marked ⭐ were pinned by the user during the meeting — "
                        "treat them as the most important context.\n"
                        "In action_items, list only NEW items found in the transcript "
                        "that are NOT already in 'Action Items Already Logged'.\n\n"
                        "Respond ONLY with JSON:\n"
                        "{\n"
                        '  "executive_summary": "2-3 paragraph overview",\n'
                        '  "key_discussion_points": [\n'
                        '    {"point": "...", "context": "..."}\n'
                        "  ],\n"
                        '  "decisions_summary": [\n'
                        '    {"decision": "...", "owner": "...", "deadline": "..."}\n'
                        "  ],\n"
                        '  "action_items": [\n'
                        '    {"item": "...", "assignee": "...", "priority": "high|medium|low"}\n'
                        "  ],\n"
                        '  "ai_insights_used": [\n'
                        '    {"insight": "...", "impact": "..."}\n'
                        "  ],\n"
                        '  "follow_up_recommendations": ["..."]\n'
                        "}"
                    ),
                },
                {"role": "user", "content": context},
            ],
            temperature=0.3,
            max_tokens=3000,
        )

        from apps.api.core.llm_meter import record as record_cost

        await record_cost(meeting_id, "summary", settings.model_smart, response.usage)

        content = response.choices[0].message.content.strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[1].rsplit("```", 1)[0]

        result = json.loads(content)
        logger.info(
            f"Summary generated: {len(result.get('decisions_summary', []))} decisions, "
            f"{len(result.get('action_items', []))} action items"
        )
        return result
