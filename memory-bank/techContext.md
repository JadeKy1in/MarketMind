# Technical Context

## Technology Stack

| 层次 | 技术 | 版本 | 备注 |
|------|------|------|------|
| 语言 | TypeScript | 6.0.3 | `"strict": true` 编译模式 |
| 运行时 | Node.js | ≥ 18 | 无运行时外部依赖 |
| 模块系统 | CommonJS | — | `tsconfig.json` 配置 |
| 目标 | ES2022 | — | 支持 `Promise`、`async/await`、`Map/Set` 等原生特性 |
| 测试框架 | Jest + ts-jest | ^29.0.0 | devDependencies |
| 包管理 | npm | — | monorepo workspace |

### 关键依赖清单

**生产依赖**：无（`package.json` 中仅 `typescript` 为开发编译所需，非运行时依赖）

**开发依赖**：
- `@types/node` — Node.js 类型定义
- `jest` — 测试框架
- `ts-jest` — TypeScript ↔ Jest 桥接

## MCP Server 集成

适配层与两个 MCP Server 交互，通过 `McpToolRunner` 接口抽象隔离：

### Browser Automation MCP（主链路）
- **工具**：`playwright_navigate`, `playwright_screenshot`
- **用途**：获取无障碍树快照（`getSnapshot`）、页面导航（`navigate`）
- **数据格式**：`BrowserAutomationSnapshot`（详见 `src/types.ts`）

### Playwright MCP Server（降级链路）
- **工具**：`playwright_evaluate`, `playwright_screenshot`, `playwright_click`, `playwright_fill`, `playwright_press_key`
- **用途**：JS innerText 注入、截图降级、页面交互操作
- **数据格式**：`PlaywrightEvaluateResult`, `PlaywrightScreenshotResult`（详见 `src/types.ts`）

## 核心架构模式

### 1. 三轨制降级编排（Degradation Ladder）

```
extractPage(url, context)
  │
  ├─ Phase 0: navigate(url)  ← 统一导航（SNA 原则）
  │
  ├─ Phase 1: getSnapshot()  → 无障碍树快照
  │     │
  │     └─ Phase 2: getPageHtml() (optional) → 页面 HTML
  │           │
  │           └─ Phase 3: analyzeCoverage() → AccessibilityCoverageReport
  │                 │
  │                 └─ Phase 4: 路由决策
  │                       ├─ coverageRatio ≥ 0.6 → Track 1: ax_tree
  │                       ├─ coverageRatio < 0.6 → Track 2: js_innertext
  │                       └─ coverageRatio = 0   → Track 3: screenshot_visual
  │
  └─ 封装 ExtractionResult 返回
```

### 2. McpToolRunner 接口模式（Strategy Pattern）

```
BrowserAutomationAdapter  ──uses──▶  McpToolRunner (interface)
                                         │
                                    ┌─────┴─────┐
                                    │           │
                            ProductionImpl   MockImpl
                            (真实 MCP 调用)  (单元测试)
```

### 3. 场景感知上下文（Context Object Pattern）

`ExtractionContext` 携带运行时参数传递到各层，无需全局状态：

```typescript
interface ExtractionContext {
  causationId: string;            // 请求追踪 ID
  scenario: ExtractionScenario;   // 'realtime_request' | 'offline_batch_sync' | 'interactive_operation'
  timeoutMs?: number;             // 超时毫秒（场景默认值自动填充）
  allowScreenshotFallback?: boolean;
  allowScriptInjection?: boolean;
  pageUrl?: string;
}
```

## 核心约束（.clinerules §3.7 & 架构约定）

| 约束 ID | 规则 | 来源 | 代码证据位置 |
|---------|------|------|------------|
| C-1 | **SNA 单导航** — navigate 只在 `extractPage` 入口调用一次 | §3.7(a) | `adapter.ts:131-140` Phase 0 |
| C-2 | **反爬上下文验证** — 'robot' 匹配必须在 ±500 字符内有反爬上下文 | §3.7(b) | `coverage-analyzer.ts:267-289` `isRobotInAntiCrawlContext()` |
| C-3 | **SPA 未 Hydrate 检测** — nodeCount < 5 且 HTML 含 Loading → 强制 0 | §3.7(c) | `coverage-analyzer.ts:131-144` |
| C-4 | **安全超时** — 禁止 `Promise.race`，使用 `new Promise<T>` + `clearTimeout` | §3.7(d) | `adapter.ts:470-491` `withTimeout()` |
| C-5 | **零运行时依赖** — 不引入第三方库 | projectBrief | `package.json` dependencies |
| C-6 | **无状态分析** — `coverage-analyzer.ts` 函数均为纯函数 | projectBrief | `coverage-analyzer.ts:102-183` |

## 目录结构与职责

```
src/
├── adapter.ts                    # BrowserAutomationAdapter — 降级编排主类
│                                 #   - extractPage() 三轨制降级入口
│                                 #   - interact() 交互操作路由
│                                 #   - withTimeout() 安全超时包装
│                                 #   - McpToolRunner 接口定义
│
├── coverage-analyzer.ts          # AccessibilityCoverageAnalyzer — 覆盖率引擎
│                                 #   - analyzeCoverage() 核心分析函数
│                                 #   - detectAnticrawl() 反爬检测
│                                 #   - detectSpaLoading() SPA 未渲染检测
│                                 #   - isRobotInAntiCrawlContext() 上下文验证
│                                 #   - recommendStrategy() 策略推荐
│
├── types.ts                      # 域类型定义
│                                 #   - ExtractionStrategy, ExtractionScenario, ExtractionContext
│                                 #   - AccessibilityCoverageReport, ExtractionResult
│                                 #   - BrowserAutomationSnapshot, BrowserAutomationInput
│                                 #   - PlaywrightEvaluateInput/Result
│                                 #   - PlaywrightScreenshotInput/Result
│                                 #   - InteractionInput, InteractionResult
│                                 #   - createDefaultContext() 场景默认值工厂
│
├── SCENARIO_CONTEXT_MANIFEST.md  # 场景上下文清单（AGENTS.md 宪法要求）
│
├── __tests__/                    # 测试目录（待实现）
│   ├── adapter.test.ts           # 全链路测试
│   ├── coverage-analyzer.test.ts # 覆盖率引擎测试
│   └── helpers/
│       └── mockToolRunner.ts     # Mock 工厂
│
├── package.json                  # @ai-studio/browser-automation-adapter
├── tsconfig.json                  # TypeScript strict 配置
└── TEST_DESIGN_OUTLINE.md        # 测试设计大纲（本文档输出）
```

## 开发环境

### 编译验证
```bash
cd src && npx tsc --noEmit --strict
# 预期输出：零错误
```

### 测试执行（Jest 配置后）
```bash
cd src && npx jest --coverage
# 目标：branches ≥ 85%, lines ≥ 90%
```

### TypeScript 严格模式验证清单
- `strict: true` — 含 `noImplicitAny`, `strictNullChecks`, `strictFunctionTypes` 等
- `ES2022` target — 无需 `tslib` 运行时
- `CommonJS` 模块 — 与 Node.js 原生兼容

### 已知技术债务
1. `estimateDomFromHtml()` 使用正则匹配 start tags，不识别自定义元素的具体类型，仅作为粗略估算
2. 反爬签名列表需要定期维护以覆盖新兴反爬服务
3. SPA Loading 签名组目前基于常见模式，可能存在特定框架的假阴性
4. 无运行时性能基准测试（待 Inquisitor 后续审查）