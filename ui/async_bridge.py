"""Bridge between asyncio (LLM calls) and CustomTkinter (GUI main thread).

Pattern: daemon-thread event loop + queue.Queue + root.after() polling.
"""
from __future__ import annotations
import asyncio
import queue
import threading
from typing import Any, Callable, Coroutine


class AsyncBridge:
    def __init__(self, tk_root):
        self._root = tk_root
        self._loop: asyncio.AbstractEventLoop | None = None
        self._queue: queue.Queue = queue.Queue()
        self._pending: dict[str, asyncio.Task] = {}
        self._callbacks: dict[str, Callable[[Any], None]] = {}
        self._lock = threading.Lock()
        self._running = False

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        ready = threading.Event()

        def _run_loop():
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            ready.set()
            self._loop.run_forever()

        t = threading.Thread(target=_run_loop, daemon=True)
        t.start()
        ready.wait(timeout=5.0)

    def submit(self, task_id: str, coro: Coroutine, callback: Callable[[Any], None]) -> None:
        with self._lock:
            self._callbacks[task_id] = callback

        async def _wrapper():
            try:
                result = await coro
                self._queue.put((task_id, "done", result, None))
            except Exception as e:
                self._queue.put((task_id, "error", None, e))

        future = asyncio.run_coroutine_threadsafe(_wrapper(), self._loop)
        with self._lock:
            self._pending[task_id] = future

    def poll(self, interval_ms: int = 100) -> None:
        try:
            while True:
                task_id, status, result, error = self._queue.get_nowait()
                with self._lock:
                    cb = self._callbacks.pop(task_id, None)
                    if task_id in self._pending:
                        del self._pending[task_id]
                if cb and status == "done":
                    cb(result)
                elif cb and status == "error":
                    cb(error)
        except queue.Empty:
            pass
        self._root.after(interval_ms, lambda: self.poll(interval_ms))

    def stop(self) -> None:
        self._running = False
        if self._loop:
            self._loop.call_soon_threadsafe(self._loop.stop)

    @property
    def pending_count(self) -> int:
        with self._lock:
            return len(self._pending)
