# Test Design Outline — Mock McpToolRunner 单元测试

> **关联任务**：MRP 报告指定的遗留任务 —— 集成测试套件设计  
> **版本**：v1.0  
> **日期**：2026-05-03  
> **受测系统**：`src/adapter.ts`（BrowserAutomationAdapter）+ `src/coverage-analyzer.ts`（CoverageAnalyzer）  
> **框架**：Jest + ts-jest（见 `src/package.json`）

---

## 1. 测试架构总览

```
src/
├── adapter.ts              # 主测单元
├── coverage-analyzer.ts    # 辅助测单元（覆盖率分析引擎）
├── types.ts                # 类型引用
├── __tests__/
│   ├── adapter.test.ts     # adapter 全链路测试
│   ├── coverage-analyzer.test.ts  # 覆盖率分析引擎单元测试
│   └── helpers/
│       └── mockToolRunner.ts      # Mock McpToolRunner 工厂
```

### 1.1 Mock McpToolRunner 设计

```typescript
// mockToolRunner.ts — 核心 Mock 工厂

interface MockToolRunnerConfig {
  /** navigate: 是否成功（默认 true） */
  navigateSuccess?: boolean;
  navigateError?: string;

  /** getSnapshot: 返回的无障碍树快照 */
  snapshot?: BrowserAutomationSnapshot;
  snapshotError?: string;

  /** getPageHtml: 返回的原始 HTML */
  pageHtml?: string;
  pageHtmlError?: string;

  /** evaluate: JS 注入结果 */
  evaluateResult?: PlaywrightEvaluateResult;
  evaluateError?: string;

  /** screenshot: 截图结果 */
  screenshotResult?: PlaywrightScreenshotResult;
  screenshotError?: string;

  /** 延迟模拟（ms） */
  delayMs?: number;

  /** 调用追踪（验证 navigate 调用次数等） */
  trackCalls?: boolean;
}

// 返回 McpToolRunner 实现 + 调用追踪记录
function createMockRunner(config: MockToolRunnerConfig): {
  runner: McpToolRunner;
  calls: {
    navigate: string[];
    getSnapshot: BrowserAutomationInput[];
    getPageHtml: string[];
    evaluate: PlaywrightEvaluateInput[];
    screenshot: PlaywrightScreenshotInput[];
  };
}
```

**设计要点**：
- 每个方法返回 `Promise`，可配置成功/失败/延迟
- `trackCalls` 启用时记录每次调用的参数，用于断言调用次数
- 默认 `navigate` 成功，`getSnapshot` 返回含 2-3 个节点的标准无障碍树

---

## 2. CoverageAnalyzer 单元测试（覆盖 C2 层）

### 2.1 覆盖率计算核心路径

| ID | Test Case | 输入条件 | 期望输出 |
|----|-----------|---------|---------|
| CA-01 | 覆盖率 ≥ 60% — 标准页面 | snapshot 含 60 个 a11y 节点, html 含 80 个 DOM 元素 | `coverageRatio ≥ 0.6`, `recommendedStrategy = 'ax_tree'` |
| CA-02 | 覆盖率 ≥ 60% — 边界值 | snapshot 含 60 个 a11y 节点, html 含 100 个 DOM 元素（正好 60%） | `coverageRatio = 0.6`, `recommendedStrategy = 'ax_tree'` |
| CA-03 | 覆盖率 < 60% — 触发降级 | snapshot 含 40 个 a11y 节点, html 含 100 个 DOM 元素 | `coverageRatio = 0.4`, `recommendedStrategy = 'js_innertext'` |
| CA-04 | 覆盖率 = 0% — 极端降级 | snapshot 为空或 nodeCount=0, 有文本内容 | `coverageRatio = 0`, `recommendedStrategy = 'screenshot_visual'` |
| CA-05 | DOM 元素统计靠 HTML 标签 | html 含 120 个 `<div>`, `<p>`, `<a>` 标签 | `totalDomElements ≈ 120` |
| CA-06 | 无 pageHtml 时的回退估算 | 无 html 参数 | 使用 `nodeCount * 1.25` 估算 |

### 2.2 SPA Hydration 检测（C2-1 修复验证）

| ID | Test Case | 输入条件 | 期望输出 |
|----|-----------|---------|---------|
| SPA-01 | SPA 未 Hydrate — Loading 占位符 | nodeCount = 2, html 含 "Loading..." | `coverageRatio = 0`, `strategy = 'screenshot_visual'` |
| SPA-02 | SPA 未 Hydrate — 省略号占位符 | nodeCount = 3, html 含 "..." | `coverageRatio = 0`, `strategy = 'screenshot_visual'` |
| SPA-03 | SPA 未 Hydrate — Please wait | nodeCount = 1, html 含 "Please wait" | `coverageRatio = 0`, `strategy = 'screenshot_visual'` |
| SPA-04 | 非 SPA 页面 — 节点少但无 Loading 签名 | nodeCount = 4, html 无 Loading 签名 | 正常计算覆盖率（不强制降级） |
| SPA-05 | nodeCount > MIN_TRUSTED_NODES 时即使有 Loading 也正常处理 | nodeCount = 10, html 含 "Loading..." | 正常计算覆盖率（有足够的 a11y 节点） |
| SPA-06 | nodeCount = 0 | snapshot 空 | 走覆盖率 0% 逻辑 |

### 2.3 反爬检测（C2-2 修复验证）

| ID | Test Case | 输入条件 | 期望输出 |
|----|-----------|---------|---------|
| AC-01 | Cloudflare classic | html 含 "Just a moment..." | `coverageRatio = 0`, `strategy = 'screenshot_visual'` |
| AC-02 | reCAPTCHA v3 | html 含 "grecaptcha" | `coverageRatio = 0`, `strategy = 'screenshot_visual'` |
| AC-03 | DataDome | html 含 "ddome-" | `coverageRatio = 0`, `strategy = 'screenshot_visual'` |
| AC-04 | Kasada | html 含 "kaptcha" | `coverageRatio = 0`, `strategy = 'screenshot_visual'` |
| AC-05 | Cloudflare Turnstile | html 含 "challenges.cloudflare.com" | `coverageRatio = 0`, `strategy = 'screenshot_visual'` |
| AC-06 | 'robot' 在反爬上下文中 — meta robots | html 含 `<meta name="robots" content="noindex">` 且附近含 "robot" | `coverageRatio = 0`, `strategy = 'screenshot_visual'` |
| AC-07 | 'robot' 在反爬上下文中 — User-Agent | html 含 "User-Agent: *" 且附近含 "robot" | `coverageRatio = 0`, `strategy = 'screenshot_visual'` |
| AC-08 | 'robot' 在正常内容中（假阳性消除） | html 含 "AI Robot Technology Blog"（title），无反爬上下文 | 不触发反爬，正常计算覆盖率 |
| AC-09 | 'captcha' 在正常页面中 | html 含 "captcha" 但无反爬其他特征（假阳性率 < 0.5% 容忍） | 触发反爬（保持直接匹配） |
| AC-10 | 多重反爬特征叠加 | html 同时含 Cloudflare + reCAPTCHA | 只触发一次降级，结果一致 |

### 2.4 隐藏元素与文本检测

| ID | Test Case | 输入条件 | 期望输出 |
|----|-----------|---------|---------|
| HE-01 | 隐藏元素 > 50% — 触发文本降级 | hiddenRatio = 0.6, hasText=true | `strategy = 'js_innertext'` |
| HE-02 | 隐藏元素 > 50% — 无文本触发截图 | hiddenRatio = 0.7, hasText=false | `strategy = 'screenshot_visual'` |
| HE-03 | 隐藏元素 ≤ 50% — 不影响策略 | hiddenRatio = 0.3, coverage ≥ 0.6 | `strategy = 'ax_tree'` |
| TC-01 | 文本检测 — 有长文本 | tree 含 name="This is page content with >10 chars" | `hasTextContent = true` |
| TC-02 | 文本检测 — 仅有短文本 | tree 含 name="OK", label="Hi"（均 < 10 字符） | `hasTextContent = false` |
| TC-03 | 文本检测 — 空树 | tree = null | `hasTextContent = false` |

---

## 3. BrowserAutomationAdapter 全链路测试（覆盖 C3 层）

### 3.1 Track 1 — ax_tree 正常路径

| ID | Test Case | Mock 配置 | 期望行为 |
|----|-----------|----------|---------|
| AD-01 | 标准提取 — 无障碍树全覆盖 | navigate ok, snapshot 含足量节点（coverage ≥ 60%）, pageHtml 无异常 | `strategyUsed = 'ax_tree'`, `structuredData` 存在, `navigate` 调用 1 次 |
| AD-02 | 标准提取 — 含 getPageHtml 可选失败 | navigate ok, snapshot ok, getPageHtml 抛出错误 | 忽略 getPageHtml 错误，继续正常分析 |
| AD-03 | 标准提取 — 验证 causationId 传递 | 正常调用 | result.context.causationId 与输入一致 |

### 3.2 Track 2 — js_innertext 降级路径

| ID | Test Case | Mock 配置 | 期望行为 |
|----|-----------|----------|---------|
| AD-04 | 覆盖率不足 — JS 注入成功 | snapshot 覆盖率 < 60%, evaluate 返回有效文本 | `strategyUsed = 'js_innertext'`, `textContent` 存在, navigate 仍仅 1 次 |
| AD-05 | JS 注入 — evaluate 失败 | evaluate 抛出错误 | 降级到 screenshot（若 allowScreenshotFallback=true） |
| AD-06 | JS 注入 — 返回内容过少 | evaluate 返回 < 10 字符 | 降级到 screenshot |
| AD-07 | JS 注入被禁用 | allowScriptInjection=false, allowScreenshotFallback=false | 返回 ax_tree 结果 + error 注明禁用 |
| AD-08 | JS 注入被禁用但允许截图 | allowScriptInjection=false, allowScreenshotFallback=true | 降级到 screenshot |

### 3.3 Track 3 — screenshot_visual 全量降级

| ID | Test Case | Mock 配置 | 期望行为 |
|----|-----------|----------|---------|
| AD-09 | 截图降级 — 反爬触发 | pageHtml 含 "Just a moment...", screenshot 成功 | `strategyUsed = 'screenshot_visual'`, `screenshotBase64` 存在 |
| AD-10 | 截图降级 — navigate 失败 | navigate 抛出错误 | 直接进入 fallbackToScreenshot，screenshot 成功 |
| AD-11 | 截图降级 — getSnapshot 失败 | snapshot 抛出错误 | 进入 fallbackToScreenshot |
| AD-12 | 截图降级 — screenshot 自身失败 | screenshot 抛出错误 | `strategyUsed = 'failed'`, error 信息存在 |
| AD-13 | 截图降级被禁用 | allowScreenshotFallback=false, 反爬触发 | `strategyUsed = 'failed'`, error 注明禁用 |

### 3.4 C3-3 导航单次调用验证（关键修复）

| ID | Test Case | Mock 配置 | 期望行为 |
|----|-----------|----------|---------|
| AD-14 | 完整 Track 1 路径 — navigate 仅 1 次 | 正常 ax_tree 路径 | `calls.navigate.length === 1` |
| AD-15 | Track 1 → Track 2 降级 — navigate 仅 1 次 | coverage < 60%, JS 注入成功 | `calls.navigate.length === 1` |
| AD-16 | Track 1 → Track 3 降级 — navigate 仍仅 1 次 | 反爬触发, screenshot 成功 | `calls.navigate.length === 1` |
| AD-17 | navigate 失败 — navigate 仍仅 1 次 | navigate 抛出错误 | `calls.navigate.length === 1` |

### 3.5 C3-4 安全超时验证（关键修复）

| ID | Test Case | Mock 配置 | 期望行为 |
|----|-----------|----------|---------|
| AD-18 | navigate 超时 | 设置 delayMs > timeoutMs | 抛出 TimeoutError，navigate 状态为 rejected |
| AD-19 | getSnapshot 超时 | snapshot 延迟 6s, timeoutMs=5000 | 超时后进入 fallbackToScreenshot |
| AD-20 | evaluate 超时 | evaluate 延迟 12s, timeoutMs=10000 | 超时后进入 fallbackToScreenshot |
| AD-21 | screenshot 超时 | screenshot 延迟 20s, timeoutMs=15000 | 返回 failed |
| AD-22 | 超时后 Promise 不残留（验证） | 模拟长延迟 Promise, 超时后在 100ms 后 resolve（本应被忽略） | 最终结果仍是超时，不会出现 "已超时又成功" 的矛盾状态 |

### 3.6 场景感知超时测试

| ID | Test Case | 场景类型 | 期望行为 |
|----|-----------|---------|---------|
| SC-01 | realtime_request 超时 | 'realtime_request' | timeoutMs=5000, allowScreenshotFallback=false |
| SC-02 | offline_batch_sync 全量降级 | 'offline_batch_sync' | timeoutMs=30000, 允许全量降级 |
| SC-03 | interactive_operation 交互超时 | 'interactive_operation' | timeoutMs=10000 |

---

## 4. 交互操作测试

| ID | Test Case | Mock 配置 | 期望行为 |
|----|-----------|---------|---------|
| INT-01 | click 操作 | click 成功 | `success = true` |
| INT-02 | fill 操作 | fill 成功 | `success = true` |
| INT-03 | press_key 操作 | pressKey 成功 | `success = true` |
| INT-04 | 不支持的操作类型 | type='scroll' | `success = false`, error 提示不支持 |
| INT-05 | 操作失败 | click 抛出错误 | `success = false`, error 携带异常信息 |
| INT-06 | delayBeforeMs 延迟 | delayBeforeMs=500 | 操作前等待至少 500ms |
| INT-07 | 导航失败时所有交互失败 | navigate 抛出错误 | 所有 interactions 返回 `success = false` |

---

## 5. 边界与极端情况

| ID | Test Case | 条件 | 期望行为 |
|----|----------|------|---------|
| EDGE-01 | URL 为空字符串 | url = '' | navigate 应调用但可能失败，后续走降级 |
| EDGE-02 | context 字段均为默认值 | `createDefaultContext('realtime_request')` 而不覆写 | 正确获取场景默认值 |
| EDGE-03 | 极端大无障碍树 | snapshot 含 10,000+ 节点 | 覆盖率计算不溢出，性能可接受 |
| EDGE-04 | 极端大 HTML | pageHtml = 2MB 字符串 | 反爬检测在合理时间内完成 |
| EDGE-05 | 递归深度 | 无障碍树嵌套 100 层 | countAxNodes / detectTextContent 无栈溢出 |
| EDGE-06 | HTML 含特殊字符 | pageHtml 含大量 `<`, `>`, `&` 等 | estimateDomFromHtml 正则匹配稳定 |
| EDGE-07 | snapshot 结构异常 | tree 为 null/undefined | 所有递归函数返回 0/false |
| EDGE-08 | snapshot 无 children 键但非 null | tree = { name: "root" }, 无 children | 递归正确处理，不抛出 |

---

## 6. 代码质量与工程检查

| ID | 检查项 | 方法 |
|----|-------|------|
| QA-01 | TypeScript strict 编译通过 | `tsc --noEmit --strict` |
| QA-02 | 零运行时外部依赖 | 检查 `package.json`, import 不含第三方库 |
| QA-03 | 测试覆盖率阈值 | Jest coverage: 目标 branches ≥ 85%, lines ≥ 90% |
| QA-04 | §3.7 SNA 合规 | 所有测试断言 `calls.navigate.length === 1` |
| QA-05 | §3.7 Safe Timeout 合规 | 代码审查确认无 `Promise.race` 使用 |

---

## 7. 执行顺序建议

```
Phase 1 (基础层验证):
  CA-01~CA-06  覆盖率计算核心路径
  TC-01~TC-03  文本检测
  HE-01~HE-03  隐藏元素

Phase 2 (修复验证 C2):
  SPA-01~SPA-06  SPA Hydration 检测
  AC-01~AC-10    反爬检测（含 robot 上下文验证）

Phase 3 (适配器路由):
  AD-01~AD-13    三轨制全路径
  AD-14~AD-17    C3-3 navigate 单次调用验证
  SC-01~SC-03    场景感知超时

Phase 4 (修复验证 C3):
  AD-18~AD-22    安全超时 + 无残留 Promise

Phase 5 (扩展功能):
  INT-01~INT-07  交互操作
  EDGE-01~EDGE-08 边界极端情况
  QA-01~QA-05    代码质量