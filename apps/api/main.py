# apps/api/main.py
"""
Enhanced FastAPI application for Voice Document Intelligence System
Full implementation with contextual embeddings and voice integration
"""

import json
import logging
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog
import uvicorn
from fastapi import (
    BackgroundTasks,
    Depends,
    FastAPI,
    File,
    HTTPException,
    Query,
    Request,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi.errors import RateLimitExceeded
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.middleware.base import BaseHTTPMiddleware

from apps.api.core.auth import verify_api_key
from apps.api.core.cache import (
    get_cached_response,
    invalidate_document_cache,
    set_cached_response,
)
from apps.api.core.config import settings
from apps.api.core.connections import (
    get_qdrant_client,
    get_redis_client,
    get_storage_service,
    init_qdrant,
    init_redis,
    init_storage,
)
from apps.api.core.database import AsyncSessionLocal, check_db_health, get_db, init_db
from apps.api.core.dependencies import ServiceContainer
from apps.api.core.logging import configure_logging, get_logger
from apps.api.core.metrics import (
    HTTP_REQUEST_DURATION,
    HTTP_REQUESTS_TOTAL,
    RAG_QUERY_DURATION,
    metrics_content_type,
    metrics_response,
)
from apps.api.core.rate_limit import limiter, rate_limit_exceeded_handler
from apps.api.core.resilience import get_all_breaker_states
from apps.api.core.tracing import configure_tracing
from apps.api.models.requests import QueryRequest
from apps.api.models.responses import QueryResponse
from apps.api.routers import meetings, voice
from apps.api.services.agents.agent_coordinator import DocumentIntelligenceCoordinator
from apps.api.services.agents.crew_setup import DocumentIntelligenceAgents
from apps.api.services.analytics_service import (
    append_message,
    get_conversation_history,
    get_event_stats,
    track_event,
)
from apps.api.services.document.contextual_processor import (
    ContextualEmbeddingGenerator,
    ModernDocumentProcessor,
)
from apps.api.services.document.embeddings import EmbeddingService
from apps.api.services.document.processor import DocumentProcessor
from apps.api.services.document.vector_store import (
    ModernVectorStore,
    VectorStoreService,
)
from apps.api.services.rag.llamaindex_service import ModernRAGService, RAGService
from apps.api.services.voice.enhanced_livekit_service import (
    DocumentIntelligenceVoiceAgent,
    EnhancedVoiceService,
)
from apps.api.services.voice.livekit_service import VoiceService

configure_logging()
logger = get_logger(__name__)

# WebSocket connections for real-time updates
active_connections: List[WebSocket] = []

# Voice worker runs as separate process - see START_VOICE.md


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager"""
    logger.info("Starting Voice Document Intelligence System...")

    try:
        # Initialize database
        await init_db()
        logger.info("Database initialized")

        # Initialize connections
        await init_redis()
        await init_qdrant()
        await init_storage()
        logger.info("External services connected")

        # Build service container (replaces global variables)
        _modern_vector_store = ModernVectorStore()
        await _modern_vector_store.initialize()

        app.state.services = ServiceContainer(
            doc_processor=DocumentProcessor(),
            modern_doc_processor=ModernDocumentProcessor(),
            embedding_service=EmbeddingService(),
            contextual_embedding_generator=ContextualEmbeddingGenerator(),
            vector_store=VectorStoreService(),
            modern_vector_store=_modern_vector_store,
            rag_service=RAGService(),
            modern_rag_service=ModernRAGService(),
            voice_service=VoiceService(),
            enhanced_voice_service=EnhancedVoiceService(),
            doc_intelligence_agents=DocumentIntelligenceAgents(),
            doc_intelligence_coordinator=DocumentIntelligenceCoordinator(),
        )

        logger.info("All services initialized successfully")
        logger.info("Voice worker must be started separately")

        # Best-effort: warm up Neo4j connection + schema. App still serves
        # if Neo4j is offline — KG features degrade to PostgreSQL fallback.
        try:
            from apps.api.core.neo4j_client import neo4j_client

            if await neo4j_client.ensure_ready():
                logger.info("Neo4j knowledge graph connection ready")
            else:
                logger.info("Neo4j disabled or unreachable — KG runs in fallback mode")
        except Exception as e:
            logger.warning(f"Neo4j warmup skipped: {e}")

    except Exception as e:
        logger.error(f"Initialization failed: {e}")
        raise

    yield

    # Cleanup
    logger.info("Shutting down services...")
    try:
        from apps.api.core.neo4j_client import neo4j_client

        await neo4j_client.close()
    except Exception:
        pass
    logger.info("Shutdown complete")


# Create FastAPI app
app = FastAPI(
    title="Voice Document Intelligence API",
    description="API for voice-enabled document intelligence with contextual embeddings",
    version="2.0.0",
    lifespan=lifespan,
)

# Rate limiting
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)

# OpenTelemetry tracing (no-op when disabled)
configure_tracing(app)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Request middleware: correlation-id propagation + structured logging + Prometheus metrics
class ObservabilityMiddleware(BaseHTTPMiddleware):
    """Middleware that adds request-id propagation, structured logging, and Prometheus metrics."""

    async def dispatch(self, request: Request, call_next):
        # 1. Request-ID: read from header or generate
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))

        # 2. Bind into structlog contextvars (all downstream logs include it)
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            method=request.method,
            path=request.url.path,
        )

        start_time = time.monotonic()
        req_logger = get_logger("access")
        req_logger.info(
            "request_started",
            client=request.client.host if request.client else "unknown",
        )

        try:
            response = await call_next(request)
            duration = time.monotonic() - start_time

            # 3. Prometheus metrics
            path_label = request.url.path.split("?")[0]
            HTTP_REQUESTS_TOTAL.labels(
                method=request.method, path=path_label, status=response.status_code
            ).inc()
            HTTP_REQUEST_DURATION.labels(
                method=request.method, path=path_label
            ).observe(duration)

            # 4. Structured log with duration
            log_method = (
                req_logger.warning if response.status_code >= 400 else req_logger.info
            )
            log_method(
                "request_completed",
                status=response.status_code,
                duration_ms=round(duration * 1000, 1),
            )

            # 5. Propagate request-id to response
            response.headers["X-Request-ID"] = request_id
            return response

        except Exception as exc:
            duration = time.monotonic() - start_time
            req_logger.error(
                "request_failed",
                duration_ms=round(duration * 1000, 1),
                error=str(exc),
                exc_info=True,
            )
            raise


app.add_middleware(ObservabilityMiddleware)

# Include routers
app.include_router(voice.router)
app.include_router(meetings.router)

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")


# Prometheus metrics endpoint
@app.get("/metrics", include_in_schema=False)
async def prometheus_metrics():
    """Expose Prometheus metrics for scraping."""
    from starlette.responses import Response

    return Response(content=metrics_response(), media_type=metrics_content_type())


# Health check endpoint
@app.get("/health")
async def health_check():
    """Comprehensive health check with actual service verification"""
    services_status = {}

    # Check database
    try:
        db_healthy = await check_db_health()
        services_status["database"] = "healthy" if db_healthy else "unhealthy"
    except Exception as e:
        services_status["database"] = f"unhealthy: {e}"

    # Check Redis
    try:
        redis_client = await get_redis_client()
        if redis_client:
            await redis_client.ping()
            services_status["redis"] = "healthy"
        else:
            services_status["redis"] = "unhealthy"
    except Exception as e:
        services_status["redis"] = f"unhealthy: {e}"

    # Check Qdrant
    try:
        qdrant_client = await get_qdrant_client()
        if qdrant_client:
            collections = await qdrant_client.get_collections()
            services_status["qdrant"] = {
                "status": "healthy",
                "collections": len(collections.collections),
            }
        else:
            services_status["qdrant"] = "unhealthy"
    except Exception as e:
        services_status["qdrant"] = f"unhealthy: {e}"

    # Check service instances via DI container
    svc = getattr(app.state, "services", None)
    services_status["embeddings"] = (
        "healthy" if svc and svc.embedding_service else "unavailable"
    )
    services_status["voice"] = "healthy" if svc and svc.voice_service else "unavailable"
    services_status["voice_worker"] = "separate_process"

    # Determine overall health
    core_services = [services_status["database"], services_status["redis"]]
    qdrant_status = services_status["qdrant"]
    if isinstance(qdrant_status, dict):
        core_services.append(qdrant_status["status"])
    else:
        core_services.append(qdrant_status)

    overall_health = (
        "healthy" if all(s == "healthy" for s in core_services) else "degraded"
    )

    return {
        "status": overall_health,
        "services": services_status,
        "circuit_breakers": get_all_breaker_states(),
        "version": settings.app_version,
        "timestamp": datetime.utcnow().isoformat(),
    }


# Document upload endpoint
@app.post("/api/v1/documents/upload")
@limiter.limit(settings.rate_limit_upload)
async def upload_document(
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    use_enhanced: bool = Query(
        True, description="Use enhanced processing with contextual embeddings"
    ),
    session: AsyncSession = Depends(get_db),
    _api_key: str = Depends(verify_api_key),
):
    """Upload and process a document with contextual embeddings"""
    from apps.api.services.document.document_service import (
        DocumentAlreadyExistsError,
        document_service,
    )

    try:
        # Validate file
        if file.size > settings.max_file_size:
            raise HTTPException(
                400, f"File too large. Maximum size: {settings.max_file_size} bytes"
            )

        # Read file content
        content = await file.read()

        # Get storage service
        storage_service = get_storage_service()

        # Create document in database (with deduplication)
        try:
            document = await document_service.create_document(
                session=session,
                filename=file.filename,
                file_content=content,
                file_type=file.content_type,
                user_metadata={"use_enhanced": use_enhanced, "uploaded_by": "api"},
            )
        except DocumentAlreadyExistsError as e:
            raise HTTPException(409, f"Document already exists: {str(e)}")

        # Upload to storage (local or MinIO based on config)
        storage_result = await storage_service.upload_file(
            file_content=content,
            filename=file.filename,
            document_id=str(document.id),
            metadata={"uploaded_by": "api", "use_enhanced": use_enhanced},
        )

        # Update document with storage metadata
        await document_service.update_document_metadata(
            session=session,
            document_id=document.id,
            extracted_metadata={
                "file_path": storage_result["file_path"],
                "storage_type": storage_result["storage_type"],
                "content_type": storage_result["content_type"],
            },
        )

        # Update status to processing
        await document_service.update_document_status(
            session=session, document_id=document.id, status="processing"
        )

        # Process document in background
        background_tasks.add_task(
            process_document_task,
            str(document.id),
            storage_result["file_path"],
            storage_result["content_type"],
            use_enhanced,
            request.app.state.services,
        )

        # Notify WebSocket clients
        await notify_clients(
            {
                "type": "document_uploaded",
                "document_id": str(document.id),
                "filename": file.filename,
            }
        )

        # Invalidate query cache since document corpus changed
        await invalidate_document_cache()

        # Track upload event
        await track_event(
            session,
            event_type="document_upload",
            document_id=str(document.id),
            event_data={"filename": file.filename, "file_size": len(content)},
        )

        return {
            "document_id": str(document.id),
            "filename": file.filename,
            "status": "processing",
            "message": "Document uploaded successfully and is being processed",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Document upload failed: {e}")
        raise HTTPException(500, f"Upload failed: {str(e)}")


# Document processing task
async def process_document_task(
    document_id: str,
    file_path: str,
    content_type: str,
    use_enhanced: bool = True,
    services: ServiceContainer | None = None,
):
    """Background task to process document with contextual embeddings"""
    from uuid import UUID

    from apps.api.services.document.document_service import document_service

    # Convert document_id to UUID
    doc_uuid = UUID(document_id)

    # Create a new database session for background task
    async with AsyncSessionLocal() as session:
        try:
            logger.info(
                f"Processing document {document_id} with enhanced={use_enhanced}"
            )

            # Get document from database
            document = await document_service.get_document(session, doc_uuid)
            if not document:
                logger.error(f"Document {document_id} not found in database")
                return

            await notify_clients(
                {"type": "processing_started", "document_id": document_id}
            )

            if use_enhanced:
                # Enhanced processing with contextual embeddings

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
                            **processing_result["metadata"],
                        },
                        use_voyage=bool(settings.voyage_api_key),
                    )
                )

                # 3. Store in vector database with context
                await services.modern_vector_store.store_contextual_embeddings(
                    document_id, embeddings_data, processing_result["structure"]
                )

                # 4. Add chunks to database (capture IDs for KG linkage)
                chunk_dicts = []
                for chunk in processing_result["chunks"]:
                    chunk_dicts.append(
                        {
                            "content": chunk.get("content", ""),
                            "token_count": chunk.get("token_count"),
                            "start_char": chunk.get("start_char"),
                            "end_char": chunk.get("end_char"),
                            "start_page": chunk.get("start_page"),
                            "end_page": chunk.get("end_page"),
                            "metadata": chunk.get("metadata", {}),
                            "is_table": chunk.get("is_table", False)
                            or (chunk.get("metadata", {}) or {}).get("is_table", False),
                        }
                    )

                persisted_chunks = await document_service.add_chunks(
                    session, doc_uuid, chunk_dicts
                )

                # 4.5. Knowledge graph extraction: per-chunk entities,
                #      relationships, and table/image DocumentElements
                kg_stats = await enhanced_document_pipeline.extract_knowledge_graph(
                    session=session,
                    document_id=doc_uuid,
                    persisted_chunks=persisted_chunks,
                    original_chunks=processing_result["chunks"],
                    tables=enrichment["tables"],
                    images=enrichment["images"],
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

            # Get updated document for chunk count
            document = await document_service.get_document(session, doc_uuid)
            chunk_count = len(document.chunks) if document else 0

            await notify_clients(
                {
                    "type": "processing_completed",
                    "document_id": document_id,
                    "chunk_count": chunk_count,
                }
            )

            # Track document processing analytics
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

            # Update document status to failed
            await document_service.update_document_status(
                session=session,
                document_id=doc_uuid,
                status="failed",
                error={"message": str(e), "type": type(e).__name__},
            )

            await notify_clients(
                {
                    "type": "processing_failed",
                    "document_id": document_id,
                    "error": str(e),
                }
            )


# Query endpoint with contextual search
@app.post("/api/v1/query", response_model=QueryResponse)
@limiter.limit(settings.rate_limit_query)
async def query_documents(
    query_req: QueryRequest,
    request: Request,
    session: AsyncSession = Depends(get_db),
    _api_key: str = Depends(verify_api_key),
):
    """Query documents using contextual embeddings"""
    import time as _time

    query_start = _time.monotonic()
    svc: ServiceContainer = request.app.state.services
    conversation_id = query_req.conversation_id or f"api-{uuid.uuid4()}"

    try:
        # Check Redis cache first (skip for conversations with history)
        context_level = query_req.context_level or "document"
        if not query_req.conversation_id:
            cached = await get_cached_response(query_req.query, context_level)
            if cached:
                return QueryResponse(**cached)

        # Load conversation history from DB for context
        await get_conversation_history(session, conversation_id, last_n=5)

        if query_req.use_enhanced:
            voice_agent = DocumentIntelligenceVoiceAgent()
            result = await voice_agent.process_voice_query(
                query=query_req.query,
                conversation_id=conversation_id,
                audio_metadata={
                    "source": "api",
                    "context_level": query_req.context_level,
                },
            )
            answer = result["answer"]
            sources = result["sources"]
            context_level = result["context_level"]
            metadata = {
                "metrics": result.get("metrics", {}),
                "context_info": result.get("context_info", {}),
            }
        else:
            result = await svc.rag_service.process_query(
                query=query_req.query,
                conversation_id=conversation_id,
            )
            answer = result["answer"]
            sources = result.get("sources", [])
            context_level = "document"
            metadata = {}

        latency_ms = int((_time.monotonic() - query_start) * 1000)

        # Persist conversation turn to DB
        await append_message(session, conversation_id, query_req.query, answer)

        # Track analytics event
        await track_event(
            session,
            event_type="query",
            session_id=conversation_id,
            event_data={
                "query": query_req.query,
                "context_level": context_level,
                "enhanced": query_req.use_enhanced,
                "source_count": len(sources),
            },
            latency_ms=latency_ms,
        )

        # Record Prometheus metric
        RAG_QUERY_DURATION.observe(latency_ms / 1000.0)

        response = QueryResponse(
            answer=answer,
            sources=sources,
            conversation_id=conversation_id,
            context_level=context_level,
            metadata=metadata,
        )

        # Cache the response for future identical queries
        if not query_req.conversation_id:
            await set_cached_response(
                query_req.query, context_level, response.model_dump()
            )

        return response

    except Exception as e:
        logger.error("query_failed", error=str(e), query=query_req.query)
        raise HTTPException(500, f"Query failed: {str(e)}")


# List documents endpoint
@app.get("/api/v1/documents")
async def list_documents(
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=100),
    status: Optional[str] = None,
    session: AsyncSession = Depends(get_db),
    _api_key: str = Depends(verify_api_key),
):
    """List all documents with pagination"""
    from apps.api.services.document.document_service import document_service

    documents = await document_service.list_documents(
        session=session, skip=skip, limit=limit, status=status
    )

    # Convert to dict for response
    documents_list = [
        {
            "id": str(doc.id),
            "filename": doc.filename,
            "file_type": doc.file_type,
            "file_size": doc.file_size,
            "processing_status": doc.processing_status,
            "created_at": doc.created_at.isoformat(),
            "chunk_count": len(doc.chunks) if doc.chunks else 0,
            "metadata": doc.doc_metadata,
        }
        for doc in documents
    ]

    # Get total count
    from sqlalchemy import func
    from sqlalchemy import select as sql_select

    from apps.api.models.document import Document as DocumentModel

    total_query = (
        sql_select(func.count())
        .select_from(DocumentModel)
        .where(DocumentModel.deleted_at.is_(None))
    )
    if status:
        total_query = total_query.where(DocumentModel.processing_status == status)

    total = await session.scalar(total_query) or 0

    return {"documents": documents_list, "total": total, "skip": skip, "limit": limit}


# Get document details
@app.get("/api/v1/documents/{document_id}")
async def get_document(
    document_id: str,
    session: AsyncSession = Depends(get_db),
    _api_key: str = Depends(verify_api_key),
):
    """Get document details including structure"""
    from uuid import UUID

    from apps.api.services.document.document_service import document_service

    try:
        doc_uuid = UUID(document_id)
    except ValueError:
        raise HTTPException(400, "Invalid document ID format")

    document = await document_service.get_document(
        session=session, document_id=doc_uuid, include_chunks=True
    )

    if not document:
        raise HTTPException(404, "Document not found")

    return {
        "id": str(document.id),
        "filename": document.filename,
        "file_type": document.file_type,
        "file_size": document.file_size,
        "processing_status": document.processing_status,
        "processing_started_at": document.processing_started_at.isoformat()
        if document.processing_started_at
        else None,
        "processing_completed_at": document.processing_completed_at.isoformat()
        if document.processing_completed_at
        else None,
        "processing_error": document.processing_error,
        "created_at": document.created_at.isoformat(),
        "updated_at": document.updated_at.isoformat(),
        "chunk_count": len(document.chunks) if document.chunks else 0,
        "metadata": document.doc_metadata,
        "extracted_metadata": document.extracted_metadata,
    }


@app.get("/api/v1/documents/{document_id}/elements")
async def get_document_elements(
    document_id: str,
    session: AsyncSession = Depends(get_db),
    _api_key: str = Depends(verify_api_key),
):
    """Return tables/images/charts extracted from a document."""
    from uuid import UUID

    from apps.api.services.document.knowledge_graph_service import (
        knowledge_graph_service,
    )

    try:
        doc_uuid = UUID(document_id)
    except ValueError:
        raise HTTPException(400, "Invalid document ID format")

    elements = await knowledge_graph_service.get_elements_for_document(
        session, doc_uuid
    )
    return {
        "document_id": document_id,
        "count": len(elements),
        "elements": [
            {
                "id": str(e.id),
                "type": e.element_type,
                "content": e.content,
                "page": e.page_number,
                "position_index": e.position_index,
                "caption": e.caption,
                "raw_data": e.raw_data,
            }
            for e in elements
        ],
    }


@app.get("/api/v1/documents/{document_id}/knowledge-graph")
async def get_document_knowledge_graph(
    document_id: str,
    session: AsyncSession = Depends(get_db),
    _api_key: str = Depends(verify_api_key),
):
    """Return the document's knowledge graph.

    Primary path: Cypher query against Neo4j (deduplicated, fast).
    Fallback path: PostgreSQL `entities` + `entity_relationships`
    (raw, may contain duplicate entity rows from per-chunk spaCy
    extractions) when Neo4j is offline or empty for this document.
    """
    from uuid import UUID

    from sqlalchemy import select

    from apps.api.core.neo4j_client import neo4j_client
    from apps.api.models.document import Entity
    from apps.api.services.document.knowledge_graph_service import (
        knowledge_graph_service,
    )

    try:
        doc_uuid = UUID(document_id)
    except ValueError:
        raise HTTPException(400, "Invalid document ID format")

    # --- Try Neo4j first ---
    if neo4j_client.enabled:
        cypher = """
        MATCH (e:Entity {document_id: $doc_id})
        OPTIONAL MATCH (e)-[r:REL]-(other:Entity)
        RETURN
            collect(DISTINCT {
                id: e.id,
                label: e.label,
                type: e.type,
                confidence: e.confidence
            }) AS nodes,
            collect(DISTINCT CASE
                WHEN other IS NOT NULL THEN {
                    source_norm: e.normalized,
                    source_type: e.type,
                    target_norm: other.normalized,
                    target_type: other.type,
                    relationship: r.type,
                    confidence: r.confidence,
                    context: r.context
                } ELSE NULL END
            ) AS rels
        """
        result = await neo4j_client.execute(cypher, {"doc_id": str(doc_uuid)})
        if result and result[0].get("nodes"):
            row = result[0]
            # Map normalized keys back to node IDs for the UI's edge.source/target
            nodes_by_key = {
                (n["label"].lower().strip(), n["type"]): n["id"] for n in row["nodes"]
            }
            edges = []
            for r in row.get("rels") or []:
                if not r:
                    continue
                s = nodes_by_key.get((r["source_norm"], r["source_type"]))
                t = nodes_by_key.get((r["target_norm"], r["target_type"]))
                if not s or not t:
                    continue
                edges.append(
                    {
                        "source": s,
                        "target": t,
                        "relationship": (r["relationship"] or "").lower(),
                        "confidence": r.get("confidence"),
                        "context": r.get("context"),
                    }
                )
            return {
                "document_id": document_id,
                "node_count": len(row["nodes"]),
                "edge_count": len(edges),
                "nodes": row["nodes"],
                "edges": edges,
                "source": "neo4j",
            }

    # --- Fallback: PostgreSQL ---
    rels = await knowledge_graph_service.get_relationships_for_document(
        session, doc_uuid
    )
    entity_ids = set()
    for r in rels:
        entity_ids.add(r.source_entity_id)
        entity_ids.add(r.target_entity_id)

    result = await session.execute(
        select(Entity).where(Entity.document_id == doc_uuid)
    )
    doc_entities = list(result.scalars().all())
    entity_map = {ent.id: ent for ent in doc_entities}
    for eid in entity_ids:
        if eid not in entity_map:
            entity_map[eid] = None

    nodes = []
    for eid, ent in entity_map.items():
        if ent is None:
            nodes.append({"id": str(eid), "label": "(external)", "type": "UNKNOWN"})
        else:
            nodes.append(
                {
                    "id": str(ent.id),
                    "label": ent.entity_value,
                    "type": ent.entity_type,
                    "confidence": ent.confidence_score,
                }
            )

    edges = [
        {
            "source": str(r.source_entity_id),
            "target": str(r.target_entity_id),
            "relationship": r.relationship_type,
            "confidence": r.confidence_score,
            "context": r.context,
        }
        for r in rels
    ]

    return {
        "document_id": document_id,
        "node_count": len(nodes),
        "edge_count": len(edges),
        "nodes": nodes,
        "edges": edges,
        "source": "postgresql",
    }


# Delete document
@app.delete("/api/v1/documents/{document_id}")
async def delete_document(
    document_id: str,
    request: Request,
    session: AsyncSession = Depends(get_db),
    _api_key: str = Depends(verify_api_key),
):
    """Delete a document and its embeddings"""
    from uuid import UUID

    from apps.api.services.document.document_service import document_service

    svc: ServiceContainer = request.app.state.services

    try:
        doc_uuid = UUID(document_id)
    except ValueError:
        raise HTTPException(400, "Invalid document ID format")

    # Get document first to check if it exists and get metadata
    document = await document_service.get_document(
        session=session, document_id=doc_uuid
    )
    if not document:
        raise HTTPException(404, "Document not found")

    try:
        # Delete from vector store (best-effort, may not exist if still processing)
        try:
            processing_method = (document.doc_metadata or {}).get(
                "processing_method", "basic"
            )
            if processing_method == "enhanced_contextual":
                await svc.modern_vector_store.delete_document(document_id)
            else:
                await svc.vector_store.delete_document(document_id)
        except Exception as e:
            logger.warning(f"Vector store delete (non-fatal): {e}")

        # Delete from storage
        storage_service = get_storage_service()
        file_path = (document.extracted_metadata or {}).get("file_path")
        if file_path:
            try:
                await storage_service.delete_file(document_id, document.filename)
            except Exception as e:
                logger.warning(f"Failed to delete file from storage: {e}")

        # Soft delete from database
        success = await document_service.delete_document(
            session=session, document_id=doc_uuid, soft_delete=True
        )

        if not success:
            raise HTTPException(500, "Failed to delete document from database")

        await notify_clients({"type": "document_deleted", "document_id": document_id})

        return {"message": "Document deleted successfully"}

    except Exception as e:
        logger.error(f"Document deletion failed: {e}")
        raise HTTPException(500, f"Deletion failed: {str(e)}")


# Voice endpoints
@app.get("/api/v1/voice/token")
async def get_voice_token(
    request: Request,
    room_name: str = Query("document-chat", description="Room name"),
    participant_name: str = Query("user", description="Participant name"),
):
    """Get LiveKit token for voice connection"""
    try:
        svc: ServiceContainer = request.app.state.services
        token = await svc.voice_service.generate_token(
            room_name=room_name, participant_name=participant_name
        )

        return {"token": token, "url": settings.livekit_url, "room_name": room_name}

    except Exception as e:
        logger.error(f"Token generation failed: {e}", exc_info=True)
        raise HTTPException(500, "Failed to generate voice token")


# WebSocket endpoint for real-time updates
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time updates"""
    await websocket.accept()
    active_connections.append(websocket)

    try:
        while True:
            # Keep connection alive
            data = await websocket.receive_text()

            # Handle ping/pong
            if data == "ping":
                await websocket.send_text("pong")

    except WebSocketDisconnect:
        active_connections.remove(websocket)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        if websocket in active_connections:
            active_connections.remove(websocket)


async def notify_clients(message: Dict[str, Any]):
    """Notify all connected WebSocket clients"""
    if not active_connections:
        return

    message_json = json.dumps(message)
    disconnected = []

    for connection in active_connections:
        try:
            await connection.send_text(message_json)
        except Exception:
            disconnected.append(connection)

    # Remove disconnected clients
    for conn in disconnected:
        active_connections.remove(conn)


# Analytics endpoints
@app.get("/api/v1/analytics/usage")
async def get_usage_analytics(session: AsyncSession = Depends(get_db)):
    """Get usage analytics from database"""
    from apps.api.services.document.document_service import document_service

    stats = await document_service.get_document_stats(session)
    status_counts = stats.processing_status_counts

    total_docs = stats.total_documents
    completed_docs = status_counts.get("completed", 0)
    failed_docs = status_counts.get("failed", 0)
    processing_docs = status_counts.get("processing", 0) + status_counts.get(
        "pending", 0
    )

    return {
        "documents": {
            "total": total_docs,
            "completed": completed_docs,
            "failed": failed_docs,
            "processing": processing_docs,
        },
        "chunks": {
            "total": stats.total_chunks,
            "average_per_doc": stats.total_chunks / completed_docs
            if completed_docs > 0
            else 0,
        },
        "entities": {"total": stats.total_entities},
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.get("/api/v1/analytics/performance")
async def get_performance_analytics(
    request: Request, session: AsyncSession = Depends(get_db)
):
    """Get performance analytics from real tracked events."""
    stats = await get_event_stats(session, hours=24)
    latencies = stats.get("latencies", {})
    svc = getattr(request.app.state, "services", None)
    evs = svc.enhanced_voice_service if svc else None

    return {
        "average_latencies": {
            "query": latencies.get("query", {}).get("avg_ms", 0),
            "query_p95": latencies.get("query", {}).get("p95_ms", 0),
            "document_upload": latencies.get("document_upload", {}).get("avg_ms", 0),
        },
        "event_counts": stats.get("event_counts", {}),
        "active_sessions": len(evs.sessions) if evs and hasattr(evs, "sessions") else 0,
        "period_hours": stats.get("period_hours", 24),
        "timestamp": datetime.utcnow().isoformat(),
    }


# Test endpoints for development
@app.get("/api/v1/test/demo")
async def demo_test(request: Request):
    """Demo endpoint to test system"""
    svc = getattr(request.app.state, "services", None)
    return {
        "message": "Voice Document Intelligence System v2.0",
        "features": {
            "contextual_embeddings": "3-level (local, document, global)",
            "voice_stack": "Deepgram Nova-3 + Cartesia Sonic + LiveKit",
            "document_processing": "Intelligent chunking with structure preservation",
            "rag": "Multi-context aware retrieval",
        },
        "services": {
            "modern_doc_processor": svc is not None
            and svc.modern_doc_processor is not None,
            "contextual_embeddings": svc is not None
            and svc.contextual_embedding_generator is not None,
            "enhanced_voice": svc is not None
            and svc.enhanced_voice_service is not None,
            "modern_vector_store": svc is not None
            and svc.modern_vector_store is not None,
        },
    }


@app.post("/api/v1/test/process-sample")
async def process_sample_document(
    request: Request,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_db),
):
    """Process a sample document for testing"""
    sample_content = """
    # Sample Document: Voice Document Intelligence System

    ## Introduction
    This is a sample document to test the contextual embedding system.

    ## Features
    - Intelligent document chunking that preserves semantic boundaries
    - Three-level contextual embeddings (local, document, global)
    - Real-time voice interaction with document search
    - Advanced RAG with context-aware retrieval

    ## Architecture
    The system uses a microservices architecture with the following components:
    1. Document Processor: Handles intelligent chunking
    2. Embedding Generator: Creates contextual embeddings
    3. Vector Store: Manages embeddings with metadata
    4. Voice Service: Handles real-time voice interactions

    ## Implementation Details
    The contextual embedding approach ensures that each chunk maintains awareness of its surrounding context,
    document structure, and relationships to other documents in the system.
    """

    # Save sample document to storage
    file_path = Path("uploads") / "sample_document.txt"
    file_path.parent.mkdir(exist_ok=True)
    with open(file_path, "w") as f:
        f.write(sample_content)

    # Create document in database
    content_bytes = sample_content.encode("utf-8")
    from apps.api.services.document.document_service import (
        DocumentAlreadyExistsError,
        document_service,
    )

    try:
        document = await document_service.create_document(
            session=session,
            filename="sample_document.txt",
            file_content=content_bytes,
            file_type="text/plain",
            user_metadata={"source": "sample", "use_enhanced": True},
        )
    except DocumentAlreadyExistsError:
        return {"message": "Sample document already exists", "document_id": None}

    document_id = str(document.id)

    # Process in background
    background_tasks.add_task(
        process_document_task,
        document_id,
        str(file_path),
        "text/plain",
        True,
        request.app.state.services,
    )

    return {
        "document_id": document_id,
        "message": "Sample document created and processing started",
    }


# Error handlers
@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    """Handle HTTP exceptions"""
    # Log HTTP exceptions
    logger.warning(
        f"HTTP {exc.status_code} - {request.method} {request.url.path} - {exc.detail}"
    )

    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": exc.detail,
            "status_code": exc.status_code,
            "timestamp": datetime.utcnow().isoformat(),
            "path": str(request.url.path),
        },
    )


@app.exception_handler(Exception)
async def general_exception_handler(request, exc):
    """Handle general exceptions"""
    # Log full exception with traceback
    logger.error(
        f"Unhandled exception in {request.method} {request.url.path}: {exc}",
        exc_info=True,
    )

    # Log to separate error file for critical review
    error_logger = logging.getLogger("critical_errors")
    error_logger.error(
        f"CRITICAL - Unhandled exception\n"
        f"Path: {request.method} {request.url.path}\n"
        f"Client: {request.client.host if request.client else 'unknown'}\n"
        f"Exception: {type(exc).__name__}: {str(exc)}",
        exc_info=True,
    )

    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal server error",
            "status_code": 500,
            "timestamp": datetime.utcnow().isoformat(),
            "path": str(request.url.path),
        },
    )


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=settings.api_port,
        reload=settings.debug,
        log_level=settings.log_level.lower(),
        access_log=True,
    )
