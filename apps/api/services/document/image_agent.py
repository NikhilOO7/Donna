"""
Image / Chart OCR Agent.

Two-stage understanding of document images:

1. **EasyOCR** pulls any literal text out of the image region (labels,
   axis ticks, legends, embedded text).
2. **GPT-4o Vision** describes what the image actually *shows* — chart
   type, trend, what the figure communicates — using the rendered PNG
   plus the OCR text as grounding.

The vision call is best-effort: if ``OPENAI_API_KEY`` is unset or the
call fails, the agent degrades to OCR-only output. Both signals are
combined into a single ``description`` used downstream for embedding
and the document-elements UI.
"""

import base64
import logging
from typing import Any, Dict, List, Optional

from openai import AsyncOpenAI

from apps.api.core.config import settings
from apps.api.core.resilience import resilient_call

logger = logging.getLogger(__name__)

# Only attempt a vision description when the rendered region is large
# enough to plausibly be a chart/figure (skip tiny icons/bullets).
_MIN_VISION_BYTES = 3000


class ImageAgent:
    """Extract text and descriptions from document images and charts."""

    def __init__(self):
        self._ocr_reader = None
        self._client: Optional[AsyncOpenAI] = None

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

    def _get_client(self) -> Optional[AsyncOpenAI]:
        if self._client is None and settings.openai_api_key:
            self._client = AsyncOpenAI(api_key=settings.openai_api_key)
        return self._client

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
            List of processed image dicts with OCR text + vision description.
        """
        if not images:
            return []

        results = []
        for img_info in images:
            ocr_text = ""
            vision_desc = ""
            png_bytes: Optional[bytes] = None

            # Render + OCR the page region if we can locate it
            if pdf_path and img_info.get("bbox") and img_info.get("page"):
                png_bytes = self._render_region(
                    pdf_path, img_info["page"], img_info["bbox"]
                )
                if png_bytes:
                    ocr_text = self._ocr_bytes(png_bytes)

            # GPT-4o Vision description (best-effort)
            if png_bytes and len(png_bytes) >= _MIN_VISION_BYTES:
                vision_desc = await self._describe_with_vision(
                    png_bytes, ocr_text, img_info.get("page")
                )

            # Compose the final description: prefer the vision summary,
            # fall back to OCR text, then to a positional placeholder.
            page = img_info.get("page", "?")
            if vision_desc:
                description = vision_desc
            elif ocr_text:
                description = f"Image on page {page}: {ocr_text[:200]}"
            else:
                description = f"Image on page {page}"

            results.append(
                {
                    "page": img_info.get("page"),
                    "index": img_info.get("index", 0),
                    "ocr_text": ocr_text,
                    "description": description,
                    "vision_description": vision_desc,
                    "caption": img_info.get("caption", ""),
                    "method": "easyocr+gpt4v" if vision_desc else "easyocr",
                }
            )

        n_vision = sum(1 for r in results if r.get("vision_description"))
        logger.info(f"Processed {len(results)} images ({n_vision} with GPT-4o Vision)")
        return results

    # ------------------------------------------------------------------

    def _render_region(
        self, pdf_path: str, page_num: int, bbox: tuple
    ) -> Optional[bytes]:
        """Render a PDF page region to PNG bytes."""
        try:
            import fitz  # pymupdf

            doc = fitz.open(pdf_path)
            page = doc[page_num - 1]
            clip = fitz.Rect(*bbox)
            pix = page.get_pixmap(clip=clip, dpi=200)
            img_bytes = pix.tobytes("png")
            doc.close()
            return img_bytes
        except Exception as e:
            logger.warning(f"Region render failed (page {page_num}): {e}")
            return None

    def _ocr_bytes(self, png_bytes: bytes) -> str:
        """Run EasyOCR over PNG bytes."""
        reader = self._get_ocr_reader()
        if not reader:
            return ""
        try:
            import io

            import numpy as np
            from PIL import Image

            img = Image.open(io.BytesIO(png_bytes))
            img_array = np.array(img)
            ocr_results = reader.readtext(img_array, detail=0)
            return " ".join(ocr_results)
        except Exception as e:
            logger.warning(f"OCR failed: {e}")
            return ""

    @resilient_call("openai", max_retries=2, timeout_seconds=25)
    async def _describe_with_vision(
        self, png_bytes: bytes, ocr_text: str, page: Optional[int]
    ) -> str:
        """Describe a chart/figure with GPT-4o Vision, grounded by OCR text."""
        client = self._get_client()
        if not client:
            return ""

        b64 = base64.b64encode(png_bytes).decode("ascii")
        ocr_hint = (
            f"\n\nText detected in the image via OCR: {ocr_text[:500]}"
            if ocr_text
            else ""
        )

        try:
            response = await client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You describe charts, figures, and diagrams from "
                            "documents so they become searchable. In 1-3 "
                            "sentences, state what the image shows: the chart "
                            "type (bar/line/pie/diagram/table/photo), the key "
                            "trend or data point, and what it communicates. Be "
                            "concrete and factual. If it's a decorative image "
                            "with no information, say so briefly."
                        ),
                    },
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": (
                                    f"Describe this figure from page {page}.{ocr_hint}"
                                ),
                            },
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/png;base64,{b64}",
                                    "detail": "low",
                                },
                            },
                        ],
                    },
                ],
                temperature=0.2,
                max_tokens=200,
            )
            return (response.choices[0].message.content or "").strip()
        except Exception as e:
            logger.warning(f"GPT-4o Vision description failed: {e}")
            return ""
