"""
Dependency injection container for FastAPI.

Replaces module-level global variables with a ServiceContainer stored on
app.state.  Endpoints use ``Depends(get_rag_service)`` (etc.) instead of
reading mutable globals.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import Request


@dataclass
class ServiceContainer:
    """Holds all initialised service singletons."""

    # Document processing
    doc_processor: Any = None
    modern_doc_processor: Any = None

    # Embeddings
    embedding_service: Any = None
    contextual_embedding_generator: Any = None

    # Vector stores
    vector_store: Any = None
    modern_vector_store: Any = None

    # RAG
    rag_service: Any = None
    modern_rag_service: Any = None

    # Voice
    voice_service: Any = None
    enhanced_voice_service: Any = None


def _get_container(request: Request) -> ServiceContainer:
    return request.app.state.services


def get_services(request: Request) -> ServiceContainer:
    """Return the full service container."""
    return _get_container(request)


# --- Convenience extractors for individual services ---


def get_doc_processor(request: Request) -> Any:
    return _get_container(request).doc_processor


def get_modern_doc_processor(request: Request) -> Any:
    return _get_container(request).modern_doc_processor


def get_embedding_service(request: Request) -> Any:
    return _get_container(request).embedding_service


def get_contextual_embedding_generator(request: Request) -> Any:
    return _get_container(request).contextual_embedding_generator


def get_vector_store(request: Request) -> Any:
    return _get_container(request).vector_store


def get_modern_vector_store(request: Request) -> Any:
    return _get_container(request).modern_vector_store


def get_rag_service(request: Request) -> Any:
    return _get_container(request).rag_service


def get_modern_rag_service(request: Request) -> Any:
    return _get_container(request).modern_rag_service


def get_voice_service(request: Request) -> Any:
    return _get_container(request).voice_service


def get_enhanced_voice_service(request: Request) -> Any:
    return _get_container(request).enhanced_voice_service
