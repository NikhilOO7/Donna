"""
Topic Extraction Agent.

Analyzes a meeting brief and extracts 3-5 specific, searchable
research topics with rationale and suggested search queries.
"""

import json
import logging
from typing import Any, Dict, List

from openai import AsyncOpenAI

from apps.api.core.config import settings
from apps.api.core.resilience import resilient_call

logger = logging.getLogger(__name__)


class TopicAgent:
    """Extract research topics from a meeting brief."""

    def __init__(self):
        self.client = AsyncOpenAI(api_key=settings.openai_api_key)

    @resilient_call("openai", max_retries=2, timeout_seconds=20)
    async def extract_topics(
        self, title: str, description: str
    ) -> List[Dict[str, Any]]:
        """Extract 3-5 research topics from meeting context.

        Returns:
            List of dicts: [{topic, rationale, search_queries: [str]}]
        """
        response = await self.client.chat.completions.create(
            model=settings.model_fast,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a strategic research analyst preparing for a business meeting. "
                        "Extract 3-5 specific, externally searchable research topics from the "
                        "meeting brief. Each topic should be something you can find information "
                        "about online — market data, competitor moves, industry trends, etc.\n\n"
                        "Respond ONLY with a JSON array. Each object must have:\n"
                        '- "topic": concise topic title\n'
                        '- "rationale": why this topic matters for the meeting (1 sentence)\n'
                        '- "search_queries": array of 2-3 search queries to find information'
                    ),
                },
                {
                    "role": "user",
                    "content": f"Meeting Title: {title}\n\nDescription:\n{description or 'No description provided.'}",
                },
            ],
            temperature=0.2,
            max_tokens=1000,
        )

        content = response.choices[0].message.content.strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[1].rsplit("```", 1)[0]

        topics = json.loads(content)
        logger.info(f"Extracted {len(topics)} research topics")
        return topics
