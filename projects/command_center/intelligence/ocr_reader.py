"""ocr_reader.py — Sprint 5: 多模态附件解析器

职责: 将图片/PDF/MD/TXT 文件转换为纯文本。
异步执行，不阻塞 UI 主线程。

红线:
  - 所有 I/O 操作必须在后台线程执行
  - 图片通过 base64 编码发送到 Flash Vision API
  - PDF 通过 pdfplumber 提取文本（try-except 降级）
  - 纯文本文件直接读取

设计:
  纯函数式模块，无状态，无副作用。
  OCRReader.read(file_paths) → str
"""

from __future__ import annotations

import base64
import logging
import os
from typing import List, Optional

logger = logging.getLogger(__name__)

# 尝试导入 PDF 依赖（优雅降级）
try:
    import pdfplumber
    _HAS_PDFPLUMBER = True
except ImportError:
    _HAS_PDFPLUMBER = False
    logger.info("pdfplumber not installed. PDF extraction will use plain text fallback.")


# 图片文件扩展名
_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"}
# 文本文件扩展名
_TEXT_EXTS = {".md", ".txt", ".csv", ".json", ".xml", ".yaml", ".yml", ".log"}


def _read_text_file(path: str) -> str:
    """安全读取文本文件。"""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except Exception as exc:
        logger.warning("Failed to read text file %s: %s", path, exc)
        return f"[文件读取失败: {os.path.basename(path)}]"


def _read_image(path: str) -> str:
    """将图片文件编码为 base64 数据 URI。

    返回可直接插入 Flash Vision API 的 data URI 字符串。
    """
    try:
        with open(path, "rb") as f:
            b64_data = base64.b64encode(f.read()).decode("ascii")
        ext = os.path.splitext(path)[1].lower()
        mime = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".gif": "image/gif",
            ".bmp": "image/bmp",
            ".webp": "image/webp",
        }.get(ext, "image/png")
        return f"data:{mime};base64,{b64_data}"
    except Exception as exc:
        logger.warning("Failed to read image %s: %s", path, exc)
        return f"[图片读取失败: {os.path.basename(path)}]"


def _read_pdf(path: str) -> str:
    """使用 pdfplumber 提取 PDF 文本内容。

    失败时优雅降级为纯文本读取。
    """
    if not _HAS_PDFPLUMBER:
        logger.info("pdfplumber not available, reading %s as plain text", path)
        return _read_text_file(path)

    try:
        text_parts: List[str] = []
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text_parts.append(page_text)
        if text_parts:
            return "\n\n".join(text_parts)
        return f"[PDF: {os.path.basename(path)} 无文本内容]"
    except Exception as exc:
        logger.warning("pdfplumber failed for %s: %s. Falling back to text.", path, exc)
        return _read_text_file(path)


def read_files(file_paths: List[str]) -> str:
    """读取一系列文件，返回合并的文本内容。

    每个文件以标记分隔:
      --- [文件名] ---
      [内容]

    Args:
        file_paths: 文件路径列表

    Returns:
        所有文件内容的合并文本字符串
    """
    if not file_paths:
        return ""

    parts: List[str] = []
    for path in file_paths:
        if not os.path.isfile(path):
            logger.warning("File not found: %s", path)
            parts.append(f"--- [文件不存在: {path}] ---")
            continue

        basename = os.path.basename(path)
        ext = os.path.splitext(path)[1].lower()

        if ext in _IMAGE_EXTS:
            # 图片: 返回 base64 并标记为需要 Flash Vision 处理
            data_uri = _read_image(path)
            parts.append(
                f"--- [图片: {basename}] ---\n"
                f"[IMAGE_DATA:{data_uri}]\n"
                f"[文件大小: {os.path.getsize(path)} 字节]"
            )
        elif ext == ".pdf":
            content = _read_pdf(path)
            parts.append(f"--- [PDF: {basename}] ---\n{content}")
        elif ext in _TEXT_EXTS:
            content = _read_text_file(path)
            parts.append(f"--- [文件: {basename}] ---\n{content}")
        else:
            # 未知类型：尝试文本读取
            content = _read_text_file(path)
            parts.append(f"--- [文件: {basename}] ---\n{content}")

    return "\n\n".join(parts)


def build_vision_messages(files_content: str, user_text: str = "") -> list:
    """从 OCR reader 输出构建 Flash Vision API 的消息列表。

    扫描 files_content 中的 [IMAGE_DATA:...] 标记，生成 vision 格式消息。
    非图片文件内容作为上下文文本携带。

    Args:
        files_content: read_files() 的输出
        user_text: 用户附加的文本消息

    Returns:
        OpenAI 格式的消息列表，兼容 Flash Vision API
    """
    import re

    messages = []

    # 提取所有图片 data URI
    image_uris = re.findall(r"\[IMAGE_DATA:(data:image/[^;]+;base64,[^\]]+)\]", files_content)

    # 提取非图片文本内容
    text_content = re.sub(r"\[IMAGE_DATA:data:image/[^;]+;base64,[^\]]+\]", "", files_content)
    text_content = text_content.strip()

    if image_uris:
        # Vision 多模态格式
        content: list = []
        if user_text:
            content.append({"type": "text", "text": user_text})
        if text_content:
            content.append({"type": "text", "text": f"上下文:\n{text_content}"})
        for uri in image_uris:
            content.append({"type": "image_url", "image_url": {"url": uri}})
        messages.append({"role": "user", "content": content})
    else:
        # 纯文本格式
        combined = user_text
        if text_content:
            combined = f"{user_text}\n\n以下附件内容供参考:\n{text_content}" if user_text else text_content
        messages.append({"role": "user", "content": combined})

    return messages