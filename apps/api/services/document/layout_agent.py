"""
Layout Analysis Agent.

Uses Docling for structured PDF layout detection: text blocks, tables,
images, headers. Falls back to pdfplumber for basic extraction.
"""

import logging
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


class LayoutAgent:
    """Detect document structure and extract elements by type."""

    async def analyze(self, file_path: str) -> Dict[str, Any]:
        """Analyze PDF layout and return structured elements."""
        logger.info(f"Analyzing layout: {file_path}")

        try:
            return await self._analyze_with_docling(file_path)
        except Exception as e:
            logger.warning(f"Docling layout analysis failed, using pdfplumber: {e}")
            return await self._analyze_with_pdfplumber(file_path)

    async def _analyze_with_docling(self, file_path: str) -> Dict[str, Any]:
        from docling.document_converter import DocumentConverter

        converter = DocumentConverter()
        result = converter.convert(file_path)

        markdown_text = result.document.export_to_markdown()

        tables = []
        images = []
        text_blocks = []

        # Docling exposes structured elements when available
        if hasattr(result.document, "tables"):
            for idx, table in enumerate(result.document.tables):
                tables.append(
                    {
                        "index": idx,
                        "data": table.export_to_markdown()
                        if hasattr(table, "export_to_markdown")
                        else str(table),
                        "page": None,
                    }
                )

        if hasattr(result.document, "pictures"):
            for idx, pic in enumerate(result.document.pictures):
                images.append({"index": idx, "caption": str(pic), "page": None})

        return {
            "full_text": markdown_text,
            "tables": tables,
            "images": images,
            "text_blocks": text_blocks,
            "page_count": len(result.document.pages)
            if hasattr(result.document, "pages")
            else 1,
            "title": getattr(result.document, "title", Path(file_path).stem),
            "method": "docling",
        }

    async def _analyze_with_pdfplumber(self, file_path: str) -> Dict[str, Any]:
        import pdfplumber

        content_parts: List[str] = []
        tables: List[Dict[str, Any]] = []
        images: List[Dict[str, Any]] = []

        with pdfplumber.open(file_path) as pdf:
            for page_num, page in enumerate(pdf.pages):
                text = page.extract_text() or ""
                content_parts.append(text)

                for idx, table in enumerate(page.extract_tables()):
                    tables.append(
                        {"index": idx, "data": table, "page": page_num + 1}
                    )

                for idx, img in enumerate(page.images):
                    images.append(
                        {
                            "index": idx,
                            "bbox": (img["x0"], img["top"], img["x1"], img["bottom"]),
                            "page": page_num + 1,
                        }
                    )

        return {
            "full_text": "\n\n".join(content_parts),
            "tables": tables,
            "images": images,
            "text_blocks": [],
            "page_count": len(content_parts),
            "title": Path(file_path).stem,
            "method": "pdfplumber",
        }
