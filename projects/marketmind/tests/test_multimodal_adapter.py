"""Tests for multimodal_adapter — async extraction from images, PDFs, screenshots, text."""
import base64
import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from marketmind.gateway.multimodal_adapter import (
    MultimodalAdapter,
    GeminiFlashGateway,
    _make_observation_id,
    _now_iso,
    _error_observation,
    _tesseract_ocr,
    _pil_metadata,
    _pdfplumber_extract,
    _write_temp_image,
)
from marketmind.shadows.shadow_agent import ExternalObservation


# ---------------------------------------------------------------------------
# Unit helpers
# ---------------------------------------------------------------------------

def test_make_observation_id():
    oid = _make_observation_id()
    assert len(oid) == 12
    assert oid != _make_observation_id()  # unique each call


def test_now_iso():
    ts = _now_iso()
    assert "T" in ts
    assert "+" in ts or "Z" in ts


def test_error_observation():
    obs = _error_observation("pdf", "/tmp/test.pdf", "Something went wrong", method="none")
    assert isinstance(obs, ExternalObservation)
    assert obs.source_type == "pdf"
    assert obs.confidence == 0.0
    assert "Something went wrong" in obs.extracted_text
    assert obs.metadata["error"] == "Something went wrong"


# ---------------------------------------------------------------------------
# MultimodalAdapter — text passthrough (no external deps)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_extract_text_passthrough():
    adapter = MultimodalAdapter()
    obs = await adapter.extract_text("Hello world", source_path="chat:test")
    assert isinstance(obs, ExternalObservation)
    assert obs.source_type == "text"
    assert obs.extracted_text == "Hello world"
    assert obs.confidence == 1.0
    assert obs.metadata["extraction_method"] == "passthrough"


@pytest.mark.asyncio
async def test_extract_text_passthrough_no_source():
    adapter = MultimodalAdapter()
    obs = await adapter.extract_text("Just text")
    assert obs.source_path.startswith("text:")
    assert obs.extracted_text == "Just text"


# ---------------------------------------------------------------------------
# Missing file → error observation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_extract_text_from_image_missing_file():
    adapter = MultimodalAdapter()
    obs = await adapter.extract_text_from_image("/nonexistent/image.png")
    assert obs.confidence == 0.0
    assert "File not found" in obs.extracted_text


@pytest.mark.asyncio
async def test_extract_text_from_pdf_missing_file():
    adapter = MultimodalAdapter()
    obs = await adapter.extract_text_from_pdf("/nonexistent/doc.pdf")
    assert obs.confidence == 0.0
    assert "File not found" in obs.extracted_text


# ---------------------------------------------------------------------------
# Missing API key → graceful degradation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_extract_text_from_image_no_api_key():
    """When GEMINI_API_KEY is not set, extraction falls back to PIL metadata."""
    with patch.dict(os.environ, {}, clear=True):
        adapter = MultimodalAdapter(gemini_api_key="")
        assert await adapter._get_gemini() is None

        # Create a tiny valid PNG and test extraction
        tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        tmp.close()
        try:
            # Write a minimal 1x1 PNG
            minimal_png = (
                b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
                b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f"
                b"\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
            )
            with open(tmp.name, "wb") as f:
                f.write(minimal_png)

            obs = await adapter.extract_text_from_image(tmp.name)
            # Should fall back to PIL metadata (no API key, no tesseract)
            assert obs.source_type == "image"
            # PIL metadata fallback should produce something, or error if PIL not installed
            assert isinstance(obs.extracted_text, str)
            assert len(obs.extracted_text) > 0
        finally:
            os.unlink(tmp.name)


# ---------------------------------------------------------------------------
# GeminiFlashGateway — mock the API
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_gemini_flash_extract_vision_success():
    """Mock Gemini API to return extracted text."""
    gateway = GeminiFlashGateway(api_key="test-key")

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "candidates": [{
            "content": {
                "parts": [{"text": "Extracted chart data: Q1 revenue $1.2B"}]
            }
        }]
    }

    with patch.object(gateway, "_ensure_client", new_callable=AsyncMock) as mock_ensure:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_ensure.return_value = mock_client

        # Create a temp PNG file
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
                     b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f"
                     b"\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82")
            tmp_name = f.name

        try:
            result = await gateway.extract_vision(tmp_name)
            assert result == "Extracted chart data: Q1 revenue $1.2B"
        finally:
            os.unlink(tmp_name)

    await gateway.close()


@pytest.mark.asyncio
async def test_gemini_flash_extract_vision_returns_none_on_error():
    """When Gemini API fails, extract_vision returns None."""
    gateway = GeminiFlashGateway(api_key="test-key")

    with patch.object(gateway, "_ensure_client", new_callable=AsyncMock) as mock_ensure:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=Exception("Network error"))
        mock_ensure.return_value = mock_client

        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(b"fake")
            tmp_name = f.name

        try:
            result = await gateway.extract_vision(tmp_name)
            assert result is None
        finally:
            os.unlink(tmp_name)

    await gateway.close()


# ---------------------------------------------------------------------------
# Screenshot extraction (base64 → Gemini Vision)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_extract_text_from_screenshot_no_api_key():
    """Without API key, screenshot returns metadata note."""
    adapter = MultimodalAdapter(gemini_api_key="")
    dummy_b64 = base64.b64encode(b"fake-screenshot-data").decode()
    obs = await adapter.extract_text_from_screenshot(dummy_b64)
    assert obs.source_type == "screenshot"
    assert "GEMINI_API_KEY" in obs.extracted_text
    assert obs.confidence == 0.0


@pytest.mark.asyncio
async def test_extract_text_from_screenshot_invalid_base64():
    """Invalid base64 produces error observation."""
    adapter = MultimodalAdapter(gemini_api_key="test-key")
    obs = await adapter.extract_text_from_screenshot("not-valid-base64!!!")
    assert obs.confidence == 0.0
    assert "Base64 decode" in obs.extracted_text


# ---------------------------------------------------------------------------
# PDF extraction with mocked pdfplumber
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_extract_text_from_pdf_with_pdfplumber():
    """When pdfplumber is available, it's used as the primary method."""
    mock_result = {
        "text": "Page 1 content\n\nPage 2 content",
        "meta": {"extraction_method": "pdfplumber", "pages_extracted": 2},
    }

    # Create a temp file so os.path.isfile() passes
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(b"%PDF-1.4 fake pdf content")
        pdf_path = tmp.name

    try:
        with patch(
            "marketmind.gateway.multimodal_adapter._pdfplumber_extract",
            return_value=mock_result,
        ):
            adapter = MultimodalAdapter(gemini_api_key="")
            obs = await adapter.extract_text_from_pdf(pdf_path)
            assert obs.source_type == "pdf"
            assert obs.extracted_text == "Page 1 content\n\nPage 2 content"
            assert obs.metadata["extraction_method"] == "pdfplumber"
            assert obs.confidence == 0.9
    finally:
        os.unlink(pdf_path)


@pytest.mark.asyncio
async def test_extract_text_from_pdf_no_methods():
    """When no extraction method is available, error observation is returned."""
    # Create a temp file so os.path.isfile() passes
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(b"%PDF-1.4 fake pdf content")
        pdf_path = tmp.name

    try:
        with patch(
            "marketmind.gateway.multimodal_adapter._pdfplumber_extract",
            return_value=None,
        ):
            adapter = MultimodalAdapter(gemini_api_key="")
            obs = await adapter.extract_text_from_pdf(pdf_path)
            assert obs.confidence == 0.0
            assert "No PDF extraction method available" in obs.extracted_text
    finally:
        os.unlink(pdf_path)
