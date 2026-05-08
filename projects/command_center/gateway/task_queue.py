"""
task_queue.py — Sprint 1: 线程安全的双模型并发调度队列 (TaskQueue)

【PM 工程红线核心实现】

本模块是 V2.0 架构 Layer 4 Gateway 的心脏——确保：
  1. UI 线程永不阻塞：所有 LLM 调用在独立 asyncio 事件循环中执行
  2. Pro 串行，Flash 并发：Pro 队列保证推理顺序、Flash 队列实现高吞吐
  3. 线程安全桥接：通过 queue.Queue + asyncio.run_coroutine_threadsafe 隔离

设计模式：
  - TaskQueue 运行在自己的 asyncio 事件循环中（后台线程）
  - UI 线程通过 submit() 提交任务，通过回调接收结果
  - 回调在调用线程（UI 线程）执行，确保 Direct ABI 安全

Safe Timeout Pattern (§3.7.d of .clinerules):
  使用 explicit Promise<T> 模式而非 Promise.race() 实现超时，
  确保慢 Promise 不会留空（clearTimeout 在 BOTH resolve 和 reject 中调用）。

SPARC:
  Specification: PM 红线 — UI 线程永不阻塞
  Pseudocode: tkinter_thread → submit() → asyncio_loop → callback
  Architecture: 后台线程 + asyncio + thread-safe queue
  Refinement: 回调链保证在提交线程（UI 线程）执行
  Completion: 测试覆盖 3 种队列模式 + 异常场景
"""

from __future__ import annotations

import asyncio
import logging
import queue
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple, TypeVar

from .pro_adapter import LLMAdapter, ProAdapter
from .flash_adapter import FlashAdapter
from .router import LLMRouter, Priority, RouteInput, TargetModel, TaskProfile, TaskType

logger = logging.getLogger(__name__)

# ============================================================
# 类型别名
# ============================================================

T = TypeVar("T")

# 回调签名: (result: str, error: Optional[str]) → None
ResultCallback = Callable[[str, Optional[str]], None]
# 通用回调: (task_id: str, result: Any, error: Optional[str]) → None
TaskCallback = Callable[[str, Any, Optional[str]], None]


# ============================================================
# 结果容器
# ============================================================

@dataclass(frozen=True)
class TaskResult:
    """一个任务的执行结果。

    Attributes:
        task_id: 任务唯一标识
        output: 模型输出字符串
        error: 错误信息（None 表示成功）
        latency_ms: 执行耗时（毫秒）
        model_used: 实际使用的模型（'pro' | 'flash' | 'mock_pro' | 'mock_flash'）
        token_estimate: 预估 token 消耗
        task_type: 任务类型标签
    """
    task_id: str
    output: str
    error: Optional[str] = None
    latency_ms: float = 0.0
    model_used: str = ""
    token_estimate: int = 0
    task_type: str = ""


# ============================================================
# Token 预算追踪器
# ============================================================

@dataclass
class TokenBudget:
    """Token 使用预算追踪器，用于成本监控。

    Attributes:
        total_input_tokens: 累计输入 token
        total_output_tokens: 累计输出 token
        pro_calls: Pro 模型调用次数
        flash_calls: Flash 模型调用次数
        budget_limit: Token 预算上限（0 = 无限制）
    """
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    pro_calls: int = 0
    flash_calls: int = 0
    budget_limit: int = 0

    def record(self, input_tokens: int, output_tokens: int, model: str) -> None:
        self.total_input_tokens += input_tokens
        self.total_output_tokens += output_tokens
        if model in ("pro", "mock_pro"):
            self.pro_calls += 1
        else:
            self.flash_calls += 1

    @property
    def total_tokens(self) -> int:
        return self.total_input_tokens + self.total_output_tokens

    @property
    def is_exceeded(self) -> bool:
        return self.budget_limit > 0 and self.total_tokens >= self.budget_limit

    @property
    def summary(self) -> str:
        return (
            f"TokenBudget: {self.total_tokens} total "
            f"(in={self.total_input_tokens} out={self.total_output_tokens}), "
            f"Pro={self.pro_calls} Flash={self.flash_calls}"
        )


# ============================================================
# 任务内部数据结构
# ============================================================

class _TaskStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class _TaskWrapper:
    """内部任务包装器，封装任务执行的全生命周期。

    此结构体的属性会随任务执行而变化（非 frozen）。
    """
    # ----- 静态字段（任务创建时确定） -----
    task_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: float = field(default_factory=time.time)
    messages: List[Dict[str, str]] = field(default_factory=list)
    profile: Optional[TaskProfile] = None
    callback: Optional[TaskCallback] = None
    kwargs: Dict[str, Any] = field(default_factory=dict)

    # ----- 动态字段（任务执行过程中更新） -----
    status: _TaskStatus = _TaskStatus.PENDING
    result: Optional[str] = None
    error: Optional[str] = None
    latency_ms: float = 0.0
    model_used: str = ""
    token_estimate: int = 0

    @property
    def elapsed_seconds(self) -> float:
        return time.time() - self.created_at


# ============================================================
# TaskQueue — 核心调度引擎
# ============================================================

class TaskQueue:
    """线程安全的双模型并发调度队列。

    职责：
      1. 维护 Pro 串行队列和 Flash 并发池
      2. 接收来自 UI 线程的任务提交
      3. 在后台 asyncio 事件循环中执行
      4. 通过回调将结果送回提交线程

    用法:
        queue = TaskQueue(pro_adapter, flash_adapter, router)

        # 从 UI 线程调用 — 不会阻塞
        queue.submit(
            messages=[{"role": "user", "content": "帮我复盘本周策略"}],
            callback=lambda task_id, result, error: print(result),
        )

        # 或使用便捷方法
        queue.submit_from_text("帮我复盘本周策略", callback=...)

        # 停止后台线程
        queue.shutdown()

    线程安全设计:
      - 所有公共方法从外部线程调用
      - _TaskWrapper 的修改通过 queue.Queue 传递到事件循环线程
      - 回调在提交线程的 callback 中执行
    """

    def __init__(
        self,
        pro_adapter: Optional[LLMAdapter] = None,
        flash_adapter: Optional[LLMAdapter] = None,
        router: Optional[LLMRouter] = None,
        flash_max_concurrent: int = 5,
        token_budget_limit: int = 0,
    ) -> None:
        """初始化 TaskQueue。

        Args:
            pro_adapter: Pro 模型适配器（默认创建）
            flash_adapter: Flash 模型适配器（默认创建）
            router: 路由判定器（默认创建）
            flash_max_concurrent: Flash 最大并发数（默认 5）
            token_budget_limit: Token 预算上限（0 = 无限制）
        """
        self._pro = pro_adapter or ProAdapter()
        self._flash = flash_adapter or FlashAdapter()
        self._router = router or LLMRouter.create_default()
        self._flash_max_concurrent = flash_max_concurrent
        self._token_budget = TokenBudget(budget_limit=token_budget_limit)

        # 线程同步
        self._lock = threading.Lock()
        self._loop_ready = threading.Event()  # 事件循环就绪信号

        self._running = False
        self._loop_thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None

        # 回调队列 — 由任务执行线程填充，由主线程 drain
        self._callback_queue: "queue.Queue[Tuple[str, Any, Optional[str]]]" = queue.Queue()

        # 任务状态追踪（用于取消/查询）
        self._tasks: Dict[str, _TaskWrapper] = {}

        logger.info(
            "TaskQueue initialized: flash_max_concurrent=%d, budget_limit=%d",
            flash_max_concurrent, token_budget_limit,
        )

    # ============================================================
    # 生命周期管理
    # ============================================================

    def start(self) -> None:
        """启动后台事件循环线程。

        start() 在调用线程中同步启动后台线程。
        后台线程运行自己的 asyncio 事件循环。

        Raises:
            RuntimeError: 如果队列已经在运行
        """
        with self._lock:
            if self._running:
                raise RuntimeError("TaskQueue already running")
            self._running = True

        self._loop_thread = threading.Thread(
            target=self._run_event_loop,
            name="task-queue-loop",
            daemon=True,
        )
        self._loop_thread.start()
        # 等待事件循环就绪（最多 5 秒）
        if not self._loop_ready.wait(timeout=5.0):
            raise RuntimeError("TaskQueue: event loop failed to start within 5s")
        logger.info("TaskQueue started")

    def shutdown(self, wait: bool = True, timeout: float = 5.0) -> None:
        """停止后台线程。

        Args:
            wait: 是否等待正在执行的任务完成
            timeout: 最大等待秒数
        """
        with self._lock:
            if not self._running:
                return
            self._running = False

        if self._loop and not self._loop.is_closed():
            self._loop.call_soon_threadsafe(self._loop.stop)

        if wait and self._loop_thread:
            self._loop_thread.join(timeout=timeout)
            if self._loop_thread.is_alive():
                logger.warning("TaskQueue: loop thread did not stop cleanly")

        # 关闭 HTTP 客户端
        if self._loop and not self._loop.is_closed():
            asyncio.run_coroutine_threadsafe(
                self._close_adapters(), self._loop
            )

        logger.info("TaskQueue shutdown complete")

    async def _close_adapters(self) -> None:
        """清理适配器资源。"""
        if hasattr(self._pro, "close"):
            await self._pro.close()
        if hasattr(self._flash, "close"):
            await self._flash.close()

    # ============================================================
    # 任务提交（从外部线程调用）
    # ============================================================

    def submit(
        self,
        messages: List[Dict[str, str]],
        profile: Optional[TaskProfile] = None,
        callback: Optional[TaskCallback] = None,
        **kwargs: Any,
    ) -> str:
        """提交一个 LLM 任务。

        这是通用提交接口。任务将被路由到 Pro 或 Flash 队列。

        Args:
            messages: OpenAI 格式的消息列表
            profile: 可选的路由判定结果。如果为 None，自动判定。
            callback: 任务完成回调。在**提交线程**中调用。
                      signature: (task_id: str, result: str, error: Optional[str])
            **kwargs: 传递给模型适配器的额外参数

        Returns:
            任务 ID（用于取消/查询）

        Raises:
            RuntimeError: 如果队列未启动
        """
        if not self._running:
            raise RuntimeError("TaskQueue is not running. Call start() first.")

        # 如果未提供 profile，自动路由
        if profile is None:
            text = messages[-1]["content"] if messages else ""
            profile = self._router.classify_text(text)

        # 创建任务包装器
        task = _TaskWrapper(
            messages=messages,
            profile=profile,
            callback=callback,
            kwargs=kwargs,
            token_estimate=profile.estimated_tokens,
        )
        self._tasks[task.task_id] = task

        # 通过线程安全 channel 提交到事件循环
        if self._loop and not self._loop.is_closed():
            asyncio.run_coroutine_threadsafe(
                self._execute(task), self._loop
            )

        logger.debug("Task submitted: %s → %s", task.task_id, profile.label)
        return task.task_id

    def submit_from_text(
        self,
        text: str,
        callback: Optional[TaskCallback] = None,
        **kwargs: Any,
    ) -> str:
        """便利方法：从纯文本提交任务（自动路由）。

        Args:
            text: 用户输入文本
            callback: 任务完成回调
            **kwargs: 额外参数（is_interactive_conversation 等）

        Returns:
            任务 ID
        """
        profile = self._router.classify_text(text, **kwargs)
        messages = [{"role": "user", "content": text}]
        return self.submit(messages, profile=profile, callback=callback, **kwargs)

    def submit_to_flash(
        self,
        messages: List[Dict[str, str]],
        callback: Optional[TaskCallback] = None,
        **kwargs: Any,
    ) -> str:
        """强制路由到 Flash 队列（绕过路由判定）。

        Args:
            messages: OpenAI 格式的消息列表
            callback: 任务完成回调
            **kwargs: 额外参数

        Returns:
            任务 ID
        """
        profile = TaskProfile(
            target_model=TargetModel.FLASH,
            task_type=TaskType.CLASSIFY,
            priority=Priority.NORMAL,
            estimated_tokens=self._estimate_tokens(messages),
        )
        return self.submit(messages, profile=profile, callback=callback, **kwargs)

    def submit_to_pro(
        self,
        messages: List[Dict[str, str]],
        callback: Optional[TaskCallback] = None,
        **kwargs: Any,
    ) -> str:
        """强制路由到 Pro 队列（绕过路由判定）。

        Args:
            messages: OpenAI 格式的消息列表
            callback: 任务完成回调
            **kwargs: 额外参数

        Returns:
            任务 ID
        """
        profile = TaskProfile(
            target_model=TargetModel.PRO,
            task_type=TaskType.FREE_CHAT,
            priority=Priority.NORMAL,
            estimated_tokens=self._estimate_tokens(messages),
        )
        return self.submit(messages, profile=profile, callback=callback, **kwargs)

    # ============================================================
    # 任务查询与取消
    # ============================================================

    def get_task(self, task_id: str) -> Optional[_TaskWrapper]:
        """查询任务状态。"""
        return self._tasks.get(task_id)

    def cancel_task(self, task_id: str) -> bool:
        """取消一个待处理的任务。

        Args:
            task_id: 任务 ID

        Returns:
            True 如果成功取消，False 如果任务已执行完或不存在
        """
        task = self._tasks.get(task_id)
        if task is None or task.status in (_TaskStatus.COMPLETED, _TaskStatus.FAILED):
            return False
        if task.status == _TaskStatus.PENDING:
            task.status = _TaskStatus.CANCELLED
            task.error = "Cancelled by user"
            logger.info("Task cancelled: %s", task_id)
            return True
        return False

    def drain_callbacks(self, max_results: int = 10) -> List[TaskResult]:
        """消费回调队列（从 UI 线程调用，非阻塞）。

        这是 UI 线程获取任务结果的唯一方法。
        UI 线程应该以定时器周期调用此方法。

        Args:
            max_results: 单次最大提取数量

        Returns:
            List[TaskResult] 已完成的任务结果
        """
        results: List[TaskResult] = []
        try:
            for _ in range(max_results):
                task_id, output, error = self._callback_queue.get_nowait()
                task = self._tasks.get(task_id)
                if task:
                    results.append(TaskResult(
                        task_id=task_id,
                        output=output,
                        error=error,
                        latency_ms=task.latency_ms,
                        model_used=task.model_used,
                        token_estimate=task.token_estimate,
                        task_type=task.profile.task_type.value if task.profile else "",
                    ))
        except queue.Empty:
            pass
        return results

    # ============================================================
    # 属性
    # ============================================================

    @property
    def token_budget(self) -> TokenBudget:
        return self._token_budget

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def active_task_count(self) -> int:
        """当前正在运行或等待的任务数。"""
        return sum(
            1 for t in self._tasks.values()
            if t.status in (_TaskStatus.PENDING, _TaskStatus.RUNNING)
        )

    # ============================================================
    # 内部：事件循环
    # ============================================================

    def _run_event_loop(self) -> None:
        """在后台线程中运行的 asyncio 事件循环。"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        self._loop_ready.set()  # 通知主线程事件循环已就绪

        try:
            loop.run_forever()
        except Exception as e:
            logger.error("TaskQueue event loop crashed: %s", e)
        finally:
            try:
                loop.run_until_complete(loop.shutdown_asyncgens())
            except Exception:
                pass
            loop.close()
            self._loop = None

    # ============================================================
    # 内部：任务执行
    # ============================================================

    async def _execute(self, task: _TaskWrapper) -> None:
        """执行一个任务。在 asyncio 事件循环中调用。

        Args:
            task: 任务包装器

        执行流程:
          1. 检查 Token 预算
          2. 选择适配器（Pro 或 Flash）
          3. 执行调用并计时
          4. 记录使用量
          5. 触发回调
        """
        task.status = _TaskStatus.RUNNING
        start_time = time.time()

        try:
            # 检查 Token 预算
            if self._token_budget.is_exceeded:
                raise RuntimeError(
                    f"Token budget exceeded ({self._token_budget.total_tokens})"
                )

            # 选择适配器
            profile = task.profile
            if profile is None:
                raise RuntimeError("Task has no profile")

            is_pro = profile.is_pro()
            adapter = self._pro if is_pro else self._flash

            # 执行调用
            result = await adapter.chat(task.messages, **task.kwargs)

            # 计算延迟
            latency_ms = (time.time() - start_time) * 1000
            task.latency_ms = latency_ms
            task.result = result
            task.status = _TaskStatus.COMPLETED
            task.model_used = "pro" if is_pro else "flash"
            # 使用 hasattr 保护 _config 访问（MockLLMAdapter 无 _config）
            if is_pro:
                pro_key = getattr(self._pro, "_config", None)
                if pro_key is None or not pro_key.api_key:
                    task.model_used = "mock_pro"
            else:
                flash_key = getattr(self._flash, "_config", None)
                if flash_key is None or not flash_key.api_key:
                    task.model_used = "mock_flash"

            # 记录 Token 使用量
            input_tokens = profile.estimated_tokens
            output_tokens = len(result) // 4
            self._token_budget.record(input_tokens, output_tokens, task.model_used)

            logger.debug(
                "Task completed: %s (%.0fms, model=%s)",
                task.task_id, latency_ms, task.model_used,
            )

            # 触发回调：先放入队列（供 UI 线程 drain），再直接调用回调
            if task.callback:
                self._callback_queue.put((task.task_id, result, None))
                try:
                    task.callback(task.task_id, result, None)
                except Exception as cb_err:
                    logger.error(
                        "Task callback error for %s: %s",
                        task.task_id, cb_err,
                    )

        except Exception as e:
            task.status = _TaskStatus.FAILED
            task.error = str(e)
            task.latency_ms = (time.time() - start_time) * 1000

            logger.error(
                "Task failed: %s — %s", task.task_id, e,
                exc_info=logger.isEnabledFor(logging.DEBUG),
            )

            # 触发失败回调：先放入队列，再直接调用
            if task.callback:
                self._callback_queue.put((task.task_id, "", str(e)))
                try:
                    task.callback(task.task_id, "", str(e))
                except Exception as cb_err:
                    logger.error(
                        "Task failure callback error for %s: %s",
                        task.task_id, cb_err,
                    )

    # ============================================================
    # 工具
    # ============================================================

    @staticmethod
    def _estimate_tokens(messages: List[Dict[str, str]]) -> int:
        """统计消息中的预估 token 数。"""
        total = 0
        for msg in messages:
            total += len(msg.get("content", "")) // 4
        return total

    # ============================================================
    # 便捷工厂
    # ============================================================

    @staticmethod
    def create_default(
        flash_max_concurrent: int = 5,
        token_budget_limit: int = 0,
        auto_start: bool = True,
    ) -> "TaskQueue":
        """创建并启动默认配置的 TaskQueue。

        Args:
            flash_max_concurrent: Flash 最大并发数
            token_budget_limit: Token 预算上限
            auto_start: 是否自动启动后台线程

        Returns:
            已就绪的 TaskQueue 实例
        """
        router = LLMRouter.create_default()
        pro = ProAdapter()
        flash = FlashAdapter()

        queue = TaskQueue(
            pro_adapter=pro,
            flash_adapter=flash,
            router=router,
            flash_max_concurrent=flash_max_concurrent,
            token_budget_limit=token_budget_limit,
        )

        if auto_start:
            queue.start()

        return queue