"""
Knowledge Graph Query Agent.

The agent that finally puts the graph to work during meetings.

For each new utterance:
  1. Find entities in the graph whose label appears in recent
     utterances (substring, case-insensitive).
  2. For each matched entity, traverse 1-2 hops in Neo4j to find a
     neighbor that *hasn't* been mentioned yet.
  3. If we surface a non-trivial connection, emit a
     ``knowledge_graph`` nudge.

Silent no-op when Neo4j is unavailable or no entities have been
extracted yet — so the dispatcher fan-out stays cheap.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Set

from apps.api.core.neo4j_client import neo4j_client

logger = logging.getLogger(__name__)

# Per-meeting cooldown: don't re-emit the same connection within N seconds.
# Holds (meeting_id, src_normalized, tgt_normalized) → last emit timestamp.
_RECENT_EMITS: Dict[tuple, float] = {}
_COOLDOWN_SECONDS = 90.0

# Don't surface trivial neighbors that match the meeting's chitchat surface
_STOP_WORDS = {"q", "ai", "team", "meeting"}


class KGQueryAgent:
    """Surface multi-hop connections from the knowledge graph."""

    async def analyze(
        self,
        meeting_id: str,
        recent_utterances: List[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        if not neo4j_client.enabled or not recent_utterances:
            return None

        # Window: last 3 utterances combined
        window = " ".join(u.get("text", "") for u in recent_utterances[-3:]).strip()
        if len(window) < 20:
            return None

        # Set of normalized labels already mentioned in this window — we
        # don't want the nudge to surface something the speakers already
        # named themselves.
        mentioned: Set[str] = self._extract_candidate_phrases(window)
        if not mentioned:
            return None

        # Step 1: find which mentioned phrases match real entities in the graph
        anchor = await self._find_anchor_entity(mentioned)
        if not anchor:
            return None

        # Step 2: BFS one to two hops, skipping already-mentioned neighbors
        connection = await self._find_novel_connection(
            anchor_normalized=anchor["normalized"],
            anchor_type=anchor["type"],
            already_mentioned=mentioned,
        )
        if not connection:
            return None

        # Cooldown: same src/tgt pair shouldn't re-fire within 90s
        import time

        key = (meeting_id, anchor["normalized"], connection["target_normalized"])
        now = time.monotonic()
        last = _RECENT_EMITS.get(key)
        if last and now - last < _COOLDOWN_SECONDS:
            return None
        _RECENT_EMITS[key] = now

        rel_pretty = (connection["relationship"] or "related").replace("_", " ").lower()
        if connection["hops"] == 1:
            content = (
                f"{anchor['label']} is connected to {connection['target_label']} "
                f"via {rel_pretty} (from the knowledge base). "
                f"Worth flagging if it's relevant to the decision on the table."
            )
        else:
            content = (
                f"{anchor['label']} → {connection['middle_label']} → "
                f"{connection['target_label']} — a 2-hop path the graph just "
                f"surfaced from uploaded docs."
            )

        return {
            "nudge_type": "knowledge_graph",
            "title": f"Connection: {anchor['label']} ↔ {connection['target_label']}",
            "content": content,
            "source_agent": "kg_query_agent",
            "source_data": {
                "source_label": anchor["label"],
                "source_type": anchor["type"],
                "target_label": connection["target_label"],
                "target_type": connection["target_type"],
                "relationship": connection["relationship"],
                "hops": connection["hops"],
                "context": connection.get("context"),
            },
            "relevance_score": min(0.5 + 0.1 * connection["hops"], 0.85),
        }

    # ------------------------------------------------------------------

    @staticmethod
    def _extract_candidate_phrases(text: str) -> Set[str]:
        """Extract proper-noun-ish phrases. Cheap heuristic — we then
        validate against real entities in Neo4j."""
        # Capitalized words / multi-word phrases (e.g., "Beacon Cloud")
        matches = re.findall(r"\b([A-Z][a-z0-9]+(?:\s+[A-Z][a-z0-9]+){0,2})\b", text)
        out: Set[str] = set()
        for m in matches:
            norm = m.lower().strip()
            if norm in _STOP_WORDS or len(norm) < 3:
                continue
            out.add(norm)
        return out

    async def _find_anchor_entity(
        self, candidate_labels: Set[str]
    ) -> Optional[Dict[str, Any]]:
        """Match any candidate phrase to a real :Entity node."""
        if not candidate_labels:
            return None
        cypher = """
        MATCH (e:Entity)
        WHERE e.normalized IN $candidates
        RETURN e.label AS label, e.normalized AS normalized, e.type AS type
        LIMIT 1
        """
        result = await neo4j_client.execute(
            cypher, {"candidates": list(candidate_labels)}
        )
        if not result:
            return None
        return result[0]

    async def _find_novel_connection(
        self,
        anchor_normalized: str,
        anchor_type: str,
        already_mentioned: Set[str],
    ) -> Optional[Dict[str, Any]]:
        """Find a 1-2 hop neighbor that hasn't been mentioned yet."""
        # 1-hop first (preferred — tighter connection)
        cypher_1hop = """
        MATCH (a:Entity {normalized: $norm, type: $type})-[r:REL]-(b:Entity)
        WHERE NOT b.normalized IN $exclude
        RETURN b.label AS target_label, b.normalized AS target_normalized,
               b.type AS target_type, r.type AS relationship,
               r.context AS context, 1 AS hops
        ORDER BY COALESCE(r.confidence, 0.5) DESC
        LIMIT 1
        """
        result = await neo4j_client.execute(
            cypher_1hop,
            {
                "norm": anchor_normalized,
                "type": anchor_type,
                "exclude": list(already_mentioned),
            },
        )
        if result:
            return result[0]

        # 2-hop fallback — a transitive connection through one bridge entity
        cypher_2hop = """
        MATCH (a:Entity {normalized: $norm, type: $type})
              -[r1:REL]-(mid:Entity)-[r2:REL]-(b:Entity)
        WHERE NOT b.normalized IN $exclude
          AND NOT mid.normalized IN $exclude
          AND b.normalized <> $norm
        RETURN b.label AS target_label, b.normalized AS target_normalized,
               b.type AS target_type, r2.type AS relationship,
               r2.context AS context, mid.label AS middle_label,
               2 AS hops
        ORDER BY COALESCE(r2.confidence, 0.5) DESC
        LIMIT 1
        """
        result = await neo4j_client.execute(
            cypher_2hop,
            {
                "norm": anchor_normalized,
                "type": anchor_type,
                "exclude": list(already_mentioned),
            },
        )
        if result:
            return result[0]
        return None


kg_query_agent = KGQueryAgent()
