# Product Context

## Why This Project Exists

Browser Automation MCP Server 和 Playwright MCP Server 是两个互补的浏览器自动化工具，各自擅长不同的内容获取路径：

| 工具 | 优势 | 劣势 |
|------|------|------|
| Browser Automation MCP | 无障碍树（ax_tree）轻量高效，结构化语义数据，延迟低（~1-2s） | SPA 未 Hydrate/反爬页面覆盖率可能降至 0% |
| Playwright MCP | JS evaluate 获取完整 page content，截图兜底 | evaluate 消耗更大（~3-5s），截图需要 VLM 后处理成本高 |

没有任何一个单一策略能覆盖所有网页场景。**核心问题**：没有统一的智能编排层来根据页面特征自动选择最优提取路径，导致 `use_mcp_tool` 调用方需要手动判断页面类型并选择工具，付出了大量无效的试错延迟。

## Problems It Solves

### 1. 单点故障 — 覆盖率不足时的数据空洞

**场景**：AI Agent 导航到一个 SPA 应用页面，无障碍树仅包含 `<div>Loading...</div>` 一个节点。如果开发者只依赖 ax_tree，将返回一个无意义的结果。

**本项目的解决方案**：覆盖率分析引擎实时计算 `coverageRatio`。当 nodeCount < MIN_TRUSTED_NODES 且检测到 Loading 占位符时，强制 `coverageRatio = 0`，触发全量降级到 screenshot_visual — 而不是返回空数据。

### 2. 延迟浪费 — 无谓的重复导航

**场景**：现有实现中，当 ax_tree 覆盖率不足时，降级链路各自独立触发 navigate 到同一 URL，一个页面提取流程可能触发 3 次 navigate，2 次完全浪费（占全链 38% 延迟 ≈ 4,000ms）。

**本项目的解决方案**：Single-Navigation Architecture（SNA），所有降级链路共享同一页面实例，降级时不重新 navigate，仅在当前页执行 evaluate/screenshot。

### 3. 反爬检测 — 返回误导性数据

**场景**：目标页面被 Cloudflare 保护，返回空壳页面。ax_tree 可能报告 0% 覆盖率，但如果没有反爬检测，系统会误判为 "正常页面但无内容" 而非 "被反爬拦截"。

**本项目的解决方案**：启发式反爬签名检测（涵盖 Cloudflare Turnstile、reCAPTCHA v3、DataDome、Kasada 等现代方案 + 上下文验证的 `robot` 关键词），触发后直接路由到 screenshot_visual，避免向错误方向浪费时间。

### 4. 场景需求差异 — 一刀切的超时策略

**场景**：
- 实时用户请求：5s 内必须给出结果，允许失败但不允许长时间等待
- 离线批量同步：可容忍 30s 等待，但需要尽量完整的数据
- 交互操作：需要在页面稳定（约 10s）后执行精确的 DOM 操作

**本项目的解决方案**：场景上下文（`ExtractionContext` + `ExtractionScenario`）驱动超时阈值和降级许可的动态调整。

## How It Should Work — 用户体验

### 调用方视角

```typescript
import { BrowserAutomationAdapter, createDefaultContext } from './adapter';
import { McpToolRunnerImpl } from './mcp-runner-impl';

// 工厂方法由外部注入 MCP runner 实现
const adapter = new BrowserAutomationAdapter(new McpToolRunnerImpl());

// 实时请求：5s 超时，不允许截图降级
const result = await adapter.extractPage(
  'https://example.com',
  createDefaultContext('realtime_request'),
);

// 返回统一 ExtractionResult，调用方根据 strategyUsed 决定是否值得使用
console.log(result.strategyUsed); // 'ax_tree' | 'js_innertext' | 'screenshot_visual' | 'failed'
console.log(result.textContent);   // 提取的纯文本（Track 1 & 2）
console.log(result.structuredData);// 结构化数据（Track 1）
console.log(result.screenshotBase64); // Base64 截图（Track 3，可送 VLM 管道）
```

### 交互操作视角

```typescript
const results = await adapter.interact(
  'https://example.com/login',
  [
    { type: 'fill', selector: '#username', value: 'admin' },
    { type: 'fill', selector: '#password', value: 'secret' },
    { type: 'click', selector: '#login-button', delayBeforeMs: 300 },
  ],
  { causationId: 'login-flow', timeoutMs: 10_000 },
);
// results 数组包含每个操作的执行结果和潜在错误
```

### 核心体验原则

1. **零配置**：调用方无需关心页面类型——适配层自动判断并选择最优路径。
2. **可预测的失败**：所有失败路径返回结构化错误信息而非抛出未处理的异常。
3. **延迟透明**：`ExtractionResult.durationMs` 让调用方了解每次提取的实际耗时。
4. **渐进增强**：不出图 → 尝试 JS 注入 → 仍有缺口 → 截图兜底，每次"降级"都在上一次的基础上补充而非丢弃。

## User Experience Goals

| 角色 | 目标 | 衡量标准 |
|------|------|---------|
| AI Agent 开发者 | 无需了解浏览器底层实现即可可靠获取网页内容 | 一次 `extractPage()` 调用覆盖所有场景 |
| 平台运维者 | 清晰的错误链路和可观测性 | 结构化错误信息 + coverageReport |
| 最终用户 | 页面信息被完整、及时地获取 | 综合覆盖率 ≥ 95%，全链 ≤ 15s |
| MCP 贡献者 | 可 mock 的接口便于测试和替换实现 | McpToolRunner 接口 100% 可 mock |