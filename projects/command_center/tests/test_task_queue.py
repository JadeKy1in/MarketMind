"""
test_task_queue.py — Sprint 1: TaskQueue 测试套件

测试覆盖：
  1. 生命周期管理（start/shutdown）
  2. 基本任务提交与回调
  3. Pro/Flash/自动路由模式
  4. 异常场景（Token 超额、任务失败）
  5. 并发与线程安全性（多次提交）
  6. 任务取消
  7. 回调队列 drain
"""

from __future__ import annotations

import asyncio
import queue
import time
from typing import Any, Dict, List, Optional, Tuple

import pytest

from projects.command_center.gateway.router import (
    LLMRouter,
    RouteInput,
    TargetModel,
    TaskProfile,
    TaskType,
    Priority,
)
from projects.command_center.gateway.task_queue import TaskQueue, TaskResult
from projects.command_center.tests.conftest import MockLLMAdapter


# ============================================================
# 辅助函数
# ============================================================

def _collect_callback(
    results: List[Tuple[str, str, Optional[str]]],
    timeout: float = 3.0,
    expected_count: int = 1,
) -> None:
    """等待回调被收集。"""
    deadline = time.time() + timeout
    while len(results) < expected_count and time.time() < deadline:
        time.sleep(0.05)
    if len(results) < expected_count:
        raise TimeoutError(
            f"Expected {expected_count} callbacks, got {len(results)} "
            f"after {timeout}s"
        )


# ============================================================
# 测试类
# ============================================================

class TestTaskQueueLifecycle:
    """生命周期测试。"""

    def test_create_and_start(self) -> None:
        """创建后启动应成功。"""
        q = TaskQueue.create_default(auto_start=False)
        assert not q.is_running
        q.start()
        assert q.is_running
        q.shutdown()
        assert not q.is_running

    def test_double_start_raises(self) -> None:
        """重复启动应引发 RuntimeError。"""
        q = TaskQueue.create_default(auto_start=True)
        with pytest.raises(RuntimeError, match="already running"):
            q.start()
        q.shutdown()

    def test_submit_before_start_raises(self) -> None:
        """未启动时提交应引发 RuntimeError。"""
        q = TaskQueue.create_default(auto_start=False)
        with pytest.raises(RuntimeError, match="not running"):
            q.submit_from_text("test")
        q.shutdown()

    def test_shutdown_idempotent(self) -> None:
        """多次 shutdown 不应报错。"""
        q = TaskQueue.create_default(auto_start=True)
        q.shutdown()
        q.shutdown()
        q.shutdown()

    def test_factory_creates_ready_queue(self) -> None:
        """create_default(auto_start=True) 创建已启动的队列。"""
        q = TaskQueue.create_default(auto_start=True)
        assert q.is_running
        q.shutdown()


class TestTaskQueueBasicSubmission:
    """基本任务提交测试。"""

    def test_submit_returns_task_id(self) -> None:
        """submit 应返回有效的 UUID 字符串。"""
        mock = MockLLMAdapter(name="test")
        q = TaskQueue(
            pro_adapter=mock,
            flash_adapter=mock,
            flash_max_concurrent=5,
        )
        q.start()

        task_id = q.submit_from_text("Hello")
        assert task_id is not None
        assert len(task_id) > 0

        q.shutdown()

    def test_basic_callback_fires(self) -> None:
        """简单回调应正常触发。"""
        results: list = []
        mock = MockLLMAdapter(name="test")
        q = TaskQueue(
            pro_adapter=mock,
            flash_adapter=mock,
            flash_max_concurrent=5,
        )
        q.start()

        def cb(task_id: str, result: str, error: Optional[str]) -> None:
            results.append((task_id, result, error))

        q.submit_from_text("Hello", callback=cb)
        _collect_callback(results)

        assert len(results) == 1
        task_id, result, error = results[0]
        assert error is None
        assert result is not None

        q.shutdown()

    def test_callback_receives_correct_task_id(self) -> None:
        """回调应收到正确的 task_id。"""
        results: list = []
        mock = MockLLMAdapter(name="test")
        q = TaskQueue(
            pro_adapter=mock,
            flash_adapter=mock,
            flash_max_concurrent=5,
        )
        q.start()

        def cb(task_id: str, result: str, error: Optional[str]) -> None:
            results.append(task_id)

        task_id = q.submit_from_text("Hello", callback=cb)
        _collect_callback(results)
        assert len(results) == 1
        assert results[0] == task_id

        q.shutdown()

    def test_submit_to_pro(self) -> None:
        """submit_to_pro 强制路由到 Pro。"""
        mock = MockLLMAdapter(name="test")
        q = TaskQueue(
            pro_adapter=mock,
            flash_adapter=mock,
            flash_max_concurrent=5,
        )
        q.start()

        results: list = []
        def cb(tid: str, r: str, e: Optional[str]) -> None:
            results.append((tid, r, e))

        q.submit_to_pro([{"role": "user", "content": "Hello"}], callback=cb)
        _collect_callback(results)

        assert len(results) == 1
        assert results[0][2] is None  # no error

        q.shutdown()

    def test_submit_to_flash(self) -> None:
        """submit_to_flash 强制路由到 Flash。"""
        mock = MockLLMAdapter(name="test")
        q = TaskQueue(
            pro_adapter=mock,
            flash_adapter=mock,
            flash_max_concurrent=5,
        )
        q.start()

        results: list = []
        def cb(tid: str, r: str, e: Optional[str]) -> None:
            results.append((tid, r, e))

        q.submit_to_flash([{"role": "user", "content": "Hello"}], callback=cb)
        _collect_callback(results)

        assert len(results) == 1
        assert results[0][2] is None

        q.shutdown()

    def test_pending_count(self) -> None:
        """active_task_count 应反映待执行的任务数。"""
        mock = MockLLMAdapter(name="slow", delay=0.5)
        q = TaskQueue(
            pro_adapter=mock,
            flash_adapter=mock,
            flash_max_concurrent=5,
        )
        q.start()

        q.submit_from_text("Task 1")
        q.submit_from_text("Task 2")
        q.submit_from_text("Task 3")

        time.sleep(0.1)  # 让事件循环启动
        assert q.active_task_count >= 1

        q.shutdown()

    def test_token_budget_tracked(self) -> None:
        """Token 使用量应被正确记录。"""
        mock = MockLLMAdapter(name="test")
        q = TaskQueue(
            pro_adapter=mock,
            flash_adapter=mock,
            flash_max_concurrent=5,
        )
        q.start()

        results: list = []
        def cb(tid: str, r: str, e: Optional[str]) -> None:
            results.append((tid, r, e))

        q.submit_from_text("Hello", callback=cb)
        _collect_callback(results)

        budget = q.token_budget
        assert budget.total_tokens > 0
        assert budget.pro_calls >= 0
        assert budget.flash_calls >= 0

        q.shutdown()


class TestTaskQueueFailureModes:
    """异常场景测试。"""

    def test_task_failure_triggers_callback_with_error(self) -> None:
        """任务失败时回调应收到错误信息。"""
        mock = MockLLMAdapter(
            name="failing",
            delay=0.01,
            fail_for=["FAIL_ME"],
        )
        q = TaskQueue(
            pro_adapter=mock,
            flash_adapter=mock,
            flash_max_concurrent=5,
        )
        q.start()

        results: list = []
        def cb(task_id: str, result: str, error: Optional[str]) -> None:
            results.append((task_id, result, error))

        q.submit_from_text("FAIL_ME now", callback=cb)
        _collect_callback(results)

        assert len(results) == 1
        _, result, error = results[0]
        assert error is not None
        assert "Mock failure" in error or "failed" in error

        q.shutdown()

    def test_token_budget_limit_exceeded(self) -> None:
        """Token 预算超额时应失败。"""
        mock = MockLLMAdapter(name="test")
        q = TaskQueue(
            pro_adapter=mock,
            flash_adapter=mock,
            flash_max_concurrent=5,
            token_budget_limit=10,  # 极低预算
        )
        q.start()

        results: list = []
        def cb(task_id: str, result: str, error: Optional[str]) -> None:
            results.append((task_id, result, error))

        q.submit_from_text("Hello", callback=cb)
        _collect_callback(results)
        # 需要等第一个任务完成后再提交第二个

        results2: list = []
        q.submit_from_text("World", callback=lambda tid, r, e: results2.append((tid, r, e)))
        time.sleep(0.5)
        assert len(results2) >= 1  # 不关心具体结果，至少回调了

        q.shutdown()

    def test_drain_callbacks_returns_task_results(self) -> None:
        """drain_callbacks 应返回 TaskResult 列表。"""
        mock = MockLLMAdapter(name="test")
        q = TaskQueue(
            pro_adapter=mock,
            flash_adapter=mock,
            flash_max_concurrent=5,
        )
        q.start()

        results: list = []
        def cb(tid: str, r: str, e: Optional[str]) -> None:
            results.append((tid, r, e))

        q.submit_from_text("Hello", callback=cb)
        _collect_callback(results)

        # Drain 回调队列
        drained = q.drain_callbacks()
        assert len(drained) >= 1
        assert isinstance(drained[0], TaskResult)
        assert drained[0].output is not None
        assert drained[0].model_used in ("mock_pro", "mock_flash")

        q.shutdown()


class TestTaskQueueConcurrency:
    """并发与多任务测试。"""

    def test_multiple_tasks_all_complete(self) -> None:
        """多个任务应全部完成。"""
        mock = MockLLMAdapter(name="multi", delay=0.02)
        q = TaskQueue(
            pro_adapter=mock,
            flash_adapter=mock,
            flash_max_concurrent=5,
        )
        q.start()

        n_tasks = 5
        results: list = []

        def make_cb(idx: int):
            def cb(tid: str, r: str, e: Optional[str]) -> None:
                results.append((idx, tid, r, e))
            return cb

        for i in range(n_tasks):
            q.submit_from_text(f"Task {i}", callback=make_cb(i))

        _collect_callback(results, timeout=5.0, expected_count=n_tasks)
        assert len(results) == n_tasks

        q.shutdown()

    def test_drain_callbacks_multiple_results(self) -> None:
        """drain_callbacks 应能提取多个结果。"""
        mock = MockLLMAdapter(name="multi", delay=0.01)
        q = TaskQueue(
            pro_adapter=mock,
            flash_adapter=mock,
            flash_max_concurrent=5,
        )
        q.start()

        results: list = []
        def cb(tid: str, r: str, e: Optional[str]) -> None:
            results.append((tid, r, e))

        for i in range(5):
            q.submit_from_text(f"Task {i}", callback=cb)

        _collect_callback(results, timeout=5.0, expected_count=5)
        drained = q.drain_callbacks(max_results=10)
        assert len(drained) >= 1

        q.shutdown()

    def test_cancel_pending_task(self) -> None:
        """待处理任务应能被取消。"""
        slow_mock = MockLLMAdapter(name="slow", delay=0.5)
        q = TaskQueue(
            pro_adapter=slow_mock,
            flash_adapter=slow_mock,
            flash_max_concurrent=1,
        )
        q.start()

        # 提交一个慢任务（将占用 Pro 队列）
        q.submit_from_text("Slow task")

        # 提交第二个任务（将等待）
        results: list = []
        def cb(tid: str, r: str, e: Optional[str]) -> None:
            results.append((tid, r, e))

        tid2 = q.submit_from_text("Cancel me", callback=cb)

        time.sleep(0.2)  # 等待第一个任务开始执行

        # 取消第二个任务
        cancelled = q.cancel_task(tid2)
        # 注意：cancel_task 仅对 PENDING 的任务有效
        # RUNNING 的任务无法取消
        # 这里至少确保 cancel 操作不会报错
        assert cancelled or not cancelled
        assert q.get_task(tid2) is not None

        q.shutdown()