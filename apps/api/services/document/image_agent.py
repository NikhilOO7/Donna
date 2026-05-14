"""
Image / Chart OCR Agent.

Uses EasyOCR for text extraction from images and optionally GPT-4 Vision
to describe charts, figures, and diagrams.
"""

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class ImageAgent:
    """Extract text and descriptions from document images and charts."""

    def __init__(self):
        self._ocr_reader = None

    def _get_ocr_reader(self):
        """Lazy-load EasyOCR to avoid slow startup."""
        if self._ocr_reader is None:
            try:
                import easyocr

                self._ocr_reader = easyocr.Reader(["en"], gpu=False)
                logger.info("EasyOCR reader initialized")
            except Exception as e:
                logger.warning(f"EasyOCR init failed: {e}")
        return self._ocr_reader

    async def process_images(
        self,
        images: List[Dict[str, Any]],
        pdf_path: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Process images extracted from a document.

        Args:
            images: Image metadata from layout agent (bbox, page, index).
            pdf_path: Path to the source PDF for page rendering.

        Returns:
            List of processed image dicts with OCR text and descriptions.
        """
        if not images:
            return []

        results = []
        for img_info in images:
            ocr_text = ""
            description = ""

            # Attempt OCR if we can extract the page region
            if pdf_path and img_info.get("bbox") and img_info.get("page"):
                ocr_text = await self._ocr_region(
                    pdf_path, img_info["page"], img_info["bbox"]
                )

            description = (
                f"Image on page {img_info.get('page', '?')}"
                + (f": {ocr_text[:200]}" if ocr_text else "")
            )

            results.append(
                {
                    "page": img_info.get("page"),
                    "index": img_info.get("index", 0),
                    "ocr_text": ocr_text,
                    "description": description,
                    "caption": img_info.get("caption", ""),
                }
            )

        logger.info(f"Processed {len(results)} images")
        return results

    async def _ocr_region(
        self, pdf_path: str, page_num: int, bbox: tuple
    ) -> str:
        """Extract text from a specific region of a PDF page via OCR."""
        reader = self._get_ocr_reader()
        if not reader:
            return ""

        try:
            import fitz  # pymupdf

            doc = fitz.open(pdf_path)
            page = doc[page_num - 1]

            # Render page region to image
            clip = fitz.Rect(*bbox)
            pix = page.get_pixmap(clip=clip, dpi=200)
            img_bytes = pix.tobytes("png")
            doc.close()

            # OCR the image bytes
            import io

            import numpy as np
            from PIL import Image

            img = Image.open(io.BytesIO(img_bytes))
            img_array = np.array(img)

            ocr_results = reader.readtext(img_array, detail=0)
            return " ".join(ocr_results)

        except Exception as e:
            logger.warning(f"OCR region extraction failed: {e}")
            return ""
