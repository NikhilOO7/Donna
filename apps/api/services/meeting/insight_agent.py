"""
Insight Agent.

Matches recent utterances against pre-meeting research topics and
surfaces an `insight` nudge citing the relevant finding when a
topical match is found.
"""

import logging
from typing import Any, Dict, List, Optional

from apps.api.core import json_parse, llm_provider
from apps.api.core.config import settings
from apps.api.core.resilience import resilient_call

logger = logging.getLogger(__name__)


class InsightAgent:
    """Surface pre-meeting research when it becomes topically relevant."""

    def __init__(self):
        self.client = llm_provider.failover_client()

    async def analyze(
        self,
        recent_utterances: List[Dict[str, Any]],
        research_topics: List[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        """Return an insight nudge if discussion overlaps with research."""
        if not recent_utterances or not research_topics:
            return None

        # Limit topics to keep prompt small
        topics_for_prompt = research_topics[:6]
        recent_text = " ".join(u.get("text", "") for u in recent_utterances[-3:])

        if len(recent_text) < 20:
            return None

        try:
            result = await self._match_topics(recent_text, topics_for_prompt)
        except Exception as e:
            logger.warning(f"[Insight] match failed: {e}")
            return None

        if not result or not result.get("has_match"):
            return None

        topic_name = result.get("matched_topic", "")
        finding = result.get("relevant_finding", "")

        if not finding:
            return None

        logger.info(f"[Insight] research match: {topic_name}")

        # Find the source URL from the matched topic
        source_url = None
        for t in research_topics:
            if t.get("topic") == topic_name:
                sources = t.get("sources") or []
                if sources:
                    source_url = sources[0].get("url")
                break

        return {
            "nudge_type": "insight",
            "title": f"From my research on {topic_name}"[:120],
            "content": finding,
            "source_agent": "insight_agent",
            "source_data": {
                "matched_topic": topic_name,
                "source_url": source_url,
            },
            "relevance_score": float(result.get("confidence", 0.75)),
        }

    @resilient_call("openai", max_retries=1, timeout_seconds=12)
    async def _match_topics(
        self,
        discussion: str,
        topics: List[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        # Build compact topic summary
        topic_summary = []
        for t in topics:
            topic_name = t.get("topic", "")
            rationale = t.get("rationale", "")
            sources = t.get("sources") or []
            excerpt = sources[0].get("excerpt", "")[:200] if sources else ""
            topic_summary.append(f"- {topic_name}: {rationale}\n  Finding: {excerpt}")

        prompt = (
            f"Recent meeting discussion:\n{discussion}\n\n"
            f"Pre-meeting research topics:\n" + "\n".join(topic_summary)
        )

        response = await self.client.chat.completions.create(
            model=settings.model_fast,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You decide whether recent meeting discussion overlaps with "
                        "pre-meeting research. Return JSON ONLY: "
                        '{"has_match": bool, "matched_topic": str|null, '
                        '"relevant_finding": str|null, "confidence": float}. '
                        "Only set has_match=true when the overlap is meaningful "
                        "and a specific finding can be surfaced as guidance."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            max_tokens=400,
        )

        content = response.choices[0].message.content.strip()
        return json_parse.loads_array(content, [])


insight_agent = InsightAgent()
