# MarketMind 主管线优化 — 迭代反馈结构 (2026-05-31)

**变更**: 4 项管线优化，将审计中识别的最高优先级问题一次性修复

---

## 优化 1: L1 早停 (Early Terminate)

**问题**: Daily 管线无 Gate——L1 grade=E + quadrant=observe_skip 时，后续 L2/L3/RedTeam/Resonance 照常运行，浪费 ~4 次 Pro 调用。

**修复** (`orchestration.py:run_daily`):

```
L1 result → 检查: grade=='E' AND quadrant=='observe_skip' AND signals==0
  ├── TRUE  → 跳过 L2+L3+Shadows+RedTeam+Resonance+Fragility
  │          所有阶段使用空默认值
  │          tracker 输出: "~4 Pro calls saved"
  │          → 直接进入 Decision (自动 no_trade)
  └── FALSE → 正常执行全部阶段
```

**触发条件**（三重 AND）:
1. `event_grade == 'E'` — 无重要事件
2. `matrix_quadrant == 'observe_skip'` — 低意外 + 小市场 = 不值得交易
3. `len(signals) == 0` — Flash 未提取任何信号

仅当三个条件全部满足才跳过。如果 Flash 提取了信号（即使 L1 评估为 E），仍正常执行——因为可能存在需要人工关注的边缘信号。

**测试验证**: Mock 管线 `--lang zh` 运行成功触发早停，管线正常完成。

---

## 优化 2: 逐 Stage 校准 (Per-Stage Calibration)

**问题**: 7 天校准上下文仅注入 L1 系统提示词。L2/L3/Decision 看不到自己的历史精度。

**修复**:

### 新增数据结构 (`daily_calibration.py`)

`DailyPrediction` 扩展:
```python
l2_sectors: list[str]               # 当日 L2 选择的板块
l2_sector_directions: dict[str,str]  # 板块方向 {sector: bullish/bearish}
l3_green_tickers: list[str]          # 当日 L3 绿灯标的
l3_red_tickers: list[str]            # 当日 L3 红灯标的
decision_no_trade: bool              # 当日是否 no_trade
```

### 新增函数: `get_stage_calibration(stage, shadow_db, days=7)`

每个 Stage 获得独立的、针对性校准:

| Stage | 校准内容 | 数据来源 |
|-------|------|------|
| **L1** | 方向精度、量级分数、等级分布、象限精度、Flash 验证率、HVR ROI | 原有 `get_calibration_context()` |
| **L2** | 板块方向精度（bullish/bearish 判断是否正确）、标的选择精度（选的标的是否上涨） | `l2_sectors`, `l2_sector_directions`, `ticker_candidates` |
| **L3** | 绿灯精度（绿灯标的是否真的上涨）、红灯避免率（红灯标的是否真的下跌） | `l3_green_tickers`, `l3_red_tickers` |
| **Decision** | 决策精度（long/short 判断是否正确）、no-trade 率 | `decisions`, `decision_no_trade` |

### 注入点

```
_do_l1_analysis    → calib = get_calibration_context(shadow_db) → analyze_layer1(calibration_context=calib)
_do_l2_l3_parallel → l2_calib = get_stage_calibration("l2", shadow_db) → analyze_layer2(calibration_context=l2_calib)
                   → l3_calib = get_stage_calibration("l3", shadow_db) → analyze_layer3(calibration_context=l3_calib)
```

### 额外: L2-L3 交叉检测

`_do_l2_l3_parallel` 现在在并行完成后检查交叉一致性:
```python
if l2_tickers and not (l2_tickers & l3_green):
    tracker.result("[WARN: L2-L3 mismatch — all L2 picks are L3 red]")
```
这个警告标记在未来运行中可作为 L2 重新选择的信号。

---

## 优化 3: Fragility → Decision 对接

**问题**: `fragility_scanner.py` 独立运行，Decision stage 不接收脆弱性数据。

**修复**:

### 新 Stage: Fragility Scan (7b)

```
Stage 7: Resonance (统计验证)
Stage 7b: Fragility Scan (市场脆弱性) ← 新增
Stage 8: Decision
```

Fragility 扫描在 Red Team 和 Resonance 之后、Decision 之前运行。顺序设计：
- Red Team 可能在挑战中提到脆弱性问题（阈值穿越）→ 先跑 Red Team
- Resonance 统计验证信号是否真实 → 再跑 Resonance
- Fragility 扫描当前市场结构脆弱性 → 在 Decision 前
- Decision 综合所有输入 → 最后

### Decision 中的脆弱性调整

```python
fragility_score = getattr(fragility, 'overall_fragility_score', 0.0)
fragility_crossed = len(getattr(fragility, 'crossed', []))

# 如果穿越阈值 > 2 个，在 no_trade 卡片中追加脆弱性注释
if fragility_crossed > 2:
    fragility_note = f" [Fragility: {fragility_crossed} thresholds crossed, score={fragility_score:.2f}]"
    no_trade_card.thesis += fragility_note
```

### Brief 持久化

`_save_decision_brief()` 现在包含 `fragility_score` 和 `fragility_crossed` 字段，供 Dashboard drill-down 使用。

---

## 优化 4: Red Team → Resonance 反馈

**问题**: Red Team 挑战关于数据挖掘/幸存偏误的内容不被 Resonance 统计验证考虑。

**修复**:

### 数据挖掘严重度提取

```python
def _extract_data_mining_severity(red_team) -> float:
    """从 Red Team 挑战中提取数据挖掘严重度分数"""
    dm_keywords = ["data mining", "survivorship", "overfit", "multiple testing",
                   "p-hacking", "look-ahead", "数据挖掘", "幸存偏误", "过度拟合"]
    score = 0.0
    for ch in red_team.challenges:
        if any(kw in challenge_text for kw in dm_keywords):
            score += 0.15 if ch.severity == 'critical' else 0.08
    return min(score, 0.5)  # 上限 0.5，避免过度惩罚
```

### PBO 阈值收紧

```python
# resonance.py evaluate_resonance() 新增参数: data_mining_severity
pbo_threshold = 0.10 - (data_mining_severity * 0.10)     # 0.10 → 0.05
strong_threshold = 0.05 - (data_mining_severity * 0.05)  # 0.05 → 0.025
```

**效果**: Red Team 发现的每个数据挖掘问题都会收紧 Resonance 的 PBO 阈值，使信号更难通过统计验证。这是 "有罪推定" 原则——如果存在数据挖掘嫌疑，要求更严格的统计证据。

---

## 优化后管线全貌

```
Stage 0: Shadow Init
Stage 1: Scout (37源异步采集)
Stage 2: Flash (批量预处理)
Stage 3: L1 Narrative + 校准上下文注入 (日 + 周)
    ↓
    ├── [L1早停检查] grade=E AND quadrant=observe_skip AND signals=0
    │       ├── TRUE → 跳到 Decision (保存 ~4 Pro calls)
    │       └── FALSE ↓
    │
Stage 4: L2+L3 Parallel + 逐 Stage 校准注入
    │     └── [交叉检测] L2 选的标的全部是 L3 红灯？→ WARN
    │
Stage 5: Shadows (非阻塞后台)
Stage 6: Red Team (对抗审计, temp=0.5)
    │     └── 提取数据挖掘严重度 → 传给 Resonance
    │
Stage 7: Resonance (统计验证, 零 LLM)
    │     └── PBO 阈值 = 0.10 - data_mining_severity * 0.10
    │
Stage 7b: Fragility Scan (市场脆弱性, 零 LLM) ← NEW
    │     └── 脆弱性分数 → 传给 Decision
    │
Stage 8: Decision + Contrarian 挑战
    │     └── fragility_crossed > 2 → 追加脆弱性注释
    │
Stage 9: Archive + 保存预测 + 保存 Brief + 记录指标
    │
Post: 保存校准数据 (含 L2/L3/Decision 逐 Stage 字段)
      可能触发周审计 (7天间隔)
      可能触发 SHARP 规则进化 (精度持续性 <45%)
```

---

## 反馈闭环完整图

```
                          ┌──────────────────────────────────┐
                          │         日校准 (Layer 1)          │
                          │  ┌───────────────────────────┐   │
                          │  │ L1: 方向精度 + 量级分数   │   │
                          │  │ L2: 板块精度 + 选择精度   │   │
                          │  │ L3: 绿灯精度 + 红灯避免   │   │
                          │  │ Decision: 决策精度        │   │
                          │  └───────────────────────────┘   │
                          │  注入: 各 Stage system prompt     │
                          └──────────────┬───────────────────┘
                                         │
                          ┌──────────────┴───────────────────┐
                          │       周战术审计 (Layer 2)        │
                          │  7天间隔 → Flash 分析 Stage 健康  │
                          │  建议注入 L1 提示词              │
                          └──────────────┬───────────────────┘
                                         │
                          ┌──────────────┴───────────────────┐
                          │    SHARP 规则进化 (Layer 3)       │
                          │  触发: 7天+30天 精度均 <45%      │
                          │  StageAttribution → 生成假设      │
                          │  RuleValidator → walk-forward gate│
                          │  RuleEvolver → 原子编辑规则       │
                          │  → evolutions.jsonl → L1 读取     │
                          └──────────────┬───────────────────┘
                                         │
                    ┌────────────────────┴────────────────────┐
                    │          跨 Stage 实时反馈               │
                    │  ┌──────────────────────────────────┐   │
                    │  │ L1 早停 → 跳过后端 Stage         │   │
                    │  │ L2-L3 交叉检测 → 标的选择警告     │   │
                    │  │ Red Team → Resonance PBO 收紧    │   │
                    │  │ Fragility → Decision 风险警告    │   │
                    │  └──────────────────────────────────┘   │
                    └─────────────────────────────────────────┘
```

---

## 测试验证

| 测试 | 结果 |
|------|:--:|
| Pipeline tests (1,043) | ✅ All pass |
| API tests (45) | ✅ All pass |
| Mock pipeline `--lang zh` (L1 early terminate) | ✅ Triggered, ~4 Pro calls saved |
| Mock pipeline `--lang en` | ✅ Full 9-stage, no errors |

---

## 变更文件清单

| 文件 | 变更类型 | 说明 |
|------|:--:|------|
| `pipeline/orchestration.py` | Modify | L1 早停 + 逐 Stage 校准 + Fragility scan + Red Team→Resonance |
| `pipeline/daily_calibration.py` | Modify | DailyPrediction 扩展 + get_stage_calibration() |
| `pipeline/decision.py` | Modify | fragility 参数 + 脆弱性调整 |
| `pipeline/resonance.py` | Modify | data_mining_severity 参数 + PBO 阈值收紧 |
| `pipeline/layer2_fundamental.py` | Modify | calibration_context 参数 |
| `pipeline/layer3_technical.py` | Modify | calibration_context 参数 |

## References

| # | Source | Date | Type |
|---|--------|------|------|
| 1 | `pipeline/orchestration.py` (修改后) | 2026-05-31 | `[V]` primary |
| 2 | `pipeline/daily_calibration.py` (修改后) | 2026-05-31 | `[V]` primary |
| 3 | `pipeline/resonance.py` (修改后) | 2026-05-31 | `[V]` primary |
| 4 | `pipeline/decision.py` (修改后) | 2026-05-31 | `[V]` primary |
| 5 | `docs/dev/pipeline-iteration-audit-20260531.md` | 2026-05-31 | `[V]` secondary |
