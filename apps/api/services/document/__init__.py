from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, BackgroundTasks, Query
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from typing import List, Optional, Dict, Any
import uuid
import os
from datetime import datetime

from ...core.database import get_db
from ...core.config import settings
from ...core.connections import get_storage_service
from ...models.document import Document, DocumentChunk
from .processor import ModernDocumentProcessor
from .embeddings import ContextualEmbeddingGenerator
from .vector_store import ModernVectorStore

router = APIRouter()

# Initialize services
document_processor = ModernDocumentProcessor()
embedding_generator = ContextualEmbeddingGenerator()
vector_store = ModernVectorStore()

@router.post("/upload")
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    metadata: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
) -> Dict[str, Any]:
    """Upload a document for processing"""
    
    # Validate file
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")
    
    if file.size > settings.max_file_size:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Maximum size: {settings.max_file_size / 1024 / 1024}MB"
        )
    
    # Parse metadata
    user_metadata = {}
    if metadata:
        try:
            import json
            user_metadata = json.loads(metadata)
        except Exception:
            pass
    
    # Save file to storage
    storage_service = get_storage_service()
    file_id = str(uuid.uuid4())

    try:
        # Upload to storage (local or MinIO)
        file_data = await file.read()

        storage_result = await storage_service.upload_file(
            file_content=file_data,
            filename=file.filename,
            document_id=file_id,
            metadata=user_metadata
        )
        
        # Create document record
        document = Document(
            filename=file.filename,
            file_type=storage_result["content_type"],
            file_size=storage_result["file_size"],
            user_metadata=user_metadata,
            processing_status="queued",
            file_hash=storage_result["file_hash"]
        )

        db.add(document)
        await db.commit()
        await db.refresh(document)

        # Queue processing task
        background_tasks.add_task(
            process_document_task,
            str(document.id),
            storage_result["file_path"],
            storage_result["file_path"],
            storage_result["content_type"]
        )
        
        return {
            "document_id": str(document.id),
            "external_id": document.external_id,
            "filename": file.filename,
            "status": "queued",
            "message": "Document queued for processing"
        }
        
    except Exception as e:
        # Clean up on error
        try:
            await storage_service.delete_file(file_id, file.filename)
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")

async def process_document_task(
    document_id: str,
    file_path: str,
    object_name: str,
    content_type: str
):
    """Background task to process document"""
    from ...core.database import get_db_context
    
    async with get_db_context() as db:
        try:
            # Update status
            document = await db.get(Document, document_id)
            document.processing_status = "processing"
            document.processing_started_at = datetime.utcnow()
            await db.commit()
            
            # Process document
            result = await document_processor.process_document(file_path, content_type)
            
            # Check for duplicate
            if result["file_hash"]:
                existing = await db.execute(
                    select(Document).where(
                        and_(
                            Document.file_hash == result["file_hash"],
                            Document.id != document_id
                        )
                    )
                )
                if existing.scalar_one_or_none():
                    document.processing_status = "failed"
                    document.processing_error = {"error": "Duplicate document"}
                    await db.commit()
                    return
            
            # Store file hash
            document.file_hash = result["file_hash"]
            document.extracted_metadata = result.get("metadata", {})
            
            # Store chunks
            chunk_records = []
            for chunk_data in result["chunks"]:
                chunk = DocumentChunk(
                    document_id=document_id,
                    chunk_index=chunk_data["chunk_index"],
                    content=chunk_data["content"],
                    token_count=chunk_data.get("token_count", 0),
                    metadata=chunk_data.get("metadata", {}),
                    section_path=chunk_data.get("section_path", [])
                )
                db.add(chunk)
                chunk_records.append(chunk)
            
            await db.commit()
            
            # Generate embeddings
            embeddings_data = await embedding_generator.generate_embeddings(
                result["chunks"],
                {
                    "filename": document.filename,
                    "file_type": document.file_type,
                    "file_size": document.file_size,
                    **result.get("metadata", {})
                }
            )
            
            # Store in vector database
            stored_counts = await vector_store.store_embeddings(
                document_id,
                embeddings_data
            )
            
            # Extract entities (optional)
            # TODO: Implement entity extraction
            
            # Update document status
            document.processing_status = "completed"
            document.processing_completed_at = datetime.utcnow()
            document.doc_metadata = {
                "chunks_count": len(result["chunks"]),
                "embeddings_stored": stored_counts,
                "object_name": object_name
            }
            await db.commit()
            
        except Exception as e:
            import traceback
            error_details = {
                "error": str(e),
                "traceback": traceback.format_exc()
            }
            
            document = await db.get(Document, document_id)
            document.processing_status = "failed"
            document.processing_error = error_details
            document.processing_completed_at = datetime.utcnow()
            await db.commit()
            
            logger.error(f"Document processing failed: {error_details}")
        
        finally:
            # Clean up temp file
            if os.path.exists(file_path):
                os.remove(file_path)

@router.get("/{document_id}")
async def get_document(
    document_id: str,
    include_chunks: bool = False,
    db: AsyncSession = Depends(get_db)
) -> Dict[str, Any]:
    """Get document details"""
    
    # Try to find by UUID or external_id
    try:
        doc_uuid = uuid.UUID(document_id)
        document = await db.get(Document, doc_uuid)
    except ValueError:
        # Not a UUID, try external_id
        result = await db.execute(
            select(Document).where(Document.external_id == document_id)
        )
        document = result.scalar_one_or_none()
    
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    
    response = {
        "id": str(document.id),
        "external_id": document.external_id,
        "filename": document.filename,
        "file_type": document.file_type,
        "file_size": document.file_size,
        "processing_status": document.processing_status,
        "metadata": document.doc_metadata,
        "extracted_metadata": document.extracted_metadata,
        "user_metadata": document.user_metadata,
        "created_at": document.created_at,
        "updated_at": document.updated_at
    }
    
    if document.processing_error:
        response["error"] = document.processing_error
    
    if include_chunks and document.processing_status == "completed":
        chunks = await db.execute(
            select(DocumentChunk)
            .where(DocumentChunk.document_id == document.id)
            .order_by(DocumentChunk.chunk_index)
        )
        response["chunks"] = [
            {
                "chunk_index": chunk.chunk_index,
                "content": chunk.content[:200] + "..." if len(chunk.content) > 200 else chunk.content,
                "token_count": chunk.token_count,
                "metadata": chunk.chunk_metadata
            }
            for chunk in chunks.scalars()
        ]
    
    return response

@router.get("/")
async def list_documents(
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=100),
    status: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
) -> Dict[str, Any]:
    """List documents with pagination"""
    
    # Build query
    query = select(Document).where(Document.deleted_at.is_(None))
    
    if status:
        query = query.where(Document.processing_status == status)
    
    # Get total count
    count_query = select(func.count()).select_from(query.subquery())
    total = await db.scalar(count_query)
    
    # Get documents
    query = query.order_by(Document.created_at.desc()).offset(skip).limit(limit)
    result = await db.execute(query)
    documents = result.scalars().all()
    
    return {
        "documents": [
            {
                "id": str(doc.id),
                "external_id": doc.external_id,
                "filename": doc.filename,
                "file_type": doc.file_type,
                "file_size": doc.file_size,
                "processing_status": doc.processing_status,
                "created_at": doc.created_at
            }
            for doc in documents
        ],
        "pagination": {
            "total": total,
            "skip": skip,
            "limit": limit,
            "pages": (total + limit - 1) // limit
        }
    }

@router.delete("/{document_id}")
async def delete_document(
    document_id: str,
    db: AsyncSession = Depends(get_db)
) -> Dict[str, Any]:
    """Delete a document and all associated data"""
    
    # Find document
    try:
        doc_uuid = uuid.UUID(document_id)
        document = await db.get(Document, doc_uuid)
    except ValueError:
        result = await db.execute(
            select(Document).where(Document.external_id == document_id)
        )
        document = result.scalar_one_or_none()
    
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    
    # Delete from vector store
    deleted_counts = await vector_store.delete_document(str(document.id))
    
    # Delete from storage
    try:
        storage_service = get_storage_service()
        await storage_service.delete_file(str(document.id), document.filename)
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.warning(f"Failed to delete from storage: {e}")
    
    # Soft delete from database
    document.deleted_at = datetime.utcnow()
    await db.commit()
    
    return {
        "message": "Document deleted successfully",
        "document_id": str(document.id),
        "vectors_deleted": deleted_counts
    }

@router.post("/{document_id}/reprocess")
async def reprocess_document(
    document_id: str,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db)
) -> Dict[str, Any]:
    """Reprocess a document"""
    
    # Find document
    try:
        doc_uuid = uuid.UUID(document_id)
        document = await db.get(Document, doc_uuid)
    except ValueError:
        result = await db.execute(
            select(Document).where(Document.external_id == document_id)
        )
        document = result.scalar_one_or_none()
    
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    
    if document.deleted_at:
        raise HTTPException(status_code=400, detail="Cannot reprocess deleted document")
    
    # Get file from storage
    try:
        storage_service = get_storage_service()
        file_path = await storage_service.get_file_path(str(document.id), document.filename)
        
        # Reset status
        document.processing_status = "queued"
        document.processing_error = None
        await db.commit()
        
        # Queue reprocessing
        background_tasks.add_task(
            process_document_task,
            str(document.id),
            file_path,
            file_path,
            document.file_type
        )
        
        return {
            "document_id": str(document.id),
            "message": "Document queued for reprocessing"
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Reprocessing failed: {str(e)}")