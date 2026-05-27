# apps/api/services/storage/local_storage.py
"""
Local filesystem storage service as an alternative to MinIO
"""

import hashlib
import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiofiles

# Try to import magic, but make it optional
# Note: Requires libmagic system library (install with: brew install libmagic or port install file)
try:
    import magic

    # Test if libmagic is actually available
    _ = magic.Magic(mime=True)
    HAS_MAGIC = True
except (ImportError, OSError, AttributeError):
    HAS_MAGIC = False
    # Fallback to extension-based MIME type detection (works fine for PDF, DOCX, TXT, DOC)
    # To enable python-magic: install libmagic system library first

from apps.api.core.config import settings

logger = logging.getLogger(__name__)


class LocalStorageService:
    """Local filesystem storage service"""

    def __init__(self):
        self.base_path = Path(settings.local_storage_path)
        self.base_path.mkdir(parents=True, exist_ok=True)
        self.allowed_extensions = settings.allowed_file_types
        self.max_file_size = settings.max_file_size

        # Create subdirectories
        self.uploads_path = self.base_path / "uploads"
        self.processed_path = self.base_path / "processed"
        self.temp_path = self.base_path / "temp"

        for path in [self.uploads_path, self.processed_path, self.temp_path]:
            path.mkdir(parents=True, exist_ok=True)

    async def upload_file(
        self,
        file_content: bytes,
        filename: str,
        document_id: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Upload a file to local storage"""
        try:
            # Validate file
            validation_result = await self._validate_file(file_content, filename)
            if not validation_result["valid"]:
                raise ValueError(validation_result["error"])

            # Create document directory
            doc_path = self.uploads_path / document_id
            doc_path.mkdir(parents=True, exist_ok=True)

            # Save file
            file_path = doc_path / filename
            async with aiofiles.open(file_path, "wb") as f:
                await f.write(file_content)

            # Calculate file hash
            file_hash = hashlib.sha256(file_content).hexdigest()

            # Save metadata
            metadata_path = doc_path / f"{filename}.metadata.json"
            metadata_content = {
                "document_id": document_id,
                "filename": filename,
                "file_size": len(file_content),
                "file_hash": file_hash,
                "content_type": validation_result["content_type"],
                "uploaded_at": datetime.utcnow().isoformat(),
                "custom_metadata": metadata or {},
            }

            import json

            async with aiofiles.open(metadata_path, "w") as f:
                await f.write(json.dumps(metadata_content, indent=2))

            logger.info(f"File uploaded successfully: {document_id}/{filename}")

            return {
                "success": True,
                "file_path": str(file_path),
                "file_size": len(file_content),
                "file_hash": file_hash,
                "content_type": validation_result["content_type"],
                "storage_type": "local",
            }

        except Exception as e:
            logger.error(f"File upload failed: {e}")
            raise

    async def download_file(self, document_id: str, filename: str) -> bytes:
        """Download a file from local storage"""
        try:
            file_path = self.uploads_path / document_id / filename

            if not file_path.exists():
                raise FileNotFoundError(f"File not found: {document_id}/{filename}")

            async with aiofiles.open(file_path, "rb") as f:
                content = await f.read()

            return content

        except Exception as e:
            logger.error(f"File download failed: {e}")
            raise

    async def delete_file(self, document_id: str, filename: str) -> bool:
        """Delete a file from local storage"""
        try:
            doc_path = self.uploads_path / document_id
            file_path = doc_path / filename
            metadata_path = doc_path / f"{filename}.metadata.json"

            # Delete file
            if file_path.exists():
                file_path.unlink()

            # Delete metadata
            if metadata_path.exists():
                metadata_path.unlink()

            # Remove directory if empty
            if doc_path.exists() and not any(doc_path.iterdir()):
                doc_path.rmdir()

            logger.info(f"File deleted: {document_id}/{filename}")
            return True

        except Exception as e:
            logger.error(f"File deletion failed: {e}")
            return False

    async def list_files(
        self, document_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """List files in storage"""
        try:
            files = []

            if document_id:
                # List files for specific document
                doc_path = self.uploads_path / document_id
                if doc_path.exists():
                    for file_path in doc_path.glob("*"):
                        if not file_path.name.endswith(".metadata.json"):
                            files.append(await self._get_file_info(file_path))
            else:
                # List all files
                for doc_dir in self.uploads_path.iterdir():
                    if doc_dir.is_dir():
                        for file_path in doc_dir.glob("*"):
                            if not file_path.name.endswith(".metadata.json"):
                                files.append(await self._get_file_info(file_path))

            return files

        except Exception as e:
            logger.error(f"File listing failed: {e}")
            return []

    async def move_to_processed(self, document_id: str, filename: str) -> str:
        """Move file to processed directory after processing"""
        try:
            source_path = self.uploads_path / document_id / filename
            dest_dir = self.processed_path / document_id
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest_path = dest_dir / filename

            # Move file
            shutil.move(str(source_path), str(dest_path))

            # Move metadata
            source_metadata = (
                self.uploads_path / document_id / f"{filename}.metadata.json"
            )
            if source_metadata.exists():
                dest_metadata = dest_dir / f"{filename}.metadata.json"
                shutil.move(str(source_metadata), str(dest_metadata))

            logger.info(f"File moved to processed: {document_id}/{filename}")
            return str(dest_path)

        except Exception as e:
            logger.error(f"File move failed: {e}")
            raise

    async def get_file_path(self, document_id: str, filename: str) -> str:
        """Get the full path of a file"""
        # Check uploads first
        file_path = self.uploads_path / document_id / filename
        if file_path.exists():
            return str(file_path)

        # Check processed
        file_path = self.processed_path / document_id / filename
        if file_path.exists():
            return str(file_path)

        raise FileNotFoundError(f"File not found: {document_id}/{filename}")

    async def _validate_file(
        self, file_content: bytes, filename: str
    ) -> Dict[str, Any]:
        """Validate file type and size"""
        # Check file size
        if len(file_content) > self.max_file_size:
            return {
                "valid": False,
                "error": f"File size exceeds maximum allowed size of {self.max_file_size} bytes",
            }

        # Check file extension
        file_ext = Path(filename).suffix.lower()
        if file_ext not in self.allowed_extensions:
            return {
                "valid": False,
                "error": f"File type {file_ext} not allowed. Allowed types: {', '.join(self.allowed_extensions)}",
            }

        # Detect content type
        if HAS_MAGIC:
            try:
                mime = magic.Magic(mime=True)
                content_type = mime.from_buffer(file_content)
            except Exception:
                # Fallback to extension-based detection
                content_type_map = {
                    ".pdf": "application/pdf",
                    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    ".doc": "application/msword",
                    ".txt": "text/plain",
                }
                content_type = content_type_map.get(
                    file_ext, "application/octet-stream"
                )
        else:
            # Fallback to extension-based detection when magic is not available
            content_type_map = {
                ".pdf": "application/pdf",
                ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                ".doc": "application/msword",
                ".txt": "text/plain",
            }
            content_type = content_type_map.get(file_ext, "application/octet-stream")

        return {"valid": True, "content_type": content_type}

    async def _get_file_info(self, file_path: Path) -> Dict[str, Any]:
        """Get file information"""
        stat = file_path.stat()

        # Try to load metadata
        metadata_path = file_path.parent / f"{file_path.name}.metadata.json"
        metadata = {}
        if metadata_path.exists():
            import json

            async with aiofiles.open(metadata_path, "r") as f:
                content = await f.read()
                metadata = json.loads(content)

        return {
            "filename": file_path.name,
            "document_id": file_path.parent.name,
            "file_path": str(file_path),
            "file_size": stat.st_size,
            "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            "metadata": metadata,
        }

    async def cleanup_temp_files(self, older_than_hours: int = 24):
        """Clean up temporary files older than specified hours"""
        try:
            cutoff_time = datetime.now().timestamp() - (older_than_hours * 3600)

            cleaned = 0
            for file_path in self.temp_path.glob("*"):
                if file_path.stat().st_mtime < cutoff_time:
                    if file_path.is_file():
                        file_path.unlink()
                    elif file_path.is_dir():
                        shutil.rmtree(file_path)
                    cleaned += 1

            logger.info(f"Cleaned up {cleaned} temporary files")
            return cleaned

        except Exception as e:
            logger.error(f"Temp file cleanup failed: {e}")
            return 0


# Singleton instance
local_storage_service = LocalStorageService()
