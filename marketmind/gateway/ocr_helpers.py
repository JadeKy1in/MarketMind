"""OCR helper functions for multimodal_adapter — run via asyncio.to_thread.

These are internal synchronous/asynchronous helpers extracted from
multimodal_adapter.py to keep that module under 500 lines.
"""
from __future__ import annotations

import asyncio
import atexit
import logging
import os

logger = logging.getLogger("marketmind.gateway.ocr_helpers")


async def _tesseract_ocr(image_path: str) -> str | None:
    """Run Tesseract OCR on an image (runs in thread to avoid blocking)."""
    try:
        import subprocess
        proc = await asyncio.to_thread(
            subprocess.run,
            ["tesseract", image_path, "stdout", "-l", "eng+chi_sim", "--psm", "6"],
            capture_output=True, text=True, timeout=30,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return proc.stdout.strip()
    except FileNotFoundError:
        logger.debug("Tesseract not installed; skipping OCR")
    except Exception as exc:
        logger.debug("Tesseract failed: %s", exc)
    return None


async def _pil_metadata(image_path: str) -> dict | None:
    """Extract basic metadata from an image via PIL (runs in thread to avoid blocking)."""
    try:
        from PIL import Image
    except ImportError:
        logger.debug("PIL not installed; cannot extract image metadata")
        return None
    try:
        def _open_and_read():
            with Image.open(image_path) as img:
                # Force load to ensure all metadata is read while file is open
                img.load()
                text = (
                    f"[Image: {img.format} | {img.size[0]}x{img.size[1]} | "
                    f"mode={img.mode} | No OCR text available. Install tesseract for OCR.]"
                )
                return {
                    "text": text,
                    "meta": {
                        "extraction_method": "pil_metadata",
                        "image_format": img.format,
                        "dimensions": list(img.size),
                    },
                }
        return await asyncio.to_thread(_open_and_read)
    except Exception as exc:
        logger.debug("PIL metadata extraction failed: %s", exc)
    return None


async def _pdfplumber_extract(pdf_path: str) -> dict | None:
    """Extract text from a PDF using pdfplumber (runs in thread to avoid blocking)."""
    try:
        import pdfplumber
    except ImportError:
        logger.debug("pdfplumber not installed; skipping PDF extraction")
        return None
    try:
        def _extract():
            with pdfplumber.open(pdf_path) as pdf:
                pages_text = []
                for page in pdf.pages[:20]:
                    text = page.extract_text()
                    if text:
                        pages_text.append(text)
                if pages_text:
                    return {
                        "text": "\n\n".join(pages_text),
                        "meta": {
                            "extraction_method": "pdfplumber",
                            "pages_extracted": len(pages_text),
                        },
                    }
                return None
        return await asyncio.to_thread(_extract)
    except Exception as exc:
        logger.debug("pdfplumber extraction failed for %s: %s", pdf_path, exc)
    return None


def _write_temp_image(image_bytes: bytes) -> str | None:
    """Write image bytes to a temporary .png file (sync, called directly).

    Returns the temp file path, or None on failure.
    """
    try:
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(image_bytes)
            tmp_path = f.name
        atexit.register(os.unlink, tmp_path)
        return tmp_path
    except Exception as exc:
        logger.debug("Failed to write temp image: %s", exc)
    return None
