"""
Pydantic request models for API validation.
"""

from typing import Optional

from pydantic import BaseModel, Field


class QueryRequest(BaseModel):
    """Request model for document queries."""

    query: str = Field(..., min_length=1, max_length=2000, description="The query text")
    conversation_id: Optional[str] = Field(
        default=None, description="Conversation ID for context"
    )
    context_level: Optional[str] = Field(
        default="local", description="Context level: local, document, global"
    )
    max_results: Optional[int] = Field(
        default=5, ge=1, le=50, description="Maximum results to return"
    )
    use_enhanced: Optional[bool] = Field(
        default=True, description="Use enhanced contextual processing"
    )


class DocumentUploadParams(BaseModel):
    """Parameters for document upload (used for validation only)."""

    use_enhanced: bool = Field(
        default=True, description="Use enhanced processing with contextual embeddings"
    )
