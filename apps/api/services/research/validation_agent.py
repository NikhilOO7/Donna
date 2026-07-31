"""
Validation Agent.

Classifies sources into tiers (T1/T2/T3), assigns credibility scores,
and filters to the top sources per topic.
"""

import json
import logging
from typing import Any, Dict, List
from urllib.parse import urlparse

from openai import AsyncOpenAI

from apps.api.core.config import settings
from apps.api.core.resilience import resilient_call

logger = logging.getLogger(__name__)

TIER_1_DOMAINS = {
    "bloomberg.com",
    "reuters.com",
    "wsj.com",
    "sec.gov",
    "ft.com",
    "nytimes.com",
    "apnews.com",
    "bbc.com",
}

TIER_2_DOMAINS = {
    "forbes.com",
    "techcrunch.com",
    "mckinsey.com",
    "hbr.org",
    "cnbc.com",
    "theverge.com",
    "wired.com",
    "axios.com",
    "businessinsider.com",
    "economist.com",
}


class ValidationAgent:
    """Validate and score search results by source credibility."""

    def __init__(self):
        self.client = AsyncOpenAI(api_key=settings.openai_api_key)

    async def validate_sources(
        self, sources: List[Dict[str, Any]], top_n: int = 5
    ) -> List[Dict[str, Any]]:
        """Classify sources into tiers and return the top N.

        Each returned source gets: tier (1/2/3), credibility_score, excerpt.
        """
        if not sources:
            return []

        # Quick domain-based pre-classification
        for source in sources:
            domain = self._extract_domain(source.get("url", ""))
            if domain in TIER_1_DOMAINS:
                source["tier"] = 1
                source["credibility_score"] = 0.95
            elif domain in TIER_2_DOMAINS:
                source["tier"] = 2
                source["credibility_score"] = 0.85
            else:
                source["tier"] = 3
                source["credibility_score"] = 0.5

        # Use GPT to refine scoring and extract excerpts for non-obvious sources
        tier3_sources = [s for s in sources if s["tier"] == 3]
        if tier3_sources:
            refined = await self._refine_with_gpt4(tier3_sources)
            # Merge refined scores back
            url_to_refined = {r["url"]: r for r in refined}
            for source in sources:
                if source["url"] in url_to_refined:
                    ref = url_to_refined[source["url"]]
                    source["tier"] = ref.get("tier", source["tier"])
                    source["credibility_score"] = ref.get(
                        "credibility_score", source["credibility_score"]
                    )

        # Filter out tier 3 and sort by credibility
        validated = [s for s in sources if s.get("tier", 3) <= 2]
        validated.sort(key=lambda x: x.get("credibility_score", 0), reverse=True)

        # Extract excerpts
        for source in validated[:top_n]:
            text = source.get("text", "")
            source["excerpt"] = text[:500] + "..." if len(text) > 500 else text

        result = validated[:top_n]
        logger.info(f"Validated {len(sources)} sources → {len(result)} passed (T1/T2)")
        return result

    def _extract_domain(self, url: str) -> str:
        try:
            parsed = urlparse(url)
            domain = parsed.netloc.lower()
            # Strip www.
            if domain.startswith("www."):
                domain = domain[4:]
            return domain
        except Exception:
            return ""

    @resilient_call("openai", max_retries=2, timeout_seconds=15)
    async def _refine_with_gpt4(
        self, sources: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Use GPT-4 to classify ambiguous sources."""
        source_list = "\n".join(
            f"- {s.get('url', 'unknown')} | {s.get('title', 'untitled')}"
            for s in sources[:15]
        )

        try:
            response = await self.client.chat.completions.create(
                model=settings.model_fast,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Classify each source as tier 1 (major news/official), "
                            "tier 2 (reputable industry), or tier 3 (blog/unknown). "
                            "Respond ONLY with a JSON array: "
                            '[{"url": "...", "tier": 1|2|3, "credibility_score": 0.0-1.0}]'
                        ),
                    },
                    {"role": "user", "content": source_list},
                ],
                temperature=0.1,
                max_tokens=1000,
            )

            content = response.choices[0].message.content.strip()
            if content.startswith("```"):
                content = content.split("\n", 1)[1].rsplit("```", 1)[0]
            return json.loads(content)
        except Exception as e:
            logger.warning(f"GPT-4 source validation failed: {e}")
            return []
