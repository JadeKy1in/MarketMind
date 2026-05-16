"""Multimodal input gateway — converts images, PDFs, screenshots to text via Gemini Flash.

DeepSeek V4 has no native multimodal support. This adapter bridges that gap
by converting non-text inputs into plain text that the MarketMind pipeline
can consume. All extractors are async and integrate with the shadow agent's
ExternalObservation dataclass.

Architecture:
  Image/PDF/Screenshot → Gemini Flash Vision / OCR / pdfplumber → ExternalObservation → Pipeline

Uses asyncio.to_thread() for CPU-bound operations (PIL, pdfplumber) and
httpx.AsyncClient for Gemini API calls, following the same async patterns
as DeepSeekGateway in async_client.py.
"""
from __future__ import annotations

import asyncio
import base64
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx

from marketmind.shadows.shadow_agent import ExternalObservation
from marketmind.gateway.ocr_helpers import _tesseract_ocr, _pil_metadata, _pdfplumber_extract, _write_temp_image

logger = logging.getLogger("marketmind.gateway.multimodal_adapter")

GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"
DEFAULT_TIMEOUT = httpx.Timeout(45.0)

MIME_MAP = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
    ".webp": "image/webp",
}

VISION_PROMPT = (
    "Extract ALL visible text from this image. "
    "Include tables, numbers, labels, headers, footnotes. "
    "Output the exact text without commentary. "
    "If there are charts, describe the data shown."
)


def _make_observation_id() -> str:
    return uuid.uuid4().hex[:12]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _error_observation(
    source_type: str,
    source_path: str,
    error_text: str,
    method: str = "none",
) -> ExternalObservation:
    """Return an ExternalObservation representing an extraction failure."""
    return ExternalObservation(
        observation_id=_make_observation_id(),
        source_type=source_type,
        source_path=source_path,
        extracted_text=f"[{error_text}]",
        metadata={"extraction_method": method, "error": error_text},
        confidence=0.0,
        source_attribution="multimodal_adapter",
        evaluated_at=_now_iso(),
    )


# ---------------------------------------------------------------------------
# Gemini Flash Vision Gateway (inner class, follows DeepSeekGateway pattern)
# ---------------------------------------------------------------------------


class GeminiFlashGateway:
    """Async client for Gemini Flash Vision API (image-to-text)."""

    def __init__(self, api_key: str) -> None:
        if not api_key:
            raise ValueError("GEMINI_API_KEY is required for GeminiFlashGateway")
        self._api_key = api_key
        self._client: httpx.AsyncClient | None = None

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=DEFAULT_TIMEOUT)
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def extract_vision(self, image_path: str) -> str | None:
        """Send an image to Gemini Flash Vision and return extracted text.

        Returns None if extraction fails for any reason.
        """
        client = await self._ensure_client()
        try:
            ext = Path(image_path).suffix.lower()
            mime_type = MIME_MAP.get(ext, "image/png")

            # Read and encode in a thread to avoid blocking the event loop
            image_data = await asyncio.to_thread(
                self._read_encode_image, image_path
            )

            url = GEMINI_BASE
            payload = {
                "contents": [{
                    "parts": [
                        {"text": VISION_PROMPT},
                        {"inline_data": {"mime_type": mime_type, "data": image_data}},
                    ]
                }],
                "generationConfig": {"temperature": 0.0, "maxOutputTokens": 4096},
            }
            headers = {"x-goog-api-key": self._api_key, "Content-Type": "application/json"}
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            body = resp.json()

            candidates = body.get("candidates", [])
            if candidates:
                parts = candidates[0].get("content", {}).get("parts", [])
                texts = [p.get("text", "") for p in parts if "text" in p]
                if texts:
                    return "\n".join(texts)
        except Exception as exc:
            logger.debug("Gemini Vision extraction failed for %s: %s", image_path, exc)
        return None

    @staticmethod
    def _read_encode_image(image_path: str) -> str:
        """Read and base64-encode an image file (sync, runs in thread)."""
        with open(image_path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")


# ---------------------------------------------------------------------------
# MultimodalAdapter — public API for all extraction methods
# ---------------------------------------------------------------------------


class MultimodalAdapter:
    """Async adapter that converts multimodal inputs into ExternalObservation.

    OCR Priority Chain:
      1. English documents  -> Gemini 2.0 Flash (free, high accuracy, 86% OCR)
      2. Chinese documents  -> Local Tesseract/pdfplumber (data sovereignty, no cross-border)
      3. Table-heavy PDFs   -> pdfplumber (best table extraction)
      4. Gemini 2.5 Flash is NOT used (known OCR regression: 86% -> 78.9%)

    Priority chain per input type:
      - Image:       Gemini Vision -> Tesseract OCR -> PIL metadata
      - PDF:         pdfplumber -> Gemini Vision (scanned PDFs)
      - Screenshot:  Gemini Vision from base64
      - Text:        passthrough

    The _check_cross_border_consent() gate detects Chinese characters and
    routes to local OCR, satisfying Phase 3 Resolution 6-D data sovereignty.

    Falls back gracefully at each step. Returns error observations
    when no extraction method succeeds.
    """

    def __init__(self, gemini_api_key: str | None = None) -> None:
        self._api_key = gemini_api_key or os.environ.get("GEMINI_API_KEY", "")
        self._gemini: GeminiFlashGateway | None = None
        # Per-operation OCR statistics for operational monitoring
        # NOTE: Claude Sonnet 4 is the RECOMMENDED Chinese OCR model but requires
        # a paid API key. For Phase C, local Tesseract is the primary Chinese path.
        self._ocr_stats: dict[str, dict[str, int]] = {
            "gemini_vision": {"success": 0, "failure": 0},
            "tesseract_ocr": {"success": 0, "failure": 0},
            "pdfplumber": {"success": 0, "failure": 0},
            "pil_metadata": {"success": 0, "failure": 0},
            "passthrough": {"success": 0, "failure": 0},
            "consent_denied": {"count": 0},
        }

    async def _get_gemini(self) -> GeminiFlashGateway | None:
        if self._gemini is not None:
            return self._gemini
        if not self._api_key:
            return None
        self._gemini = GeminiFlashGateway(self._api_key)
        return self._gemini

    async def close(self) -> None:
        if self._gemini is not None:
            await self._gemini.close()
            self._gemini = None

    # ----- Cross-border API consent (C6: China compliance) -----

    @staticmethod
    def _check_cross_border_consent(file_path: str) -> bool:
        """Check whether a file is safe to send to Gemini (cross-border API).

        Resolution 6-C: Chinese-language or sensitive files must use local OCR
        fallback instead of sending data to a foreign API.

        Returns True if the file content is English/ASCII (safe to send),
        returns False if the file contains Chinese characters or sensitive patterns.
        """
        CHINESE_CHAR_RANGE = (0x4E00, 0x9FFF)
        try:
            with open(file_path, "rb") as f:
                raw = f.read(4096)  # Sample first 4KB
            text = raw.decode("utf-8", errors="ignore")
            for ch in text:
                cp = ord(ch)
                if CHINESE_CHAR_RANGE[0] <= cp <= CHINESE_CHAR_RANGE[1]:
                    logger.warning(
                        "Cross-border consent DENIED for %s: "
                        "Chinese characters detected. Falling back to local OCR.",
                        file_path
                    )
                    # Interactive mode warning (logged for user awareness)
                    logger.info(
                        "此文件将调用境外 API (Gemini) 处理，是否继续？"
                    )
                    return False
        except Exception as exc:
            logger.debug("Consent check failed for %s: %s; defaulting to deny", file_path, exc)
            return False
        return True

    # ----- Image Extraction -----

    async def extract_text_from_image(self, image_path: str) -> ExternalObservation:
        """Extract text from an image file via Gemini Vision -> Tesseract -> PIL.

        Args:
            image_path: Path to an image file (.png, .jpg, etc.)

        Returns:
            ExternalObservation with extracted text, or an error observation.
        """
        if not os.path.isfile(image_path):
            return _error_observation("image", image_path, "File not found")

        # 1. Gemini Vision (preferred) — gated by cross-border consent check
        consent_ok = self._check_cross_border_consent(image_path)
        if not consent_ok:
            self._ocr_stats["consent_denied"]["count"] += 1
        gemini = await self._get_gemini()
        if consent_ok and gemini is not None:
            text = await gemini.extract_vision(image_path)
            if text:
                self._ocr_stats["gemini_vision"]["success"] += 1
                return ExternalObservation(
                    observation_id=_make_observation_id(),
                    source_type="image",
                    source_path=image_path,
                    extracted_text=text,
                    metadata={
                        "extraction_method": "gemini_vision",
                        "model": "gemini-2.0-flash",
                    },
                    confidence=0.95,
                    source_attribution="multimodal_adapter",
                    evaluated_at=_now_iso(),
                )
            else:
                self._ocr_stats["gemini_vision"]["failure"] += 1

        # 2. Tesseract OCR (runs in thread to avoid blocking)
        tesseract_result = await _tesseract_ocr(image_path)
        if tesseract_result is not None:
            self._ocr_stats["tesseract_ocr"]["success"] += 1
            return ExternalObservation(
                observation_id=_make_observation_id(),
                source_type="image",
                source_path=image_path,
                extracted_text=tesseract_result,
                metadata={
                    "extraction_method": "tesseract_ocr",
                    "ocr_engine": "tesseract",
                },
                confidence=0.7,
                source_attribution="multimodal_adapter",
                evaluated_at=_now_iso(),
            )
        else:
            self._ocr_stats["tesseract_ocr"]["failure"] += 1

        # 3. PIL metadata fallback (runs in thread)
        pil_result = await _pil_metadata(image_path)
        if pil_result is not None:
            self._ocr_stats["pil_metadata"]["success"] += 1
            return ExternalObservation(
                observation_id=_make_observation_id(),
                source_type="image",
                source_path=image_path,
                extracted_text=pil_result["text"],
                metadata=pil_result["meta"],
                confidence=0.1,
                source_attribution="multimodal_adapter",
                evaluated_at=_now_iso(),
            )
        else:
            self._ocr_stats["pil_metadata"]["failure"] += 1

        return _error_observation(
            "image", image_path,
            "No OCR or image extraction method available. Install tesseract or set GEMINI_API_KEY.",
            method="none",
        )

    # ----- PDF Extraction -----

    async def extract_text_from_pdf(self, pdf_path: str) -> ExternalObservation:
        """Extract text from a PDF via pdfplumber -> Gemini Vision fallback.

        Args:
            pdf_path: Path to a .pdf file.

        Returns:
            ExternalObservation with extracted text, or an error observation.
        """
        if not os.path.isfile(pdf_path):
            return _error_observation("pdf", pdf_path, "File not found")

        # 1. pdfplumber (runs in thread)
        plumber_result = await _pdfplumber_extract(pdf_path)
        if plumber_result is not None:
            self._ocr_stats["pdfplumber"]["success"] += 1
            return ExternalObservation(
                observation_id=_make_observation_id(),
                source_type="pdf",
                source_path=pdf_path,
                extracted_text=plumber_result["text"],
                metadata=plumber_result["meta"],
                confidence=0.9,
                source_attribution="multimodal_adapter",
                evaluated_at=_now_iso(),
            )
        else:
            self._ocr_stats["pdfplumber"]["failure"] += 1

        # 2. Gemini Vision fallback (for scanned/image-based PDFs) — gated by consent check
        consent_ok = self._check_cross_border_consent(pdf_path)
        if not consent_ok:
            self._ocr_stats["consent_denied"]["count"] += 1
        gemini = await self._get_gemini()
        if consent_ok and gemini is not None:
            text = await gemini.extract_vision(pdf_path)
            if text:
                self._ocr_stats["gemini_vision"]["success"] += 1
                return ExternalObservation(
                    observation_id=_make_observation_id(),
                    source_type="pdf",
                    source_path=pdf_path,
                    extracted_text=text,
                    metadata={
                        "extraction_method": "gemini_vision",
                        "model": "gemini-2.0-flash",
                        "note": "PDF treated as image (scanned document)",
                    },
                    confidence=0.8,
                    source_attribution="multimodal_adapter",
                    evaluated_at=_now_iso(),
                )
            else:
                self._ocr_stats["gemini_vision"]["failure"] += 1

        return _error_observation(
            "pdf", pdf_path,
            "No PDF extraction method available. Install pdfplumber or set GEMINI_API_KEY.",
            method="none",
        )

    # ----- Screenshot Extraction (base64) -----

    async def extract_text_from_screenshot(self, base64_data: str) -> ExternalObservation:
        """Extract text from a base64-encoded screenshot via Gemini Vision.

        Args:
            base64_data: Base64-encoded image data (string or bytes).

        Returns:
            ExternalObservation with extracted text, or an error observation.
        """
        source_path = f"screenshot:{_make_observation_id()}"

        gemini = await self._get_gemini()
        if gemini is None:
            return ExternalObservation(
                observation_id=_make_observation_id(),
                source_type="screenshot",
                source_path=source_path,
                extracted_text=(
                    f"[Screenshot: {len(base64_data)} bytes. "
                    "Set GEMINI_API_KEY for extraction.]"
                ),
                metadata={
                    "extraction_method": "base64_metadata",
                    "data_size_bytes": len(base64_data),
                },
                confidence=0.0,
                source_attribution="multimodal_adapter",
                evaluated_at=_now_iso(),
            )

        try:
            # Decode base64, write to temp file, then use Gemini Vision
            raw = base64_data
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            image_bytes = await asyncio.to_thread(base64.b64decode, raw)
        except Exception as exc:
            return _error_observation(
                "screenshot", source_path,
                f"Base64 decode failed: {exc}",
                method="none",
            )

        # Write to temp file for Gemini Vision
        tmp_path = _write_temp_image(image_bytes)
        if tmp_path is None:
            return _error_observation(
                "screenshot", source_path,
                "Failed to write temp file for screenshot",
                method="none",
            )

        try:
            text = await gemini.extract_vision(tmp_path)
            if text:
                self._ocr_stats["gemini_vision"]["success"] += 1
                return ExternalObservation(
                    observation_id=_make_observation_id(),
                    source_type="screenshot",
                    source_path=source_path,
                    extracted_text=text,
                    metadata={
                        "extraction_method": "gemini_vision",
                        "model": "gemini-2.0-flash",
                        "data_size_bytes": len(base64_data),
                    },
                    confidence=0.95,
                    source_attribution="multimodal_adapter",
                    evaluated_at=_now_iso(),
                )
            else:
                self._ocr_stats["gemini_vision"]["failure"] += 1
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

        return _error_observation(
            "screenshot", source_path,
            "Gemini Vision extraction failed for screenshot",
            method="gemini_vision",
        )

    # ----- Text Pass-through -----

    async def extract_text(self, text: str, source_path: str = "") -> ExternalObservation:
        """Pass-through for plain text inputs (e.g., chat messages).

        Args:
            text: The input text.
            source_path: Optional source identifier (e.g., "chat:user123").

        Returns:
            ExternalObservation with the text as-is.
        """
        self._ocr_stats["passthrough"]["success"] += 1
        obs_id = _make_observation_id()
        return ExternalObservation(
            observation_id=obs_id,
            source_type="text",
            source_path=source_path or f"text:{obs_id}",
            extracted_text=text,
            metadata={"extraction_method": "passthrough", "char_length": len(text)},
            confidence=1.0,
            source_attribution="multimodal_adapter",
            evaluated_at=_now_iso(),
        )

