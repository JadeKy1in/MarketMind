"""Information injection — accept user-provided external info before Gate 1.

User can paste text, upload images (OCR via Gemini Flash), or attach PDFs.
Injected content flows to BOTH main pipeline (full analysis) and shadow
ecosystem (raw text only, per Millennium-style Chinese Wall).

Usage:
    injector = InfoInjector()
    results = await injector.inject(
        text="高盛的Jim说Q2 GDP可能下修到1.4%...",
        files=["reports/gs_q2.pdf", "screenshots/nvda_flow.png"],
    )
    # results.pipeline_items  → merged into scout news_items
    # results.shadow_items    → stripped raw text for shadow distribution
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from pathlib import Path
from datetime import datetime, timezone

logger = logging.getLogger("marketmind.pipeline.info_injector")


@dataclass
class InjectedItem:
    """One piece of injected information, ready for pipeline consumption."""
    content: str                   # extracted text content
    source_type: str               # "user_text" | "file_image" | "file_pdf"
    source_label: str              # human-readable label (file name or "手动输入")
    char_count: int
    timestamp: str


@dataclass
class InjectionResult:
    """Result of an information injection session."""
    items: list[InjectedItem] = field(default_factory=list)
    pipeline_items: list[dict] = field(default_factory=list)
    shadow_items: list[dict] = field(default_factory=list)
    total_chars: int = 0

    @property
    def has_content(self) -> bool:
        return self.total_chars > 0


class InfoInjector:
    """Accept and process user-provided external information.

    Text goes directly into the pipeline. Images and PDFs are extracted
    via MultimodalAdapter (Gemini Flash Vision / pdfplumber).
    """

    def __init__(self):
        self._adapter = None  # lazy init

    async def inject(
        self,
        text: str = "",
        files: list[str] | None = None,
    ) -> InjectionResult:
        """Process user text + file paths into pipeline-ready items.

        Args:
            text: Free-text information pasted by the user.
            files: List of file paths to images (.png/.jpg) or PDFs.

        Returns:
            InjectionResult with pipeline_items and shadow_items.
        """
        result = InjectionResult()

        # Process free text
        if text and text.strip():
            item = InjectedItem(
                content=text.strip(),
                source_type="user_text",
                source_label="外部输入",
                char_count=len(text.strip()),
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
            result.items.append(item)

        # Process files
        for file_path in (files or []):
            path = Path(file_path)
            if not path.exists():
                logger.warning("Injected file not found: %s", file_path)
                continue

            ext = path.suffix.lower()
            try:
                if ext in (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"):
                    content = await self._extract_image(path)
                    source_type = "file_image"
                elif ext == ".pdf":
                    content = await self._extract_pdf(path)
                    source_type = "file_pdf"
                else:
                    # Try reading as plain text
                    try:
                        content = path.read_text(encoding="utf-8")
                        source_type = "file_text"
                    except UnicodeDecodeError:
                        logger.warning("Cannot read file as text or known format: %s", file_path)
                        continue

                if content and content.strip():
                    item = InjectedItem(
                        content=content.strip(),
                        source_type=source_type,
                        source_label=path.name,
                        char_count=len(content.strip()),
                        timestamp=datetime.now(timezone.utc).isoformat(),
                    )
                    result.items.append(item)

            except Exception as e:
                logger.warning("Failed to inject file %s: %s", file_path, e)
                # Inject a degraded item so user knows extraction failed
                item = InjectedItem(
                    content=f"[文件解析失败: {path.name} — {e}]",
                    source_type="file_error",
                    source_label=path.name,
                    char_count=0,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                )
                result.items.append(item)

        result.total_chars = sum(i.char_count for i in result.items)

        # Build pipeline items (scout-compatible format)
        result.pipeline_items = [
            {
                "title": f"[外部信息] {i.source_label}",
                "content": i.content,
                "source": "user_injected",
                "content_type": "external_info",
                "char_count": i.char_count,
                "timestamp": i.timestamp,
            }
            for i in result.items
        ]

        # Build shadow items — RAW content only (Chinese Wall compliance)
        result.shadow_items = [
            {
                "text": i.content,
                "source_label": f"external:{i.source_label}",
                "timestamp": i.timestamp,
                # NO AWA scores, NO AI analysis, NO direction hints
            }
            for i in result.items
        ]

        logger.info(
            "Info injector: %d items, %d chars total (%d text, %d files)",
            len(result.items), result.total_chars,
            sum(1 for i in result.items if i.source_type == "user_text"),
            sum(1 for i in result.items if i.source_type != "user_text"),
        )
        return result

    async def _extract_image(self, path: Path) -> str:
        """Extract text from image via Gemini Flash Vision."""
        adapter = await self._get_adapter()
        return await adapter.extract_image(path)

    async def _extract_pdf(self, path: Path) -> str:
        """Extract text from PDF via pdfplumber or Gemini Flash."""
        adapter = await self._get_adapter()
        return await adapter.extract_pdf(path)

    async def _get_adapter(self):
        """Lazy init MultimodalAdapter."""
        if self._adapter is None:
            from marketmind.gateway.multimodal_adapter import MultimodalAdapter
            self._adapter = MultimodalAdapter()
        return self._adapter


# Convenience: direct function for CLI integration
async def inject_user_info(
    text: str = "",
    files: list[str] | None = None,
) -> InjectionResult:
    """One-shot injection — use in app.py or orchestration.py."""
    injector = InfoInjector()
    return await injector.inject(text=text, files=files)
