"""
Protocol-based service abstractions for dependency injection.

Defines typing.Protocol interfaces for all major services, enabling
testability via substitution without inheritance coupling.
"""

from typing import Any, Dict, List, Optional, Protocol, runtime_checkable


@runtime_checkable
class DocumentProcessorProtocol(Protocol):
    """Interface for document processing services."""

    async def process_document(
        self,
        file_path: str,
        content_type: str | None = None,
        metadata: Dict[str, Any] | None = None,
    ) -> Any: ...


@runtime_checkable
class EmbeddingServiceProtocol(Protocol):
    """Interface for embedding generation services."""

    async def generate_embedding(self, text: str) -> List[float]: ...

    async def generate_embeddings_batch(
        self, texts: List[str]
    ) -> List[List[float]]: ...


@runtime_checkable
class ContextualEmbeddingGeneratorProtocol(Protocol):
    """Interface for multi-level contextual embedding generation."""

    async def generate_embeddings(
        self,
        chunks: List[Dict[str, Any]],
        document_metadata: Dict[str, Any],
        use_voyage: bool = False,
    ) -> List[Dict[str, Any]]: ...

    async def generate_contextual_embedding(
        self,
        text: str,
        context_level: str = "local",
        conversation_history: Optional[List[Dict[str, str]]] = None,
        document_context: Optional[List[str]] = None,
    ) -> List[float]: ...


@runtime_checkable
class VectorStoreProtocol(Protocol):
    """Interface for vector storage services."""

    async def store_embeddings(
        self, document_id: str, embeddings_data: List[Dict[str, Any]]
    ) -> None: ...

    async def search(
        self, query_embedding: List[float], top_k: int = 5
    ) -> List[Any]: ...

    async def delete_document(self, document_id: str) -> None: ...


@runtime_checkable
class ModernVectorStoreProtocol(Protocol):
    """Interface for multi-collection vector storage."""

    async def initialize(self) -> None: ...

    async def store_contextual_embeddings(
        self,
        document_id: str,
        embeddings_data: List[Dict[str, Any]],
        document_structure: Any,
    ) -> None: ...

    async def search_with_context(
        self,
        query_embedding: List[float],
        context_level: str = "local",
        top_k: int = 5,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[Any]: ...

    async def delete_document(self, document_id: str) -> None: ...


@runtime_checkable
class RAGServiceProtocol(Protocol):
    """Interface for RAG query processing."""

    async def process_query(
        self, query: str, conversation_id: Optional[str] = None
    ) -> Dict[str, Any]: ...


@runtime_checkable
class VoiceServiceProtocol(Protocol):
    """Interface for voice services."""

    async def generate_token(self, room_name: str, participant_name: str) -> str: ...
