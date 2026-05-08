"""
flash_adapter.py — Sprint 1: Flash 模型适配器 (DeepSeek Flash)

封装对 DeepSeek Flash API 的异步调用。
Flash 适配器与 Pro 适配器共享相同的 LLMAdapter 抽象基类，
但使用不同的配置参数（更低温度、更低 max_tokens、更高重试次数）。

Flash 适用任务：
  - URL 抓取 + 结构化提取
  - 长文档速读摘要
  - 基础事实核查
  - 文本格式化/关键词提取

SPARC:
  Specification: V2.0 蓝图 §三-3 Pro/Flash Adapter Interface
  Pseudocode: 复用 ProAdapter 结构，仅配置不同
  Architecture: FlashAdapter 继承 LLMAdapter（共享 ABC）
  Refinement: Flash 的 mock 回复更短，模拟高吞吐特性
  Completion: 测试覆盖率 ≥ 90%
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncGenerator, Dict, List, Optional

import httpx

from .pro_adapter import FlashAdapterConfig, LLMAdapter, ProAdapterConfig

logger = logging.getLogger(__name__)


class FlashAdapter(LLMAdapter):
    """DeepSeek Flash — 高吞吐，低延迟，极低成本。

    机械层任务使用 Flash 模型：
    - URL 抓取 + 结构化提取
    - 长文档速读摘要
    - 事实核查
    - 文本格式化
    """

    def __init__(self, config: Optional[FlashAdapterConfig] = None) -> None:
        """初始化 Flash 适配器。

        Args:
            config: 配置对象。默认为 FlashAdapterConfig.from_env()。
                    如果 API Key 为空，启用 Mock 模式。
        """
        self._config = config or FlashAdapterConfig.from_env()
        self._client: Optional[httpx.AsyncClient] = None
        self._mock_mode = not bool(self._config.api_key)

        if self._mock_mode:
            logger.warning(
                "FlashAdapter in MOCK mode — no DEEPSEEK_API_KEY set."
            )
        else:
            logger.info(
                "FlashAdapter initialized: model=%s, endpoint=%s",
                self._config.model,
                self._config.endpoint,
            )

    async def _ensure_client(self) -> httpx.AsyncClient:
        """懒初始化 httpx 客户端（与 ProAdapter 共享模式）。"""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self._config.timeout)
        return self._client

    async def chat(
        self,
        messages: List[Dict[str, str]],
        **kwargs: Any,
    ) -> str:
        """非流式对话。"""
        if self._mock_mode:
            return self._mock_chat(messages)

        payload = self._build_payload(messages, **kwargs)
        retries = 0

        while retries <= self._config.max_retries:
            try:
                client = await self._ensure_client()
                resp = await client.post(
                    self._config.endpoint,
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {self._config.api_key}",
                        "Content-Type": "application/json",
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                return self._extract_content(data)

            except (httpx.TimeoutException, httpx.ConnectError) as e:
                retries += 1
                if retries > self._config.max_retries:
                    raise RuntimeError(
                        f"FlashAdapter: all {self._config.max_retries + 1} "
                        f"retries exhausted. Last error: {e}"
                    ) from e
                wait = self._config.retry_delay * (2 ** (retries - 1))
                logger.warning(
                    "FlashAdapter retry %d/%d after %s: %s",
                    retries, self._config.max_retries + 1, e, wait,
                )
                await asyncio.sleep(wait)

            except httpx.HTTPStatusError as e:
                raise RuntimeError(
                    f"FlashAdapter: HTTP {e.response.status_code}: {e.response.text}"
                ) from e

        return ""

    async def chat_stream(
        self,
        messages: List[Dict[str, str]],
        **kwargs: Any,
    ) -> AsyncGenerator[str, None]:
        """流式对话。"""
        if self._mock_mode:
            for token in self._mock_chat(messages).split():
                yield token + " "
                await asyncio.sleep(0.005)  # Flash 更快
            return

        payload = self._build_payload(messages, stream=True, **kwargs)

        try:
            client = await self._ensure_client()
            async with client.stream(
                "POST",
                self._config.endpoint,
                json=payload,
                headers={
                    "Authorization": f"Bearer {self._config.api_key}",
                    "Content-Type": "application/json",
                },
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if line.startswith("data: "):
                        data_str = line[6:].strip()
                        if data_str == "[DONE]":
                            break
                        try:
                            data = json.loads(data_str)
                            delta = (
                                data.get("choices", [{}])[0]
                                .get("delta", {})
                                .get("content", "")
                            )
                            if delta:
                                yield delta
                        except json.JSONDecodeError:
                            continue

        except httpx.TimeoutException:
            logger.error("FlashAdapter stream: timeout")
        except httpx.HTTPStatusError as e:
            logger.error("FlashAdapter stream: HTTP %s", e.response.status_code)

    def estimate_tokens(self, text: str) -> int:
        return len(text) // 4

    # ============================================================
    # Private
    # ============================================================

    def _build_payload(
        self,
        messages: List[Dict[str, str]],
        stream: bool = False,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        return {
            "model": kwargs.get("model", self._config.model),
            "messages": messages,
            "temperature": kwargs.get("temperature", self._config.temperature),
            "max_tokens": kwargs.get("max_tokens", self._config.max_tokens),
            "stream": stream,
        }

    @staticmethod
    def _extract_content(response_data: Dict[str, Any]) -> str:
        choices = response_data.get("choices", [])
        if not choices:
            return ""
        return choices[0].get("message", {}).get("content", "")

    @staticmethod
    def _mock_chat(messages: List[Dict[str, str]]) -> str:
        """Mock 模式的回复。Flash 回复更短、结构更机械。"""
        last_msg = messages[-1]["content"] if messages else ""
        return (
            f"⚡ [Flash Mock] 任务收到。\n"
            f"输入摘要: {last_msg[:60]}...\n\n"
            f"提取结果(JSON):\n"
            f'{{"status": "mock", "input_length": {len(last_msg)}, '
            f'"type": "auto_detected", "confidence": 0.85}}\n\n'
            f"设置 DEEPSEEK_API_KEY 可切换真实 Flash 模型。"
        )

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()