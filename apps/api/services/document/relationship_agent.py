"""
Relationship Extraction Agent.

Takes entities extracted by spaCy and uses GPT-4 to determine
relationships between entity pairs within the same chunk.
Outputs edges for the knowledge graph.
"""

import logging
from typing import Any, Dict, List

from apps.api.core import json_parse, llm_provider
from apps.api.core.config import settings
from apps.api.core.resilience import resilient_call

logger = logging.getLogger(__name__)

RELATIONSHIP_TYPES = [
    "works_at",
    "mentioned_in",
    "decided_on",
    "reports_to",
    "competes_with",
    "part_of",
    "located_in",
    "produced_by",
    "related_to",
]


class RelationshipAgent:
    """Extract relationships between entities using GPT-4."""

    def __init__(self):
        self.client = llm_provider.failover_client()

    async def extract_relationships(
        self,
        entities: List[Dict[str, Any]],
        chunk_text: str,
        document_id: str,
    ) -> List[Dict[str, Any]]:
        """Extract relationships between entities found in the same text.

        Args:
            entities: List of entity dicts with keys: id, entity_type, entity_value
            chunk_text: The text chunk these entities were extracted from.
            document_id: Parent document ID for provenance.

        Returns:
            List of relationship dicts ready for KnowledgeGraphService.add_relationships_batch.
        """
        if len(entities) < 2:
            return []

        # Build entity list for the prompt
        entity_descriptions = [
            f"- {e['entity_value']} ({e['entity_type']})" for e in entities[:15]
        ]

        relationships = await self._extract_with_gpt4(entity_descriptions, chunk_text)

        # Map entity values back to IDs
        value_to_id = {e["entity_value"]: e["id"] for e in entities}

        results = []
        for rel in relationships:
            source_id = value_to_id.get(rel.get("source"))
            target_id = value_to_id.get(rel.get("target"))
            if source_id and target_id and source_id != target_id:
                results.append(
                    {
                        "source_entity_id": source_id,
                        "target_entity_id": target_id,
                        "relationship_type": rel.get("type", "related_to"),
                        "confidence": rel.get("confidence", 0.7),
                        "context": rel.get("context", chunk_text[:200]),
                        "extraction_method": "gpt4",
                        "document_id": document_id,
                    }
                )

        logger.info(
            f"Extracted {len(results)} relationships from {len(entities)} entities"
        )
        return results

    @resilient_call("openai", max_retries=2, timeout_seconds=20)
    async def _extract_with_gpt4(
        self,
        entity_descriptions: List[str],
        chunk_text: str,
    ) -> List[Dict[str, Any]]:
        """Use GPT-4 to identify relationships between entities."""
        if not settings.openai_api_key:
            return []

        type_list = ", ".join(RELATIONSHIP_TYPES)

        try:
            response = await self.client.chat.completions.create(
                model=settings.model_fast,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You extract relationships between named entities. "
                            f"Valid relationship types: {type_list}. "
                            "Respond ONLY with a JSON array of objects, each with: "
                            '"source", "target", "type", "confidence" (0-1). '
                            "If no relationships exist, return []."
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            f"Entities:\n{''.join(entity_descriptions)}\n\n"
                            f"Text:\n{chunk_text[:1500]}"
                        ),
                    },
                ],
                temperature=0.1,
                max_tokens=1000,
            )

            content = response.choices[0].message.content.strip()
            return json_parse.loads_array(content, [])

        except Exception as e:
            logger.warning(f"GPT-4 relationship extraction failed: {e}")
            return []
