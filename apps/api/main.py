# apps/api/main.py
"""
Enhanced FastAPI application for Voice Document Intelligence System
Full implementation with contextual embeddings and voice integration
"""

import asyncio
import logging
import os
import json
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional

import uvicorn
from fastapi import FastAPI, HTTPException, UploadFile, File, Depends, BackgroundTasks, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

# Core imports
from apps.api.core.config import settings
from apps.api.core.database import init_db, get_db, Base, AsyncSessionLocal, check_db_health
from apps.api.core.connections import init_redis, init_qdrant, init_storage, get_redis_client, get_qdrant_client, get_storage_service
from apps.api.core.auth import verify_api_key
from apps.api.services.analytics_service import track_event, get_event_stats, append_message, get_conversation_history
from apps.api.core.cache import get_cached_response, set_cached_response, invalidate_document_cache

# Document processing services
from apps.api.services.document.processor import DocumentProcessor
from apps.api.services.document.contextual_processor import ModernDocumentProcessor, ContextualEmbeddingGenerator
from apps.api.services.document.embeddings import EmbeddingService
from apps.api.services.document.vector_store import VectorStoreService, ModernVectorStore

# RAG services
from apps.api.services.rag.llamaindex_service import RAGService, ModernRAGService

# Voice services
from apps.api.services.voice.livekit_service import VoiceService
from apps.api.services.voice.enhanced_livekit_service import (
    EnhancedVoiceService,
    DocumentIntelligenceVoiceAgent,
    entrypoint
)

# Agents - Multi-Agent System with CrewAI
from apps.api.services.agents.crew_setup import DocumentIntelligenceAgents
from apps.api.services.agents.agent_coordinator import DocumentIntelligenceCoordinator

# Models
from apps.api.models.document import Document, DocumentChunk, DocumentCreate, DocumentResponse, DocumentStats
from apps.api.models.requests import QueryRequest
from apps.api.models.responses import QueryResponse
from pydantic import BaseModel

# Structured logging (structlog + stdlib)
from apps.api.core.logging import configure_logging, get_logger

configure_logging()
logger = get_logger(__name__)

# Global service instances
doc_processor: DocumentProcessor = None
modern_doc_processor: ModernDocumentProcessor = None
embedding_service: EmbeddingService = None
contextual_embedding_generator: ContextualEmbeddingGenerator = None
vector_store: VectorStoreService = None
modern_vector_store: ModernVectorStore = None
rag_service: RAGService = None
modern_rag_service: ModernRAGService = None
voice_service: VoiceService = None
enhanced_voice_service: EnhancedVoiceService = None
doc_intelligence_agents: DocumentIntelligenceAgents = None
doc_intelligence_coordinator: DocumentIntelligenceCoordinator = None

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
        logger.info("✅ Database initialized")
        
        # Initialize connections
        await init_redis()
        await init_qdrant()
        await init_storage()
        logger.info("✅ External services connected")
        
        # Initialize services
        global doc_processor, modern_doc_processor, embedding_service, contextual_embedding_generator
        global vector_store, modern_vector_store, rag_service, modern_rag_service
        global voice_service, enhanced_voice_service, doc_intelligence_agents, doc_intelligence_coordinator
        
        # Document processing
        doc_processor = DocumentProcessor()
        modern_doc_processor = ModernDocumentProcessor()
        logger.info("✅ Document processors initialized")
        
        # Embeddings
        embedding_service = EmbeddingService()
        contextual_embedding_generator = ContextualEmbeddingGenerator()
        logger.info("✅ Embedding services initialized")
        
        # Vector stores
        vector_store = VectorStoreService()
        modern_vector_store = ModernVectorStore()
        await modern_vector_store.initialize()  # Initialize collections
        logger.info("✅ Vector stores initialized")
        
        # RAG services
        rag_service = RAGService()
        modern_rag_service = ModernRAGService()
        logger.info("✅ RAG services initialized")
        
        # Voice services
        voice_service = VoiceService()
        enhanced_voice_service = EnhancedVoiceService()
        logger.info("✅ Voice services initialized")

        # Multi-Agent System (CrewAI)
        doc_intelligence_agents = DocumentIntelligenceAgents()
        doc_intelligence_coordinator = DocumentIntelligenceCoordinator()
        logger.info("✅ Multi-agent system initialized (CrewAI)")

        logger.info("🚀 All services initialized successfully!")
        logger.info("🎙️  Voice worker must be started separately")

    except Exception as e:
        logger.error(f"❌ Initialization failed: {e}")
        raise

    yield

    # Cleanup
    logger.info("Shutting down services...")
    logger.info("✅ Shutdown complete")

# Create FastAPI app
app = FastAPI(
    title="Voice Document Intelligence API",
    description="API for voice-enabled document intelligence with contextual embeddings",
    version="2.0.0",
    lifespan=lifespan
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Request middleware: correlation-id propagation + structured logging + Prometheus metrics
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
import structlog
import time

from apps.api.core.metrics import (
    HTTP_REQUESTS_TOTAL, HTTP_REQUEST_DURATION,
    metrics_response, metrics_content_type,
)
from apps.api.core.resilience import get_all_breaker_states


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
        req_logger.info("request_started", client=request.client.host if request.client else "unknown")

        try:
            response = await call_next(request)
            duration = time.monotonic() - start_time

            # 3. Prometheus metrics
            path_label = request.url.path.split("?")[0]
            HTTP_REQUESTS_TOTAL.labels(
                method=request.method, path=path_label, status=response.status_code
            ).inc()
            HTTP_REQUEST_DURATION.labels(method=request.method, path=path_label).observe(duration)

            # 4. Structured log with duration
            log_method = req_logger.warning if response.status_code >= 400 else req_logger.info
            log_method("request_completed", status=response.status_code, duration_ms=round(duration * 1000, 1))

            # 5. Propagate request-id to response
            response.headers["X-Request-ID"] = request_id
            return response

        except Exception as exc:
            duration = time.monotonic() - start_time
            req_logger.error("request_failed", duration_ms=round(duration * 1000, 1), error=str(exc), exc_info=True)
            raise


app.add_middleware(ObservabilityMiddleware)

# Import and include routers
from apps.api.routers import voice
app.include_router(voice.router)

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
                "collections": len(collections.collections)
            }
        else:
            services_status["qdrant"] = "unhealthy"
    except Exception as e:
        services_status["qdrant"] = f"unhealthy: {e}"

    # Check service instances
    services_status["embeddings"] = "healthy" if embedding_service else "unavailable"
    services_status["voice"] = "healthy" if voice_service else "unavailable"
    services_status["voice_worker"] = "separate_process"

    # Determine overall health
    core_services = [services_status["database"], services_status["redis"]]
    qdrant_status = services_status["qdrant"]
    if isinstance(qdrant_status, dict):
        core_services.append(qdrant_status["status"])
    else:
        core_services.append(qdrant_status)

    overall_health = "healthy" if all(
        s == "healthy" for s in core_services
    ) else "degraded"

    return {
        "status": overall_health,
        "services": services_status,
        "circuit_breakers": get_all_breaker_states(),
        "version": settings.app_version,
        "timestamp": datetime.utcnow().isoformat()
    }

# Document upload endpoint
@app.post("/api/v1/documents/upload")
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    use_enhanced: bool = Query(True, description="Use enhanced processing with contextual embeddings"),
    session: AsyncSession = Depends(get_db),
    _api_key: str = Depends(verify_api_key)
):
    """Upload and process a document with contextual embeddings"""
    from apps.api.services.document.document_service import (
        document_service,
        DocumentAlreadyExistsError,
        DocumentProcessingError
    )

    try:
        # Validate file
        if file.size > settings.max_file_size:
            raise HTTPException(400, f"File too large. Maximum size: {settings.max_file_size} bytes")

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
                user_metadata={
                    "use_enhanced": use_enhanced,
                    "uploaded_by": "api"
                }
            )
        except DocumentAlreadyExistsError as e:
            raise HTTPException(409, f"Document already exists: {str(e)}")

        # Upload to storage (local or MinIO based on config)
        storage_result = await storage_service.upload_file(
            file_content=content,
            filename=file.filename,
            document_id=str(document.id),
            metadata={
                "uploaded_by": "api",
                "use_enhanced": use_enhanced
            }
        )

        # Update document with storage metadata
        await document_service.update_document_metadata(
            session=session,
            document_id=document.id,
            extracted_metadata={
                "file_path": storage_result["file_path"],
                "storage_type": storage_result["storage_type"],
                "content_type": storage_result["content_type"]
            }
        )

        # Update status to processing
        await document_service.update_document_status(
            session=session,
            document_id=document.id,
            status="processing"
        )

        # Process document in background
        background_tasks.add_task(
            process_document_task,
            str(document.id),
            storage_result["file_path"],
            storage_result["content_type"],
            use_enhanced
        )

        # Notify WebSocket clients
        await notify_clients({
            "type": "document_uploaded",
            "document_id": str(document.id),
            "filename": file.filename
        })

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
            "message": "Document uploaded successfully and is being processed"
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
    use_enhanced: bool = True
):
    """Background task to process document with contextual embeddings"""
    from apps.api.services.document.document_service import document_service
    from uuid import UUID

    # Convert document_id to UUID
    doc_uuid = UUID(document_id)

    # Create a new database session for background task
    async with AsyncSessionLocal() as session:
        try:
            logger.info(f"Processing document {document_id} with enhanced={use_enhanced}")

            # Get document from database
            document = await document_service.get_document(session, doc_uuid)
            if not document:
                logger.error(f"Document {document_id} not found in database")
                return

            await notify_clients({
                "type": "processing_started",
                "document_id": document_id
            })
        
            if use_enhanced:
                # Enhanced processing with contextual embeddings

                # 1. Process document with intelligent chunking
                processing_result = await modern_doc_processor.process_document(
                    file_path,
                    content_type,
                    metadata={"document_id": document_id}
                )

                # 2. Generate contextual embeddings (3 levels)
                embeddings_data = await contextual_embedding_generator.generate_embeddings(
                    chunks=processing_result["chunks"],
                    document_metadata={
                        "document_id": document_id,
                        "title": document.filename,
                        **processing_result["metadata"]
                    },
                    use_voyage=bool(settings.voyage_api_key)
                )

                # 3. Store in vector database with context
                await modern_vector_store.store_contextual_embeddings(
                    document_id,
                    embeddings_data,
                    processing_result["structure"]
                )

                # 4. Add chunks to database
                chunk_dicts = []
                for chunk in processing_result["chunks"]:
                    chunk_dicts.append({
                        "content": chunk.get("content", ""),
                        "token_count": chunk.get("token_count"),
                        "start_char": chunk.get("start_char"),
                        "end_char": chunk.get("end_char"),
                        "start_page": chunk.get("start_page"),
                        "end_page": chunk.get("end_page"),
                        "metadata": chunk.get("metadata", {})
                    })

                await document_service.add_chunks(session, doc_uuid, chunk_dicts)

                # 4.5. Extract and persist named entities from chunks
                all_entities = []
                for chunk in processing_result["chunks"]:
                    chunk_entities = chunk.get("metadata", {}).get("entities", [])
                    for ent in chunk_entities:
                        all_entities.append({
                            "entity_type": ent.get("type", ent.get("label", "UNKNOWN")),
                            "entity_value": ent.get("text", ent.get("value", "")),
                            "confidence_score": ent.get("confidence"),
                            "extraction_method": "spacy",
                        })
                if all_entities:
                    await document_service.add_entities(session, doc_uuid, all_entities)

                # 5. Update document metadata and status
                await document_service.update_document_metadata(
                    session=session,
                    document_id=doc_uuid,
                    doc_metadata={
                        "structure": processing_result["structure"].__dict__ if hasattr(processing_result["structure"], "__dict__") else {},
                        "processing_method": "enhanced_contextual",
                        "chunk_count": len(processing_result["chunks"])
                    }
                )

                await document_service.update_document_status(
                    session=session,
                    document_id=doc_uuid,
                    status="completed"
                )
            else:
                # Basic processing (backward compatibility)
                chunks = await doc_processor.process_document(file_path)

                embeddings_data = []
                chunk_dicts = []

                for i, chunk in enumerate(chunks):
                    embedding = await embedding_service.generate_embedding(chunk["content"])
                    embeddings_data.append({
                        "chunk_id": f"{document_id}_chunk_{i}",
                        "content": chunk["content"],
                        "metadata": chunk.get("metadata", {}),
                        "embedding": embedding
                    })

                    chunk_dicts.append({
                        "content": chunk["content"],
                        "token_count": chunk.get("token_count"),
                        "metadata": chunk.get("metadata", {})
                    })

                await vector_store.store_embeddings(document_id, embeddings_data)
                await document_service.add_chunks(session, doc_uuid, chunk_dicts)

                await document_service.update_document_metadata(
                    session=session,
                    document_id=doc_uuid,
                    doc_metadata={
                        "processing_method": "basic",
                        "chunk_count": len(chunks)
                    }
                )

                await document_service.update_document_status(
                    session=session,
                    document_id=doc_uuid,
                    status="completed"
                )

            logger.info(f"✅ Document {document_id} processed successfully")

            # Get updated document for chunk count
            document = await document_service.get_document(session, doc_uuid)
            chunk_count = len(document.chunks) if document else 0

            await notify_clients({
                "type": "processing_completed",
                "document_id": document_id,
                "chunk_count": chunk_count
            })

            # Track document processing analytics
            await track_event(
                session,
                event_type="document_processed",
                document_id=document_id,
                event_data={"chunk_count": chunk_count, "method": "enhanced" if use_enhanced else "basic"},
            )

        except Exception as e:
            logger.error(f"❌ Document processing failed for {document_id}: {e}")

            # Update document status to failed
            await document_service.update_document_status(
                session=session,
                document_id=doc_uuid,
                status="failed",
                error={"message": str(e), "type": type(e).__name__}
            )

            await notify_clients({
                "type": "processing_failed",
                "document_id": document_id,
                "error": str(e)
            })

# Query endpoint with contextual search
@app.post("/api/v1/query", response_model=QueryResponse)
async def query_documents(
    request: QueryRequest,
    session: AsyncSession = Depends(get_db),
    _api_key: str = Depends(verify_api_key),
):
    """Query documents using contextual embeddings"""
    import time as _time
    query_start = _time.monotonic()
    conversation_id = request.conversation_id or f"api-{uuid.uuid4()}"

    try:
        # Check Redis cache first (skip for conversations with history)
        context_level = request.context_level or "document"
        if not request.conversation_id:
            cached = await get_cached_response(request.query, context_level)
            if cached:
                return QueryResponse(**cached)

        # Load conversation history from DB for context
        history = await get_conversation_history(session, conversation_id, last_n=5)

        if request.use_enhanced:
            voice_agent = DocumentIntelligenceVoiceAgent()
            result = await voice_agent.process_voice_query(
                query=request.query,
                conversation_id=conversation_id,
                audio_metadata={"source": "api", "context_level": request.context_level}
            )
            answer = result["answer"]
            sources = result["sources"]
            context_level = result["context_level"]
            metadata = {
                "metrics": result.get("metrics", {}),
                "context_info": result.get("context_info", {}),
            }
        else:
            result = await rag_service.process_query(
                query=request.query,
                conversation_id=conversation_id,
            )
            answer = result["answer"]
            sources = result.get("sources", [])
            context_level = "document"
            metadata = {}

        latency_ms = int((_time.monotonic() - query_start) * 1000)

        # Persist conversation turn to DB
        await append_message(session, conversation_id, request.query, answer)

        # Track analytics event
        await track_event(
            session,
            event_type="query",
            session_id=conversation_id,
            event_data={
                "query": request.query,
                "context_level": context_level,
                "enhanced": request.use_enhanced,
                "source_count": len(sources),
            },
            latency_ms=latency_ms,
        )

        # Record Prometheus metric
        from apps.api.core.metrics import RAG_QUERY_DURATION
        RAG_QUERY_DURATION.observe(latency_ms / 1000.0)

        response = QueryResponse(
            answer=answer,
            sources=sources,
            conversation_id=conversation_id,
            context_level=context_level,
            metadata=metadata,
        )

        # Cache the response for future identical queries
        if not request.conversation_id:
            await set_cached_response(request.query, context_level, response.model_dump())

        return response

    except Exception as e:
        logger.error("query_failed", error=str(e), query=request.query)
        raise HTTPException(500, f"Query failed: {str(e)}")

# List documents endpoint
@app.get("/api/v1/documents")
async def list_documents(
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=100),
    status: Optional[str] = None,
    session: AsyncSession = Depends(get_db),
    _api_key: str = Depends(verify_api_key)
):
    """List all documents with pagination"""
    from apps.api.services.document.document_service import document_service

    documents = await document_service.list_documents(
        session=session,
        skip=skip,
        limit=limit,
        status=status
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
            "metadata": doc.doc_metadata
        }
        for doc in documents
    ]

    # Get total count
    from sqlalchemy import func, select as sql_select
    from apps.api.models.document import Document as DocumentModel

    total_query = sql_select(func.count()).select_from(DocumentModel).where(DocumentModel.deleted_at.is_(None))
    if status:
        total_query = total_query.where(DocumentModel.processing_status == status)

    total = await session.scalar(total_query) or 0

    return {
        "documents": documents_list,
        "total": total,
        "skip": skip,
        "limit": limit
    }

# Get document details
@app.get("/api/v1/documents/{document_id}")
async def get_document(
    document_id: str,
    session: AsyncSession = Depends(get_db),
    _api_key: str = Depends(verify_api_key)
):
    """Get document details including structure"""
    from apps.api.services.document.document_service import document_service
    from uuid import UUID

    try:
        doc_uuid = UUID(document_id)
    except ValueError:
        raise HTTPException(400, "Invalid document ID format")

    document = await document_service.get_document(
        session=session,
        document_id=doc_uuid,
        include_chunks=True
    )

    if not document:
        raise HTTPException(404, "Document not found")

    return {
        "id": str(document.id),
        "filename": document.filename,
        "file_type": document.file_type,
        "file_size": document.file_size,
        "processing_status": document.processing_status,
        "processing_started_at": document.processing_started_at.isoformat() if document.processing_started_at else None,
        "processing_completed_at": document.processing_completed_at.isoformat() if document.processing_completed_at else None,
        "processing_error": document.processing_error,
        "created_at": document.created_at.isoformat(),
        "updated_at": document.updated_at.isoformat(),
        "chunk_count": len(document.chunks) if document.chunks else 0,
        "metadata": document.doc_metadata,
        "extracted_metadata": document.extracted_metadata
    }

# Delete document
@app.delete("/api/v1/documents/{document_id}")
async def delete_document(
    document_id: str,
    session: AsyncSession = Depends(get_db),
    _api_key: str = Depends(verify_api_key)
):
    """Delete a document and its embeddings"""
    from apps.api.services.document.document_service import document_service
    from uuid import UUID

    try:
        doc_uuid = UUID(document_id)
    except ValueError:
        raise HTTPException(400, "Invalid document ID format")

    # Get document first to check if it exists and get metadata
    document = await document_service.get_document(session=session, document_id=doc_uuid)
    if not document:
        raise HTTPException(404, "Document not found")

    try:
        # Delete from vector store (check metadata for processing method)
        processing_method = document.doc_metadata.get("processing_method", "basic")
        if processing_method == "enhanced_contextual":
            await modern_vector_store.delete_document(document_id)
        else:
            await vector_store.delete_document(document_id)

        # Delete from storage
        storage_service = get_storage_service()
        filename = document.filename
        file_path = document.extracted_metadata.get("file_path")
        if file_path:
            try:
                await storage_service.delete_file(document_id, filename)
            except Exception as e:
                logger.warning(f"Failed to delete file from storage: {e}")

        # Soft delete from database
        success = await document_service.delete_document(
            session=session,
            document_id=doc_uuid,
            soft_delete=True
        )

        if not success:
            raise HTTPException(500, "Failed to delete document from database")
        
        await notify_clients({
            "type": "document_deleted",
            "document_id": document_id
        })
        
        return {"message": "Document deleted successfully"}
        
    except Exception as e:
        logger.error(f"Document deletion failed: {e}")
        raise HTTPException(500, f"Deletion failed: {str(e)}")

# Voice endpoints
@app.get("/api/v1/voice/token")
async def get_voice_token(
    room_name: str = Query("document-chat", description="Room name"),
    participant_name: str = Query("user", description="Participant name")
):
    """Get LiveKit token for voice connection"""
    try:
        # Use the VoiceService which has generate_token method
        token = await voice_service.generate_token(
            room_name=room_name,
            participant_name=participant_name
        )

        return {
            "token": token,
            "url": settings.livekit_url,
            "room_name": room_name
        }

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
    processing_docs = status_counts.get("processing", 0) + status_counts.get("pending", 0)

    return {
        "documents": {
            "total": total_docs,
            "completed": completed_docs,
            "failed": failed_docs,
            "processing": processing_docs
        },
        "chunks": {
            "total": stats.total_chunks,
            "average_per_doc": stats.total_chunks / completed_docs if completed_docs > 0 else 0
        },
        "entities": {
            "total": stats.total_entities
        },
        "timestamp": datetime.utcnow().isoformat()
    }

@app.get("/api/v1/analytics/performance")
async def get_performance_analytics(session: AsyncSession = Depends(get_db)):
    """Get performance analytics from real tracked events."""
    stats = await get_event_stats(session, hours=24)
    latencies = stats.get("latencies", {})

    return {
        "average_latencies": {
            "query": latencies.get("query", {}).get("avg_ms", 0),
            "query_p95": latencies.get("query", {}).get("p95_ms", 0),
            "document_upload": latencies.get("document_upload", {}).get("avg_ms", 0),
        },
        "event_counts": stats.get("event_counts", {}),
        "active_sessions": len(enhanced_voice_service.sessions) if enhanced_voice_service else 0,
        "period_hours": stats.get("period_hours", 24),
        "timestamp": datetime.utcnow().isoformat(),
    }

# Test endpoints for development
@app.get("/api/v1/test/demo")
async def demo_test():
    """Demo endpoint to test system"""
    return {
        "message": "Voice Document Intelligence System v2.0",
        "features": {
            "contextual_embeddings": "3-level (local, document, global)",
            "voice_stack": "Deepgram Nova-3 + Cartesia Sonic + LiveKit",
            "document_processing": "Intelligent chunking with structure preservation",
            "rag": "Multi-context aware retrieval"
        },
        "services": {
            "modern_doc_processor": modern_doc_processor is not None,
            "contextual_embeddings": contextual_embedding_generator is not None,
            "enhanced_voice": enhanced_voice_service is not None,
            "modern_vector_store": modern_vector_store is not None
        }
    }

@app.post("/api/v1/test/process-sample")
async def process_sample_document(
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_db)
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
    try:
        document = await document_service.create_document(
            session=session,
            filename="sample_document.txt",
            file_content=content_bytes,
            file_type="text/plain",
            user_metadata={"source": "sample", "use_enhanced": True}
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
        True
    )

    return {
        "document_id": document_id,
        "message": "Sample document created and processing started"
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
            "path": str(request.url.path)
        }
    )

@app.exception_handler(Exception)
async def general_exception_handler(request, exc):
    """Handle general exceptions"""
    # Log full exception with traceback
    logger.error(
        f"Unhandled exception in {request.method} {request.url.path}: {exc}",
        exc_info=True
    )

    # Log to separate error file for critical review
    error_logger = logging.getLogger("critical_errors")
    error_logger.error(
        f"CRITICAL - Unhandled exception\n"
        f"Path: {request.method} {request.url.path}\n"
        f"Client: {request.client.host if request.client else 'unknown'}\n"
        f"Exception: {type(exc).__name__}: {str(exc)}",
        exc_info=True
    )

    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal server error",
            "status_code": 500,
            "timestamp": datetime.utcnow().isoformat(),
            "path": str(request.url.path)
        }
    )

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=settings.api_port,
        reload=settings.debug,
        log_level=settings.log_level.lower(),
        access_log=True
    )