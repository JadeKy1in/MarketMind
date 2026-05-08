# Phase 4 故障根因分析与修复方案

> 诊断日期: 2026-05-04 23:55 UTC  
> 诊断范围: `test_output_formatter.py` — 2/17 FAILED  
> 测试总览: **198/200 通过 (99%)**  
> 涉及模块: `src/output_formatter.py`

---

## 错误分类

| # | 测试用例 | 类别 | 严重程度 | 与 ascii_utils 关联 |
|---|---|---|---|---|
| 1 | `test_contains_executive_summary_section` | 缺失章节标题 | **高** | ❌ 无关 |
| 2 | `test_contains_4d_resonance_table` | Markdown 渲染格式不匹配 | **高** | ❌ 无关 |

---

## 根因分析

### 故障 1: 报告中缺少 "## Executive Summary" 章节标题

**现象：**  
测试断言 `"## Executive Summary" in report or "executive summary" in report.lower()` 失败。生成的报告中根本没有出现 "Executive Summary" 这个短语。

**调用链追溯：**  

```
format_report()
  └─ _build_header()      ← 负责 header / executive summary
     └─ _h1("SkillFoundry Research Report -- {ticker}")
        └─ [输出]:

           # SkillFoundry Research Report -- AAPL
           **Generated:** 2026-05-04 16:53 UTC
           **Signal:** **BUY**  |  **Weighted Score:** **72.5**/100  |  **Conviction:** **MEDIUM**
           > Four-dimensional resonance indicates constructive setup for AAPL; ...
```

`_build_header()` 虽然用 `executive_summary` 字典中的数据（`signal`, `weighted_score`, `conviction`, `one_liner`）填充了报告头部，但**从未在输出中包含 `"## Executive Summary"` 或 `"executive summary"` 这两个字符串**。整个函数的输出是一个无章节标题的裸头部。

**根本原因：** 设计意图上，报告头部本身就是 "Executive Summary" 章节的视觉呈现，但未按测试期望添加显式的章节标题头。

**修复方案（仅需输出文件 `output_formatter.py`）：**  
在 `_build_header()` 函数中，将 `_h1(...)` 标题行后面添加一条 `_h2("Executive Summary")` 作为副标题，或将头部整体重构为以 `"## Executive Summary"` 为起始的结构化章节。

*推荐最小改动：在 `_h1()` 标题行之后添加 `_h2("Executive Summary")` + `_LINE`。*

---

### 故障 2: 4D 共振表格中维度名称被 `**` 包裹导致字符串匹配失败

**现象：**  
测试断言 `"| Fundamental" in report or "4D" in report` 失败。报告中的确包含 "4D" 相关内容（`"## Four-Dimensional Resonance Score"`），但 `"4D"` 不在报告中？不对——看仔细了，报告中有 `"## Four-Dimensional Resonance Score"`，但 **`"4D"` 并不作为独立子串出现在报告中**。

实际上问题更微妙：`_build_resonance_table()` 生成的表格内容为：

```markdown
| **Fundamental** | N/A/100 |
| **Technical** | N/A/100 |
| **Event-Driven** | N/A/100 |
| **Sentiment** | N/A/100 |
```

对比测试期望的 `"| Fundamental"`，实际输出是 `"| **Fundamental"`。管道符 + 空格后紧跟 `**` 而不是直接跟 `F`，因此 `"| Fundamental"` 不匹配。

**调用链追溯：**  

```python
# _build_resonance_table() 第 261-264 行
f"| **Fundamental** | {dim_scores.get('fundamental', 'N/A')}/100 |",
f"| **Technical** | {dim_scores.get('technical', 'N/A')}/100 |",
f"| **Event-Driven** | {dim_scores.get('event_driven', 'N/A')}/100 |",
f"| **Sentiment** | {dim_scores.get('sentiment', 'N/A')}/100 |",
```

这里的 `**` 是 Markdown 加粗语法，但在表格上下文中多此一举——表格本身的结构化格式已经足够区分维度标签。`**` 的引入导致字符串字面量不匹配。

**根本原因：** `_build_resonance_table()` 中表格单元格使用了冗余的 `**` 加粗包裹，而 `_build_trading_decision()` 中同类表格也同样使用了 `**`（但那条测试未被影响是因为它检查的是特定字符串匹配），两条路径的渲染风格不一致且引入了可避免的匹配脆弱性。

**修复方案（仅需输出文件 `output_formatter.py`）：**  
移除 `_build_resonance_table()` 中表格单元格的 `**` 包裹。将：

```python
f"| **Fundamental** | {dim_scores.get('fundamental', 'N/A')}/100 |",
```

改为：

```python
f"| Fundamental | {dim_scores.get('fundamental', 'N/A')}/100 |",
```

对其他三个维度同理。注意：`_build_trading_decision()` 中的 `**` 表格不应改动，因为那里有对应的测试依赖且已经通过。

---

## 波及范围分析

| 维度 | 影响 |
|---|---|
| **需修改文件** | 仅 `src/output_formatter.py` |
| **涉及函数** | `_build_header()` + `_build_resonance_table()` |
| **受影响测试** | 2 个（当前失败的两个），**对其它 15 个无影响** |
| **运行时影响** | 无。修复后报告内容完全相同（仅少一份 `**` 和多个 `"## Executive Summary"` 标题） |
| **回归风险** | 低。两个 fix 均为纯文本格式调整，不改变数据流或业务逻辑 |

---

## 修复步骤（PM 批准后执行）

1. **`output_formatter.py` 第 152-153 行**：在 `_h1()` 标题行与 `**Generated:**` 行之间插入 `_h2("Executive Summary")` + `_LINE`。
2. **`output_formatter.py` 第 261-264 行**：移除 `| **Fundamental** |` → `| Fundamental |`（4 行同样处理）。
3. **验证**：运行 `python -m pytest tests/test_output_formatter.py -v` 确认 17/17 通过。
4. **全量回归**：运行 `python -m pytest tests/ -v` 确认 200/200 通过。

---

*诊断人: AI Pro 架构师 (Phase 4 Post-Mortem)*