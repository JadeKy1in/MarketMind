<h1 align="center">🧠 SkillFoundry</h1>
<p align="center">
  <em>AI Agent 架构 · VLM 适配器 · 信念驱动的量化决策系统</em>
</p>

<p align="center">
  <a href="#-vision"><b>愿景</b></a> •
  <a href="#-ecosystem-overview"><b>生态总览</b></a> •
  <a href="#-sub-projects"><b>子项目</b></a> •
  <a href="#-architecture"><b>架构</b></a> •
  <a href="#-getting-started"><b>快速开始</b></a> •
  <a href="#-license"><b>License</b></a>
</p>

---

## 🧿 Vision

**SkillFoundry** 是一个开放的 AI Agent 基础设施熔炉——旨在探索和验证下一代自主智能体的关键架构模式：

- **双模型认知架构**：Pro 模型（深度推理）+ Flash 模型（高吞吐响应），通过智能路由器按任务特性分发
- **信念驱动决策**：将外部情报摄入→事实核查→信念状态修改链接为闭环，实现"可证伪"的量化决策
- **Monte Carlo 影子对比**：在当前策略和候选策略之间执行全路径随机模拟，以统计显著性衡量决策质量
- **多模态感知**：通过 OCR、网页抓取、多源 API 矩阵实现跨模态情报融合
- **自省式风险管理**：Token 预算熔断、Safe Timeout 模式、优雅降级策略嵌在每一层

SkillFoundry 不是单一产品，而是一系列**可独立部署、可热插拔的子项目**的集合——每个子项目都是一个完整的技术验证原型，遵循严格的 Skill Foundry Standard（§4）开发流程。

---

## 🌐 Ecosystem Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        SkillFoundry Meta                         │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │   .clinerules — SPARC 认知循环 + PM 治理 + 自我进化矩阵  │   │
│  │   memory-bank/ — The Archivist 持久化状态机               │   │
│  │   infrastructure/ — MCP 技能工厂 & SKILLS_MANIFEST.json  │   │
│  │   docs/ — Cline OS Blueprint & 架构白皮书                │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                  │
│  ┌─────────────────────────────┐  ┌──────────────────────────┐  │
│  │  ⚙️ Command Center V2.0    │  │  📈 Robinhood             │  │
│  │  本地量化终端              │  │  信念驱动量化交易系统    │  │
│  │  · 双模型网关 (Pro+Flash)  │  │  · Belief State Manager   │  │
│  │  · Monte Carlo 影子对比    │  │  · Reflection Orchestrator│  │
│  │  · 多源情报摄入管线        │  │  · 多因子风险模型        │  │
│  │  · CustomTkinter UI        │  │  · 实时 Patrol 调度器    │  │
│  └─────────────────────────────┘  └──────────────────────────┘  │
│                                                                  │
│  ┌─────────────────────────────┐                                │
│  │  🛠️ MCP Servers            │                                │
│  │  · Filesystem Server        │                                │
│  │  · Memory Knowledge Graph   │                                │
│  │  · Playwright Automation    │                                │
│  │  · (更多在 infrastructure/) │                                │
│  └─────────────────────────────┘                                │
└─────────────────────────────────────────────────────────────────┘
```

---

## 🔥 Sub-Projects

### ⚙️ [Command Center V2.0](projects/command_center/)

> **本地量化终端 · 双模型网关 · Monte Carlo 影子对比引擎**

Command Center 是 SkillFoundry 生态的核心交互中枢——一个运行在本地的、具有多模态认知能力的量化辅助终端。它是整个生态系统的"用户面对层"。

**关键亮点**：
| 特性 | 详情 |
|---|---|
| 🧠 双模型网关 | Pro 串行推理 + Flash 高并发，LLMRouter 按任务类型自动路由 |
| 📊 Monte Carlo 影子对比 | 10,000 条 GBM 路径模拟，比较"当前仓位" vs "调仓建议" |
| 📡 多源情报矩阵 | Scraper → FactChecker → BeliefModifier 三级摄入管线 |
| 🔧 发布-订阅设置 | Singleton + Pub-Sub 热更新，API Key XOR 混淆存储 |
| 💰 Token 预算追踪 | 跨模型成本监控与预算熔断机制 |
| 🖥️ CustomTkinter UI | 现代暗色界面，Dashboard + Chat + 影子对比面板 |

[▶ 进入 Command Center →](projects/command_center/README.md)

---

### 📈 Robinhood *(信念驱动量化交易系统)*

> **信念状态机 · 影子预测器 · 多因子风险引擎**

Robinhood 是 SkillFoundry 生态中信念驱动决策的理论验证原型，实现了从情报摄入到仓位调整建议的完整决策闭环。

---

### 🛠️ MCP Servers *(工具适配器工厂)*

位于 `infrastructure/skills/` 中的 MCP 服务器实现，通过 MCP 协议与外部环境交互：
- **Filesystem Server** — 安全的文件系统操作接口
- **Memory Server** — 知识图谱持久化与检索
- **Playwright Server** — 浏览器自动化与网页交互

所有服务器遵循 §3.7 浏览器自动化设计规范和 §6 DeepSeek 交互优化协议。

---

## 🏛️ Architecture

SkillFoundry 的核心架构遵循 **SPARC 认知循环**（Specification → Pseudocode → Architecture → Refinement → Completion）和 **四层分层原则**：

```
Layer 0: 感知层 (Perception)
  └── Scraper / OCR / API Matrix / Playwright

Layer 1: 认知层 (Cognition)
  └── FactChecker / BeliefModifier / LLMRouter / TaskQueue

Layer 2: 决策层 (Decision)
  └── ShadowComparator / Optimizer / BeliefStateManager

Layer 3: 交互层 (Interaction)
  └── CustomTkinter UI / Report Viewer / Settings Modal
```

每个子项目都实现了这个分层的子集，但共享同一套基础设施契约：
- `infrastructure/SKILLS_MANIFEST.json` — 技能注册中心
- `memory-bank/` — The Archivist 持久化状态机
- `.clinerules` — 认知矩阵与自我进化指令

---

## 🚀 Getting Started

### 克隆仓库

```bash
git clone https://github.com/JadeKy1in/SkillFoundry.git
cd SkillFoundry
```

### 启动 Command Center（Windows）

```batch
launch_command_center.bat
```

系统会自动：
1. 检测 Python 3.10+
2. 创建虚拟环境并安装依赖
3. 读取 `.env` 中的 `DEEPSEEK_API_KEY`（可选）
4. 启动图形界面

详细文档：[Command Center README →](projects/command_center/README.md)

### 运行测试

```bash
# Command Center 测试
cd projects/command_center && python -m pytest tests/ -v --tb=short

# Robinhood 测试
cd projects/robinhood && python -m pytest tests/ -v --tb=short
```

---

## 📂 Repository Structure

```
SkillFoundry/
├── .clinerules                      # 认知矩阵 (Matrix 1-8)
├── README.md                        # ← 你在这里
├── LICENSE
├── launch_command_center.bat        # 一键启动器
├── memory-bank/                     # The Archivist 持久化状态机
│   ├── activeContext.md
│   ├── progress.md
│   ├── decision_log.md
│   ├── transcript_ledger.md
│   └── projectBrief.md
├── infrastructure/                  # MCP 技能工厂
│   ├── SKILLS_MANIFEST.json         # 技能注册中心
│   ├── skills/                      # MCP 服务器实现
│   └── README.md
├── projects/
│   ├── command_center/               # 核心子项目：本地量化终端
│   └── robinhood/                    # 子项目：信念驱动量化交易
├── docs/                            # 架构白皮书
│   └── cline_os_blueprint_v1.0.md
└── scripts/                         # 实用工具脚本
```

---

## 📐 Design Principles

| 原则 | 说明 |
|---|---|
| **DRY First** | 严禁重复。基础设施层和 Memory Bank 是所有子项目的唯一真实来源 |
| **The Archivist** | 每个 Session 必须更新 activeContext.md 和 progress.md 才能声明完成 |
| **Safe Timeout** | 显式 `Promise<T>` 模式，`clearTimeout` 在 resolve/reject 双路调用 |
| **Token Budget Tripwire** | 1M Token 窗口内不同水位的分级响应策略 |
| **PM Governance** | 跨文件修改前必须执行 Step 0 侦察-对抗-移交四步 SOP |
| **Skill Foundry Standard** | 新技能开发需经过 Discovery → Interface → Adapter → Test → Register 五阶段 |

---

## 📄 License

MIT License — 详见 [LICENSE](LICENSE)

---

<p align="center">
  Built with ❤️ by <a href="https://github.com/JadeKy1in">JadeKy1in</a> & the SkillFoundry Team
</p>