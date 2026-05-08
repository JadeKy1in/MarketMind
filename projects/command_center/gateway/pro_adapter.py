"""
pro_adapter.py — Sprint 1: Pro 模型适配器 (DeepSeek V4 Pro)

封装对 DeepSeek Pro API 的异步调用。
支持流式和非流式两种模式。

接口抽象化，使得适配器可被 Mock 替换（测试和离线模式支持）。

SPARC:
  Specification: V2.0 蓝图 §三-3 Pro/Flash Adapter Interface
  Pseudocode: chat() → httpx.AsyncClient POST → parse response
  Architecture: ABC 基类 + Concrete ProAdapter。ABC 与 FlashAdapter 共享
  Refinement: 使用 Safe Timeout Pattern（explicit Promise<T> 模式）
  Completion: test 覆盖率 ≥ 90%
"""

from __future__ import annotations

import abc
import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Dict, List, Optional

import httpx

from projects.command_center.config.settings_manager import SettingsManager

logger = logging.getLogger(__name__)


# ============================================================
# LLM 接口定义
# ============================================================

class LLMAdapter(abc.ABC):
    """双模型适配器抽象基类。

    提供统一的 chat() 和 chat_stream() 接口。
    ProAdapter 和 FlashAdapter 均实现此接口。
    """

    @abc.abstractmethod
    async def chat(
        self,
        messages: List[Dict[str, str]],
        **kwargs: Any,
    ) -> str:
        """非流式对话。等待完整回复后返回。

        Args:
            messages: OpenAI 格式的消息列表 [{"role": "user", "content": "..."}]
            **kwargs: 覆盖默认参数（temperature, max_tokens 等）

        Returns:
            模型回复的文本内容
        """
        ...

    @abc.abstractmethod
    async def chat_stream(
        self,
        messages: List[Dict[str, str]],
        **kwargs: Any,
    ) -> AsyncGenerator[str, None]:
        """流式对话。逐 token 产出回复。

        Args:
            messages: OpenAI 格式的消息列表
            **kwargs: 覆盖默认参数

        Yields:
            逐 token 的文本片段
        """
        ...
        yield  # pragma: no cover

    @abc.abstractmethod
    def estimate_tokens(self, text: str) -> int:
        """预估文本的 token 数量。"""
        ...


# ============================================================
# 配置
# ============================================================

@dataclass
class ProAdapterConfig:
    """Pro 模型适配器的配置。

    Attributes:
        api_key: API Key（可从环境变量读取）
        endpoint: API 端点 URL
        model: 模型名称
        max_tokens: 最大输出 token 数
        temperature: 温度参数（低温度保证策略一致性）
        timeout: HTTP 超时秒数
        max_retries: 最大重试次数
        retry_delay: 重试间隔基础秒数
    """
    api_key: str = ""
    endpoint: str = "https://api.deepseek.com/v1/chat/completions"
    model: str = "deepseek-chat"  # DeepSeek Pro 实际 model ID
    max_tokens: int = 8192
    temperature: float = 0.3  # 低温度保证策略一致性
    timeout: float = 120.0
    max_retries: int = 2
    retry_delay: float = 2.0

    @classmethod
    def from_env(cls) -> "ProAdapterConfig":
        """从环境变量读取配置。"""
        import os
        return cls(
            api_key=os.environ.get("DEEPSEEK_API_KEY", ""),
            endpoint=os.environ.get(
                "DEEPSEEK_PRO_ENDPOINT",
                "https://api.deepseek.com/v1/chat/completions",
            ),
            model=os.environ.get("DEEPSEEK_PRO_MODEL", "deepseek-chat"),
        )

    @classmethod
    def from_settings(cls, settings: SettingsManager) -> "ProAdapterConfig":
        """从 SettingsManager 读取配置（config.json 优先，环境变量后备）。"""
        return cls(
            api_key=settings.get_api_key(),
            endpoint=settings.get("api.deepseek_pro_endpoint",
                                   "https://api.deepseek.com/v1/chat/completions"),
            model=settings.get("api.deepseek_pro_model", "deepseek-chat"),
        )


@dataclass
class FlashAdapterConfig:
    """Flash 模型适配器的配置。

    Attributes:
        api_key: API Key
        endpoint: API 端点 URL
        model: 模型名称
        max_tokens: 最大输出 token 数
        temperature: 温度参数（极低温度保证提取准确性）
        timeout: HTTP 超时秒数
        max_retries: 最大重试次数
        retry_delay: 重试间隔基础秒数
    """
    api_key: str = ""
    endpoint: str = "https://api.deepseek.com/v1/chat/completions"
    model: str = "deepseek-chat"  # DeepSeek Flash 实际 model ID
    max_tokens: int = 4096
    temperature: float = 0.1  # 极低温度保证提取准确性
    timeout: float = 60.0
    max_retries: int = 3
    retry_delay: float = 1.0

    @classmethod
    def from_env(cls) -> "FlashAdapterConfig":
        """从环境变量读取配置。"""
        import os
        return cls(
            api_key=os.environ.get("DEEPSEEK_API_KEY", ""),
            endpoint=os.environ.get(
                "DEEPSEEK_FLASH_ENDPOINT",
                "https://api.deepseek.com/v1/chat/completions",
            ),
            model=os.environ.get("DEEPSEEK_FLASH_MODEL", "deepseek-chat"),
        )

    @classmethod
    def from_settings(cls, settings: SettingsManager) -> "FlashAdapterConfig":
        """从 SettingsManager 读取配置（config.json 优先，环境变量后备）。"""
        return cls(
            api_key=settings.get_api_key(),
            endpoint=settings.get("api.deepseek_flash_endpoint",
                                   "https://api.deepseek.com/v1/chat/completions"),
            model=settings.get("api.deepseek_flash_model", "deepseek-chat"),
        )


# ============================================================
# ProAdapter — 实现
# ============================================================

class ProAdapter(LLMAdapter):
    """DeepSeek V4 Pro — 深度推理，高延迟，高成本。

    策略级任务使用 Pro 模型：
    - 策略深度复盘
    - 信念更新研判
    - 调仓逻辑辩论
    """

    def __init__(self, config: Optional[ProAdapterConfig] = None) -> None:
        """初始化 Pro 适配器。

        Args:
            config: 配置对象。默认为 ProAdapterConfig.from_env()。
                    如果 API Key 为空，启用 Mock 模式。
        """
        self._config = config or ProAdapterConfig.from_env()
        self._client: Optional[httpx.AsyncClient] = None
        self._mock_mode = not bool(self._config.api_key)

        if self._mock_mode:
            logger.warning(
                "ProAdapter in MOCK mode — no DEEPSEEK_API_KEY set. "
                "Set the environment variable for real API calls."
            )
        else:
            logger.info(
                "ProAdapter initialized: model=%s, endpoint=%s",
                self._config.model,
                self._config.endpoint,
            )

    async def _ensure_client(self) -> httpx.AsyncClient:
        """懒初始化 httpx 客户端。"""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self._config.timeout)
        return self._client

    async def chat(
        self,
        messages: List[Dict[str, str]],
        **kwargs: Any,
    ) -> str:
        """非流式对话。

        Args:
            messages: OpenAI 格式消息列表
            **kwargs: 覆盖默认参数

        Returns:
            模型回复字符串

        Raises:
            RuntimeError: API 调用失败（超时/HTTP 错误）
        """
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
                        f"ProAdapter: all {self._config.max_retries + 1} "
                        f"retries exhausted. Last error: {e}"
                    ) from e
                wait = self._config.retry_delay * (2 ** (retries - 1))
                logger.warning(
                    "ProAdapter retry %d/%d after %s: %s",
                    retries, self._config.max_retries + 1, e, wait,
                )
                await asyncio.sleep(wait)

            except httpx.HTTPStatusError as e:
                raise RuntimeError(
                    f"ProAdapter: HTTP {e.response.status_code}: {e.response.text}"
                ) from e

        # 不应到达此处
        return ""

    async def chat_stream(
        self,
        messages: List[Dict[str, str]],
        **kwargs: Any,
    ) -> AsyncGenerator[str, None]:
        """流式对话。

        使用 SSE (Server-Sent Events) 逐 token 产出回复。
        """
        if self._mock_mode:
            for token in self._mock_chat(messages).split():
                yield token + " "
                await asyncio.sleep(0.01)
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
            logger.error("ProAdapter stream: timeout")
        except httpx.HTTPStatusError as e:
            logger.error("ProAdapter stream: HTTP %s", e.response.status_code)

    def estimate_tokens(self, text: str) -> int:
        """粗略预估 token 数量（每 4 字符 ≈ 1 token）。"""
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
        """构建 OpenAI 兼容的请求 payload。"""
        payload = {
            "model": kwargs.get("model", self._config.model),
            "messages": messages,
            "temperature": kwargs.get("temperature", self._config.temperature),
            "max_tokens": kwargs.get("max_tokens", self._config.max_tokens),
            "stream": stream,
        }
        return payload

    @staticmethod
    def _extract_content(response_data: Dict[str, Any]) -> str:
        """从 API 响应中提取文本内容。"""
        choices = response_data.get("choices", [])
        if not choices:
            return ""
        return choices[0].get("message", {}).get("content", "")

    @staticmethod
    def _mock_chat(messages: List[Dict[str, str]]) -> str:
        """Mock 模式下的回复生成。"""
        last_msg = messages[-1]["content"] if messages else ""
        return (
            f"🤖 [Pro Mock] 收到您的信息：\"{last_msg[:80]}...\"\n\n"
            "这是一条来自 Mock Pro 模型的自动回复。\n"
            "设置 DEEPSEEK_API_KEY 环境变量后可切换到真实模型。\n\n"
            "从您的输入中，我注意到几个值得深入讨论的方向：\n"
            "1. 市场环境与当前仓位的匹配度\n"
            "2. 潜在风险和下行保护策略\n"
            "3. 下一步的战术调整建议\n\n"
            "请补充更多信息，我可以提供更有针对性的分析。"
        )

    async def close(self) -> None:
        """关闭 HTTP 客户端，释放资源。"""
        if self._client and not self._client.is_closed:
            await self._client.aclose()