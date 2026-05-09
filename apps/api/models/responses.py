"""
Pydantic response models for API responses.
"""

from typing import Dict, List, Any, Optional
from pydantic import BaseModel, Field


class QueryResponse(BaseModel):
    """Response model for document queries."""
    answer: str
    sources: List[Dict[str, Any]]
    conversation_id: str
    context_level: str
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ServiceStatus(BaseModel):
    """Status of a single service."""
    status: str
    details: Optional[Dict[str, Any]] = None


class HealthResponse(BaseModel):
    """Response model for health checks."""
    status: str
    services: Dict[str, Any]
    version: str
    timestamp: str


class DocumentAnalytics(BaseModel):
    """Document-level analytics."""
    total: int
    completed: int
    failed: int
    processing: int


class ChunkAnalytics(BaseModel):
    """Chunk-level analytics."""
    total: int
    average_per_doc: float


class UsageAnalyticsResponse(BaseModel):
    """Response model for usage analytics."""
    documents: DocumentAnalytics
    chunks: ChunkAnalytics
    entities: Dict[str, int] = Field(default_factory=dict)
    timestamp: str


class PerformanceAnalyticsResponse(BaseModel):
    """Response model for performance analytics."""
    average_latencies: Dict[str, float]
    success_rate: float
    active_sessions: int
    timestamp: str
