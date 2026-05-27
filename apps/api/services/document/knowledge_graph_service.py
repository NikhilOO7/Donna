"""
Knowledge graph service.

PostgreSQL is the system of record for entities / relationships
(maintains FK integrity to documents and chunks). Neo4j is the query
layer — dual-written via ``MERGE`` so duplicate entity values
collapse server-side, and multi-hop traversal during meetings happens
in Cypher rather than in-memory NetworkX.
"""

import logging
from typing import Any, Dict, List, Optional
from uuid import UUID

import networkx as nx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.neo4j_client import neo4j_client
from apps.api.models.document import Entity
from apps.api.models.meeting import DocumentElement, EntityRelationship

logger = logging.getLogger(__name__)


def _normalize(value: str) -> str:
    """Cheap entity-value normalization for MERGE keys."""
    return (value or "").strip().lower()


class KnowledgeGraphService:
    """Build, persist, and query knowledge graphs."""

    # -- Relationships -----------------------------------------------------

    async def add_relationship(
        self,
        session: AsyncSession,
        source_entity_id: UUID,
        target_entity_id: UUID,
        relationship_type: str,
        confidence: float = 0.8,
        context: Optional[str] = None,
        extraction_method: str = "gpt4",
        document_id: Optional[UUID] = None,
        meeting_id: Optional[UUID] = None,
    ) -> EntityRelationship:
        try:
            rel = EntityRelationship(
                source_entity_id=source_entity_id,
                target_entity_id=target_entity_id,
                relationship_type=relationship_type,
                confidence_score=confidence,
                extraction_method=extraction_method,
                context=context,
                document_id=document_id,
                meeting_id=meeting_id,
            )
            session.add(rel)
            await session.commit()
            await session.refresh(rel)
            return rel
        except Exception as e:
            await session.rollback()
            logger.error(f"Failed to add relationship: {e}")
            raise

    async def add_relationships_batch(
        self,
        session: AsyncSession,
        relationships: List[Dict[str, Any]],
        owner_id: Optional[str] = None,
    ) -> int:
        """Bulk insert relationships. Each dict needs source/target entity IDs.

        Writes to PostgreSQL (system of record) and, when Neo4j is
        enabled, mirrors the edges into the graph database for fast
        multi-hop traversal during meetings. ``owner_id`` scopes the
        Neo4j entity match to the tenant.
        """
        count = 0
        try:
            for r in relationships:
                rel = EntityRelationship(
                    source_entity_id=r["source_entity_id"],
                    target_entity_id=r["target_entity_id"],
                    relationship_type=r.get("relationship_type", "related"),
                    confidence_score=r.get("confidence", 0.8),
                    extraction_method=r.get("extraction_method", "gpt4"),
                    context=r.get("context"),
                    document_id=r.get("document_id"),
                    meeting_id=r.get("meeting_id"),
                )
                session.add(rel)
                count += 1
            await session.commit()
            logger.info(f"Added {count} relationships to PostgreSQL")
        except Exception as e:
            await session.rollback()
            logger.error(f"Failed to add relationships batch: {e}")
            return 0

        # Mirror to Neo4j (best-effort; failures don't break the upload)
        try:
            await self._sync_relationships_to_neo4j(session, relationships, owner_id)
        except Exception as e:
            logger.warning(f"[Neo4j] mirror failed (non-fatal): {e}")

        return count

    async def sync_entities_to_neo4j(
        self,
        entities: List[Entity],
        owner_id: Optional[str] = None,
    ) -> int:
        """Upsert entities into Neo4j via MERGE on (normalized, type, owner_id).

        Dedup point within a tenant — five "Acme" extractions across five
        chunks collapse into one node — while keeping tenants separate.
        ``owner_id`` falls back to the GLOBAL_OWNER sentinel when unset.
        """
        if not entities or not neo4j_client.enabled:
            return 0

        from apps.api.core.neo4j_client import GLOBAL_OWNER

        owner = str(owner_id) if owner_id else GLOBAL_OWNER
        rows = [
            {
                "id": str(e.id),
                "label": e.entity_value,
                "normalized": _normalize(e.entity_value),
                "type": e.entity_type or "UNKNOWN",
                "owner_id": owner,
                "document_id": str(e.document_id) if e.document_id else None,
                "chunk_id": str(e.chunk_id) if e.chunk_id else None,
                "confidence": e.confidence_score,
            }
            for e in entities
            if e.entity_value
        ]
        if not rows:
            return 0

        cypher = """
        UNWIND $rows AS row
        MERGE (e:Entity {normalized: row.normalized, type: row.type,
                         owner_id: row.owner_id})
        ON CREATE SET
            e.id = row.id,
            e.label = row.label,
            e.document_id = row.document_id,
            e.chunk_id = row.chunk_id,
            e.confidence = row.confidence,
            e.created_at = timestamp()
        ON MATCH SET
            e.label = COALESCE(e.label, row.label),
            e.confidence = CASE
                WHEN row.confidence > COALESCE(e.confidence, 0) THEN row.confidence
                ELSE e.confidence END
        RETURN count(e) AS upserted
        """
        result = await neo4j_client.execute(cypher, {"rows": rows}, write=True)
        if result is None:
            return 0
        n = result[0].get("upserted", 0) if result else 0
        logger.info(f"[Neo4j] upserted {n} entity nodes from {len(rows)} extractions")
        return n

    async def _sync_relationships_to_neo4j(
        self,
        session: AsyncSession,
        relationships: List[Dict[str, Any]],
        owner_id: Optional[str] = None,
    ) -> None:
        """Mirror relationships to Neo4j keyed by (normalized, type, owner_id)
        of the source/target entities (not raw UUIDs, since those duplicate)."""
        if not relationships or not neo4j_client.enabled:
            return

        from apps.api.core.neo4j_client import GLOBAL_OWNER

        owner = str(owner_id) if owner_id else GLOBAL_OWNER

        # Resolve entity rows in one query so we can map UUID → (norm, type)
        entity_ids = list(
            {r["source_entity_id"] for r in relationships}
            | {r["target_entity_id"] for r in relationships}
        )
        result = await session.execute(select(Entity).where(Entity.id.in_(entity_ids)))
        entities = list(result.scalars().all())
        keymap = {
            e.id: {
                "normalized": _normalize(e.entity_value),
                "type": e.entity_type or "UNKNOWN",
            }
            for e in entities
        }

        rows = []
        for r in relationships:
            s_key = keymap.get(r["source_entity_id"])
            t_key = keymap.get(r["target_entity_id"])
            if not s_key or not t_key:
                continue
            if s_key == t_key:
                continue
            rows.append(
                {
                    "src_norm": s_key["normalized"],
                    "src_type": s_key["type"],
                    "tgt_norm": t_key["normalized"],
                    "tgt_type": t_key["type"],
                    "owner_id": owner,
                    "rel_type": (r.get("relationship_type") or "related").upper(),
                    "confidence": r.get("confidence", 0.8),
                    "context": (r.get("context") or "")[:500],
                    "document_id": str(r["document_id"])
                    if r.get("document_id")
                    else None,
                }
            )
        if not rows:
            return

        cypher = """
        UNWIND $rows AS row
        MATCH (s:Entity {normalized: row.src_norm, type: row.src_type,
                         owner_id: row.owner_id})
        MATCH (t:Entity {normalized: row.tgt_norm, type: row.tgt_type,
                         owner_id: row.owner_id})
        MERGE (s)-[r:REL {type: row.rel_type}]->(t)
        ON CREATE SET
            r.confidence = row.confidence,
            r.context = row.context,
            r.document_id = row.document_id,
            r.created_at = timestamp()
        ON MATCH SET
            r.confidence = CASE
                WHEN row.confidence > COALESCE(r.confidence, 0) THEN row.confidence
                ELSE r.confidence END
        RETURN count(r) AS upserted
        """
        result = await neo4j_client.execute(cypher, {"rows": rows}, write=True)
        if result:
            n = result[0].get("upserted", 0)
            logger.info(f"[Neo4j] upserted {n} relationship edges")

    # -- Meeting knowledge graph (Neo4j) -----------------------------------

    @staticmethod
    def _build_meeting_graph_rows(
        meeting_id: str,
        title: str,
        status: str,
        owner: str,
        decisions: List[Dict[str, Any]],
        action_items: List[Dict[str, Any]],
        research_topics: List[str],
        utterance_count: int,
    ) -> Dict[str, Any]:
        """Shape meeting data into Neo4j MERGE rows. Pure → unit-testable.

        Models the meeting as a graph: a Meeting node connected to its
        Decisions, ActionItems, ResearchTopics, and a Transcript node — the
        decision/action/transcript/research relationships the platform claims.
        """
        mid = str(meeting_id)
        decision_rows = [
            {
                "id": f"{mid}:d:{i}",
                "text": (d.get("decision_text") or d.get("decision") or "")[:500],
                "owner": d.get("owner") or "TBD",
                "deadline": str(d.get("deadline") or "TBD"),
                "status": d.get("status") or "open",
                "meeting_id": mid,
                "owner_id": owner,
            }
            for i, d in enumerate(decisions)
            if (d.get("decision_text") or d.get("decision"))
        ]
        action_rows = [
            {
                "id": f"{mid}:a:{i}",
                "description": (a.get("description") or a.get("item") or "")[:500],
                "assignee": a.get("assignee") or "TBD",
                "priority": a.get("priority") or "medium",
                "status": a.get("status") or "open",
                "meeting_id": mid,
                "owner_id": owner,
            }
            for i, a in enumerate(action_items)
            if (a.get("description") or a.get("item"))
        ]
        topic_rows = [
            {"name": t.strip()[:200], "meeting_id": mid, "owner_id": owner}
            for t in research_topics
            if t and t.strip()
        ]
        return {
            "meeting": {
                "id": mid,
                "title": (title or "")[:300],
                "status": status or "completed",
                "owner_id": owner,
                "utterance_count": int(utterance_count or 0),
            },
            "decisions": decision_rows,
            "actions": action_rows,
            "topics": topic_rows,
        }

    async def sync_meeting_to_neo4j(
        self,
        meeting_id: str,
        title: str,
        status: str,
        decisions: List[Dict[str, Any]],
        action_items: List[Dict[str, Any]],
        research_topics: Optional[List[str]] = None,
        utterance_count: int = 0,
        owner_id: Optional[str] = None,
    ) -> int:
        """Mirror a completed meeting into Neo4j as a typed subgraph.

        Best-effort: a Neo4j outage must not break summary generation.
        Returns the number of decision+action+topic nodes written.
        """
        if not neo4j_client.enabled:
            return 0

        from apps.api.core.neo4j_client import GLOBAL_OWNER

        owner = str(owner_id) if owner_id else GLOBAL_OWNER
        rows = self._build_meeting_graph_rows(
            meeting_id=meeting_id,
            title=title,
            status=status,
            owner=owner,
            decisions=decisions or [],
            action_items=action_items or [],
            research_topics=research_topics or [],
            utterance_count=utterance_count,
        )

        cypher = """
        MERGE (m:Meeting {id: $meeting.id, owner_id: $meeting.owner_id})
        SET m.title = $meeting.title,
            m.status = $meeting.status,
            m.utterance_count = $meeting.utterance_count,
            m.updated_at = timestamp()
        WITH m
        // Transcript node (one per meeting)
        FOREACH (_ IN CASE WHEN $meeting.utterance_count > 0 THEN [1] ELSE [] END |
            MERGE (t:Transcript {meeting_id: $meeting.id, owner_id: $meeting.owner_id})
            SET t.utterance_count = $meeting.utterance_count
            MERGE (m)-[:HAS_TRANSCRIPT]->(t)
        )
        WITH m
        UNWIND (CASE WHEN size($decisions) = 0 THEN [null] ELSE $decisions END) AS d
        FOREACH (_ IN CASE WHEN d IS NULL THEN [] ELSE [1] END |
            MERGE (dec:Decision {id: d.id, owner_id: d.owner_id})
            SET dec.text = d.text, dec.owner = d.owner,
                dec.deadline = d.deadline, dec.status = d.status,
                dec.meeting_id = d.meeting_id
            MERGE (m)-[:MADE_DECISION]->(dec)
        )
        WITH m
        UNWIND (CASE WHEN size($actions) = 0 THEN [null] ELSE $actions END) AS a
        FOREACH (_ IN CASE WHEN a IS NULL THEN [] ELSE [1] END |
            MERGE (ai:ActionItem {id: a.id, owner_id: a.owner_id})
            SET ai.description = a.description, ai.assignee = a.assignee,
                ai.priority = a.priority, ai.status = a.status,
                ai.meeting_id = a.meeting_id
            MERGE (m)-[:HAS_ACTION]->(ai)
        )
        WITH m
        UNWIND (CASE WHEN size($topics) = 0 THEN [null] ELSE $topics END) AS tp
        FOREACH (_ IN CASE WHEN tp IS NULL THEN [] ELSE [1] END |
            MERGE (rt:ResearchTopic {name: tp.name, meeting_id: tp.meeting_id,
                                     owner_id: tp.owner_id})
            MERGE (m)-[:RESEARCHED]->(rt)
        )
        RETURN 1 AS ok
        """
        try:
            await neo4j_client.execute(cypher, rows, write=True)
        except Exception as e:
            logger.warning(f"[Neo4j] meeting sync failed (non-fatal): {e}")
            return 0

        n = len(rows["decisions"]) + len(rows["actions"]) + len(rows["topics"])
        logger.info(
            f"[Neo4j] synced meeting {meeting_id}: "
            f"{len(rows['decisions'])} decisions, {len(rows['actions'])} actions, "
            f"{len(rows['topics'])} topics"
        )
        return n

    async def get_meeting_graph(
        self, meeting_id: str, owner_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Read a meeting's decisions/actions/topics back out of Neo4j."""
        if not neo4j_client.enabled:
            return {"decisions": [], "actions": [], "topics": []}

        from apps.api.core.neo4j_client import GLOBAL_OWNER

        owner = str(owner_id) if owner_id else GLOBAL_OWNER
        cypher = """
        MATCH (m:Meeting {id: $meeting_id, owner_id: $owner})
        OPTIONAL MATCH (m)-[:MADE_DECISION]->(d:Decision)
        OPTIONAL MATCH (m)-[:HAS_ACTION]->(a:ActionItem)
        OPTIONAL MATCH (m)-[:RESEARCHED]->(rt:ResearchTopic)
        RETURN
            collect(DISTINCT {text: d.text, owner: d.owner, status: d.status}) AS decisions,
            collect(DISTINCT {description: a.description, assignee: a.assignee,
                              priority: a.priority}) AS actions,
            collect(DISTINCT rt.name) AS topics
        """
        result = await neo4j_client.execute(
            cypher, {"meeting_id": str(meeting_id), "owner": owner}
        )
        if not result:
            return {"decisions": [], "actions": [], "topics": []}
        row = result[0]
        return {
            "decisions": [d for d in row.get("decisions", []) if d.get("text")],
            "actions": [a for a in row.get("actions", []) if a.get("description")],
            "topics": [t for t in row.get("topics", []) if t],
        }

    async def get_relationships_for_entity(
        self, session: AsyncSession, entity_id: UUID
    ) -> List[EntityRelationship]:
        result = await session.execute(
            select(EntityRelationship).where(
                (EntityRelationship.source_entity_id == entity_id)
                | (EntityRelationship.target_entity_id == entity_id)
            )
        )
        return list(result.scalars().all())

    async def get_relationships_for_document(
        self, session: AsyncSession, document_id: UUID
    ) -> List[EntityRelationship]:
        result = await session.execute(
            select(EntityRelationship).where(
                EntityRelationship.document_id == document_id
            )
        )
        return list(result.scalars().all())

    # -- Graph Building & Querying ----------------------------------------

    async def build_graph(
        self, session: AsyncSession, document_id: Optional[UUID] = None
    ) -> nx.DiGraph:
        """Load relationships from DB into a NetworkX graph."""
        graph = nx.DiGraph()

        if document_id:
            rels = await self.get_relationships_for_document(session, document_id)
        else:
            result = await session.execute(select(EntityRelationship))
            rels = list(result.scalars().all())

        for rel in rels:
            graph.add_node(str(rel.source_entity_id), type="entity")
            graph.add_node(str(rel.target_entity_id), type="entity")
            graph.add_edge(
                str(rel.source_entity_id),
                str(rel.target_entity_id),
                relationship=rel.relationship_type,
                confidence=rel.confidence_score,
                context=rel.context,
            )

        logger.info(
            f"Built graph: {graph.number_of_nodes()} nodes, {graph.number_of_edges()} edges"
        )
        return graph

    def query_graph(
        self, graph: nx.DiGraph, entity_id: str, max_hops: int = 2
    ) -> Dict[str, Any]:
        """Get subgraph around an entity within N hops."""
        if entity_id not in graph:
            return {"nodes": [], "edges": [], "statistics": {}}

        # BFS to collect nodes within max_hops
        visited = {entity_id}
        frontier = {entity_id}
        for _ in range(max_hops):
            next_frontier = set()
            for node in frontier:
                for neighbor in graph.successors(node):
                    if neighbor not in visited:
                        visited.add(neighbor)
                        next_frontier.add(neighbor)
                for neighbor in graph.predecessors(node):
                    if neighbor not in visited:
                        visited.add(neighbor)
                        next_frontier.add(neighbor)
            frontier = next_frontier

        subgraph = graph.subgraph(visited)
        return {
            "nodes": [{"id": n, **subgraph.nodes[n]} for n in subgraph.nodes()],
            "edges": [
                {"source": u, "target": v, **subgraph.edges[u, v]}
                for u, v in subgraph.edges()
            ],
            "statistics": {
                "total_nodes": subgraph.number_of_nodes(),
                "total_edges": subgraph.number_of_edges(),
            },
        }

    # -- Document Elements -------------------------------------------------

    async def add_document_element(
        self,
        session: AsyncSession,
        document_id: UUID,
        element_type: str,
        content: str,
        raw_data: Optional[dict] = None,
        caption: Optional[str] = None,
        page_number: Optional[int] = None,
        position_index: Optional[int] = None,
        chunk_id: Optional[UUID] = None,
        embedding_id: Optional[str] = None,
    ) -> DocumentElement:
        try:
            element = DocumentElement(
                document_id=document_id,
                chunk_id=chunk_id,
                element_type=element_type,
                content=content,
                raw_data=raw_data or {},
                caption=caption,
                page_number=page_number,
                position_index=position_index,
                embedding_id=embedding_id,
            )
            session.add(element)
            await session.commit()
            await session.refresh(element)
            logger.info(
                f"Added {element_type} element for document {document_id} (page {page_number})"
            )
            return element
        except Exception as e:
            await session.rollback()
            logger.error(f"Failed to add document element: {e}")
            raise

    async def get_elements_for_document(
        self, session: AsyncSession, document_id: UUID
    ) -> List[DocumentElement]:
        result = await session.execute(
            select(DocumentElement)
            .where(DocumentElement.document_id == document_id)
            .order_by(DocumentElement.page_number, DocumentElement.position_index)
        )
        return list(result.scalars().all())


knowledge_graph_service = KnowledgeGraphService()
