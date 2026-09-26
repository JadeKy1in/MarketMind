"""Tests for pipeline/info_injector.py — user information injection."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from marketmind.pipeline.info_injector import (
    InfoInjector, InjectionResult, InjectedItem, inject_user_info,
)


class TestInjectionResult:
    def test_empty_result_has_no_content(self):
        r = InjectionResult()
        assert not r.has_content
        assert r.total_chars == 0

    def test_with_text_has_content(self):
        r = InjectionResult()
        r.items.append(InjectedItem(
            content="Test info", source_type="user_text",
            source_label="test", char_count=9, timestamp=""))
        r.total_chars = 9
        assert r.has_content


class TestInfoInjectorText:
    @pytest.mark.asyncio
    async def test_inject_text_only(self):
        injector = InfoInjector()
        result = await injector.inject(text="高盛的Jim说Q2 GDP可能下修到1.4%")
        assert result.has_content
        assert len(result.items) == 1
        assert result.items[0].source_type == "user_text"
        assert result.items[0].char_count > 0
        assert len(result.pipeline_items) == 1
        assert result.pipeline_items[0]["content_type"] == "external_info"

    @pytest.mark.asyncio
    async def test_inject_empty_returns_no_content(self):
        injector = InfoInjector()
        result = await injector.inject(text="   ")
        assert not result.has_content

    @pytest.mark.asyncio
    async def test_shadow_items_stripped(self):
        """Chinese Wall: shadow items have no AWA scores, no direction hints."""
        injector = InfoInjector()
        result = await injector.inject(text="NVDA看多，目标价150")
        assert len(result.shadow_items) == 1
        shadow = result.shadow_items[0]
        assert "text" in shadow
        assert "awa_score" not in shadow
        assert "direction" not in shadow

    @pytest.mark.asyncio
    async def test_multiple_items(self):
        injector = InfoInjector()
        result = await injector.inject(
            text="第一段信息",
        )
        result2 = await injector.inject(
            text="第二段信息",
        )
        assert result.has_content


class TestInfoInjectorFiles:
    @pytest.mark.asyncio
    async def test_inject_nonexistent_file_skipped(self, tmp_path):
        injector = InfoInjector()
        result = await injector.inject(
            text="valid text",
            files=[str(tmp_path / "nonexistent.pdf")],
        )
        assert result.has_content
        assert len(result.items) == 1  # text kept, file skipped

    @pytest.mark.asyncio
    async def test_inject_image(self, tmp_path):
        # Create a real temp file so path.exists() passes
        img_path = tmp_path / "chart.png"
        img_path.write_text("")  # empty but exists
        injector = InfoInjector()
        with patch.object(injector, '_extract_image', new_callable=AsyncMock) as mock_extract:
            mock_extract.return_value = "extracted image text"
            result = await injector.inject(files=[str(img_path)])
            assert result.has_content
            assert result.items[0].source_type == "file_image"
            assert "extracted" in result.items[0].content

    @pytest.mark.asyncio
    async def test_multiple_files_mixed(self, tmp_path):
        img_path = tmp_path / "chart.png"
        img_path.write_text("")
        pdf_path = tmp_path / "report.pdf"
        pdf_path.write_text("")
        injector = InfoInjector()
        with patch.object(injector, '_extract_image', new_callable=AsyncMock) as mock_img, \
             patch.object(injector, '_extract_pdf', new_callable=AsyncMock) as mock_pdf:
            mock_img.return_value = "image text"
            mock_pdf.return_value = "pdf text"
            result = await injector.inject(
                text="manual text",
                files=[str(img_path), str(pdf_path)],
            )
            assert len(result.items) == 3
            assert result.total_chars > 0


@pytest.mark.asyncio
async def test_inject_user_info_convenience():
    result = await inject_user_info(text="test")
    assert isinstance(result, InjectionResult)
    assert result.has_content
