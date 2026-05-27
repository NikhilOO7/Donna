"""
Enhanced Document Pipeline.

Orchestrates the four advanced document agents:
  1. LayoutAgent     — Docling / pdfplumber structure detection
  2. TableAgent      — table normalization → markdown via GPT-4
  3. ImageAgent      — EasyOCR + (optional) GPT-4 Vision
  4. RelationshipAgent — entity-pair relationships via GPT-4

Wires their outputs into:
  • the processing_result chunk list (so tables/images are embedded in Qdrant)
  • the entities + entity_relationships PostgreSQL tables (per-chunk linkage)
  • the document_elements table (tables/images for retrieval & UI display)

Designed to be additive — called from `process_document_task` without
breaking the existing contextual-embedding flow.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.models.document import DocumentChunk, Entity
from apps.api.services.document.image_agent import ImageAgent
from apps.api.services.document.knowledge_graph_service import knowledge_graph_service
from apps.api.services.document.layout_agent import LayoutAgent
from apps.api.services.document.relationship_agent import RelationshipAgent
from apps.api.services.document.table_agent import TableAgent

logger = logging.getLogger(__name__)


class EnhancedDocumentPipeline:
    """Orchestrate layout / table / image / relationship extraction."""

    def __init__(self):
        self.layout_agent = LayoutAgent()
        self.table_agent = TableAgent()
        self.image_agent = ImageAgent()
        self.relationship_agent = RelationshipAgent()
        self.kg = knowledge_graph_service

    # ------------------------------------------------------------------
    # Stage 1 — pre-embedding enrichment
    # ------------------------------------------------------------------

    async def enrich_chunks(
        self,
        chunks: List[Dict[str, Any]],
        file_path: str,
        content_type: str,
    ) -> Dict[str, Any]:
        """Run layout / table / image agents, append synthetic chunks.

        The returned ``chunks`` list contains the original text chunks plus
        one synthetic chunk per detected table and per detected image so
        the downstream contextual-embedding pipeline will index them
        alongside text.

        Returns ``{"chunks": List, "tables": List, "images": List}``.
        """
        result = {"chunks": chunks, "tables": [], "images": []}

        if content_type != "application/pdf":
            return result

        try:
            layout = await self.layout_agent.analyze(file_path)
        except Exception as e:
            logger.warning(f"[enhanced] Layout agent failed: {e}")
            return result

        raw_tables = layout.get("tables", []) or []
        raw_images = layout.get("images", []) or []

        async def _run_tables():
            if not raw_tables:
                return []
            try:
                return await self.table_agent.process_tables(raw_tables)
            except Exception as e:
                logger.warning(f"[enhanced] Table agent failed: {e}")
                return []

        async def _run_images():
            if not raw_images:
                return []
            try:
                return await self.image_agent.process_images(raw_images, file_path)
            except Exception as e:
                logger.warning(f"[enhanced] Image agent failed: {e}")
                return []

        tables, images = await asyncio.gather(_run_tables(), _run_images())

        # Append synthetic chunks so they're embedded by the existing pipeline
        for t in tables:
            md = (t.get("markdown") or "").strip()
            if not md:
                continue
            chunks.append(
                {
                    "content": f"[TABLE]\n{md}",
                    "metadata": {
                        "element_type": "table",
                        "is_table": True,
                        "page": t.get("page"),
                        "row_count": t.get("row_count"),
                        "col_count": t.get("col_count"),
                    },
                    "start_page": t.get("page"),
                    "end_page": t.get("page"),
                    "is_table": True,
                }
            )

        for im in images:
            ocr = (im.get("ocr_text") or "").strip()
            desc = (im.get("description") or "").strip()
            text = (desc + ("\n" + ocr if ocr else "")).strip()
            if not text or len(text) < 20:
                continue
            chunks.append(
                {
                    "content": f"[IMAGE]\n{text}",
                    "metadata": {
                        "element_type": "image",
                        "page": im.get("page"),
                        "ocr_text": ocr,
                        "caption": im.get("caption"),
                    },
                    "start_page": im.get("page"),
                    "end_page": im.get("page"),
                }
            )

        logger.info(
            f"[enhanced] Enriched chunks: +{len(tables)} tables, "
            f"+{len([i for i in images if (i.get('ocr_text') or i.get('description'))])} images "
            f"(layout method={layout.get('method')})"
        )

        result["chunks"] = chunks
        result["tables"] = tables
        result["images"] = images
        return result

    # ------------------------------------------------------------------
    # Stage 2 — post-persistence: entities, relationships, elements
    # ------------------------------------------------------------------

    async def extract_knowledge_graph(
        self,
        session: AsyncSession,
        document_id: UUID,
        persisted_chunks: List[DocumentChunk],
        original_chunks: List[Dict[str, Any]],
        tables: List[Dict[str, Any]],
        images: List[Dict[str, Any]],
        owner_id: Optional[str] = None,
    ) -> Dict[str, int]:
        """Persist entities (with chunk linkage), extract relationships,
        and store tables/images as DocumentElements. ``owner_id`` scopes
        the Neo4j nodes/edges to the document's tenant."""
        stats = {"entities": 0, "relationships": 0, "tables": 0, "images": 0}

        # ---- Per-chunk entity persistence with chunk_id linkage ----
        chunk_entity_pairs: List[Tuple[DocumentChunk, List[Entity]]] = []
        all_persisted_entities: List[Entity] = []
        for chunk_obj, chunk_data in zip(persisted_chunks, original_chunks):
            ents_meta = (chunk_data.get("metadata") or {}).get("entities") or []
            if not ents_meta:
                chunk_entity_pairs.append((chunk_obj, []))
                continue
            persisted = await self._persist_chunk_entities(
                session, document_id, chunk_obj.id, ents_meta
            )
            chunk_entity_pairs.append((chunk_obj, persisted))
            all_persisted_entities.extend(persisted)
            stats["entities"] += len(persisted)

        # Mirror entities into Neo4j (MERGE on normalized+type+owner → dedup)
        try:
            await self.kg.sync_entities_to_neo4j(
                all_persisted_entities, owner_id=owner_id
            )
        except Exception as e:
            logger.warning(f"[enhanced] Neo4j entity sync skipped: {e}")

        # ---- Per-chunk relationship extraction in parallel ----
        rel_tasks = []
        for chunk_obj, ents in chunk_entity_pairs:
            if len(ents) < 2:
                continue
            entity_dicts = [
                {
                    "id": ent.id,
                    "entity_type": ent.entity_type,
                    "entity_value": ent.entity_value,
                }
                for ent in ents
            ]
            rel_tasks.append(
                self.relationship_agent.extract_relationships(
                    entities=entity_dicts,
                    chunk_text=chunk_obj.content,
                    document_id=str(document_id),
                )
            )

        if rel_tasks:
            results = await asyncio.gather(*rel_tasks, return_exceptions=True)
            all_rels: List[Dict[str, Any]] = []
            for r in results:
                if isinstance(r, Exception):
                    logger.warning(f"[enhanced] Relationship extraction failed: {r}")
                    continue
                all_rels.extend(r)
            if all_rels:
                stats["relationships"] = await self.kg.add_relationships_batch(
                    session, all_rels, owner_id=owner_id
                )

        # ---- Map synthetic chunks back so DocumentElements can link to them ----
        synth_table_chunks: Dict[str, UUID] = {}
        synth_image_chunks: Dict[str, UUID] = {}
        for chunk_obj, chunk_data in zip(persisted_chunks, original_chunks):
            etype = (chunk_data.get("metadata") or {}).get("element_type")
            if etype == "table":
                # Key by first 60 chars of markdown content
                key = (chunk_obj.content or "")[:60]
                synth_table_chunks[key] = chunk_obj.id
            elif etype == "image":
                key = (chunk_obj.content or "")[:60]
                synth_image_chunks[key] = chunk_obj.id

        # ---- Persist tables ----
        for idx, t in enumerate(tables):
            md = (t.get("markdown") or "").strip()
            if not md:
                continue
            link_key = f"[TABLE]\n{md}"[:60]
            try:
                await self.kg.add_document_element(
                    session=session,
                    document_id=document_id,
                    element_type="table",
                    content=md,
                    raw_data={
                        "row_count": t.get("row_count"),
                        "col_count": t.get("col_count"),
                    },
                    page_number=t.get("page"),
                    position_index=idx,
                    chunk_id=synth_table_chunks.get(link_key),
                )
                stats["tables"] += 1
            except Exception as e:
                logger.warning(f"[enhanced] Failed to store table element: {e}")

        # ---- Persist images ----
        for idx, im in enumerate(images):
            ocr = (im.get("ocr_text") or "").strip()
            desc = (im.get("description") or "").strip()
            text = (desc + ("\n" + ocr if ocr else "")).strip()
            if not text or len(text) < 20:
                continue
            link_key = f"[IMAGE]\n{text}"[:60]
            try:
                await self.kg.add_document_element(
                    session=session,
                    document_id=document_id,
                    element_type="image",
                    content=text,
                    raw_data={
                        "ocr_text": ocr,
                        "caption": im.get("caption"),
                    },
                    page_number=im.get("page"),
                    position_index=idx,
                    chunk_id=synth_image_chunks.get(link_key),
                )
                stats["images"] += 1
            except Exception as e:
                logger.warning(f"[enhanced] Failed to store image element: {e}")

        logger.info(
            f"[enhanced] KG extraction for {document_id}: "
            f"entities={stats['entities']} relationships={stats['relationships']} "
            f"tables={stats['tables']} images={stats['images']}"
        )
        return stats

    # ------------------------------------------------------------------

    async def _persist_chunk_entities(
        self,
        session: AsyncSession,
        document_id: UUID,
        chunk_id: UUID,
        entities_meta: List[Dict[str, Any]],
    ) -> List[Entity]:
        """Insert entities for a single chunk, returning the persisted rows."""
        created: List[Entity] = []
        try:
            for em in entities_meta:
                val = em.get("text") or em.get("value") or ""
                if not val:
                    continue
                e = Entity(
                    id=uuid4(),
                    document_id=document_id,
                    chunk_id=chunk_id,
                    entity_type=em.get("type") or em.get("label") or "UNKNOWN",
                    entity_value=val,
                    confidence_score=em.get("confidence"),
                    extraction_method="spacy",
                    entity_metadata={},
                )
                session.add(e)
                created.append(e)
            if created:
                await session.commit()
                for e in created:
                    await session.refresh(e)
            return created
        except Exception as exc:
            await session.rollback()
            logger.error(f"[enhanced] Failed to persist chunk entities: {exc}")
            return []


enhanced_document_pipeline = EnhancedDocumentPipeline()
