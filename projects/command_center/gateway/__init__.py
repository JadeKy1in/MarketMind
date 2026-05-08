"""
Cline OS Command Center V2.0 — Gateway Layer (Sprint 1)

Layer 4 — 双模型调度网关。
提供 Pro (DeepSeek Pro) 和 Flash (DeepSeek Flash) 的双路异步适配器、
任务类型路由判定器、以及线程安全的并发调度队列。

设计原则:
  1. 纯异步 — 所有 I/O 操作通过 httpx.AsyncClient，不阻塞任何线程
  2. 线程安全 — TaskQueue 通过 queue.Queue + asyncio.run_coroutine_threadsafe 桥接
  3. 可测试 — 所有组件支持 Mock，无网络依赖也可运行
"""