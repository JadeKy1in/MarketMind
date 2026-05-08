# ⚙️ Cline OS Command Center V2.0

> **本地量化终端 · 双模型网关 · Monte Carlo 影子对比引擎**

Command Center V2.0 是 [SkillFoundry](https://github.com/JadeKy1in/SkillFoundry) 生态的核心交互中枢——一个运行在本地的、具有多模态认知能力的量化辅助终端。它通过双模型网关（Pro + Flash）实现智能路由，配合多源情报矩阵和 Monte Carlo 模拟引擎，为量化决策提供全链条支持。

---

## ✨ 核心能力

| 模块 | 能力 |
|---|---|
| **🧠 双模型网关** | Pro 串行推理 + Flash 高并发，智能 LLMRouter 按任务类型自动路由 |
| **📊 Monte Carlo 影子对比** | 10,000 条随机路径模拟，对比"当前仓位" vs "调仓建议"的收益分布 |
| **📡 多源情报矩阵** | 三级摄入管线（Scraper → FactChecker → BeliefModifier） |
| **🔧 发布-订阅设置中心** | 单例 + Pub-Sub 热更新，API Key XOR 混淆存储 |
| **💰 Token 预算追踪** | 跨模型调用成本实时监控与预算熔断 |
| **🖥️ CustomTkinter UI** | 现代暗色界面，Dashboard + Chat + 影子对比面板 |

---

## 🏗️ 架构总览

```
┌─────────────────────────────────────────────────────────────┐
│                        UI Layer                              │
│  ┌──────────┐  ┌──────────────┐  ┌──────────────────────┐   │
│  │Dashboard  │  │  Chat Panel  │  │  Shadow Comparison   │   │
│  │Panel      │  │              │  │  Panel               │   │
│  └─────┬─────┘  └──────┬──────┘  └──────────┬───────────┘   │
│        │               │                    │                │
│        └───────────────┼────────────────────┘                │
│                        │                                     │
│              ┌─────────▼──────────┐                           │
│              │  SettingsManager   │                           │
│              │  (Singleton+PubSub)│                           │
│              └─────────┬──────────┘                           │
├────────────────────────┼─────────────────────────────────────┤
│                    Gateway Layer                              │
│              ┌─────────▼──────────┐                           │
│              │     TaskQueue      │                           │
│              │  (thread-safe)     │                           │
│              │  asyncio event loop│                           │
│              └────┬──────────┬────┘                           │
│                   │          │                                │
│          ┌────────▼──┐   ┌──▼────────┐                       │
│          │ ProAdapter │   │FlashAdapter│                      │
│          │ (serial)   │   │(concurrent)│                      │
│          └────────┬───┘   └───┬───────┘                       │
│                   │          │                                │
│          ┌────────▼──────────▼───────┐                        │
│          │       LLMRouter            │                       │
│          │  Priority-based routing    │                       │
│          └────────────────────────────┘                       │
├──────────────────────────────────────────────────────────────┤
│                    Intelligence Layer                          │
│  ┌────────────────────────────────────────────────────────┐   │
│  │  IntakePipeline                                         │   │
│  │  ┌─────────┐   ┌────────────┐   ┌─────────────────┐    │   │
│  │  │ Scraper │──▶│FactChecker │──▶│ BeliefModifier  │    │   │
│  │  └─────────┘   └────────────┘   └─────────────────┘    │   │
│  └────────────────────────────────────────────────────────┘   │
│                                                               │
│                    Engine Layer                                │
│  ┌─────────────────────────────────────────────────────────┐  │
│  │ ShadowComparator (Monte Carlo × 10,000)                  │  │
│  │   current_weights ─▶ GBM simulation ─▶ Distribution_A   │  │
│  │   suggested_weights─▶ GBM simulation ─▶ Distribution_B  │  │
│  │   compare(mean, VaR, Sharpe, win_rate)                  │  │
│  └─────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────┘
```

### 数据流

```
User Input
    │
    ▼
LLMRouter.classify_text() ──▶ TaskType (FREE_CHAT / ANALYZE / CLASSIFY / ...)
    │
    ├── TargetModel.PRO   ──▶ serial queue ──▶ ProAdapter.chat()
    └── TargetModel.FLASH ──▶ concurrent pool ──▶ FlashAdapter.chat()
                                │
                                ▼
                        callback(task_id, result, error)
                                │
                                ▼
                        UI thread callback
```

---

## 🚀 一键运行

### 前置条件

- Python 3.10+
- 一个 DeepSeek API Key（可选，无 Key 时自动降级为 Mock 模式）

### 快速启动（Windows）

```batch
launch_command_center.bat
```

该启动脚本会自动：
1. 检测 Python 环境
2. 创建虚拟环境（venv）
3. 安装依赖（httpx, customtkinter, pytest）
4. 读取 `.env` 中的 `DEEPSEEK_API_KEY`
5. 启动 Tkinter 用户界面

### 手动配置

在 `projects/command_center/` 下创建 `.env` 文件：

```ini
DEEPSEEK_API_KEY=sk-your-key-here
```

如果不设置 API Key，系统会自动进入 **Mock 模式**，所有模型调用返回模拟数据——适合快速体验 UI 和流程。

### Linux / macOS

```bash
cd projects/command_center
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pip install python-dotenv pdfplumber
python -m projects.command_center.app
```

---

## 🧩 项目结构

```
projects/command_center/
├── app.py                        # 应用入口点
├── requirements.txt              # 最小依赖集
├── config/
│   ├── defaults.py               # 默认设置字典
│   └── settings_manager.py       # 单例 SettingsManager (Pub-Sub)
├── gateway/
│   ├── router.py                 # LLMRouter — 智能任务路由
│   ├── task_queue.py             # TaskQueue — 线程安全调度队列
│   ├── pro_adapter.py            # ProAdapter — 串行推理适配器
│   └── flash_adapter.py          # FlashAdapter — 高并发适配器
├── intelligence/
│   ├── scraper.py                # 多源情报抓取
│   ├── fact_checker.py           # 事实核查引擎
│   ├── belief_modifier.py        # 信念修改建议
│   ├── intake_pipeline.py        # 三级摄入管线编排
│   └── ocr_reader.py             # OCR 图像文本提取
├── engine/
│   ├── shadow_comparator.py      # Monte Carlo 影子对比
│   ├── optimizer.py              # 组合优化器
│   ├── reporter.py               # 报告生成器
│   └── semantic_translator.py    # 语义翻译器
├── ui/
│   ├── main_window.py            # 主窗口
│   ├── dashboard_panel.py        # 仪表盘面板
│   ├── chat_panel.py             # 对话面板
│   ├── shadow_comparison_panel.py# 影子对比面板
│   ├── intake_bar.py             # 情报摄入栏
│   ├── report_viewer.py          # 报告查看器
│   └── settings_modal.py         # 设置模态框
├── models/
│   ├── position.py               # 仓位数据模型
│   └── __init__.py
├── tests/
│   ├── test_task_queue.py        # TaskQueue 单元测试
│   ├── test_router.py            # 路由测试
│   ├── test_engine.py            # 引擎测试
│   ├── test_intelligence.py      # 情报管线测试
│   ├── test_settings_manager.py  # 设置测试
│   └── test_integration.py       # 集成测试
└── .gitignore
```

---

## 🧪 测试

```bash
cd projects/command_center
python -m pytest tests/ -v --tb=short
```

测试覆盖：
- TaskQueue 三队列模式 + 异常场景
- LLMRouter 优先级路由判定
- Monte Carlo 模拟统计正确性
- IntakePipeline 三级管线编排
- SettingsManager 单例 + Pub-Sub
- 端到端集成测试

---

## 📐 设计原则

| 原则 | 实现 |
|---|---|
| **UI 线程永不阻塞** | TaskQueue 后台 asyncio 事件循环 + 回调桥接 |
| **线程安全** | queue.Queue + asyncio.run_coroutine_threadsafe |
| **优雅降级** | 无 API Key → Mock 模式；IntakePipeline 级间降级 |
| **Safe Timeout** | 显式 `Promise<T>` 模式，`clearTimeout` 在 resolve/reject 双路调用 |
| **Token 预算熔断** | 超限后拒绝新任务，防止 API 成本失控 |
| **混淆存储** | API Key XOR + base64 防意外暴露 |

---

## 🔗 相关项目

- [SkillFoundry](https://github.com/JadeKy1in/SkillFoundry) — AI Agent 架构 + VLM 适配器主仓库
- Robinhood — 信念驱动的量化交易系统

---

## 📄 License

MIT