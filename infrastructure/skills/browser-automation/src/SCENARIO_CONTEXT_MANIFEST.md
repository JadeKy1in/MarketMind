# Scenario Context Manifest
## 场景上下文宣言

**Status**: Constitutional (Unamendable by Runtime)
**Classification**: SYSTEM_ARCHITECTURE → SCENARIO_AWARE_CONTRACT
**Constitution Ratified**: 2026-05-03
**Authored by**: The Maker (INQ-2026-05-03-001 Mandate)
**Signature**: `scenario-aware-degradation-adapter-v1`

---

## Preamble

本宣言定义 `BrowserAutomationAdapter` 与调用者之间的**运行时场景契约**。任何调用本适配层的代码——无论来自 Agent 宿主（Claude Code）、工具编排器（MCP Orchestrator）还是其他 AI 组件——均须遵守本声明中的场景约束。

违反本场景声明的调用，后果由调用方承担，适配层不保证执行结果的正确性。

---

## Article I — The Three Scenarios (三场景法则)

适配层严格识别以下三种运行场景：

### Scene 1: `realtime_request` — 实时请求

| Property          | Value       |
|-------------------|-------------|
| Timeout           | ≤ 5,000 ms  |
| Screenshot        | ❌ 禁止     |
| JS Injection      | ✅ 允许     |
| Retry Policy      | 最多 1 次   |
| Ideal Strategy    | `ax_tree`   |

**释义**：用户等待在线响应，延迟敏感。截图被禁止因为它引入了过高的不确定性延迟（3s+）。如果无障碍树覆盖率 < 60%，降级到 `js_innertext`；若 JS 注入也失败，返回部分结果 + 错误标志，不尝试截图。

### Scene 2: `offline_batch_sync` — 离线批量同步

| Property          | Value       |
|-------------------|-------------|
| Timeout           | ≤ 30,000 ms |
| Screenshot        | ✅ 允许     |
| JS Injection      | ✅ 允许     |
| Retry Policy      | 最多 3 次   |
| Ideal Strategy    | `ax_tree`   |

**释义**：批量定时任务（如每晚抓取），延迟不敏感，允许多次重试和全量降级。即使 `ax_tree` 和 `js_innertext` 都失败，也尝试截图视觉提取。

### Scene 3: `interactive_operation` — 交互式操作

| Property          | Value       |
|-------------------|-------------|
| Timeout           | ≤ 10,000 ms |
| Screenshot        | ✅ 允许*    |
| JS Injection      | ✅ 允许     |
| Retry Policy      | 最多 2 次   |

**释义**：Agent 与页面交互（点击、输入）后抓取结果。截图仅在交互后有视觉变化的必要时使用。优先级：`ax_tree` > `js_innertext` > `screenshot_visual`。

*截图需经 `allowScreenshotFallback` 显式授权。

---

## Article II — The Causation Chain (因果链)

每次 `extractPage()` 调用生成唯一 `causationId`，格式为 `{timestamp36}-{random8}`。该 ID 贯穿：

1. 日志输出
2. 覆盖率报告
3. 截图文件命名
4. 错误消息

要求：任何调试环节，必须能通过 `causationId` 追溯完整的执行链路。

---

## Article III — The Coverage Threshold (覆盖率阈值)

```
IF coverageRatio < 0.60 THEN MUST trigger degradation
IF coverageRatio = 0   AND NOT hasTextContent THEN MUST fallback to screenshot_visual
IF hiddenRatio   > 0.5 AND hasTextContent THEN SHOULD fallback to js_innertext
```

**解释**：
- `coverageRatio < 60%` 是宪法性触发条件，不可在代码中绕过。
- `coverageRatio = 0` 且无文本内容，说明页面被反爬或加载失败——必须使用截图视觉提取，即使这需要 VLM 后处理。
- `hiddenRatio > 50%` 说明页面上大多数元素对无障碍树不可见（例如复杂的 SPA），此时 JS innerText 注入可获得更完整的内容。

---

## Article IV — The Graceful Degradation Chain (优雅降级链)

```
[Primary]      ax_tree (getSnapshot)
   │ coverageRatio < 60% ────────────→ [Fallback 1] js_innertext (evaluate)
   │   │ JS injection disabled        │ JS injection fails/empty
   │   └──→ [Fallback 2]             └──→ [Fallback 2]
   │                                   │ screenshot disabled
   │                                   └──→ [Failed]
   └──→ [Fallback 2] screenshot_visual
         │ screenshot fails
         └──→ [Failed]
```

所有降级路径必须有明确的、可单元测试的触发条件。不允许隐含的、无文档的降级。

---

## Article V — The Privacy & Security Clause (隐私与安全条款)

1. **截图数据**受 `allowScreenshotFallback` 控制。默认 `true`；在涉及敏感内容的页面（如内部管理后台、支付页面）必须设为 `false`。
2. **JS 注入**受 `allowScriptInjection` 控制。默认 `true`；非同源策略的页面（CORS 受限）必须设为 `false`。
3. 所有降级数据（含截图 base64）不得超过 24MB。适配层不做存储——调用方负责内存管理。

---

## Article VI — Integration Contract (集成契约)

本适配层是**纯编排层**，不附带任何 MCP Server 的安装或启动逻辑。集成者需要：

```typescript
import { BrowserAutomationAdapter } from './src/adapter';
import { createDefaultContext } from './src/types';

// 1. 实现 McpToolRunner 接口（绑定真实 MCP Server）
const runner: McpToolRunner = {
  getSnapshot: async (input) => use_mcp_tool(...),
  evaluate: async (input) => use_mcp_tool(...),
  screenshot: async (input) => use_mcp_tool(...),
  navigate: async (url) => { ... },
  click: async (selector) => { ... },
  fill: async (input) => { ... },
  pressKey: async (key) => { ... },
};

// 2. 初始化适配层
const adapter = new BrowserAutomationAdapter(runner);

// 3. 创建场景上下文
const ctx = createDefaultContext('realtime_request');

// 4. 提取页面
const result = await adapter.extractPage('https://example.com', ctx);

// 5. 消费结果
if (result.strategyUsed === 'ax_tree') {
  console.log(result.structuredData);
} else if (result.strategyUsed === 'screenshot_visual') {
  // 需要 VLM 后处理
  console.log(`Screenshot base64 length: ${result.screenshotBase64?.length}`);
}
```

---

## Signatures

```
The Maker:
  ┌──────────────────────────────┐
  │ INQ-2026-05-03-001           │
  │ BrowserAutomationAdapter v1  │
  │ Scenario-Aware Degradation   │
  └──────────────────────────────┘
```

**Ratified on**: 2026-05-03
**Expires**: Never (此宣言为双向约束，不设有效期)