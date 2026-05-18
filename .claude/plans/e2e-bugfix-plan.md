# 端到端 Bug 修复方案

**来源**: 首次 `python app.py --mode full` 运行日志 | **日期**: 2026-05-18

---

## Bug 1: SanitizedText 类型错误——event_clusterer 传入 LLM 时未解包

**根因**: `input_guard.sanitize_for_llm_prompt()` 返回 `SanitizedText` 对象，但 `event_clusterer.py` 把它当 `str` 传入 `chat_flash()`。`chat_flash()` 内部调用 `len()` → 崩溃。

**修复**: 在 `event_clusterer.py` 中，调用 `sanitize_for_llm_prompt()` 后使用 `.sanitized` 字段提取字符串，再传给 `chat_flash()`。

```python
# OLD (bug):
sanitized = sanitize_for_llm_prompt(headline, source="hypothesis_card")
result = await chat_flash(system_prompt=..., user_prompt=sanitized)  # SanitizedText → crash

# NEW (fix):
sanitized = sanitize_for_llm_prompt(headline, source="hypothesis_card")
result = await chat_flash(system_prompt=..., user_prompt=sanitized.sanitized)  # str → OK
```

**影响文件**: `pipeline/event_clusterer.py`

---

## Bug 2: Flash 分诊返回空——所有批次 JSON 解析失败

**根因**: Flash LLM 调用返回 content 为空或 JSON 解析失败。需要检查：
1. `flash_triage.py` 的 `preprocess_batch()` 实际调用了 `chat_flash()` 吗？
2. JSON 解析是否因 `_parse_json_strict()` 太严格而拒绝有效输出？
3. 是否有 `SanitizedText` 类型错误同样影响了这里？

**修复**:
1. 检查 `flash_triage.py` → 确保 LLM 调用正确，prompt 内使用 `.sanitized` 字段
2. 添加调试日志：记录 Flash 原始返回内容前 200 字符
3. 如果 batch 解析失败，用单条重试机制

**影响文件**: `pipeline/flash_triage.py`, `pipeline/event_clusterer.py`

---

## Bug 3: 影子方向 CHECK 约束失败

**根因**: 影子输出 `direction` 字段值为 `"0.6, thesis: ..."` 或 `"neutral"` 等非标准值。数据库约束要求 `direction IN ('long','short','abstain')`。

**修复**: `shadow_agent.py` 或 `shadow_mother.py` 中的方向解析：
1. 添加方向值规范化：`"bullish"→"long"`, `"bearish"→"short"`, `"neutral"→"abstain"`
2. REIT 浮点错误：影子的结构化输出被错误解析（vote 文本泄露到 direction 字段）。检查 VOTE_START/VOTE_END 块解析逻辑。
3. 添加防御：解析失败时默认 `direction="abstain"`

**影响文件**: `shadows/shadow_agent.py` (`_parse_votes()` 或等效函数), `shadows/shadow_state.py`

---

## Bug 4: BLS PPI 无数据

**根因**: BLS API 返回空 observations。可能系列代码过期或数据延迟。

**修复**: 添加 fallback——PPI 系列失败时不报错，静默跳过。日志级别从 ERROR 降到 WARNING。

**影响文件**: `pipeline/bls_fetcher.py`

---

## Bug 5: Bluesky 凭证缺失

**根因**: 环境变量 `BLUESKY_USERNAME` / `BLUESKY_APP_PASSWORD` 未设置。

**修复**: 已有日志提示，无需修复。如不需要 Bluesky，将其状态降为 DEGRADED（不阻塞）。

---

## 修复优先级

| 顺序 | Bug | 修复难度 | 修复时间 |
|:---:|------|:---:|:---:|
| 1 | SanitizedText 类型错误 | 低 | ~5 行 |
| 2 | Flash 分诊空 | 中 | ~20 行 |
| 3 | 影子方向约束 | 低 | ~15 行 |
| 4 | BLS PPI | 低 | ~3 行 |

Bug 1 影响最大——修完它，Flash 分诊和事件聚类就能工作了。

---

## 测试

修复后跑 `python app.py --mode full --mock --verbose`，验证：
- [ ] 事件聚类命名成功（无 SanitizedText 错误）
- [ ] Flash 分诊产出 ≥1 个信号
- [ ] HVR 产 ≥1 个假设
- [ ] Gate 1 展示卡片
- [ ] 影子方向全部合法
- [ ] 全量 pytest 1285 通过
