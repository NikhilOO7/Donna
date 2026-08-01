"""
Document processing task — the cold-path pipeline body.

Lives in the service layer (NOT apps.api.main) so the job worker can
import it without executing the FastAPI app module. Importing main from
a worker once crashed every document job at the import statement
(main mounts ./static, which doesn't exist in the worker container) —
and a job that dies before the task runs never marks the document
failed. Task modules must be import-safe from any process.

``notify`` is an optional async callable for realtime WS updates; the
API passes its hub broadcaster, workers pass nothing.
"""

import logging
from typing import Any, Awaitable, Callable, Dict, Optional
from uuid import UUID

from apps.api.core.config import settings
from apps.api.core.database import AsyncSessionLocal
from apps.api.services.document.contextual_processor import chunk_to_row

logger = logging.getLogger(__name__)

Notify = Callable[[Dict[str, Any]], Awaitable[None]]


async def _notify(notify: Optional[Notify], message: Dict[str, Any]) -> None:
    if notify is None:
        return
    try:
        await notify(message)
    except Exception:  # realtime updates are best-effort
        pass


async def mark_document_failed(document_id: str, error: str) -> None:
    """Safety net: force a document out of 'processing' after a crash.

    Used by the job wrapper for failures that happen OUTSIDE the task's
    own try/except (imports, service construction, timeouts) — without
    this, a crashed job leaves the document processing forever and the
    UI polls into eternity.
    """
    try:
        from apps.api.services.document.document_service import document_service

        async with AsyncSessionLocal() as session:
            await document_service.update_document_status(
                session=session,
                document_id=UUID(document_id),
                status="failed",
                error={"message": error[:500], "type": "job_crash"},
            )
        logger.info(f"Document {document_id} marked failed after job crash")
    except Exception as e:
        logger.error(f"Could not mark document {document_id} failed: {e}")


async def process_document_task(
    document_id: str,
    file_path: str,
    content_type: str,
    use_enhanced: bool = True,
    services: Any = None,
    notify: Optional[Notify] = None,
):
    """Process an uploaded document end-to-end (parse → embed → index)."""
    from apps.api.services.analytics_service import track_event
    from apps.api.services.document.document_service import document_service

    doc_uuid = UUID(document_id)

    async with AsyncSessionLocal() as session:
        try:
            logger.info(
                f"Processing document {document_id} with enhanced={use_enhanced}"
            )

            document = await document_service.get_document(session, doc_uuid)
            if not document:
                logger.error(f"Document {document_id} not found in database")
                return

            # Tenant scope for Qdrant payloads + Neo4j nodes
            owner_id = str(document.owner_id) if document.owner_id else None

            await _notify(
                notify, {"type": "processing_started", "document_id": document_id}
            )

            if use_enhanced:
                # 1. Process document with intelligent chunking
                processing_result = (
                    await services.modern_doc_processor.process_document(
                        file_path, content_type, metadata={"document_id": document_id}
                    )
                )

                # 1.5. Enrich with layout/table/image agents (PDF only — additive)
                from apps.api.services.document.enhanced_pipeline import (
                    enhanced_document_pipeline,
                )

                enrichment = await enhanced_document_pipeline.enrich_chunks(
                    processing_result["chunks"], file_path, content_type
                )
                processing_result["chunks"] = enrichment["chunks"]

                # 2. Generate contextual embeddings (3 levels)
                embeddings_data = (
                    await services.contextual_embedding_generator.generate_embeddings(
                        chunks=processing_result["chunks"],
                        document_metadata={
                            "document_id": document_id,
                            "title": document.filename,
                            "owner_id": str(owner_id) if owner_id else None,
                            **processing_result["metadata"],
                        },
                        use_voyage=bool(settings.voyage_api_key),
                    )
                )

                # 3. Store in vector database with context (tenant-tagged)
                await services.modern_vector_store.store_contextual_embeddings(
                    document_id,
                    embeddings_data,
                    processing_result["structure"],
                    owner_id=owner_id,
                )

                # 4. Add chunks to database (capture IDs for KG linkage)
                chunk_dicts = [
                    chunk_to_row(chunk) for chunk in processing_result["chunks"]
                ]
                persisted_chunks = await document_service.add_chunks(
                    session, doc_uuid, chunk_dicts
                )

                # 4.5. Knowledge graph extraction
                kg_stats = await enhanced_document_pipeline.extract_knowledge_graph(
                    session=session,
                    document_id=doc_uuid,
                    persisted_chunks=persisted_chunks,
                    original_chunks=processing_result["chunks"],
                    tables=enrichment["tables"],
                    images=enrichment["images"],
                    owner_id=owner_id,
                )

                # 5. Update document metadata and status
                await document_service.update_document_metadata(
                    session=session,
                    document_id=doc_uuid,
                    doc_metadata={
                        "structure": processing_result["structure"].__dict__
                        if hasattr(processing_result["structure"], "__dict__")
                        else {},
                        "processing_method": "enhanced_contextual",
                        "chunk_count": len(processing_result["chunks"]),
                        "knowledge_graph": kg_stats,
                    },
                )
                await document_service.update_document_status(
                    session=session, document_id=doc_uuid, status="completed"
                )
            else:
                # Basic processing (backward compatibility)
                chunks = await services.doc_processor.process_document(file_path)

                embeddings_data = []
                chunk_dicts = []
                for i, chunk in enumerate(chunks):
                    embedding = await services.embedding_service.generate_embedding(
                        chunk["content"]
                    )
                    embeddings_data.append(
                        {
                            "chunk_id": f"{document_id}_chunk_{i}",
                            "content": chunk["content"],
                            "metadata": chunk.get("metadata", {}),
                            "embedding": embedding,
                        }
                    )
                    chunk_dicts.append(
                        {
                            "content": chunk["content"],
                            "token_count": chunk.get("token_count"),
                            "metadata": chunk.get("metadata", {}),
                        }
                    )

                await services.vector_store.store_embeddings(
                    document_id, embeddings_data
                )
                await document_service.add_chunks(session, doc_uuid, chunk_dicts)
                await document_service.update_document_metadata(
                    session=session,
                    document_id=doc_uuid,
                    doc_metadata={
                        "processing_method": "basic",
                        "chunk_count": len(chunks),
                    },
                )
                await document_service.update_document_status(
                    session=session, document_id=doc_uuid, status="completed"
                )

            logger.info(f"✅ Document {document_id} processed successfully")

            document = await document_service.get_document(session, doc_uuid)
            chunk_count = len(document.chunks) if document else 0

            await _notify(
                notify,
                {
                    "type": "processing_completed",
                    "document_id": document_id,
                    "chunk_count": chunk_count,
                },
            )

            await track_event(
                session,
                event_type="document_processed",
                document_id=document_id,
                event_data={
                    "chunk_count": chunk_count,
                    "method": "enhanced" if use_enhanced else "basic",
                },
            )

        except Exception as e:
            logger.error(f"❌ Document processing failed for {document_id}: {e}")
            await document_service.update_document_status(
                session=session,
                document_id=doc_uuid,
                status="failed",
                error={"message": str(e), "type": type(e).__name__},
            )
            await _notify(
                notify,
                {
                    "type": "processing_failed",
                    "document_id": document_id,
                    "error": str(e),
                },
            )
