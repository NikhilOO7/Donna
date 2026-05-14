"""
Table Extraction Agent.

Takes raw table data (nested lists from pdfplumber) and uses GPT-4 to
normalize headers, infer types, and produce clean markdown.
"""

import logging
from typing import Any, Dict, List, Optional

from openai import AsyncOpenAI

from apps.api.core.config import settings
from apps.api.core.resilience import resilient_call

logger = logging.getLogger(__name__)


class TableAgent:
    """Extract and normalize tables from documents."""

    def __init__(self):
        self.client = AsyncOpenAI(api_key=settings.openai_api_key)

    async def process_tables(
        self, tables: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Process raw tables into normalized markdown."""
        results = []
        for table_info in tables:
            raw_data = table_info.get("data")
            if not raw_data or not isinstance(raw_data, list):
                continue

            markdown = self._raw_to_markdown(raw_data)
            normalized = await self._normalize_with_gpt4(markdown)

            results.append(
                {
                    "page": table_info.get("page"),
                    "index": table_info.get("index", 0),
                    "raw_data": raw_data,
                    "markdown": normalized or markdown,
                    "row_count": len(raw_data),
                    "col_count": len(raw_data[0]) if raw_data else 0,
                }
            )

        logger.info(f"Processed {len(results)} tables")
        return results

    def _raw_to_markdown(self, table: List[List[Optional[str]]]) -> str:
        """Convert nested list to basic markdown table."""
        if not table:
            return ""

        cleaned = [
            [str(cell).strip() if cell else "" for cell in row] for row in table
        ]

        lines = []
        # Header
        lines.append("| " + " | ".join(cleaned[0]) + " |")
        lines.append("| " + " | ".join("---" for _ in cleaned[0]) + " |")
        # Rows
        for row in cleaned[1:]:
            # Pad rows to match header length
            padded = row + [""] * (len(cleaned[0]) - len(row))
            lines.append("| " + " | ".join(padded[: len(cleaned[0])]) + " |")

        return "\n".join(lines)

    @resilient_call("openai", max_retries=2, timeout_seconds=15)
    async def _normalize_with_gpt4(self, markdown_table: str) -> Optional[str]:
        """Use GPT-4 to normalize table headers and clean data."""
        if not settings.openai_api_key:
            return None

        try:
            response = await self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a data analyst. Clean up this markdown table: "
                            "fix header names to be clear and consistent, remove empty "
                            "rows, normalize data formats. Return ONLY the cleaned "
                            "markdown table, nothing else."
                        ),
                    },
                    {"role": "user", "content": markdown_table},
                ],
                temperature=0.1,
                max_tokens=2000,
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            logger.warning(f"GPT-4 table normalization failed: {e}")
            return None
