"""
conftest.py — Sprint 1 pytest fixtures

提供测试用的公共 fixtures：
  - MockProAdapter / MockFlashAdapter
  - MockTaskQueue
  - 路由测试用的标准 RouteInput 样本
"""

from __future__ import annotations

import asyncio
import pytest
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple

from projects.command_center.gateway.router import (
    LLMRouter,
    RouteInput,
    TaskProfile,
    TargetModel,
    TaskType,
    Priority,
)
from projects.command_center.gateway.pro_adapter import (
    LLMAdapter,
    ProAdapter,
    ProAdapterConfig,
)
from projects.command_center.gateway.flash_adapter import FlashAdapter, FlashAdapterConfig


# ============================================================
# Mock 适配器（用于 TaskQueue 测试）
# ============================================================

class MockLLMAdapter(LLMAdapter):
    """测试用的 Mock LLM 适配器。

    不会发起真实网络请求，直接返回预设回复。
    """

    def __init__(
        self,
        name: str = "mock",
        delay: float = 0.01,
        fail_for: Optional[List[str]] = None,
    ) -> None:
        """初始化 Mock 适配器。

        Args:
            name: 模型名称（用于标识）
            delay: 模拟延迟（秒）
            fail_for: 输入前缀列表——匹配的任务应失败
        """
        self.name = name
        self.delay = delay
        self.fail_for = fail_for or []
        self.call_count = 0

    async def chat(
        self,
        messages: List[Dict[str, str]],
        **kwargs: Any,
    ) -> str:
        """模拟非流式对话。"""
        self.call_count += 1
        await asyncio.sleep(self.delay)

        last_content = messages[-1]["content"] if messages else ""

        # 检查是否应模拟失败
        for prefix in self.fail_for:
            if last_content.startswith(prefix):
                raise RuntimeError(f"Mock failure for: {prefix}")

        return (
            f"[{self.name} Mock] 已处理您的请求。\n"
            f"输入: {last_content[:100]}..."
        )

    async def chat_stream(
        self,
        messages: List[Dict[str, str]],
        **kwargs: Any,
    ) -> AsyncGenerator[str, None]:
        """模拟流式对话。"""
        self.call_count += 1
        response = await self.chat(messages, **kwargs)
        for token in response.split():
            yield token + " "
            await asyncio.sleep(0.005)

    def estimate_tokens(self, text: str) -> int:
        return len(text) // 4

    async def close(self) -> None:
        """模拟资源清理。"""
        pass


# ============================================================
# pytest fixtures
# ============================================================

@pytest.fixture
def router() -> LLMRouter:
    """默认路由器的 fixture。"""
    return LLMRouter.create_default()


@pytest.fixture
def mock_pro() -> MockLLMAdapter:
    """Mock Pro 适配器。"""
    return MockLLMAdapter(name="pro-mock", delay=0.01)


@pytest.fixture
def mock_flash() -> MockLLMAdapter:
    """Mock Flash 适配器。"""
    return MockLLMAdapter(name="flash-mock", delay=0.005)


@pytest.fixture
def failing_mock() -> MockLLMAdapter:
    """会失败的 Mock 适配器。"""
    return MockLLMAdapter(
        name="failing-mock",
        delay=0.01,
        fail_for=["FAIL_ME"],
    )


@pytest.fixture
def sample_inputs() -> Dict[str, RouteInput]:
    """标准路由测试样本。"""
    return {
        "url_fetch": RouteInput(
            text="https://example.com/news/article-1",
            has_url=True,
            is_interactive_conversation=False,
        ),
        "url_debate": RouteInput(
            text="https://example.com/news/article-1 这篇报告靠谱吗？",
            has_url=True,
            is_interactive_conversation=True,
        ),
        "strategy_debate": RouteInput(
            text="帮我复盘本周的做市策略",
        ),
        "rebalance": RouteInput(
            text="调仓建议：TSLA 当前占比太高了",
        ),
        "summarize": RouteInput(
            text="请帮我摘要这份研报",
        ),
        "fact_check": RouteInput(
            text="事实核查：高盛说降息概率80%，数据来源可靠吗",
        ),
        "free_chat": RouteInput(
            text="今天天气怎么样？",
            is_interactive_conversation=True,
        ),
        "deep_analysis": RouteInput(
            text="为什么美联储这次不降息？这对我们的持仓有什么影响？",
        ),
        "belief_debate": RouteInput(
            text="我认为中国经济复苏信号在增强，这个信念需要更新吗？",
        ),
        "bare_text_fallback": RouteInput(
            text="测试",
        ),
        "report_gen": RouteInput(
            text="生成一份本周报告",
        ),
        "scrape": RouteInput(
            text="抓取这个页面并把关键数据提取出来",
        ),
        "long_text_multi_question": RouteInput(
            text="这是一个非常长的文本，包含了多个问句。首先我想知道第一个问题的答案？其次第二个问题的结果是什么？还有第三个问题需要解释？以及第四个问题也需要分析？",
        ),
    }


@pytest.fixture
def event_loop() -> asyncio.AbstractEventLoop:
    """提供事件循环 for async tests。"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    yield loop
    loop.close()