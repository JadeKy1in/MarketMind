# Debug Handoff — Phase 8.3.1 Belief State Manager

## 状态摘要

| 文件 | 测试结果 |
|---|---|
| `test_belief_types.py` | ✅ **43 passed** (已修复对齐) |
| `test_belief_math.py` | ✅ **48 passed** (正确无误) |
| `test_belief_state_manager.py` | ❌ **16 failed + 4 errors** (当前拦路虎) |
| `test_belief_memory_adapter.py` | ❓ 尚未运行 |

---

## 核心失败模式诊断

### 失败组 1：BeliefSource 枚举值缺失（~4 failures）

**根因：枚举值名称不一致**

**证据：**
- `belief_types.py` 定义了 `BeliefSource.SHADOW_PREDICTION`、`BeliefSource.MARKET_DATA`、`BeliefSource.MACRO_CALENDAR`、`BeliefSource.HUMAN_INPUT`、`BeliefSource.INFERRED`
- 测试 `test_belief_state_manager.py` 引用了：
  - `BeliefSource.HUMAN` → ❌ 不存在，应为 `HUMAN_INPUT`
  - `BeliefSource.SHADOW_TRIBUNAL` → ❌ 不存在，应为 `SHADOW_PREDICTION`

**修复方案：** 在 `belief_types.py` 中为 `BeliefSource` 添加 `HUMAN` 和 `SHADOW_TRIBUNAL` 别名，或修改测试中的引用。**建议添加别名**，保持现有业务语义不变。

---

### 失败组 2：beta_update 数学公式与测试期望不一致（~4 failures）

**根因：蓝色图中规范公式 vs 实际实现的错位**

**证据：**
- 测试 `test_uniform_prior_positive_evidence` (第 246 行)：
  - 输入：`alpha=1.0, beta=1.0`, 观测 `value=0.8, confidence=1.0` → effective_value = 0.8
  - 期望输出：`alpha' = 1.0 + 0.8 = 1.8`, `beta' = 1.0`（保持不变）
  - 但 `beta_update()` 的实际实现可能使用了不同的公式结构
- 测试 `test_negative_evidence` (第 257 行)：
  - 输入：`value=0.2, confidence=1.0` → effective_value = 0.2
  - 期望输出：`alpha' = 1.2`, `beta' = 1.8`
  - **判断：** 蓝图的 Beta 更新规则为 `α' = α + effective_value, β' = β + 1 - effective_value`

**问题定位：** 需要检查 `belief_math.beta_update()` 的源码是否符合上述简单累加公式，还是使用了某种加权公式。

**假设：** `beta_update` 可能使用了 `effective_value * confidence` 的二次缩放的公式，导致与测试期望不同。

---

### 失败组 3：export_state() 字典 vs 列表结构错位（~6 failures）

**根因：export_state 的返回结构是嵌套字典，测试代码按列表处理**

**证据：**
- `export_state()` (第 833 行) 返回格式：
  ```python
  {
      "nodes": {
          "btc-bull": <dict>,
          "spy-bear": <dict>,
          ...
      },  # ← 这是 dict，不是 list
      "conflicts": { "conflict-id": <dict>, ... },  # dict
      "retirements": { "retirement-id": <dict>, ... },  # dict
  }
  ```
- 测试 `test_export_state_contains_nodes` (第 813 行)：
  ```python
  assert len(state["nodes"]) >= 3  # ✅ OK, dict 也支持 len()
  for n in state["nodes"]:         # ❌ 遍历 dict 只会得到 keys (proposition_id 字符串)
      ...
  proposition_ids = {n["proposition_id"] for n in state["nodes"]}
  # TypeError: string indices must be integers
  ```

**同样问题影响测试：**
- `test_export_state_after_conflict` (第 833 行) — `state["conflicts"]` 是 dict，遍历得到 string keys
- `test_export_state_after_retirement` (第 847 行) — `state["retirements"]` 是 dict，遍历得到 string keys

**修复方案：** 两种路径：
1. **（推荐）改 export_state**：将 nodes/conflicts/retirements 改为 list
2. 改测试：用 `state["nodes"].values()` 遍历

---

### 失败组 4：export_state config 缺少字段（1 failure）

**根因：export_state() 没有导出完整的 config 字段**

- 测试期望 `state["config"]` 包含 `"max_observations_per_node"`
- 实际 `export_state()` 只包含 `gamma`, `theta`, `conflict_threshold`
- 缺失字段：`auto_decay_interval_seconds`, `max_observations_per_node`

**修复方案：** 在 `export_state()` 的 config 字典中添加缺失字段。

---

### 失败组 5：Conflict Detection 时序问题（~2 failures）

**根因：`ingest_observation` 中 `_detect_conflicts()` 的触发时序**

- 当前流程：`ingest_observation` → `_apply_decay` → beta update → `_detect_conflicts` → retirement check
- 问题：冲突检测在第一个节点接收观测时就会触发，但此时第二个节点可能还没有被置入活跃状态或还没有任何观测
- 具体失败：`test_conflict_divergent_beliefs` — 两个节点注册后都需要 `.ingest_observation()` 才会触发检测，但预期是第一次 ingest 就立刻检测到冲突

**假设：** `_detect_conflicts` 在第一个节点 ingest 时扫描 `_proposition_index` 中的同级节点，但它们的期望值可能还没有因为观测而充分分化。

---

### 失败组 6：小数精度问题（~1 failure）

- `test_conflict_divergent_beliefs` 中 `E[bull]=20/22≈0.909`，`E[bear]=2/20=0.1`
- 差值为 0.809 > 0.3 threshold，理应触发冲突
- 但 `beta_expectation` 的实现可能使用了不同的公式（如增加 Jeffreys prior correction）

**假设：** `beta_expectation` 在 `test_belief_math.py` 测试正确，但在 `belief_state_manager.py` 中的调用方式（通过 `_InternalNode.snapshot()` 间接调用）可能导致浮点计算路径略有差异。

---

## 为什么前几次修复都失败了？

### 模式 1：底层数学逻辑冲突

`beta_update()` 和 `beta_expectation()` 是 core math kernel——修改它们会同时影响 `test_belief_math.py`（48 passed）和 `test_belief_state_manager.py`。修复 `belief_state_manager.py` 测试时不小心改了 `belief_math.py`，导致 `test_belief_math.py` 也开始失败（即使它之前是全绿的）。

**教训：数学内核一旦通过 100% 覆盖，就不应再修改。** 测试对齐应该在业务逻辑层（manager）解决，而不是在核心层。

### 模式 2：语法错位（简单但致命）

- 添加 `BeliefSource` 别名时忘记重新导出到 `__init__.py`（如果存在）
- 字典改列表时漏掉了某处引用
- `export_state` 中 config 键名与测试期望不匹配

这类错误都是**一次改不完，连锁反应**的典型。

### 模式 3：修复范围判断失误

我每次试图修复"所有"失败时，`replace_in_file` 的 SEARCH/REPLACE 块在几轮修改后，文件实际内容与 SEARCH 块不再匹配，导致编辑失败。这是典型的**增量修复恶化**问题——应该一次性用 `write_to_file` 重写整个文件。

---

## 建议的恢复路径（供 PM / Pro 架构师审查）

### 方案 A：针对所有失败模式，重写 `belief_state_manager.py`（推荐）

一次性 `write_to_file` 写入完整修复版，解决：
1. `export_state()` 返回值改为 list 结构
2. 补全 config 导出字段
3. 保持 `belief_math.py` 不变
4. 确保 conflict detection 触发时序与测试期望一致

### 方案 B：只修改测试用例

更改测试用例以对齐当前实现，但会降低测试的约束力——**不推荐**。

### 方案 C：分步修复（前几次失败的模式）

不建议——增量 edit 在多次迭代后出错率太高。

---

## 当前文件快照

| 文件 | 行数 | 最后修改时间 |
|---|---|---|
| `belief_math.py` | ~120 | ✅ 已验证通过 |
| `belief_types.py` | 389 | ✅ 43 passed |
| `belief_state_manager.py` | 907 | ❌ 16 failed + 4 errors |
| `belief_memory_adapter.py` | ~80 | ❓ 未验证 |
| `test_belief_state_manager.py` | 859 | 测试文件本身 ✅ |

---

## 附件：精确失败列表（记忆复原）

从上下文恢复的最后已知失败状态（不完全精确，但代表性问题已覆盖）：

```
FAILED test_belief_state_manager.py::TestRegisterNode::test_register_with_params - BeliefSource.HUMAN not found
FAILED test_belief_state_manager.py::TestBetaUpdateCorrectness::test_uniform_prior_positive_evidence - assertion error
FAILED test_belief_state_manager.py::TestBetaUpdateCorrectness::test_negative_evidence - assertion error  
FAILED test_belief_state_manager.py::TestBetaUpdateCorrectness::test_confidence_scaling - assertion error
FAILED test_belief_state_manager.py::TestConflictDetection::test_conflict_divergent_beliefs - conflict count mismatch
FAILED test_belief_state_manager.py::TestExportState::test_export_state_contains_nodes - TypeError
FAILED test_belief_state_manager.py::TestExportState::test_export_state_config_snapshot - KeyError: 'max_observations_per_node'
FAILED test_belief_state_manager.py::TestExportState::test_export_state_after_conflict - TypeError
FAILED test_belief_state_manager.py::TestExportState::test_export_state_after_retirement - TypeError
```

---

*交接文档生成时间: 2026-05-07 20:34 CST*
*生成者: Phase 8.3.1 前线执行层 (ACT mode, DeepSeek)*