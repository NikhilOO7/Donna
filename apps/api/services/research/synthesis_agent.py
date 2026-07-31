"""
Synthesis Agent.

Takes validated research sources and produces an executive summary
with strategic insights, key findings, and identified data gaps.
"""

import json
import logging
from typing import Any, Dict, List

from openai import AsyncOpenAI

from apps.api.core.config import settings
from apps.api.core.resilience import resilient_call

logger = logging.getLogger(__name__)


class SynthesisAgent:
    """Generate executive summary from validated research."""

    def __init__(self):
        self.client = AsyncOpenAI(api_key=settings.openai_api_key)

    @resilient_call("openai", max_retries=2, timeout_seconds=45)
    async def synthesize(
        self,
        topics: List[Dict[str, Any]],
        validated_sources: Dict[str, List[Dict[str, Any]]],
        meeting_title: str,
        meeting_id: str | None = None,
    ) -> Dict[str, Any]:
        """Generate executive summary from research results.

        Args:
            topics: Original extracted topics.
            validated_sources: Dict mapping topic -> list of validated source dicts.
            meeting_title: For context.

        Returns:
            {executive_summary, key_findings: [{finding, source_url, confidence}], data_gaps: [str]}
        """
        # Build context from all validated sources
        research_context = []
        for topic_info in topics:
            topic_name = topic_info.get("topic", "Unknown")
            sources = validated_sources.get(topic_name, [])
            research_context.append(f"\n## Topic: {topic_name}")
            research_context.append(f"Rationale: {topic_info.get('rationale', 'N/A')}")
            for src in sources:
                tier_label = f"Tier {src.get('tier', '?')}"
                research_context.append(
                    f"\n### [{tier_label}] {src.get('title', 'Untitled')}"
                )
                research_context.append(f"Source: {src.get('url', 'unknown')}")
                research_context.append(
                    f"Excerpt: {src.get('excerpt', src.get('text', '')[:500])}"
                )

        context_text = "\n".join(research_context)

        response = await self.client.chat.completions.create(
            model=settings.model_smart,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a strategic research analyst. Synthesize the research "
                        "findings into a concise executive briefing for a meeting.\n\n"
                        "Respond ONLY with JSON:\n"
                        "{\n"
                        '  "executive_summary": "2-3 paragraph overview of key findings",\n'
                        '  "key_findings": [\n'
                        '    {"finding": "...", "source_url": "...", "confidence": 0.0-1.0, "urgency": "act_now|watch"}\n'
                        "  ],\n"
                        '  "data_gaps": ["topics where information was insufficient"],\n'
                        '  "suggested_topics": [\n'
                        '    {"topic": "...", "why": "one sentence on why this '
                        'adjacent topic matters"}\n'
                        "  ]\n"
                        "}\n\n"
                        "suggested_topics are BLIND SPOTS: 2-3 adjacent topics the "
                        "requester did NOT ask about but the sources suggest they "
                        "should be watching. Never repeat a requested topic."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Meeting: {meeting_title}\n\nResearch Results:\n{context_text}"
                    ),
                },
            ],
            temperature=0.3,
            max_tokens=2000,
        )

        from apps.api.core.llm_meter import record as record_cost

        await record_cost(
            meeting_id, "research_synthesis", settings.model_smart, response.usage
        )

        content = response.choices[0].message.content.strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[1].rsplit("```", 1)[0]

        result = json.loads(content)
        logger.info(
            f"Synthesis complete: {len(result.get('key_findings', []))} findings, "
            f"{len(result.get('data_gaps', []))} gaps"
        )
        return result
