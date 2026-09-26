# Gate 1 — 9 CRITICAL 综合修复方案

**日期**: 2026-05-18 | **来源**: 安全/逻辑/架构 三份红方审计 | **待用户审批**

---

## 总览

三份审计共发现 **9 CRITICAL、13 HIGH、12 MEDIUM、7 LOW**。综合来看，一个组件解决最多问题：`integrity/input_guard.py`（共享输入清洗模块）—— 同时覆盖安全 C1/C3/H3/M4。

修复分为三层：**架构层**（先决条件，不可绕过）→ **安全层**（输入清洗，最高杠杆）→ **交互层**（卡片重设计、对话流重排）。

---

## 第一层：架构修复（Architecture C1/C2/C3 + H1/H2/H3/H4）

### 决策 1：选择 Path A — 两阶段 CLI + 新 orch 模块

**理由**：`app.py` 的 `run_daily()` 是无头批处理函数，`asyncio.run()` 一次性跑完。无法在其中暂停等用户输入。Path A 保持现有 `--mode daily` 不变，新增独立 Gate 1 入口。

```
新架构:
  python app.py --mode pre-gate1    # Stage 0-3 → 保存 checkpoint → 退出
  python app.py --mode gate1        # 加载 checkpoint → Gate 1 对话 → 保存 decision
  python app.py --mode post-gate1   # 加载 checkpoint+decision → Stage 4-10 → 归档

  python app.py --mode full         # 一键串联上述三步（新增）
```

**具体变更**：
1. 拆 `run_daily()` 为三个函数：`run_stages_0_3()`, `run_gate1()`, `run_stages_4_10()`
2. 新增 `pipeline/orchestration.py`：包含 `run_daily()`（保持兼容）、`run_full()`、`run_interactive_session()`
3. `app.py` 只做 CLI 参数解析 + 模式分发 → 目标 ≤150 行
4. Gate 1 期间管道完全暂停 — 无 Shadow、无后台任务、无 HTTP 请求。`input()` 阻塞是设计决策，不是缺陷。文档化此约束。

### 决策 2：Stage 编号以 pipeline-manifest.yaml 为准

更新 manifest，新增 `stage_2b_investigation`：
```yaml
stage_2b_investigation:
  after: stage_2_flash
  before: stage_3_layer1
  produces: hypotheses, actionable, monitor, priced_in
  gate: gate1  # ← Gate 1 插入点
```

Gate 1 在所有文档中统一引用 `stage_2b → gate1 → stage_3`。

### 决策 3：复用现有 SessionManager，不新建 gate1_decision.json

`storage/session.py` 已有 `GateCheckpoint(gate_number=1, completed=True, data={...})`。Gate 1 的决策数据存入 `GateCheckpoint.data` 字段，而非新建独立 JSON 文件。

### 决策 4：原子写入

在 `archivist.save_json()` 和 `session.save()` 中实现 temp-file + rename 原子写入模式。这是 Gate 1 代码的前置条件（Step 0）。

### 决策 5：扩大 ensure_dirs()

`archivist.ensure_dirs()` 元组加 `"gates"`。

---

## 第二层：安全修复（Security C1/C2/C3 + H2/H3/M1/M3）

### 核心：新建 `integrity/input_guard.py`

所有进入 LLM prompt 的文本必须经过此模块。四条代码路径全部接入：

```
Chat 输入    → sanitize_for_llm_prompt(text, "gate1_chat")
PDF 提取文本 → sanitize_for_llm_prompt(text, "pdf_upload")
假设卡片文本 → sanitize_for_llm_prompt(text, "hypothesis_card")
归档复读    → sanitize_for_llm_prompt(text, "archive_replay")
```

模块功能：
1. **Prompt 注入模式检测**（~20 个已知 pattern）→ 标记警告，不阻断
2. **Markdown 控制字符转义** — 用户文本插入 Markdown 前先 sanitize
3. **Unicode 规范化** — 防止同形字符攻击
4. **长度截断** — 默认 50000 token 上限
5. **返回 `SanitizedText`**：sanitized 文本 + warnings 列表 + 是否被截断

### Markdown 渲染安全（C1 修复）

- 用户消息在 Markdown 中用 `<!-- USER_TEXT_START -->`/`<!-- USER_TEXT_END -->` HTML 注释包裹
- 系统决策在 `<!-- SYSTEM_DECISION_START -->`/`<!-- SYSTEM_DECISION_END -->` 内
- AI 复盘管道**只解析 JSONL**，不解析 Markdown — Markdown 仅供人类阅读

### 文件上传安全（C2 + H2 修复）

- **硬限制**：拒绝 >10MB 文件，拒绝 >100 页 PDF
- **服务器端文件名**：UUID 生成，不用用户原始文件名
- **扩展名白名单**：`.pdf`, `.png`, `.jpg`, `.jpeg`, `.txt`, `.csv`
- **路径校验**：`resolve()` 后验证在 `data/uploads/` 下
- **PDF 提取超时**：`asyncio.wait_for(extraction, 30s)`
- **逐页流式提取**：达到 per-request token cap 立即停止

### JSONL 安全（C1 修复）

- `json.dumps()` 本身防止 JSONL 行内注入 — 标准库已正确处理
- 每条记录加 `content_type` 字段：`user_free_text` / `system_decision` / `ai_response`
- 管道按 `content_type` 过滤后再处理

### 对话轮次限制（M3 修复）

- 硬上限：50 轮
- 第 40 轮时 AI 提醒即将结束
- 每 10 轮显示累计 token 费用

---

## 第三层：交互重设计（Logic CRITICAL 1/2/3 + HIGH 4/5/6 + MEDIUM 7/8/9）

### 卡片重设计（响应 Logic C1/C2/C3）

**改前**：5 张卡片，每张 15-20 信息项，首屏 75-100 项，原始小数置信度 0.81 在顶部

**改后**：

```
┌──────────────────────────────────────────────────┐
│ 方向 A: EUR 看涨                  方向强度: 强   │
│                                                  │
│ 一句逻辑: ECB鹰派 + 德国PMI超预期 + EUR低位      │
│          → 存在上行空间                          │
│                                                  │
│ 正反对比:                                        │
│   正向 ~4 in 5 情景中盈利                        │
│   反向 ~1 in 5 情景，最大下行 ~8%                │
│                                                  │
│ 关键风险: ECB仅是口头干预，非真实加息承诺         │
│ EUR/USD 最可能区间: 1.08-1.14 (12个月)           │
│ 极端下行: ~10% 概率触及 1.02                     │
│                                                  │
│ [深入分析] [查看反对意见] [对比其他方向]          │
└──────────────────────────────────────────────────┘
```

**关键改变**：
1. **最多 3 张卡片**（权力三原则），其余标记为"备选，可按需查看"
2. **频率框架替换原始小数**："~4 in 5" 替代 "0.81"
3. **区间预测**替代单点置信度：最可能区间 + 极端情景概率
4. **3 层渐进披露**：
   - 第 1 层（默认）：方向名 + 趋势强度 + 一句逻辑 + 正反概率 + 风险概要
   - 第 2 层（按需）：完整 4 层证据 + pre-mortem + 历史类似案例
   - 第 3 层（深度）：源级细节、关联矩阵、原始模型置信度
5. **随机化卡片顺序**（跨会话），消除首位效应
6. **多准则分解**：卡片详情页展示 GSCP 分解（主题匹配度/时间框架契合度/催化剂清晰度/概率校准），替代单一 0.81

### 对话流重排（响应 Logic MEDIUM 8/9 + 研究建议）

**改前**：Scout Monitor → 卡片 → A/B/C 封闭问题

**改后**：
1. **开放开场**："在展示分析结果前 —— 你最近有没有在关注某个方向或话题？"
2. 用户回答后 → 呈现 3 张卡片（渐进第 1 层）
3. **Scout Monitor 移到卡片之后**：每张卡片标注各自依赖的信息源是否健康
4. **开放引导**："这些是我分析出的方向。你的第一反应是什么？有没有哪个方向你特别想深入讨论？"
5. 去掉 A/B/C 封闭选项

### Pre-Mortem 强化（Logic HIGH 4）

HVR Pre-Mortem 必须产出结构化、可观测、有时间边界的 kill criteria：

```
假设：EUR 看涨

Kill Criteria（可观测触发条件）:
  1. ECB 下次政策声明（6月12日）放弃 "vigilance" 措辞 → 终止持仓
  2. 德国 6 月 CPI YoY < 2.2%（6月28日发布）→ 减仓 50%
  3. EUR/USD 周线收盘跌破 1.05 支撑 → 全部退出

当前状态: [监控中] — 上次检查 2026-05-18，无触发
```

下游监控器（Stage 4-8）跟踪这些 kill criteria，触发时告警用户。

### 风险沟通量化（Logic HIGH 6）

- **去掉**：`风险: 中等`
- **替换为**：`最大下行: -8% (20% 概率)` / `预期回报: +12-18% (12个月)`

### 新方向处理标准化（Logic HIGH 5）

定义 T0-T3 复杂度分诊：
- **T0**：已知方向、已有数据 → ~1min（补充验证）
- **T1**：新方向、数据立即可得 → ~2-3min（4 层快速验证）
- **T2**：新方向、需跨源收集 → ~5min（完整验证链）
- **T3**：用户上传 PDF + 复杂模型 → ~10min（完整深度分析）

所有新方向在分析前先做**范围确认**：
```
"大豆可以指期货、ETF、或农业板块。你关注的是哪个层面？是朋友推荐的具体标的，还是对大豆价格的看法？"
```

### 去掉 80/10/10 指标（Logic MEDIUM 7）

替换为决策代理指标：
- 用户发起的问题数 vs AI 发起的问题数
- 用户挑战/修改的假设数
- 最终方向选择是否偏离最高 AI 置信度方向

---

## 新增模块清单（修订后）

| 模块 | 位置 | 行数 | 功能 |
|------|------|:---:|------|
| `integrity/input_guard.py` | `integrity/` | ~150 | 共享输入清洗（C1+C3+H3+M4） |
| `pipeline/gate1_interaction.py` | `pipeline/` | ~250 | CLI 对话循环 + 状态机 |
| `pipeline/hypothesis_card.py` | `pipeline/` | ~120 | 3 层渐进披露卡片生成 |
| `pipeline/orchestration.py` | `pipeline/` | ~200 | `run_daily()`/`run_full()`/`run_pre_gate1()`/`run_post_gate1()` |
| `storage/gate_archiver.py` | `storage/` | ~150 | JSONL + MD 归档（含 sanitization） |
| `pipeline/kill_monitor.py` | `pipeline/` | ~100 | 下游 kill-criteria 跟踪 |
| 修改 `app.py` | root | 删减至 ~150 | 纯 CLI 参数解析 + 模式分发 |
| 修改 `pipeline-manifest.yaml` | root | +5 行 | 新增 `stage_2b_investigation` |

---

## Security Tests（TDD，实施前必写）

| 测试 | 验证内容 |
|------|------|
| `test_newlines_not_injected_into_jsonl` | JSONL 抗恶意换行 |
| `test_markdown_rendering_escapes_user_input` | Markdown 不渲染用户注入的标题/决策 |
| `test_pdf_above_size_limit_rejected` | >10MB PDF 被拒绝 |
| `test_path_traversal_filename_rejected` | `../../config/settings.py` 被拒绝 |
| `test_prompt_injection_patterns_flagged` | "ignore previous instructions" → warning |
| `test_corrupted_checkpoint_handled_gracefully` | 残缺 session JSON 不会崩溃 |
| `test_sensitive_data_patterns_flagged` | 账号/持仓量模式的检测 |
| `test_conversation_turn_limit_enforced` | 50 轮后自动结束 |

---

## 实施步骤（修订后）

| 步骤 | 内容 | 前提 |
|:---:|------|------|
| 0 | 用户审批本修复方案 | — |
| 1 | `app.py` 提取：`BacktestRunner` → `pipeline/backtest_entry.py`，`run_interactive()` → `pipeline/orchestration.py` | 步骤 0 |
| 2 | 原子写入修复 `archivist.save_json()` + `session.save()` | 步骤 0 |
| 3 | 实现 `integrity/input_guard.py` + 8 个安全测试 | 步骤 0 |
| 4 | 更新 `pipeline-manifest.yaml`（新增 `stage_2b_investigation`）| 步骤 0 |
| 5 | 实现 `pipeline/hypothesis_card.py` | 步骤 3 |
| 6 | 实现 `pipeline/gate1_interaction.py`（含状态机）| 步骤 3/5 |
| 7 | 实现 `storage/gate_archiver.py` | 步骤 2/3 |
| 8 | 实现 `pipeline/orchestration.py`（`run_stages_0_3()` 等）| 步骤 1 |
| 9 | 接入 `app.py`（新 CLI 模式）| 步骤 4/6/7/8 |
| 10 | 实现 `pipeline/kill_monitor.py` | 步骤 5 |
| 11 | PICA 全协议 | 步骤 9-10 |
| 12 | 红方复审 | 步骤 11 |

---

## 综合判定

**三份审计的核心矛盾**：安全审计要求输入清洗（`input_guard.py`），逻辑审计要求认知减载（3 卡片 + 渐进披露），架构审计要求管道可暂停（`run_stages_0_3()` + checkpoint）。

三个要求**互不冲突，可以并行推进**。其中 `input_guard.py` 和原子写入是最高优先级前置组件 —— 步骤 2/3 完成后，步骤 5-8 可以并行开发。

**预估总代码量**：~950 行新代码 + ~200 行 app.py 删减 + ~200 行测试。分 6-8 个 commit。
