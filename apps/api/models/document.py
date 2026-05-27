# apps/api/models/document.py
"""
MODERNIZED Document Models - SQLAlchemy 2.0 + Pydantic v2 (November 2025)
Key changes: Mapped[], mapped_column(), ConfigDict, proper typing
"""

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

# Pydantic v2 imports
from pydantic import BaseModel, ConfigDict, Field, field_validator

# SQLAlchemy 2.0 imports
from sqlalchemy import (
    ARRAY,
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID  # noqa: N811
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..core.database import Base


class Document(Base):
    """Document ORM model using SQLAlchemy 2.0 patterns"""

    __tablename__ = "documents"
    __table_args__ = {"schema": "doc_intel"}

    # Primary key with modern Mapped[] syntax
    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    external_id: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False, default=lambda: str(uuid4())
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_type: Mapped[Optional[str]] = mapped_column(String(100))
    file_size: Mapped[Optional[int]] = mapped_column(Integer)
    file_hash: Mapped[Optional[str]] = mapped_column(String(64))

    # Processing status
    processing_status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="pending"
    )
    processing_started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
    )
    processing_completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
    )
    processing_error: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON)

    # Metadata (renamed to avoid SQLAlchemy reserved name)
    doc_metadata: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    extracted_metadata: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    user_metadata: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)

    # Owner for per-tenant document isolation. Nullable so existing/demo
    # uploads (no auth) stay valid + globally visible; enforced when
    # REQUIRE_AUTH is on. Mirrored into Qdrant payloads + Neo4j nodes so
    # retrieval can be scoped to the tenant.
    owner_id: Mapped[Optional[UUID]] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("doc_intel.users.id"),
        nullable=True,
        index=True,
    )

    # Versioning
    version: Mapped[int] = mapped_column(Integer, default=1)
    parent_document_id: Mapped[Optional[UUID]] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("doc_intel.documents.id")
    )

    # Timestamps with timezone awareness
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    # Relationships with modern typing
    chunks: Mapped[List["DocumentChunk"]] = relationship(
        back_populates="document", cascade="all, delete-orphan", lazy="selectin"
    )
    entities: Mapped[List["Entity"]] = relationship(
        back_populates="document", cascade="all, delete-orphan", lazy="selectin"
    )

    def __repr__(self) -> str:
        return f"<Document(id={self.id}, filename='{self.filename}', status='{self.processing_status}')>"


class DocumentChunk(Base):
    __tablename__ = "document_chunks"
    __table_args__ = {"schema": "doc_intel"}

    id = Column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id = Column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("doc_intel.documents.id"),
        nullable=False,
    )
    chunk_index = Column(Integer, nullable=False)

    # Content
    content = Column(Text, nullable=False)
    content_hash = Column(String(64))
    token_count = Column(Integer)

    # Position
    start_char = Column(Integer)
    end_char = Column(Integer)
    start_page = Column(Integer)
    end_page = Column(Integer)

    # Structure
    section_path = Column(ARRAY(Text))
    heading_level = Column(Integer)
    is_table = Column(Boolean, default=False)
    is_list = Column(Boolean, default=False)

    # Metadata (renamed to avoid SQLAlchemy reserved name)
    chunk_metadata = Column(JSON, default=dict)
    embeddings = Column(JSON, default=dict)

    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)

    # Relationships
    document = relationship("Document", back_populates="chunks")
    contextual_embeddings = relationship(
        "ContextualEmbedding", back_populates="chunk", cascade="all, delete-orphan"
    )
    entities = relationship("Entity", back_populates="chunk")


class ContextualEmbedding(Base):
    __tablename__ = "contextual_embeddings"
    __table_args__ = {"schema": "doc_intel"}

    id = Column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    chunk_id = Column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("doc_intel.document_chunks.id"),
        nullable=False,
    )

    context_type = Column(String(50), nullable=False)
    context_window = Column(Integer, default=3)

    model_name = Column(String(100), nullable=False)
    model_version = Column(String(50))
    embedding_dimension = Column(Integer, nullable=False)

    # Note: Actual embedding stored in Qdrant, this stores metadata
    embedding_id = Column(String(255))  # ID in vector database

    context_metadata = Column(JSON, default=dict)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)

    # Relationships
    chunk = relationship("DocumentChunk", back_populates="contextual_embeddings")


class Entity(Base):
    __tablename__ = "entities"
    __table_args__ = {"schema": "doc_intel"}

    id = Column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id = Column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("doc_intel.documents.id"),
        nullable=False,
    )
    chunk_id = Column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("doc_intel.document_chunks.id")
    )

    entity_type = Column(String(100), nullable=False)
    entity_value = Column(Text, nullable=False)
    entity_normalized = Column(Text)

    confidence_score = Column(Float)
    extraction_method = Column(String(50))

    start_offset = Column(Integer)
    end_offset = Column(Integer)

    entity_metadata = Column(JSON, default=dict)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)

    # Relationships
    document = relationship("Document", back_populates="entities")
    chunk = relationship("DocumentChunk", back_populates="entities")


# ============================================================================
# Pydantic v2 API Models
# ============================================================================


class DocumentCreate(BaseModel):
    """Request model for creating a document (Pydantic v2)"""

    model_config = ConfigDict(
        str_strip_whitespace=True,
        validate_assignment=True,
    )

    filename: str = Field(
        ..., min_length=1, max_length=255, description="Document filename"
    )
    content_type: Optional[str] = Field(None, description="MIME type of document")
    metadata: Optional[Dict[str, Any]] = Field(
        default_factory=dict, description="User metadata"
    )

    @field_validator("filename")
    @classmethod
    def validate_filename(cls, v: str) -> str:
        """Ensure filename doesn't contain invalid characters"""
        invalid_chars = ["<", ">", ":", '"', "|", "?", "*"]
        if any(char in v for char in invalid_chars):
            raise ValueError(f"Filename contains invalid characters: {invalid_chars}")
        return v


class DocumentResponse(BaseModel):
    """Response model for document (Pydantic v2)"""

    model_config = ConfigDict(
        from_attributes=True,  # Replaces orm_mode in v1
    )

    id: str
    filename: str
    file_type: Optional[str] = None
    file_size: Optional[int] = None
    processing_status: str
    created_at: datetime
    metadata: Optional[Dict[str, Any]] = None
    chunk_count: Optional[int] = Field(default=0, description="Number of chunks")

    @field_validator("created_at", mode="before")
    @classmethod
    def parse_datetime(cls, v):
        """Ensure datetime is properly serialized"""
        if isinstance(v, str):
            return datetime.fromisoformat(v.replace("Z", "+00:00"))
        return v


class DocumentStats(BaseModel):
    """Document statistics (Pydantic v2)"""

    model_config = ConfigDict(validate_assignment=True)

    total_documents: int = Field(..., ge=0)
    total_chunks: int = Field(..., ge=0)
    total_entities: int = Field(..., ge=0)
    processing_status_counts: Dict[str, int] = Field(default_factory=dict)
