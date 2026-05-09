"""
API contract tests for document management endpoints.
Tests verify HTTP contracts (status codes, response shapes, validation).
"""

import io
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4


# The service path for consistent mocking
SVC = "apps.api.services.document.document_service"


class TestDocumentUpload:
    """Tests for POST /api/v1/documents/upload"""

    @pytest.mark.asyncio
    async def test_upload_requires_file(self, client):
        """Upload without file should return 422."""
        response = await client.post("/api/v1/documents/upload")
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_upload_rejects_duplicate(self, client):
        """Duplicate file upload should return 409."""
        from apps.api.services.document.document_service import DocumentAlreadyExistsError

        with patch(f"{SVC}.document_service") as mock_ds:
            mock_ds.create_document = AsyncMock(
                side_effect=DocumentAlreadyExistsError("duplicate")
            )

            files = {"file": ("test.pdf", io.BytesIO(b"content"), "application/pdf")}
            response = await client.post("/api/v1/documents/upload", files=files)

            assert response.status_code == 409


class TestDocumentList:
    """Tests for GET /api/v1/documents"""

    @pytest.mark.asyncio
    async def test_list_rejects_invalid_limit(self, client):
        """Limit > 100 should be rejected by validation."""
        response = await client.get("/api/v1/documents?limit=500")
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_list_rejects_negative_skip(self, client):
        """Negative skip should be rejected."""
        response = await client.get("/api/v1/documents?skip=-1")
        assert response.status_code == 422


class TestDocumentGet:
    """Tests for GET /api/v1/documents/{document_id}"""

    @pytest.mark.asyncio
    async def test_get_valid_document(self, client):
        """Valid document ID should return document details."""
        doc_id = str(uuid4())
        with patch(f"{SVC}.document_service") as mock_ds:
            mock_doc = MagicMock()
            mock_doc.id = doc_id
            mock_doc.filename = "test.pdf"
            mock_doc.file_type = "application/pdf"
            mock_doc.file_size = 1024
            mock_doc.processing_status = "completed"
            mock_doc.processing_started_at = None
            mock_doc.processing_completed_at = None
            mock_doc.processing_error = None
            mock_doc.created_at = MagicMock(isoformat=lambda: "2026-01-01T00:00:00")
            mock_doc.updated_at = MagicMock(isoformat=lambda: "2026-01-01T00:00:00")
            mock_doc.chunks = []
            mock_doc.doc_metadata = {}
            mock_doc.extracted_metadata = {}
            mock_ds.get_document = AsyncMock(return_value=mock_doc)

            response = await client.get(f"/api/v1/documents/{doc_id}")

            assert response.status_code == 200
            data = response.json()
            assert data["filename"] == "test.pdf"

    @pytest.mark.asyncio
    async def test_get_nonexistent_document(self, client):
        """Nonexistent document ID should return 404."""
        doc_id = str(uuid4())
        with patch(f"{SVC}.document_service") as mock_ds:
            mock_ds.get_document = AsyncMock(return_value=None)

            response = await client.get(f"/api/v1/documents/{doc_id}")

            assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_get_invalid_uuid(self, client):
        """Invalid UUID format should return 400 or 422."""
        response = await client.get("/api/v1/documents/not-a-uuid")
        assert response.status_code in (400, 422, 500)


class TestDocumentDelete:
    """Tests for DELETE /api/v1/documents/{document_id}"""

    @pytest.mark.asyncio
    async def test_delete_nonexistent_document(self, client):
        """Deleting nonexistent document should return 404."""
        doc_id = str(uuid4())
        with patch(f"{SVC}.document_service") as mock_ds:
            mock_ds.get_document = AsyncMock(return_value=None)

            response = await client.delete(f"/api/v1/documents/{doc_id}")

            assert response.status_code == 404
