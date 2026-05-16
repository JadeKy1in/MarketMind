# System Patterns

## 系统架构

项目采用 **Event Sourcing + Scenario-Aware Degradation** 架构，核心围绕浏览器自动化采集的可靠性链路展开。系统由三个层次构成：

1. **主采集层** (Browser Automation - 微软官方版 MCP)
   - 通过无障碍树 (Accessibility Tree) 提取结构化纯文本 JSON
   - 优势：Token 效率高、故障隔离性强、无 GPU 依赖
   - 弱点：对无无障碍标注的页面覆盖率不足

2. **降级适配层** (Scenario-Aware Degradation Adapter)
   - 运行时检测无障碍树覆盖率，动态决策采集策略
   - 轻量级链路：无障碍树覆盖率 ≥ 60% → 直接使用无障碍树输出
   - 重度链路：覆盖率 < 60% 或交互操作需求 → 降级到 Playwright evaluate() / screenshot
   - 可插拔设计，不修改主采集层代码

3. **后援执行层** (Playwright 社区版 MCP - 33 项技能)
   - 通过 `playwright_evaluate` 注入 JS 获取完整 DOM innerText
   - 通过 `playwright_screenshot` 进行视觉兜底
   - 通过 `playwright_click` / `playwright_fill` 等实现交互操作
   - 仅作为降级路径调用，不承担主采集职责

## 设计模式与组件关系

### Scenario-Aware Degradation Adapter 核心组件

```
┌─────────────────────────────────────────────────────────────┐
│                    BrowserAutomationAdapter                  │
├─────────────────────────────────────────────────────────────┤
│  extractContent(url): ExtractionResult                      │
│    ├─ 1. playwright_navigate(url)                           │
│    ├─ 2. 获取无障碍树 + 可见文本                             │
│    ├─ 3. CoverageAnalyzer.analyze(tree) → CoverageReport     │
│    ├─ 4. Decision Engine:                                    │
│    │   ├─ coverage < 60%  → 降级到 evaluate()               │
│    │   ├─ coverage ≥ 60%  → 直接使用无障碍树输出             │
│    │   └─ 极端反爬标记     → 降级到 screenshot + evaluate()  │
│    └─ 5. 返回统一 ExtractionResult                           │
├─────────────────────────────────────────────────────────────┤
│  interact(selector, action): void                           │
│    └─ 直接路由到 Playwright 交互技能链                       │
└─────────────────────────────────────────────────────────────┘

                ▲                    ▲
                │                    │
     ┌──────────┴──┐        ┌───────┴──────────┐
     │ Coverage     │        │  Decision        │
     │ Analyzer     │        │  Engine          │
     │ (stateless)  │        │  (rule-based)    │
     └─────────────┘        └──────────────────┘
```

### 核心类型 (types.ts)

| 类型 | 用途 |
|------|------|
| `ExtractionStrategy` | 枚举：`a11y_tree` / `dom_innertext` / `screenshot_fallback` |
| `CoverageReport` | 无障碍覆盖率分析结果：覆盖率、缺失元素分类、推荐策略 |
| `ExtractionResult` | 统一采集结果：策略来源、原始内容、元数据标记 |
| `InteractionCommand` | 交互操作命令：点击、填写、滚动、悬停等 |
| `AdapterConfig` | 适配器配置：覆盖率阈值、超时、重试策略 |

### 覆盖率分析引擎 (coverage-analyzer.ts)

算法核心逻辑：
1. 统计无障碍树中 `role` 非 generic/presentation 的元素数量 → `accessibleCount`
2. 通过 JS 注入获取页面总 DOM 元素数 → `totalElements`
3. 覆盖率 = `accessibleCount / totalElements * 100`
4. 辅助指标：缺失 `aria-label` 比例、隐藏元素比例、交互元素无障碍比例
5. 决策输出：推荐 `ExtractionStrategy` + 置信度描述

### 降级决策阶梯

```
Level 0 (轻量) : a11y_tree
  条件：覆盖率 ≥ 60% 且无反爬标记
  方法：直接读取无障碍树 JSON
  输出：结构化语义数据

Level 1 (中级) : dom_innertext
  条件：覆盖率 < 60% 或 部分元素不可访问
  方法：playwright_evaluate → document.body.innerText
  输出：纯文本内容（扁平，无结构但完整）

Level 2 (重度) : screenshot_fallback
  条件：覆盖率极低（< 20%）或 检测到反爬机制
  方法：playwright_screenshot + playwright_evaluate 双重采集
  输出：图片 base64 + 文本内容（多模态兜底）
```

### 宪法约束

根据 AGENTS.md 第三章，所有 scenario-aware 代码必须附带 **Scenario Context Manifest**，该 Manifest 已创建于 `src/SCENARIO_CONTEXT_MANIFEST.md`，包含：
- 运行场景标识与上下文描述
- 组件清单与职责分界
- 场景感知决策逻辑的显式声明
- 约束弹性条款（覆盖率阈值、反爬检测策略）
- 宪法追溯链接