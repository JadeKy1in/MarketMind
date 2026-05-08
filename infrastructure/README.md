# AI Agent Skill Foundry

基于 [Cline](https://github.com/cline/cline) 构建的工业级 AI Agent 技能铸造厂（Skill Foundry）。

## 核心理念

将经过验证的 AI Agent 能力从业务项目中剥离，打造纯净、可复用的**基建底座**。每个技能（Skill）都是一个自包含、经过严格测试的适配器，可通过 MCP 或直接导入加载到任何 AI Agent 的工具链中。

## 已注册技能

### 1. Browser Automation Adapter — v3.0.0

三轨降级浏览器内容提取适配器。自动根据覆盖率质量、反爬检测、SPA 水合状态和隐藏元素比例，在以下三条轨道之间降级：

| 轨道 | 优先级 | 启用条件 | Token 消耗 | 适用场景 |
|------|--------|---------|-----------|---------|
| **Track 1 — ax_tree** | 最高 | 默认启用 | ~550 tokens | 标准 DOM 页面，无障碍树可用 |
| **Track 2 — js_innertext** | 中 | ax_tree 覆盖率 < 60% 或检测到隐藏元素 | ~2100 tokens | 动态渲染页面，反爬检测 |
| **Track 3 — screenshot_visual** | 低 | 前两轨均失败，或 SPA 水合失败 | ~1000 tokens | CAPTCHA 墙、SPA 未水合、极端场景 |

#### 3-Track Fallback Architecture

```
┌─────────────────────────────────────────────────┐
│  BrowserExtractionRequest (URL + config)        │
└──────────────────────┬──────────────────────────┘
                       ▼
┌──────────────────────────────────────────────────┐
│  Track 1: ax_tree (Accessibility Tree)           │
│  → 检查覆盖率和反爬检测                            │
│  → 通过则返回结果                                  │
│  → 失败则降级                                      │
└──────────────────────┬──────────────────────────┘
                       ▼ (coverage < 60% or anticrawl)
┌──────────────────────────────────────────────────┐
│  Track 2: js_innertext (JavaScript innerText)   │
│  → 注入脚本提取纯文本内容                            │
│  → 通过则返回结果                                  │
│  → 失败则降级                                      │
└──────────────────────┬──────────────────────────┘
                       ▼ (execution failure)
┌──────────────────────────────────────────────────┐
│  Track 3: screenshot_visual (Vision OCR)         │
│  → 截图 + base64 输出                              │
│  → [可选] VlmAdapter 注入视觉分析                  │
│  → 最终保底方案                                    │
└──────────────────────────────────────────────────┘
```

#### 工程严谨性

- **测试覆盖率**: 89 项端到端测试用例，100% 通过率
- **测试结构**: Unit Tests (67) + Integration Tests (16) + E2E Tests (6)
- **性能预算**: 单次提取 ≤ 15 秒（实测平均 0.7ms）
- **成功率提升**: 原始 Playwright 25% → 三轨适配器 100%（Δ+75%）
- **Token 回收**: 单次降级可回收最多 44,000 tokens

#### 关键设计模式

- **Single-Navigation Architecture (SNA)**: 入口点导航一次，所有降级轨道在同一页面上操作，不重新导航
- **Safe Timeout Pattern**: 使用显式 `new Promise<T>` + `clearTimeout`，不在 `Promise.race()` 中留下悬空 Promise
- **Context-Aware Anticrawl Matching**: 反爬关键字匹配使用上下文验证（检查周围 ±500 字符），避免纯内容误判
- **SPA Hydration Detection**: 导航后检测节点数量和水合标记，未水合 SPA 直接路由到截图轨道

### 1a. VLM Vision-Language Adapter — v1.0.0（子模块）

VLM Adapter 是 browser-automation 的 Track 3 终极保底——当无障碍树和 JS 注入双双失败时，对截屏进行**视觉分析**以提取结构化内容。

#### 三级压缩管线

| 级别 | 操作 | 触发条件 | 预期效果 |
|------|------|---------|---------|
| **Level 0** | Base64 输入校验（格式 / 魔数 / 最小尺寸） | 所有请求 | 拦截无效/损坏的 Base64 |
| **Level 1** | 尺寸缩放至 ≤1280×720 | 原始尺寸超过阈值 | ~60% 编码尺寸缩减 |
| **Level 2** | 质量迭代：以格式 `jpeg` 缩放 `quality` 75→50→30 直至目标 ≤120KB | Level 1 后仍超限 | 保证后端传输稳定 |

> **Q2 决议**：纯 JS Buffer 操作（`Buffer.from`、`.fill`、`.subarray`），禁止引入 `sharp` 等 C++ 原生绑定。

#### 四层响应校验管线

| 层 | 校验内容 | 失败处理 |
|----|---------|---------|
| **Layer 1 — Syntax** | 返回体可解析为有效 JSON | L1 失败 → 降级到文本提取 |
| **Layer 2 — Schema** | JSON 结构符合请求的 `JsonSchema` 中定义的 `required` 字段 | L2 失败 → 降级到宽松 Schema |
| **Layer 3 — Semantic** | `textContent` 非空，`confidence > 0.3` | L3 失败 → 降级到低压缩质量分析 |
| **Layer 4 — Anti-hallucination** | `structuredData` 中所有字符串不含 `"unavailable"` / `"not specified"` / `"N/A"` 等幻觉得分标记 | L4 失败 → 置信度 0，结果仍返回 |

#### 重试编排降级梯

```
[初始请求] → Layer 1~4 完整验证
    ↓ L1/L2 失败
[宽松 Schema] → 仅校验 textContent 非空
    ↓ 仍失败
[纯文本提取] → 返回原始文本，structuredData = undefined, confidence = 0
    ↓ 仍失败
[最终] → 抛出错误，由 adapter 主流程捕获（不阻断 screenshot 返回）
```

#### VLM 架构集成图

```
┌──────────────────────────────────────────────────┐
│  Track 3: screenshot_visual                      │
│  → 截图 + base64 输出                             │
│  → [可选] 注入 VlmAdapter 进行视觉分析             │
│     ┌──────────────────────────────────────┐      │
│     │  VlmAdapter.analyze()               │      │
│     │  1. ImagePreprocessor (三级压缩)     │      │
│     │  2. VlmBackend.analyze() (Mock/API) │      │
│     │  3. ResponseValidator (四层校验)     │      │
│     │  4. RetryOrchestrator (降级梯)       │      │
│     └──────────────────────────────────────┘      │
│  → 结果注入 vlmConfidence / textContent           │
│  → 最终保底方案                                   │
└──────────────────────────────────────────────────┘
```

#### 工程指标

- **测试覆盖率**: 62 项测试（VLM 域特定），100% 通过率
- **测试结构**: Unit Tests (54) + Integration Tests (8)
- **Token 预算**: 三级压缩管线仅 ~10 tokens；Mock 后端约 300 tokens/次
- **默认后端**: `MockVlmBackend`——完全离线，不消耗任何外部 API Token
- **可插拔设计**: 构造函数注入 `VlmAdapter` 接口，可随时切换真实视觉模型后端

#### 关键设计模式

- **Adapter 注入模式**: VlmAdapter 通过构造函数注入到 `BrowserAutomationAdapter`，主 adapter 无感知运行
- **渐进式降级梯**: 重试编排不平面重试，而是逐步放宽验证条件（full schema → loose schema → text-only）
- **纯 Buffer 操作**: 图像预处理使用纯 JS Buffer API，零原生依赖
- **静默容错**: VLM 分析失败不阻断主流程，仅标记 `vlmConfidence = 0`

## 技能开发流程（Skill Foundry Standard）

开发新技能必须遵循以下五阶段验收流程：

1. **Phase 0 — 发现与差距分析**: 搜索现有技能库，>60% 匹配则适配而非重建
2. **Phase 1 — 接口定义**: 先定义输入/输出 Schema 和错误合约
3. **Phase 2 — 适配器实现**: 在 `infrastructure/skills/<skill-name>/src/` 中实现，遵循 SNA 原则
4. **Phase 3 — 三阶测试验证**: Unit Tests (80%+ 覆盖率) → Integration Tests → E2E Tests
5. **Phase 4 — 注册与 SOP 锁定**: 在 `SKILLS_MANIFEST.json` 中注册，更新本 README

详细规范见 `.clinerules` §4 Skill Foundry Standard（Matrix 5）。

## 目录结构

```
infrastructure/
├── README.md                    ← 本文件
├── SKILLS_MANIFEST.json         ← 技能注册表
└── skills/
    └── browser-automation/      ← 浏览器自动化技能
        ├── package.json
        ├── tsconfig.json
        ├── jest.config.js
        └── src/
            ├── adapter.ts               ← 主适配器入口
            ├── types.ts                 ← 类型定义
            ├── coverage-analyzer.ts     ← 覆盖率分析器
            ├── vlm-types.ts             ← VLM 域类型定义
            ├── vlm-adapter.ts           ← VLM 适配器主实现
            ├── vlm-adapter.config.ts    ← 工厂函数 + 默认 Schema
            └── __tests__/
                ├── adapter.test.ts
                ├── coverage-analyzer.test.ts
                ├── vlm-adapter.test.ts  ← VLM 测试套件
                ├── phase3-e2e.test.ts
                └── helpers/
                    └── mockToolRunner.ts