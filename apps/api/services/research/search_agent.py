"""
Search Agent.

Uses Exa API for semantic web search. Falls back to a simple
OpenAI-generated summary if Exa is not configured.
"""

import logging
from typing import Any, Dict, List

from apps.api.core.config import settings
from apps.api.core.resilience import resilient_call

logger = logging.getLogger(__name__)


class SearchAgent:
    """Search the web for information on research topics."""

    def __init__(self):
        self._exa_client = None

    def _get_exa(self):
        if self._exa_client is None and settings.exa_api_key:
            from exa_py import Exa

            self._exa_client = Exa(api_key=settings.exa_api_key)
        return self._exa_client

    @resilient_call("exa", max_retries=2, timeout_seconds=30)
    async def search_topic(
        self, topic: str, queries: List[str], max_results: int = 10
    ) -> List[Dict[str, Any]]:
        """Search for a topic using Exa semantic search.

        Args:
            topic: The research topic.
            queries: Search queries to execute.
            max_results: Max results across all queries.

        Returns:
            List of source dicts: [{url, title, text, published_date, score}]
        """
        exa = self._get_exa()
        if not exa:
            logger.warning("Exa API not configured — returning empty results")
            return []

        all_results: List[Dict[str, Any]] = []
        seen_urls: set = set()
        per_query = max(max_results // len(queries), 3)

        for query in queries:
            try:
                response = exa.search_and_contents(
                    query=query,
                    num_results=per_query,
                    type="auto",
                    text={"max_characters": 1500},
                    use_autoprompt=True,
                )

                for result in response.results:
                    if result.url in seen_urls:
                        continue
                    seen_urls.add(result.url)
                    all_results.append(
                        {
                            "url": result.url,
                            "title": result.title or "",
                            "text": result.text or "",
                            "published_date": result.published_date or "",
                            "score": result.score or 0.0,
                            "query": query,
                        }
                    )
            except Exception as e:
                logger.warning(f"Exa search failed for query '{query}': {e}")

        logger.info(f"Found {len(all_results)} results for topic: {topic}")
        return all_results[:max_results]
