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

from apps.api.core.coordination import cooldown_passed
from apps.api.core.logging import warn_throttled
from apps.api.core.neo4j_client import neo4j_client

logger = logging.getLogger(__name__)

# Per-meeting cooldown: don't re-emit the same connection within N seconds.
# Backed by Redis (shared across replicas) via core.coordination.
_COOLDOWN_SECONDS = 90.0

# Don't surface trivial neighbors that match the meeting's chitchat surface
_STOP_WORDS = {"q", "ai", "team", "meeting", "today", "yesterday", "tomorrow"}

# Lazy-loaded spaCy NLP pipeline. Loading the model is ~1-2s, but it
# happens at most once per worker process and gives us proper NER that
# catches lowercase entities ("beacon cloud", "jane calder") which the
# previous regex-only extractor missed.
_NLP = None
_NLP_LOAD_FAILED = False


def _get_nlp():
    global _NLP, _NLP_LOAD_FAILED
    if _NLP is not None or _NLP_LOAD_FAILED:
        return _NLP
    try:
        import spacy

        _NLP = spacy.load("en_core_web_sm", disable=["lemmatizer", "textcat"])
        logger.info("[KG] spaCy NER loaded for phrase extraction")
    except Exception as e:
        _NLP_LOAD_FAILED = True
        logger.warning(
            f"[KG] spaCy unavailable, falling back to regex-only extractor: {e}"
        )
    return _NLP


# Regex fallback for capitalized proper nouns (used when spaCy is offline
# or as a complement to NER).
_CAP_PHRASE = re.compile(r"\b([A-Z][a-z0-9]+(?:\s+[A-Z][a-z0-9]+){0,2})\b")


class KGQueryAgent:
    """Surface multi-hop connections from the knowledge graph."""

    async def analyze(
        self,
        meeting_id: str,
        recent_utterances: List[Dict[str, Any]],
        owner_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        if not neo4j_client.enabled or not recent_utterances:
            return None

        from apps.api.core.neo4j_client import GLOBAL_OWNER

        owner = str(owner_id) if owner_id else GLOBAL_OWNER

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
        anchor = await self._find_anchor_entity(mentioned, owner)
        if not anchor:
            return None

        # Step 2: BFS one to two hops, skipping already-mentioned neighbors
        connection = await self._find_novel_connection(
            anchor_normalized=anchor["normalized"],
            anchor_type=anchor["type"],
            already_mentioned=mentioned,
            owner=owner,
        )
        if not connection:
            return None

        # Cooldown: same src/tgt pair shouldn't re-fire within 90s.
        # Atomic check-and-claim, shared across replicas via Redis.
        cd_key = (
            f"kg:{meeting_id}:{anchor['normalized']}:{connection['target_normalized']}"
        )
        if not await cooldown_passed(cd_key, _COOLDOWN_SECONDS):
            return None

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
            "title": f"You'll want to know: {anchor['label']} ↔ {connection['target_label']}",
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
        """Extract candidate entity mentions from utterance text.

        Primary path uses spaCy NER + noun chunks — catches lowercase
        entities like "beacon cloud" and "jane calder" that the
        capitalization-based regex would miss. Falls back to the
        regex when spaCy isn't installed (kept for resilience and so
        the unit tests don't require the spaCy model on disk).
        """
        out: Set[str] = set()

        nlp = _get_nlp()
        if nlp is not None:
            try:
                doc = nlp(text)

                # spaCy named entities
                for ent in doc.ents:
                    norm = ent.text.lower().strip()
                    if 3 <= len(norm) <= 60 and norm not in _STOP_WORDS:
                        out.add(norm)

                # Noun chunks — strip leading determiners ("the", "a")
                # so "the beacon cloud team" becomes "beacon cloud team"
                for chunk in doc.noun_chunks:
                    tokens = [
                        t.text.lower()
                        for t in chunk
                        if not t.is_stop and not t.is_punct
                    ]
                    if not tokens:
                        continue
                    norm = " ".join(tokens).strip()
                    if 3 <= len(norm) <= 60 and norm not in _STOP_WORDS:
                        out.add(norm)
            except Exception as e:
                warn_throttled(
                    logger,
                    "kg.spacy",
                    f"[KG] spaCy extraction failed — connection nudges are silently "
                    f"not firing: {e}",
                )

        # Always also run the regex pass — cheap, catches the cases
        # where spaCy misclassifies a clearly-capitalized proper noun.
        for m in _CAP_PHRASE.findall(text):
            norm = m.lower().strip()
            if 3 <= len(norm) <= 60 and norm not in _STOP_WORDS:
                out.add(norm)

        return out

    async def _find_anchor_entity(
        self, candidate_labels: Set[str], owner: str
    ) -> Optional[Dict[str, Any]]:
        """Match any candidate phrase to a real :Entity node in this tenant."""
        if not candidate_labels:
            return None
        cypher = """
        MATCH (e:Entity)
        WHERE e.normalized IN $candidates AND e.owner_id = $owner
        RETURN e.label AS label, e.normalized AS normalized, e.type AS type
        LIMIT 1
        """
        result = await neo4j_client.execute(
            cypher, {"candidates": list(candidate_labels), "owner": owner}
        )
        if not result:
            return None
        return result[0]

    async def _find_novel_connection(
        self,
        anchor_normalized: str,
        anchor_type: str,
        already_mentioned: Set[str],
        owner: str,
    ) -> Optional[Dict[str, Any]]:
        """Find a 1-2 hop neighbor (same tenant) not yet mentioned."""
        # 1-hop first (preferred — tighter connection)
        cypher_1hop = """
        MATCH (a:Entity {normalized: $norm, type: $type, owner_id: $owner})
              -[r:REL]-(b:Entity {owner_id: $owner})
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
                "owner": owner,
                "exclude": list(already_mentioned),
            },
        )
        if result:
            return result[0]

        # 2-hop fallback — a transitive connection through one bridge entity
        cypher_2hop = """
        MATCH (a:Entity {normalized: $norm, type: $type, owner_id: $owner})
              -[r1:REL]-(mid:Entity {owner_id: $owner})
              -[r2:REL]-(b:Entity {owner_id: $owner})
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
                "owner": owner,
                "exclude": list(already_mentioned),
            },
        )
        if result:
            return result[0]
        return None


kg_query_agent = KGQueryAgent()
