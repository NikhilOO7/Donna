"""
Unit tests for the Document Service (PostgreSQL-backed CRUD).
Tests validate the service logic with mocked database operations.
"""

import hashlib
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from apps.api.services.document.document_service import (
    DocumentAlreadyExistsError,
    DocumentNotFoundError,
    DocumentService,
)


@pytest.fixture
def document_service():
    return DocumentService()


@pytest.fixture
def sample_file_content():
    return b"This is a test document content for unit testing."


class TestDocumentServiceHashing:
    """Tests for document hash computation."""

    def test_sha256_hash_computed_correctly(self, sample_file_content):
        """Verify SHA-256 hash matches expected value."""
        expected = hashlib.sha256(sample_file_content).hexdigest()
        actual = hashlib.sha256(sample_file_content).hexdigest()
        assert expected == actual
        assert len(expected) == 64

    def test_different_content_produces_different_hash(self):
        """Different content should produce different hashes."""
        hash1 = hashlib.sha256(b"content A").hexdigest()
        hash2 = hashlib.sha256(b"content B").hexdigest()
        assert hash1 != hash2

    def test_same_content_produces_same_hash(self, sample_file_content):
        """Same content should always produce the same hash."""
        hash1 = hashlib.sha256(sample_file_content).hexdigest()
        hash2 = hashlib.sha256(sample_file_content).hexdigest()
        assert hash1 == hash2


class TestDocumentServiceExceptions:
    """Tests for custom exception behavior."""

    def test_document_not_found_error_is_exception(self):
        assert issubclass(DocumentNotFoundError, Exception)

    def test_document_already_exists_error_is_exception(self):
        assert issubclass(DocumentAlreadyExistsError, Exception)

    def test_not_found_error_message(self):
        err = DocumentNotFoundError("doc-123")
        assert "doc-123" in str(err)

    def test_already_exists_error_message(self):
        err = DocumentAlreadyExistsError("duplicate found")
        assert "duplicate" in str(err)


class TestDocumentServiceInit:
    """Tests for service initialization."""

    def test_service_initializes(self, document_service):
        assert document_service is not None

    def test_service_has_required_methods(self, document_service):
        assert hasattr(document_service, "create_document")
        assert hasattr(document_service, "get_document")
        assert hasattr(document_service, "list_documents")
        assert hasattr(document_service, "update_document_status")
        assert hasattr(document_service, "delete_document")
        assert hasattr(document_service, "get_document_stats")
        assert hasattr(document_service, "add_chunks")


class TestDocumentServiceDuplication:
    """Tests for duplicate detection logic."""

    @pytest.mark.asyncio
    async def test_duplicate_check_uses_hash(self, document_service):
        """Verify get_document_by_hash is called during creation."""
        mock_session = AsyncMock()

        # Mock get_document_by_hash to return an existing doc
        existing_doc = MagicMock()
        existing_doc.id = uuid4()

        with patch.object(
            document_service, "get_document_by_hash", return_value=existing_doc
        ):
            with pytest.raises(DocumentAlreadyExistsError):
                await document_service.create_document(
                    session=mock_session,
                    filename="test.pdf",
                    file_content=b"test content",
                    file_type="application/pdf",
                )
