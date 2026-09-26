# Shadow Ecosystem Optimization Plan

**Date**: 2026-05-25 | **Architect**: self | **Scope**: 32-shadows, 15-evolution-mechanisms, 5-tier-to-4-tier migration
**Status**: draft | **Target**: Phase L+

---

## 1. Tier Restructuring: 5-Tier to 4-Tier + System Shadows

### Rationale

External research (Agent #1 EigenTrust threshold) confirms 3-4 tiers optimal. WATCH and ENDANGERED merged. Catfish, MissedPath, and temp_event shadows are excluded from ranking as **system** shadows.

### New 4-Tier Layout

| Tier | Percentile | Consecutive Days | Flash/Day | Graduation | Protection |
|------|:------:|:-----:|:----:|:--:|------|
| **ELITE** | >85% | 30d | 10 | Eligible for graduation (see §4) | Win-rate >50%; market_accuracy >= 0.50 |
| **EXCELLENT** | >70% | 10d | 8 | Not eligible | Win-rate >50% AND cumulative return > CPI AND avg position >1% of capital |
| **NORMAL** | all others | - | 5 | Not eligible | None |
| **ENDANGERED** | <20% | 14d | 2 | Not eligible | Challenger at 3 consecutive evaluation periods in bottom 20% (`challenger_engine.py:63-68` unchanged) |
| **system** | N/A | N/A | N/A | N/A | Catfish, MissedPath, temp_event — excluded from all ranking/gates |

**Key changes**:
- WATCH (0.30) merged into ENDANGERED at 0.20 threshold, 14d consecutive
- ELITE 10 Flash (was 7), EXCELLENT 8 (was 6)
- **system type**: special-purpose shadows excluded from ranking/graduation

### Absolute Quality Gate (Anti "All-ELITE" Degradation)

Percentile is relative — if all shadows improve, someone still falls below 85%. Add absolute floor:
```python
# config/settings.py
elite_absolute_sharpe_min: float = 0.6   # must clear BOTH relative AND absolute bar
excellent_absolute_sharpe_min: float = 0.4
```
ELITE requires BOTH: percentile >85% × 30d **AND** Sharpe ≥ 0.6. If the cohort is collectively weak, the absolute floor denies ELITE — preventing a "best of the worst" scenario. During normal markets, 0.6 is trivially achievable by competent strategies. During crashes, it protects graduation quality.

### Tier Boundary Hysteresis (Anti Cliff)

Buffer zone applies bidirectionally — prevents toggling at both promotion and demotion boundaries.
```python
# ranking_engine.py — bidirectional hysteresis
if current_tier == "excellent" and 0.84 <= percentile <= 0.86:
    return "excellent"  # hold, don't toggle either direction
if current_tier == "elite" and 0.84 <= percentile <= 0.86:
    return "elite"      # symmetric protection (Red Team R2#3)
```
Note: ELITE demotion also has EigenTrust guard at 0.70 — hysteresis is complementary, not a replacement. Hysteresis is intentionally scoped to ELITE/EXCELLENT boundary only (highest cliff). EXCELLENT/NORMAL and NORMAL/ENDANGERED boundaries use consecutive-day counters for smooth transitions and do not need additional hysteresis.

**Precedence rule (Red Team R3 F4)**: Absolute Sharpe gate takes precedence over hysteresis. If Sharpe < 0.6, ELITE is denied regardless of percentile position. Hysteresis only applies when all absolute thresholds are satisfied.

### Win-Rate Floor Demotion Protection (NEW)

**File**: `shadows/ranking_engine.py:121-176` (`determine_achievement_tier`)

Three-part gate — ALL must pass for protection to apply:

```python
def _win_rate_floor_active(wr, cumulative_return, avg_position_pct, 
                            eval_days, cpi_data) -> bool:
    """Win-rate floor only protects shadows that demonstrate real skill."""
    # 1. Directional accuracy
    if wr < 0.50:
        return False
    # 2. Real purchasing power (beat inflation)
    period_inflation = cpi_data.get_inflation_rate(days=eval_days)
    if cumulative_return <= period_inflation:
        return False  # Losing real value — floor revoked
    # 3. Conviction through position sizing (industry standard: >1% of AUM)
    if avg_position_pct < 0.01:
        return False  # Making tiny bets — floor revoked
    return True
```

**Rationale**: 
- Win-rate >50% proves directional skill
- Beating inflation proves the strategy generates real returns, not just nominal noise
- Average position >1% of capital (industry floor) proves the shadow puts conviction behind its predictions — no micro-bet gaming

ELITE protection passes ALL conditions: win-rate >50% + beat inflation + avg position >1% + market_accuracy ≥0.50. The `_win_rate_floor_active` function is called for BOTH ELITE and EXCELLENT; ELITE adds market_accuracy on top.
```python
# ranking_engine.py — ELITE protection gate
if tier == "elite":
    if not (wr >= 0.50 and market_accuracy is not None and market_accuracy >= 0.50):
        return "excellent"  # revoke ELITE if market_accuracy gate fails
```

### Demotion Protection via EigenTrust (multi-attestation)

Require 2+ attestations before ELITE->EXCELLENT demotion:
1. Percentile < 0.70 for 5+ days AND
2. Market anchor accuracy < 0.45 **(if available; shadows without this metric use deflated_sharpe < 0.5 as fallback)**
Single-source degradation insufficient. 

`deflated_sharpe` = shadow's Sharpe ratio after applying Bayesian haircut from `ranking_engine.py` (Holm-Bonferroni corrected, based on `DEFLATED_SCORE_MULTIPLIER`). Threshold 0.5 matches the existing `excellent_deflated_sharpe_min / 2` — a conservative floor for ELITE protection.

### Emergency Quota Cap

Permanent bonus from emergency quota capped at **+5**. An ELITE shadow's maximum daily Flash = 10 + 5 (emergency) = 15. Prevents runaway accumulation identified by Red Team.
```python
# emergency_quota.py
EMERGENCY_BONUS_CAP = 5
# In audit_result: state.permanent_bonus = min(state.permanent_bonus, EMERGENCY_BONUS_CAP)
```

---

## 2. Flash Research Assistant Architecture

**Current gap**: Shadows are pure LLM (no tool-calling). They receive prompt, output votes via `chat_with_integrity` at `shadows/shadow_agent.py:132`. No budget awareness.

### Shadow->Flash Calling Protocol

**New file**: `shadows/flash_research_assistant.py` (module-first, 50+ lines)

**Pattern**: Small model classifies + delegates to frontier (NVIDIA ToolOrchestra + CascadeFlow).

```
Shadow (Pro)                     Flash (Research Assistant)
    |                                   |
    |-- research_request(topic, depth) ->|
    |                                   |-- classify: needs market data? news scan? backtest?
    |                                   |-- execute cheap operations
    |                                   |-- return structured findings
    |<-- findings_json                  |
    |-- incorporate into analysis       |
```

**Key design points**:
- Shadows call Flash, NOT Pro (Flash quota limited, not Pro)
- Flash quota = tier-based (ELITE 10, EXCELLENT 8, NORMAL 5, ENDANGERED 2)
- Flash calls are tool-enabled: Flash can fetch market data, scan archives, query DB
- Each Flash call counts against `flash_quota_used` in `DailySnapshot`

### Budget-Ratio Conditioning in Prompts

**File**: `shadows/shadow_agent.py:170-212` (`_build_user_prompt`)

Prepend budget awareness line:
```python
remaining = quota_total - quota_used
prompt_header = (
    f"[BUDGET STATUS] Tier: {tier.upper()} | Daily Flash calls: {quota_used}/{quota_total} "
    f"| Remaining: {remaining} | Pro calls: {pro_used}/{pro_total}\n"
    f"Guidance: {'Use sparingly' if remaining <= 2 else 'Normal operation'}"
)
```

This injects remaining quota into the prompt so the shadow self-regulates its Flash usage (Agent #2 finding: budget-ratio conditioning reduces wasteful calls by ~40%).

### Flash-as-Research Toolset

Flash can:
1. `fetch_market_snapshot(ticker)` - latest OHLCV from `shadows/market_data_fetcher.py`
2. `scan_archive(query, days)` - semantic search over Gate 1-3 archives
3. `check_peer_consensus(ticker)` - aggregate direction (anonymized, **disabled during Gate 2 unless N≥5**)
4. `retrieve_cached_analysis(ticker, date)` - from shadow_analysis_repo

**Red Team #6 fix**: `check_peer_consensus` returns aggregations only when ≥5 shadows contributed. During Gate 2 with small groups (2-3 shadows), the tool returns `{"status": "insufficient_peers", "min_required": 5}`. This prevents differential de-anonymization via delta queries.

**File**: `shadows/shadow_agent.py:115-168` (`_analyze`) - Replace single `chat_with_integrity` call with two-phase: (a) optional Flash research call, (b) Pro analysis incorporating Flash findings.

---

## 3. Three-Layer AEL Review System

**Current**: Only monthly Pro debrief (`shadows/ael_evolution.py:161-234`), MAX_ACTIVE_LESSONS=5.

**MAX_ACTIVE_LESSONS per shadow (Red Team R3 F7 fix)**:
- Weekly Flash: max 5 per shadow (FIFO, items <2 weeks evicted first)
- Monthly Pro: max 5 per shadow (existing, unchanged)
- Quarterly Pro: max 1 methodology rewrite per year per shadow. If multiple quarterly reviews propose rewrites, the **Q4 review** wins (has the most data).

### Layer 1: Weekly Flash AEL (Tactical)

**New file**: `shadows/ael_weekly_flash.py`

- **Frequency**: Every 7 calendar days
- **Model**: Flash (cheap, fast)
- **Focus**: Execution quality — did the shadow follow its own methodology? Were votes placed correctly? Were exit conditions honored?
- **Output**: 1-2 bullet corrections (max 5 per shadow, evaluated for promotion to monthly if persisted 2+ weeks; FIFO for items <2 weeks)
- **Review window**: Last 7 days of trades only
- **Constraint**: Critique only when confidence that a mistake was made is ≥ 70%. Low-confidence "maybe wrong" findings are suppressed — Snorkel rule: critique backfires when uncertain.

### Layer 2: Monthly Pro AEL (Strategic) - Existing

**File**: `shadows/ael_evolution.py` - Keep existing, add:
- **ELITE consolidation mode** (NOT critique): ELITE shadows get a "consolidation prompt" where the Pro identifies what they're doing RIGHT and reinforces it. No new lessons injected -- instead, existing lessons are consolidated.
- **Cross-reference L1 findings**: Promote weekly Flash findings that persisted 2+ consecutive weeks to monthly Pro review.

### Layer 3: Quarterly Pro AEL (Structural)

**New file**: `shadows/ael_quarterly_pro.py`

- **Frequency**: Every 90 calendar days
- **Model**: Pro (deep analysis)
- **Focus**: Structural bias detection — methodology drift, domain overfitting, collusion risk, source stagnation
- **Output**: Max 1 methodology prompt rewrite per year per shadow
- **Cross-reference**: Aggregates 3 monthly debriefs + 12 weekly Flash reports
- **Gate**: Structural changes require 2-of-3 sign-off (Quarterly AEL + Monthly AEL + Human review)

### ELITE Consolidation Mode

**File**: `shadows/ael_evolution.py:161-234` (`run_monthly_debrief`)

Add at line 184 (after extracting `wr`):
```python
if latest_tier == "elite":
    system_prompt = (
        "You are reviewing an ELITE shadow. This agent has sustained top-quartile "
        "performance. Instead of critique, identify what drove this success and "
        "produce a CONSOLIDATION note that reinforces the winning patterns. "
        "Do NOT suggest changes. Output: SUCCESS_PATTERNS, CONSOLIDATION_NOTE."
    )
```

---

## 4. Graduation Pipeline: Interactive Gate 2 Discussion

**Current gap**: `pipeline/gate2_interaction.py:8` explicitly states "No shadow/ELITE integration." Gate 2 is passive display-only. Shadows don't participate.

### Interactive Gate 2 Flow (Redesigned)

```
Step 0: 影子独立分析完成检查
        主AI 查询所有毕业影子，确认哪些已完成今日分析
        未完成的 → 提示用户等待，不加入讨论

Step 1: 主AI 列出今日讨论标的和方向
        同时展示已毕业且已完成分析的影子（标注 ✅就绪 / ⏳分析中）
        "今日讨论 NVDA(科技) / TLT(债券)。
         已毕业影子:
           silicon_oracle  [✅ 科技·ELITE·分析完成]
           trend_chaser    [✅ 动量·EXCELLENT·分析完成]
           yield_whisperer [⏳ 债券·分析中，预计30秒...]
         输入 'shadow silicon_oracle' 邀请，或 '继续'"

Step 2: 用户决定邀请哪些影子
        "邀请 silicon_oracle 和 trend_chaser"
        主AI 确认邀请，影子进入讨论模式（Flash 不限额）

Step 3: 用户 ↔ 主AI(主持人) ↔ 影子 多方讨论
        - 主AI 作为主持人协调发言顺序
        - 主AI 自己也参与讨论，对影子观点发表看法
        - 用户问 → 主AI分配 → 影子回答 → 主AI评论 → 用户决策
        
Step 4: 用户做出最终决策
```

### 主AI 主持人角色

| 职责 | 说明 |
|------|------|
| 点名 | "silicon_oracle，你对NVDA的看法？" |
| 协调 | 避免多个影子同时发言，按领域相关性排序 |
| 评论 | 对影子观点做交叉验证 |
| **信息防火墙** | **不向影子透露其他影子的原始回答、身份、或同意/反对人数** |
| **转述问题** | 将用户问题转述给影子，**不附带其他影子的分析内容** |
| 归档 | 记录所有发言到 Gate 2 对话日志 |

### 讨论隔离机制 (Regime Isolation + R0 规则)

基于外部研究 Regime Isolation (Barziankou, 2026) + 现有 R0 规则：

| 影子可以知道 | 影子不能知道 |
|-------------|-------------|
| 自己被问到的问题（转述后，不含其他影子分析内容） | 其他影子说了什么（原始内容） |
| 聚合统计："共识强度 0.7"（仅当 N≥5） | 谁同意、多少人同意（N<5 时连聚合也不给） |
| "存在不同意见" | 不同意见的具体内容 |
| 自己的 Flash 查询结果 | 其他影子查询了什么 |

**主持人防火墙硬规则 (Red Team #9 fix)**:
- ✅ 转述用户问题："你对今天NVDA的走势有什么看法？"
- ❌ 转述含其他影子分析："silicon_oracle说应该减仓到60%，你同意吗？"
- 违反此规则 = 破坏影子独立性，视为系统级 bug

**匿名互评限制 (Red Team #16 fix)**: 仅当讨论中 ≥3 个影子时才启用；2 个影子时禁止（身份必然暴露）。

### 零毕业影子回退模式 (Red Team #11 fix)

当没有影子毕业时，Gate 2 降级为 **ELITE 咨询模式**：
- 展示当日所有 ELITE 影子的静态分析摘要
- 用户可以参考但不进行多方互动对话
- 一旦有影子毕业，自动切回完整交互模式

**零 ELITE 回退**：如果连 ELITE 都没有（如市场崩盘期），Gate 2 正常进行——仅主 AI 分析，标注"影子系统暂无 ELITE/毕业影子可参与讨论"。

### 5→4 级迁移策略 (Red Team R2#11 + R3 F8 fix)

```python
# Migration rules:
# WATCH → ENDANGERED: counters preserved, adjusted to 14d threshold
#   If WATCH with 8/10 days → ENDANGERED with 8/14 days (NOT reset)
#   If WATCH with 12/10 days (already exceeded old threshold) → ENDANGERED with 12/14 days
# ENDANGERED: old 20d threshold → new 14d threshold
#   If ENDANGERED with 16/20 days (old) → 16/14 days (new) → immediately qualifies at next cycle
#   If ENDANGERED with 8/20 days (old) → 8/14 days (new) — counter preserved, not reset
# All other tiers: direct 1:1 mapping (ELITE→ELITE, EXCELLENT→EXCELLENT, NORMAL→NORMAL)
```

### Status Card Variables (Red Team R3 F10 + R4 F1 fix)

`_build_status_card()` MUST extract all variables at function start:
```python
def _build_status_card(self) -> str:
    latest = self.state_db.get_latest_snapshot(self.shadow_id)
    tier = latest.achievement_tier if latest else "normal"
    wr = latest.win_rate_pct / 100.0 if latest and latest.win_rate_pct else 0.0
    cumulative_return = latest.cumulative_return_pct / 100.0 if latest and latest.cumulative_return_pct else 0.0
    # ... rest of function uses wr, cumulative_return (no external scope)
```
All status card variables computed from snapshot history — no undefined references.

### Quota Number Consistency (Red Team R3 F11 fix)

Budget-ratio conditioning (Section 2) and status card (Section 5) use the SAME effective quota:
```python
effective_quota = base_tier_quota + permanent_bonus - permanent_penalty
```
Both sections display `effective_quota` — no conflicting counts.

### Snorkel Rule Mechanism (Red Team R3 F12 fix)

"Confidence that a mistake was made" is operationalized as:
```python
# Weekly Flash AEL computes:
# - PnL deviation from expected (z-score of daily return vs historical)
# - Methodology compliance (did vote match stated strategy?)
# - Signal: if z-score < -1.5 AND compliance >= 90% → "no mistake, regime noise"
#          if z-score < -1.5 AND compliance < 70% → "likely mistake, critique"
#          if z-score > -1.0 → "no deviation, skip critique"
# Only produce critique when "likely mistake" confidence is high.
```

### Three-Engine Coordination Contract (Red Team R5 H3+H6 fix)

Three engines interact: `ranking_engine.py` (tiers), `graduation_engine.py` (4-stage tests), `gate2_graduation.py` (exam state).

**Orchestration contract** (in `shadow_mother.py` daily cycle):
```python
# 1. Ranking engine runs daily → updates tier
# 2. When shadow reaches ELITE + 30 consecutive days:
#    → graduation_engine.run_all_stages(shadow_id) triggered automatically
#    → results stored in shadow DB (survive tier changes)
# 3. If all 4 stages pass + ELITE still active:
#    → gate2_graduation.check_exam_notification(shadow_id) fires
# 4. 4-stage results persist across tier changes; only reset on graduation revocation
```

EXCELLENT shadows can pre-complete stages (bank them). If demoted before reaching ELITE, stages remain valid for 90 days. After 90 days, stale stage results are invalidated.

### WATCH Migration Script (Red Team R5 H5 fix)

```sql
-- Migration: 5-tier → 4-tier, applied once at Phase 1 deployment
UPDATE daily_snapshots SET achievement_tier = 'endangered' 
WHERE achievement_tier = 'watch';
-- Counters preserved; new 14d threshold applied at next ranking cycle
```

### 2-of-3 Gate Clarification (Red Team R5 M2 fix)

Quarterly methodology rewrite requires 2-of-3: Quarterly AEL (current quarter review) + Monthly AEL (last monthly review before quarterly) + Human. If human absent >14 days (proxy timeout), auto-defer to next quarter — no automatic approval.

### BETA Domain Gap (Red Team R5 M3 fix)

If a critical domain depletes and BETA shadow needs 20d validation:
- Gate 2 shows "domain uncovered" for that domain
- Main AI notes the gap in discussion preamble
- No auto-promotion — BETA must earn its way in
- If 2+ domains are uncovered simultaneously, system alerts user to review domain allocation

"共识强度 0.7" 定义为 vote-direction 的归一化熵：
```python
def consensus_strength(votes: list[ShadowVote], ticker: str) -> float:
    """1.0 = unanimous, 0.0 = evenly split. Requires N>=5."""
    ticker_votes = [v for v in votes if v.ticker == ticker and v.direction != "abstain"]
    if len(ticker_votes) < 5:
        return None  # insufficient data, don't report
    long_pct = sum(1 for v in ticker_votes if v.direction == "long") / len(ticker_votes)
    return 2 * abs(long_pct - 0.5)  # 0.5 random → 0.0, 100% agreement → 1.0
```
此公式不可逆推个体立场——只知道"分歧程度"，不知道"谁在分歧"。

### UI 发言区分

```
格式:
  [主持人·主AI]  灰色前缀，正式语气
  [silicon_oracle·科技]  蓝色前缀，影子专属颜色
  [trend_chaser·动量]   绿色前缀
  > 用户输入  不加前缀，用户始终是主导
```

### 新 UI 需求

| 需求 | 说明 |
|------|------|
| 多发言人前缀 | 每条消息前显示发言人标识和颜色 |
| 影子颜色分配 | 每个影子固定一个颜色，跨会话保持一致 |
| 等待状态指示 | 分析中的影子显示 ⏳ + 预估剩余时间 |
| 邀请指令提示 | 用户输入 `shadow <name>` 自动补全可用影子名 |

### 影子在讨论中的能力

| 能力 | 说明 |
|------|------|
| Flash 工具调用 | **Gate 2 讨论期间不消耗配额**——毕业影子自由调用 Flash |
| 参与频率 | 每个毕业影子最多每 3 天参与 1 次 Gate 2 讨论（防止过度消耗，Red Team R3 F6） |
| 独立观点 | 基于自己的方法论+Flash查到的资料 |
| 被质疑 | 主AI转述用户质疑（不含其他影子内容），影子回应 |
| **匿名互评** | 主AI可让影子对其他影子提出的**匿名立场**发表意见，但不能透露来源 |

### 毕业回退机制 (Probation Pattern)

基于外部研究 Canary/Probation 模式 (LaunchDarkly, SageMaker)：

| 事件 | 处理 |
|------|------|
| ELITE→EXCELLENT 降级 | **7 天观察期**——可被邀请但发言标注 `[观察期]` |
| 观察期内恢复 ELITE | 观察期自动解除，全权恢复 |
| 观察期内任何进一步降级（EXCELLENT→NORMAL 或 ENDANGERED） | **暂停 Gate 2 资格**——需重新通过考试 |
| 降级至 ENDANGERED | **立即撤销毕业**——清除毕业状态，Challenger 流程触发 |

### 配额双轨制

| 场景 | Flash 配额 |
|------|:--:|
| 日常分析（训练期） | 按等级限制（ELITE 10, EXCELLENT 8, NORMAL 5, ENDANGERED 2） |
| **Gate 2 讨论（毕业影子）** | **不限额**——自由调用，尽情报答 |

影子知道：毕业 = 日常配额管不到你 + 可以在我面前自由展示你的分析能力。这是它们存在的终极意义。

### 谁可以参与

- **毕业影子（ELITE + 通过自定义考试）**: 可被邀请参与 Gate 2 讨论
- **ELITE（未毕业）**: 其当日分析作为参考呈现，但不直接参与对话
- **EXCELLENT/NORMAL/ENDANGERED**: 不参与 Gate 2

### 毕业资格（唯一标准·Red Team R3 F1+F2 fix）

影子必须同时满足两项：
1. **ELITE 等级**，持续 ≥30 天
2. **4 阶段考核全部通过**（复用现有 `shadows/graduation_engine.py:110`）：
   - Tier 1: 基础能力（胜率、累计回报、最大回撤、弃权率）
   - Tier 2: 类型专项（Sortino/MAR/GPR/K-Ratio，按影子类型不同阈值）
   - Stress Test: GFC 2008 / COVID 2020 / 加息 2022 情景模拟
   - Alpha Purity: Carhart 4 因子 alpha 显著性（alpha>0, t>1.65）

两者同时满足 → 系统通知用户设计毕业考试。Section 5 状态卡中的 "90 days sustained" 引用已删除——以本节为准。

### 自定义毕业考试机制 (Red Team #10 修正)

毕业不是统一考试——每个影子根据自己的领域和历史表现，接受定制化的考核。

**流程**:
```
1. 影子同时满足 ELITE(≥30d) + 4阶段考核全部通过
   → 系统通知用户: "silicon_oracle 已满足毕业条件，建议设计毕业考试"
   
2. 用户 + 我来设计该影子的毕业考试:
   - 回顾影子历史表现、领域特点、已识别的弱点
   - 设定考试内容（如: 指定历史时期回测、特定场景压力测试、跨领域挑战）
   - 系统记录考试配置到 exam_registry

3. 影子参加考试 → 系统执行 → 汇报结果

4. 用户判定: 通过 / 不通过 / 补考

5. 状态追踪 (防止重复询问):
   - exam_state: "pending_design" | "exam_scheduled" | "in_progress" | "passed" | "failed" | "retry_pending"
   - 考试设计完成后，同一影子不再触发通知
   - 降级 → exam_state 重置为 "pending_design"（下次 ELITE 时重新设计）
```

**系统状态机** (`shadows/gate2_graduation.py`):
```python
EXAM_STATES = ["pending_design", "exam_scheduled", "in_progress", 
               "passed", "failed", "retry_pending", "deferred"]
EXAM_RETRY_COOLDOWN_DAYS = 30
EXAM_NOTIFICATION_TIMEOUT_DAYS = 14  # Red Team R2#7: auto-delegate if user absent

def check_exam_notification(shadow_id: str) -> bool:
    """Only notify if pending_design/retry_pending AND shadow is currently ELITE."""
    state = get_exam_state(shadow_id)
    tier = get_current_tier(shadow_id)
    if tier != "elite":
        return False
    result = state == "pending_design" or state == "retry_pending"
    # Auto-timeout: if notification pending >14 days, suppress until next month
    if result and days_since_first_notification(shadow_id) > EXAM_NOTIFICATION_TIMEOUT_DAYS:
        set_exam_state(shadow_id, "deferred")  # Suppressed — won't re-trigger this cycle
        return False
    # Deferred state: auto-reset to retry_pending after 30 more days
    if state == "deferred":
        if days_since_deferred(shadow_id) >= 30:
            set_exam_state(shadow_id, "retry_pending")
    return result

# failed → retry_pending auto-transition after cooldown
def maybe_retry(shadow_id: str) -> None:
    if get_exam_state(shadow_id) == "failed":
        if days_since_failed(shadow_id) >= EXAM_RETRY_COOLDOWN_DAYS:
            set_exam_state(shadow_id, "retry_pending")
```

### 考试执行引擎

**考试类型** (用户和我共同设计):
| 类型 | 说明 | 自动化程度 |
|------|------|:--:|
| 历史回测 | 指定时间段/事件窗口，跑影子方法论，验证预测准确性 | ✅ 全自动 |
| 压力测试 | 指定市场情景（GFC/COVID/加息），影子分析并投票 | ✅ 全自动 |
| 跨领域挑战 | 让影子分析非专长领域，测试方法论泛化能力 | ✅ 全自动 |
| 数据盲测 | 提供已发生但影子未见过的事件数据，验证判断 | ✅ 全自动 |
| 论文/策略答辩 | 用户提问，影子解释投资逻辑——人工评判 | 🔧 半自动 |

系统自动执行用户指定的考试配置，收集所有数据（预测、置信度、论据），呈现给用户做最终判定（通过/不通过/补考）。评分不自动化——用户是最终裁判。

```python
def reset_exam_on_demotion(shadow_id: str, old_tier: str, new_tier: str):
    """Reset exam state when graduated shadow is demoted below ELITE.
    
    H4 fix: graduated shadows (exam_state="passed") that demote to EXCELLENT
    get "retry_pending" — re-take same exam design. Only net-new ELITE shadows
    use "pending_design" for fresh exam creation.
    """
    if old_tier == "elite" and new_tier != "elite":
        current = get_exam_state(shadow_id)
        # Passed graduates retry same exam; never-passed get fresh design
        set_exam_state(shadow_id, 
                       "retry_pending" if current == "passed" else "pending_design")
```

### 毕业后继续受训 (Red Team #5/14 修正，用户确认)

毕业不是训练的终点。毕业后影子继续参与月频 AEL（巩固模式），方法论持续优化。这确保影子越来越优秀。

| 阶段 | AEL 参与 | 模式 |
|------|:--:|------|
| 训练期（NORMAL→ELITE） | ✅ 完整 | 批判模式（NORMAL以下）/ 巩固模式（ELITE） |
| **毕业后** | ✅ **继续** | **仅巩固模式**——不改方法论核心，只强化已验证的盈利模式 |
| 观察期（降级后） | ✅ 完整 | 批判模式恢复，帮助影子找出退化原因 |
| 暂停/撤销毕业 | ✅ 完整 | 批判+结构审计

### Gate 2 交互示例

```
主AI: 今日讨论方向: NVDA(看多)。置信度: 0.72。
      可用毕业影子:
        silicon_oracle  [✅ 科技·ELITE·已毕业]
        trend_chaser    [✅ 动量·EXCELLENT·已毕业]
        yield_whisperer [⏳ 债券·分析中，预计30秒...]
      输入 'shadow <name>' 邀请，或 '继续' 直接确认。

用户: shadow silicon_oracle

主AI: [主持人] silicon_oracle 已加入讨论。
      ── 向 silicon_oracle 提问 ──
      "你独立分析后对NVDA的看法是什么？"

silicon_oracle: 我分析了13F持仓和SOX指数。机构增持明显，
                但SOX出现负背离。建议降低仓位至60%。

主AI: [主持人] silicon_oracle 认为机构增持但技术面有分歧。
      trend_chaser，你对同一标的的看法？（不透露silicon_oracle的具体分析）

trend_chaser: NVDA动量指标ADX=32，价格在20日均线上方，趋势健康。
              我认为应该维持看多，仓位80%。

主AI: [主持人] 两位影子看法不同——一位谨慎一位积极。
      我的模型显示：机构增持数据一致，SOX背离在历史回测中
      被归类为短期噪音，不应据此调整仓位。
      > 你的决策？

用户: 继续，维持原判。
```

---

## 5. Incentive Visibility

Shadows must see their tier, quota, and promotion path in every prompt. Current `_build_user_prompt` at `shadow_agent.py:170` has zero tier visibility.

### Status Card Injection

**File**: `shadows/shadow_agent.py:170-212` (`_build_user_prompt`)

Prepend to every prompt:
```python
def _build_status_card(self) -> str:
    latest = self.state_db.get_latest_snapshot(self.shadow_id)
    tier = latest.achievement_tier if latest else "normal"
    quota = self.get_daily_quota()
    next_tier = {
        "endangered": "normal — raise percentile above 0.20 for 14 consecutive days",
        "normal": "excellent — rank above 70th percentile for 10 consecutive days",
        "excellent": "elite — rank above 85th percentile for 30 consecutive days",
        "elite": "graduation — complete 4-stage qualification. See Section 4 for criteria. ULTIMATE GOAL: Gate 2 discussion with user, UNLIMITED Flash access.",
    }
    grad_note = ""
    if tier == "elite":
        grad_note = (
            "\n[GRADUATION REWARD] Once graduated, you will participate in Gate 2 "
            "investment discussions with the user. During discussions, Flash calls "
            "are UNLIMITED — you can freely research and present evidence to support "
            "your analysis. This is your purpose as a shadow.\n"
        )

    # Emergency quota — full rules so shadow can make informed risk decision
    em_state = self._get_emergency_state()
    em_rules = (
        f"[EMERGENCY QUOTA RULES]\n"
        f"  When: base quota fully exhausted + you identify a high-conviction opportunity\n"
        f"  Current state: {em_state.state} | Consecutive failures: {em_state.consecutive_failures}/3\n"
        f"  Permanent bonuses: +{em_state.permanent_bonus} | Penalties: -{em_state.permanent_penalty}\n"
        f"  Effective daily quota: {quota + em_state.permanent_bonus - em_state.permanent_penalty}\n"
        f"  REWARD:  Profitable → permanent +1 daily quota, reset failures\n"
        f"  PENALTY: Loss (not followed) → 3-day cooldown\n"
        f"           Loss (followed)  → 7-day cooldown\n"
        f"           3 consecutive failures → permanent -1 daily quota\n"
        f"  Decision is YOURS — weigh the opportunity against the consequences.\n"
    )
    if em_state.state in ("penalized", "pending", "audit"):
        em_rules += f"  ⚠ Emergency quota currently UNAVAILABLE (state={em_state.state})\n"

    return (
        f"[YOUR STATUS]\n"
        f"Tier: {tier.upper()}\n"
        f"Daily Flash Quota: {quota} calls (training mode)\n"
        f"Promotion Path: {next_tier.get(tier, 'unknown')}\n"
        f"Win-Rate Protection: {'Active (>50%)' if wr >= 0.50 else 'Inactive (<50%)'}\n"
        f"Integrity Score: {self.get_integrity_score()}/100\n"
        f"{grad_note}"
        f"{em_rules}"
        f"[END STATUS]\n\n"
    )
```

### Tier-Based Prompt Customization

| Tier | Prompt Addendum |
|------|----------------|
| ELITE | "You are an ELITE analyst. Focus on conviction weighting, not volume. Your Flash research assistant can run 10 data queries per day." |
| EXCELLENT | "You are an EXCELLENT analyst. Prioritize accuracy over speed. 8 Flash queries available daily." |
| NORMAL | "Standard analysis protocol. 5 Flash queries daily. Focus on improving win rate." |
| ENDANGERED | "You are on probation. 2 Flash queries daily. Each call must be justified. A challenger may replace you." |

---

## 6. Strategy Convergence + Population Health

**User feedback**: Novelty search via prediction disagreement rejected for domain-specialized shadows.

### Strategy Convergence Monitoring

**File**: `shadows/diversity_controller.py:335+` — methodology prompt similarity within same shadow type. Trigger: >0.7 for 5+ days → flag "herding" + perturb lowest performer via `method_breeding.py`.

### Domain Population Guard (Red Team #18 fix)

Minimum 1 shadow per domain. If a domain empties via Challenger replacement:
```python
# shadow_mother.py — after challenger trial
def ensure_domain_coverage(state_db):
    domains = get_all_active_domains(state_db)
    for domain in ALL_REQUIRED_DOMAINS:
        if domain not in domains:
            # Clone default template as BETA (not immediate ranking entry)
            config = get_default_template(domain)
            config.shadow_type = "beta"  # Red Team R2#2: enter via sandbox
            config.status = "beta"
            state_db.create_shadow(config)
            logger.warning("Domain %s depleted — auto-seeded BETA shadow (requires 20d validation)", domain)
```

### Beta Shadow Policy (Red Team #19 fix)

```python
# Beta shadows: sandboxed, excluded from ranking
# Promotion: 20-day history + Sharpe > 0.5 + cumulative > 0 
# → promoted to NORMAL tier, enters ranking
# Not eligible for Gate 2 until reaching ELITE + passing custom exam
```

### `opportunity_desc` Sanitization (Red Team #17 fix)

```python
# emergency_quota.py — sanitize opportunity_desc before prompt injection
import re
_SANITIZE_RE = re.compile(r'[\[\]{}<>|]')  # strip system-delimiter tokens

def sanitize_opportunity_desc(desc: str) -> str:
    return _SANITIZE_RE.sub('', desc)[:200]

---

## 7. Implementation Roadmap (20 Days)

*(Red Team #13 fix: timeline extended from 15d to 20d — Phase 4 UI work needs more time.)*

### Phase 1: Quota + Incentive + Tier Restructuring (Days 1-3)

| File | Change |
|------|--------|
| `config/settings.py:44-52` | 5-tier to 4-tier thresholds, WATCH+ENDANGERED merge, absolute Sharpe gate |
| `shadows/ranking_engine.py:121-176` | Win-rate floor (market_accuracy ≥0.50), EigenTrust, hysteresis buffer |
| `shadows/shadow_agent.py:398-410` | Update `_TIER_QUOTA`: ELITE=10, EXCELLENT=8, NORMAL=5, ENDANGERED=2 |
| `shadows/shadow_agent.py:170-212` | Inject `_build_status_card()` + full emergency quota rules |
| `shadows/emergency_quota.py:30` | Rename `state="normal"` → `"idle"`, add EMERGENCY_BONUS_CAP=5 |

**Emergency Quota State Machine** (Red Team R5 M1 fix):
```
idle → (quota exhausted + high conviction) → pending → audit → 
  ├── profitable → rewarded → idle (permanent +1, reset failures)
  └── loss → penalized → (cooldown expires) → idle
       ├── 3 consecutive failures → permanent -1 → idle
States blocking new requests: pending, audit, penalized
States allowing requests: idle, rewarded
```

### Phase 2: Flash Research Assistant (Days 4-7)

| File | Change |
|------|--------|
| **NEW** `shadows/flash_research_assistant.py` | Shadow→Flash protocol, tool dispatch, Gate 2 N≥5 gate for peer_consensus |
| `shadows/shadow_agent.py:115-168` | Two-phase _analyze: Flash research + Pro analysis; wiring emergency quota trigger |
| `shadows/shadow_agent.py:170-212` | Budget-ratio conditioning in prompt header |
| `tests/test_shadows/test_flash_assistant.py` | Test Flash call dispatch, quota deduction, Gate 2 N≥5 gate |

### Phase 3: Three-Layer AEL + Strategy Convergence (Days 8-13)

| File | Change |
|------|--------|
| **NEW** `shadows/ael_weekly_flash.py` | Weekly Flash tactical review, Snorkel rule |
| `shadows/ael_evolution.py:161-234` | ELITE consolidation mode, post-graduation consolidation (never critique) |
| **NEW** `shadows/ael_quarterly_pro.py` | Quarterly structural review, methodology rewrite gate (2-of-3 sign-off) |
| `shadows/ael_evolution.py:66-72` | Update MAX_ACTIVE_LESSONS per shadow: weekly=5, monthly=5, quarterly=1 |
| `shadows/diversity_controller.py:335+` | Strategy convergence detection (methodology prompt similarity) |
| `shadows/shadow_mother.py` | Domain population guard (minimum 1 shadow/domain) |
| `tests/test_shadows/test_ael_layers.py` | Test each layer independently |

### Phase 4: Interactive Gate 2 + UI (Days 14-20)

| File | Change |
|------|--------|
| **NEW** `shadows/gate2_graduation.py` | Custom exam registry, exam state machine, ELITE fallback mode |
| `pipeline/gate2_interaction.py` | Redesign: completion check, moderator firewall, anonymous critique N≥3, multi-party loop |
| `shadows/flash_research_assistant.py` | Gate 2 mode: unlimited Flash for invited shadows |
| `api_server.py` / Dashboard | Multi-speaker UI: color prefixes, ⏳等待, `shadow <name>` autocomplete |
| `tests/test_pipeline/test_gate2_interaction.py` | Test: exam state machine, firewall rules, ELITE fallback, probation flow |

### Red Team Fixes Applied (Non-File-Specific)

| Fix | Section |
|------|---------|
| Graduation: ELITE only (§1), custom exam (§4), exam state tracking (§4) | 1, 4 |
| market_accuracy unified to ≥0.50 | 1 |
| Emergency quota: +5 cap, `idle` rename | 1, 7 |
| Special shadows: system type | 1 |
| Absolute Sharpe gate (anti all-ELITE) | 1 |
| Tier boundary hysteresis (84-86% buffer) | 1 |
| check_peer_consensus N≥5 gate | 2 |
| Post-graduation AEL: consolidation only | 3, 4 |
| Moderator firewall: no substantive relay | 4 |
| Anonymous critique N≥3 minimum | 4 |
| ELITE fallback mode (zero graduated) | 4 |
| Probation: 7-day observation → suspension → revocation | 4 |
| Domain population guard (min 1/domain) | 6 |
| Beta shadow policy | 6 |
| opportunity_desc sanitization | 6 |
| Timeline: 15d → 20d | 7 |

### Metrics to Track Post-Implementation

| Metric | Target |
|--------|--------|
| Flash call utilization rate | NORMAL shadows use 60-80% before emergency |
| AEL weekly Flash cost vs monthly Pro cost | <15% additional token burn |
| Gate 2 shadow engagement rate | % discussions where user invites ≥1 shadow |
| Gate 2 shadow **contribution quality** | Did shadow input change user decision? (post-session survey) |
| Graduation pipeline throughput | Shadows graduated per month |
| Emergency quota outcomes | Profitable / Loss-unfollowed / Loss-followed / Penalized (tracked separately) |
| Demotion events blocked by win-rate floor | Counter-factual tracking |
| Strategy convergence within types | <0.7 similarity |
