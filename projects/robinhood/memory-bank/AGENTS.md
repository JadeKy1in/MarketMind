# AGENTS.md - 多智能体对齐手册

## 项目标识

- 项目名称: Signal Foundry (智能量化投资分析系统)
- 项目根目录: `projects/robinhood/`
- 创建日期: 2026-05-04

## 并发角色定义

本系统中最多可存在以下并发角色，各角色必须严格遵守其职责边界:

| 角色 | 职责 | 写入权限 |
|---|---|---|
| **The Architect (架构师)** | 设计系统架构、定义接口契约、审批准入条件 | `systemArchitecture.md` |
| **The Act Model (执行者)** | 数据采集、指标计算、脚本执行 | `activeContext.md`, `progress.md`, `transcript_ledger.md` |
| **The Pro Model (决策者)** | 高阶逻辑推演、最终交易信号生成 | 不直接写 Memory Bank, 通过结构化 JSON 报告输出 |
| **The Archivist (档案员)** | Token 预算熔断、上下文提纯、记忆归档 | `activeContext.md` (提纯), `transcript_ledger.md` |
| **The PM (产品经理)** | 最终批准权、铁律一拦截预研、外部决策注入 | `decision_log.md` |
| **The Challenger (红方)** | 架构对抗、压力测试、安全审计 | `roi_evaluation.md` (临时) |

## Lock 协议

1. **文件写锁**：在同一时间，只有一个 AI Agent 可以写入一个具体的 Memory Bank 文件。写操作前必须检查文件头部的 `Last-Modified-By` 标记（采用注释形式）。
2. **任务隔离**：使用明确的文件路径隔离不同 Agent 的工作产物，禁止跨 Agent 修改对方的 `src/` 代码文件。
3. **新 Agent 入场**：新 Agent 必须首先读取本文件及 `memory-bank/` 下全部 6 个核心文件 + 3 个治理文件，然后读取 `decision_log.md` 确认最新决策状态，方可开始工作。

## 通信规范

- 角色间通信通过 `activeContext.md` 中的"当前阻滞（Blockers）"段落实名留言。
- 所有 Agent 在 `transcript_ledger.md` 中记录自己的运行轨迹。
- 任何 Agent 发现 `decision_log.md` 中的决策与本 Session 目标冲突时，必须立即挂起并发起 CRP。