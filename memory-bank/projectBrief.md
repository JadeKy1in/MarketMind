# Project Brief

## 核心需求

### 项目使命
构建 **BrowserAutomationAdapter** — 一个场景感知的三轨制自动降级浏览器内容提取适配层，在 Browser Automation MCP 无障碍树覆盖率不足时自动决策降级策略，确保 AI Agent 系统在不同网页场景下均能可靠获取内容数据。

### 关键业务需求

1. **自适应内容提取**：根据目标页面的无障碍树覆盖率自动选择最优采集策略（ax_tree → js_innertext → screenshot_visual），调用方无需关心底层实现细节。
2. **场景化超时控制**：根据使用场景（实时请求 / 离线批量 / 交互操作）提供差异化的超时阈值和降级许可，平衡延迟敏感度与数据完整性。
3. **覆盖率分析引擎**：精确计算无障碍树对页面 DOM 的覆盖率，严格依据数学指标（coverageRatio, hiddenRatio, hasTextContent）做出降级决策，杜绝经验阈值猜测。
4. **反爬与 SPA 鲁棒性**：检测现代反爬机制（Cloudflare Turnstile, reCAPTCHA v3, DataDome, Kasada 等）和 SPA 首次渲染占位符，在极端页面场景下无缝降级到视觉兜底方案。
5. **交互操作路由**：支持在目标页面上执行点击、填写、按键等操作，扩展 AI Agent 在需要用户交互的页面上的能力边界。

### 成功指标

| 指标 | 目标值 | 测量方法 |
|------|--------|---------|
| 综合页面覆盖率 | ≥ 95% | 三轨制全链路下的成功提取率 |
| 全链最大延迟 | ≤ 15s | 单个页面从导航到返回结果 |
| 轻量链路（ax_tree）延迟 | ≤ 2s | 覆盖率 ≥ 60% 场景 |
| 运行时外部依赖 | 0 | `package.json` 中不依赖第三方库 |
| SPA 末渲染检测准确率 | ≥ 99% | 在有/无 Loading 占位符页面上的误判率 |
| 'robot' 假阳性率 | ≤ 0.1% | 从 ~3% 降至 ≤ 0.1%（上下文验证后） |
| TypeScript 编译 | `--strict` 零错误 | `tsc --noEmit --strict` |

## 项目范围

### 包含（In Scope）

- 场景感知超时与降级策略控制（`ExtractionContext` + `createDefaultContext`）
- 无障碍树覆盖率分析引擎（`coverage-analyzer.ts`）
- 三轨制自动降级编排（`adapter.ts` — `extractPage()`）
  - Track 1：ax_tree（轻量链路）
  - Track 2：js_innertext（JS 注入降级）
  - Track 3：screenshot_visual（截图视觉兜底）
- 页面交互操作路由（`adapter.ts` — `interact()`）
- McpToolRunner 接口抽象（可 mock、可替换实现）
- 反爬检测与 SPA Hydration 检测
- Scenario Context Manifest（`SCENARIO_CONTEXT_MANIFEST.md`）
- Memory Bank 宪法文档

### 不包含（Out of Scope）

- 浏览器实例管理与生命周期控制
- 网络代理 / VPN / IP 轮换
- 数据持久化存储或数据库集成
- VLM 视觉语言模型后处理管道（预留接口但不在当前范围）
- 分布式任务队列 / 消息中间件
- 用户认证与会话管理

### 约束条件

- **零运行时外部依赖**：代码不能引入 npm 第三方库（TypeScript 类型系统本身除外）
- **McpToolRunner 接口不变性**：所有 MCP 调用必须通过抽象接口，不直接调用 `use_mcp_tool`
- **单导航原则**：每次 `extractPage()` 调用最多触发 1 次 navigate（遵守 .clinerules §3.7(a) SNA）
- **安全超时模式**：禁止使用 `Promise.race`，强制使用显式 `new Promise<T>` + `clearTimeout`（遵守 .clinerules §3.7(d)）
- **无状态覆盖率分析**：`coverage-analyzer.ts` 的函数必须为纯函数，不持有内部状态