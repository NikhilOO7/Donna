"""
Document Service - PostgreSQL-backed document management
Replaces in-memory document storage with persistent database storage
"""

import hashlib
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from apps.api.models.document import (
    Document,
    DocumentChunk,
    DocumentStats,
    Entity,
)

logger = logging.getLogger(__name__)


class DocumentNotFoundError(Exception):
    """Raised when document is not found"""

    pass


class DocumentAlreadyExistsError(Exception):
    """Raised when document with same hash already exists"""

    pass


class DocumentProcessingError(Exception):
    """Raised when document processing fails"""

    pass


class DocumentService:
    """PostgreSQL-backed document service"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)

    async def create_document(
        self,
        session: AsyncSession,
        filename: str,
        file_content: bytes,
        file_type: Optional[str] = None,
        user_metadata: Optional[Dict[str, Any]] = None,
        owner_id: Optional[UUID] = None,
    ) -> Document:
        """
        Create a new document in the database

        Args:
            session: Database session
            filename: Name of the file
            file_content: Raw file content for hash calculation
            file_type: MIME type
            user_metadata: User-provided metadata

        Returns:
            Created Document instance

        Raises:
            DocumentAlreadyExistsError: If document with same hash exists
        """
        try:
            # Calculate file hash
            file_hash = hashlib.sha256(file_content).hexdigest()
            file_size = len(file_content)

            # Check for duplicate (scoped per-owner for multi-tenancy)
            existing = await self.get_document_by_hash(session, file_hash, owner_id)
            if existing:
                if existing.processing_status == "failed":
                    # A failed upload must not block a retry — replace the
                    # dead row (and any partial chunks/entities) and reprocess.
                    self.logger.info(
                        f"Replacing failed document {existing.id} to allow re-upload"
                    )
                    await session.execute(
                        delete(Entity).where(Entity.document_id == existing.id)
                    )
                    await session.execute(
                        delete(DocumentChunk).where(
                            DocumentChunk.document_id == existing.id
                        )
                    )
                    await session.execute(
                        delete(Document).where(Document.id == existing.id)
                    )
                    await session.flush()
                else:
                    self.logger.warning(
                        f"Document with hash {file_hash} already exists: {existing.id}"
                    )
                    raise DocumentAlreadyExistsError(
                        f"Document already exists with id: {existing.id}"
                    )

            # Create document
            document = Document(
                id=uuid4(),
                external_id=str(uuid4()),
                filename=filename,
                file_type=file_type,
                file_size=file_size,
                file_hash=file_hash,
                processing_status="pending",
                owner_id=owner_id,
                user_metadata=user_metadata or {},
                doc_metadata={},
                extracted_metadata={},
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )

            session.add(document)
            await session.commit()
            await session.refresh(document)

            self.logger.info(f"Created document: {document.id} - {filename}")
            return document

        except DocumentAlreadyExistsError:
            raise
        except Exception as e:
            await session.rollback()
            self.logger.error(f"Failed to create document: {e}")
            raise DocumentProcessingError(f"Failed to create document: {str(e)}")

    async def get_document(
        self, session: AsyncSession, document_id: UUID, include_chunks: bool = False
    ) -> Optional[Document]:
        """
        Get document by ID

        Args:
            session: Database session
            document_id: Document UUID
            include_chunks: Whether to load chunks

        Returns:
            Document instance or None
        """
        try:
            query = select(Document).where(
                Document.id == document_id, Document.deleted_at.is_(None)
            )

            if include_chunks:
                query = query.options(selectinload(Document.chunks))

            result = await session.execute(query)
            document = result.scalar_one_or_none()

            return document

        except Exception as e:
            self.logger.error(f"Failed to get document {document_id}: {e}")
            return None

    async def get_document_by_hash(
        self,
        session: AsyncSession,
        file_hash: str,
        owner_id: Optional[UUID] = None,
    ) -> Optional[Document]:
        """Get document by file hash, scoped to an owner when given.

        Per-owner scoping means two tenants can independently upload the
        same file; dedup only collapses within a tenant.
        """
        try:
            query = select(Document).where(
                Document.file_hash == file_hash,
                Document.deleted_at.is_(None),
            )
            if owner_id is not None:
                query = query.where(Document.owner_id == owner_id)
            result = await session.execute(query)
            return result.scalar_one_or_none()
        except Exception as e:
            self.logger.error(f"Failed to get document by hash: {e}")
            return None

    async def list_documents(
        self,
        session: AsyncSession,
        skip: int = 0,
        limit: int = 100,
        status: Optional[str] = None,
        owner_id: Optional[UUID] = None,
    ) -> List[Document]:
        """
        List documents with pagination

        Args:
            session: Database session
            skip: Number of records to skip
            limit: Maximum number of records to return
            status: Filter by processing status
            owner_id: When set, only this owner's documents (tenant isolation)

        Returns:
            List of Document instances
        """
        try:
            query = select(Document).where(Document.deleted_at.is_(None))

            if owner_id is not None:
                query = query.where(Document.owner_id == owner_id)

            if status:
                query = query.where(Document.processing_status == status)

            query = query.offset(skip).limit(limit).order_by(Document.created_at.desc())

            result = await session.execute(query)
            documents = result.scalars().all()

            return list(documents)

        except Exception as e:
            self.logger.error(f"Failed to list documents: {e}")
            return []

    async def update_document_status(
        self,
        session: AsyncSession,
        document_id: UUID,
        status: str,
        error: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Update document processing status

        Args:
            session: Database session
            document_id: Document UUID
            status: New status (pending, processing, completed, failed)
            error: Error details if status is failed

        Returns:
            True if updated successfully
        """
        try:
            update_data = {
                "processing_status": status,
                "updated_at": datetime.now(timezone.utc),
            }

            if status == "processing":
                update_data["processing_started_at"] = datetime.now(timezone.utc)
            elif status in ("completed", "failed"):
                update_data["processing_completed_at"] = datetime.now(timezone.utc)

            if error:
                update_data["processing_error"] = error
            elif status in ("processing", "completed"):
                # Clear any stale error from a prior failed attempt so a recovered
                # document doesn't keep reporting an error it no longer has.
                update_data["processing_error"] = None

            query = (
                update(Document).where(Document.id == document_id).values(**update_data)
            )

            await session.execute(query)
            await session.commit()

            self.logger.info(f"Updated document {document_id} status to {status}")
            return True

        except Exception as e:
            await session.rollback()
            self.logger.error(f"Failed to update document status: {e}")
            return False

    async def update_document_metadata(
        self,
        session: AsyncSession,
        document_id: UUID,
        doc_metadata: Optional[Dict[str, Any]] = None,
        extracted_metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Update document metadata"""
        try:
            update_data = {"updated_at": datetime.now(timezone.utc)}

            if doc_metadata is not None:
                update_data["doc_metadata"] = doc_metadata
            if extracted_metadata is not None:
                update_data["extracted_metadata"] = extracted_metadata

            query = (
                update(Document).where(Document.id == document_id).values(**update_data)
            )

            await session.execute(query)
            await session.commit()

            return True

        except Exception as e:
            await session.rollback()
            self.logger.error(f"Failed to update metadata: {e}")
            return False

    async def delete_document(
        self, session: AsyncSession, document_id: UUID, soft_delete: bool = True
    ) -> bool:
        """
        Delete document (soft or hard delete)

        Args:
            session: Database session
            document_id: Document UUID
            soft_delete: If True, mark as deleted; if False, permanently delete

        Returns:
            True if deleted successfully
        """
        try:
            if soft_delete:
                query = (
                    update(Document)
                    .where(Document.id == document_id)
                    .values(deleted_at=datetime.now(timezone.utc))
                )
                await session.execute(query)
            else:
                query = delete(Document).where(Document.id == document_id)
                await session.execute(query)

            await session.commit()
            self.logger.info(f"Deleted document {document_id} (soft={soft_delete})")
            return True

        except Exception as e:
            await session.rollback()
            self.logger.error(f"Failed to delete document: {e}")
            return False

    async def get_document_stats(self, session: AsyncSession) -> DocumentStats:
        """Get aggregate statistics"""
        try:
            # Count documents
            doc_count = await session.scalar(
                select(func.count())
                .select_from(Document)
                .where(Document.deleted_at.is_(None))
            )

            # Count chunks
            chunk_count = await session.scalar(
                select(func.count()).select_from(DocumentChunk)
            )

            # Count entities
            entity_count = await session.scalar(
                select(func.count()).select_from(Entity)
            )

            # Status counts
            status_query = (
                select(Document.processing_status, func.count().label("count"))
                .where(Document.deleted_at.is_(None))
                .group_by(Document.processing_status)
            )

            result = await session.execute(status_query)
            status_counts = {row.processing_status: row.count for row in result}

            return DocumentStats(
                total_documents=doc_count or 0,
                total_chunks=chunk_count or 0,
                total_entities=entity_count or 0,
                processing_status_counts=status_counts,
            )

        except Exception as e:
            self.logger.error(f"Failed to get stats: {e}")
            return DocumentStats(
                total_documents=0,
                total_chunks=0,
                total_entities=0,
                processing_status_counts={},
            )

    async def add_chunks(
        self, session: AsyncSession, document_id: UUID, chunks: List[Dict[str, Any]]
    ) -> List[DocumentChunk]:
        """
        Add chunks to a document

        Args:
            session: Database session
            document_id: Document UUID
            chunks: List of chunk data dictionaries

        Returns:
            List of created DocumentChunk instances
        """
        try:
            created_chunks = []

            for idx, chunk_data in enumerate(chunks):
                chunk = DocumentChunk(
                    id=uuid4(),
                    document_id=document_id,
                    chunk_index=idx,
                    content=chunk_data.get("content", ""),
                    content_hash=hashlib.sha256(
                        chunk_data.get("content", "").encode()
                    ).hexdigest(),
                    token_count=chunk_data.get("token_count"),
                    start_char=chunk_data.get("start_char"),
                    end_char=chunk_data.get("end_char"),
                    start_page=chunk_data.get("start_page"),
                    end_page=chunk_data.get("end_page"),
                    section_path=chunk_data.get("section_path"),
                    heading_level=chunk_data.get("heading_level"),
                    is_table=chunk_data.get("is_table", False),
                    is_list=chunk_data.get("is_list", False),
                    chunk_metadata=chunk_data.get("metadata", {}),
                    created_at=datetime.now(timezone.utc),
                )
                session.add(chunk)
                created_chunks.append(chunk)

            await session.commit()

            self.logger.info(
                f"Added {len(created_chunks)} chunks to document {document_id}"
            )
            return created_chunks

        except Exception as e:
            await session.rollback()
            self.logger.error(f"Failed to add chunks: {e}")
            raise DocumentProcessingError(f"Failed to add chunks: {str(e)}")

    async def add_entities(
        self,
        session: AsyncSession,
        document_id: UUID,
        entities: List[Dict[str, Any]],
        chunk_id: Optional[UUID] = None,
    ) -> int:
        """Persist extracted named entities to the database.

        Args:
            session: Database session
            document_id: Parent document UUID
            entities: List of entity dicts with keys: entity_type, entity_value, confidence_score
            chunk_id: Optional chunk UUID this entity was extracted from

        Returns:
            Number of entities created
        """
        try:
            count = 0
            for ent in entities:
                entity = Entity(
                    id=uuid4(),
                    document_id=document_id,
                    chunk_id=chunk_id,
                    entity_type=ent.get("entity_type", "UNKNOWN"),
                    entity_value=ent.get("entity_value", ""),
                    entity_normalized=ent.get("entity_normalized"),
                    confidence_score=ent.get("confidence_score"),
                    extraction_method=ent.get("extraction_method", "spacy"),
                    start_offset=ent.get("start_offset"),
                    end_offset=ent.get("end_offset"),
                    entity_metadata=ent.get("metadata", {}),
                )
                session.add(entity)
                count += 1

            await session.commit()
            self.logger.info(f"Added {count} entities for document {document_id}")
            return count

        except Exception as e:
            await session.rollback()
            self.logger.error(f"Failed to add entities: {e}")
            return 0


# Global service instance
document_service = DocumentService()
