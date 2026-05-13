# Phase B+ Ideation Notes

## Source: Grill Me Round 1 + Design Doc v1.2 (2026-05-10)

---

## 1. Shadow Analysis Workflow (Redesign)

**Current**: Each shadow receives same news+market_data → one LLM call → output votes. Stateless.
**Target**: Shadows as independent researchers with multi-round analysis:

1. Read personal memory (past decisions, successes, failures)
2. Read today's raw news/facts
3. Watch user + main AI discussion (user's opinions + submitted materials) — but NOT the main AI's pre-discussion report/analysis (to avoid anchoring)
4. Preliminary analysis
5. Use Flash quota to request additional data (iterative, decided by shadow)
6. Judge whether to continue deep-diving or make decision
7. Investment decision

**Key insight**: Shadows see user's raw opinions and materials, NOT the main AI's analysis. This preserves shadow independence.

---

## 2. Flash Quota System

- Each shadow has fixed Flash query quota (tier-based, see #3)
- Shadows decide what data to search for, consume quota per query
- After each data retrieval: analyze → decide to continue or stop
- **Quota-saving incentive**: If shadow makes correct decision (positive return) without using full quota → promotion acceleration. Bonus proportional to return magnitude.
- **Quota-saving penalty**: If shadow makes wrong decision without using full quota → mild promotion slowdown (not severe, to avoid discouraging bold decisions)
- **Inaction while saving**: No reward (wastes discovery opportunities)
- **Emergency quota**: ONLY triggered when base quota is exhausted, not on confidence threshold

---

## 3. Tier-Based Quota Scaling

From design doc section 7.2:

| Tier | Flash Calls/Day | Condition |
|------|----------------|-----------|
| ELITE | 7 | 30 consecutive days composite > p85 + deflated Sharpe > 0.8 |
| EXCELLENT | 6 | 10 consecutive days composite > p70 + deflated Sharpe > 0.6 |
| NORMAL | 5 | Default starting point |
| WATCH | 3 | Composite < p30 for 10 days, or MDD > 30% |
| ENDANGERED | 1 | Composite < p15 for 20 days |

**Gap**: Code computes tiers correctly but `get_daily_quota()` returns flat default for all.

---

## 4. ELITE Shadow Participation

From design doc section 7.5:
- ELITE shadows participate in Gate 2 (信号确认) — contribute analysis opinions but NO decision authority
- Domain-triggered: when user discusses a topic in that shadow's domain, it can speak
- ELITE shadows work at the SAME TIME as main AI (not after discussion), analyzing daily news independently
- Await being "awakened" by user mention or domain trigger

**Gap**: No code exists for this mechanism.

---

## 5. Dynamic Win Rate Line

User's new idea (not in design doc):

**Problem**: Fixed win rate threshold is too rigid. Different domains have different win rate/profitability trade-offs.

**Design**:
- **Early stage** (new shadows): Heavily incentivize win rate. Win rate line starts high, encouraging conservative, direction-accurate learning.
- **Mature stage** (experienced shadows): Once win rate is in high water, allow trading some win rate for higher profitability. Win rate line becomes more flexible.
- **Domain flexibility**: Some domains naturally have lower win rates but higher per-trade profit (e.g., contrarian strategies). Allow them to operate below line if profitability compensates.
- **Hard floor**: Win rate cannot go below an absolute minimum.
- **Dynamic line**: Formula that considers shadow age, domain, and current win rate percentile.

**Win rate penalty zone**:
- Below line → win rate becomes penalty weight, profitability downward-pressured
- Above line → profitability bonus kicks in
- Negative profitability → becomes the LARGEST penalty weight (regardless of win rate)

---

## 6. Anti-Conservatism / Plateau Penalties

User insists: ranking must actively penalize conservative/lazy shadows.

Three mechanisms (from design doc 7.4):

1. **Plateau detection** (`detect_plateau()` exists but never called):
   - No ELITE tier for 126+ days → 0.5 stagnation score
   - Win rate fluctuation < threshold → stability penalty
   - No insight produced recently → drought penalty
   - Score >= 0.5 → flagged as plateaued

2. **Abstention penalty**: `abstention_days` tracked but weight=0 in composite. Should penalize excessive cash-holding.

3. **Reset trigger** (design doc, not in code):
   - 6 months never reaching EXCELLENT
   - 3 months win rate fluctuation < ±5% (coasting)
   - 3 months no Insight produced
   - All three → reset eligible (max 2/month, queued by stagnation severity)

**Design principle**: "要激励各个影子主动投资，要勇于试错，不能躺平走保守投资的路线"

---

## 7. Elimination & Challenger Pipeline

From design doc 7.4:

**3-stage buffer** (partially implemented):
- Stage 1: Warning (2 consecutive eval periods in bottom 20%) — no quota reduction
- Stage 2: Observation + Secret Challenger (3 periods in bottom 20%) — quota reduced, challenger created invisibly
- Stage 3: Comparison (2 weeks no improvement) — challenger vs target, winner takes the seat

**Layered evaluation cycles** (not implemented):
- Short-term (1-7 day holds) → every 2 weeks
- Medium-term (1-4 week holds) → monthly
- Long-term (1-6 month holds) → quarterly

**Challenger opacity**: Already implemented (`get_visible_shadows()` excludes challengers).

**Knowledge inheritance**: Implemented via `knowledge_filter.py`. PASS if verified, DROP if unverified, ISOLATE known false positives.

---

## 8. Emergency Quota — Design vs Code

| Design (7.3) | Code |
|-------------|------|
| Confidence ≥ 8/10 trigger | Implemented |
| Profit → permanent +1 quota + cognition credit | Missing |
| Wrong but user didn't follow → 3-day observation | Missing |
| Wrong and user followed loss → 7-day observation | Missing |
| 3 consecutive misses → permanent -1 | Missing |
| **Trigger when quota exhausted** (not confidence) | **Missing** (current triggers on confidence, not exhaustion) |

User preference: emergency quota should trigger when base quota is EXHAUSTED, not on confidence threshold. This encourages using all regular quota first.

---

## 9. Implementation Gaps (What Exists vs What's Missing)

| Feature | Code Exists | Wired Into Pipeline |
|---------|------------|---------------------|
| Achievement tiers (5 levels) | Yes | Yes |
| Composite ranking (4 metrics) | Yes | Yes |
| Bayesian haircut | Yes | Yes |
| Tier-based quota scaling | No (flat default) | No |
| `detect_plateau()` | Yes | **No** |
| `abstention_days` penalty | No (weight=0) | No |
| Reset trigger | No | No |
| Catfish `check_consensus()` | Yes | **No** |
| ELITE participation in Gate 2 | No | No |
| Domain-triggered awakening | No | No |
| Emergency quota reward/punishment | Partial | Partial |
| Emergency quota exhaustion trigger | No | No |
| Dynamic win rate line | No | No |
| Layered evaluation cycles | No | No |

---

## 10. Promoted Shadow Standards (Design Doc 7.5)

| | Expert | Daredevil |
|------|--------|---------|
| Min runtime | ≥1 full VIX cycle (~120 trading days) | 60 days |
| Min trades | ≥100 | ≥50 |
| Win rate | >60% | >55% |
| Deflated Sharpe | >0 | >0 |
| PBO | <5% | <10% |
| MDD | <25% | <35% |
| Forward validation | 30-day out-of-sample ≥50% | Same |
| Extra | — | Must cross ≥1 VIX>25 high-vol period |

---

## 11. Temp Event — 里程碑触发型 (Form C, MECHANISM not Shadow)

**Decision**: Temp Event is NOT a full shadow. It's a milestone-triggered recorder.

**Lifecycle**:
- Day 1: Pro does initial framework analysis ("what to watch for in this event's aftermath")
- Day 2-9: Python silently records OHLC + relevant news, ZERO Pro calls
- Day 5: If any affected ticker's volatility > 3σ → trigger Pro: "is this the original event driving this or new event?"
- Day 10: Pro mid-term review
- Day 30: Pro final validation report + Flash summary

**Cost**: 3-5 Pro calls / 30 days
**Value**: Causal chain verification evidence for main AI's original analysis
**Essence**: A recorder with triggers, NOT an agent with agency

---

## 12. Daredevil Final Configuration

7 environment-locked Daredevils + 1 Crash Hunter:
1. 震荡市 (Range-Bound)
2. 恐慌市 (VIX>30)
3. 高杠杆 (Leveraged ETFs)
4. 反向/共识逆行者 (Fade Master)
5. 追涨杀跌/动量 (Scalper + Trend Rider merged)
6. 板块轮动 (Rotation Engine)
7. 流动性枯竭 (Low Liquidity — exception: doesn't need large-cap)
8. **崩溃猎人** (Crash Hunter — short-biased, looking for overvalued/bubble conditions)

**Vs Expert Short Specialist**: Crash Hunter focuses on pre-crash signals; Expert Short Specialist focuses on short opportunities in their domain generally.

## 13. Catfish v2 — Ecosystem Auditor (MECHANISM, not Shadow)

No longer a shadow. Cross-shadow diversity monitor:
- Direction concentration: all shadows net long? Zero shorts?
- Asset class neglect: equities only, ignoring bonds/commodities/FX
- Methodology convergence: multiple shadows using identical reasoning chains
- Uncovered tickers: top 20 market cap stocks with zero shadow coverage this week

Input: all shadow votes + positions. Output: ≤5 blind spot alerts → Gate 2 presentation.
Python computes metrics → Pro interprets only when threshold triggered.

## 14. Beta — Split Architecture

| | Quantitative Tuning | Qualitative Methodology Change |
|---|---|---|
| **Creates** | Parameter layer (NOT a shadow) | 1-2 Beta shadows |
| **Analysis** | Pure Python recalculation, follows main AI | Independent Pro analysis |
| **Quota** | Zero | Flash query quota |
| **Duration** | 30 days | 60 days + Red Team review |
| **Judgment** | Divergence stats: Beta > Main AI? | Deflated Sharpe + Win Rate + PBO |
| **Concurrent** | Unlimited | Max 2 hypotheses |

## 15. Cross-Type Updates

**Short-Biased Shadows Added**:
- Expert: Short Specialist (one, dedicated to finding short targets in any domain)
- Daredevil: Crash Hunter (one, environment-locked to overvalued/pre-crash conditions)

**Model Change**: ALL shadows default to Pro model (was Flash). Flash reserved for: news collection, preprocessing, simple queries, one-line comments.

**Main AI Domain Benchmarking**: All main AI recommendations filed by domain, tracked for performance. Expert shadows must statistically outperform main AI in their domain to qualify for promotion to Expert level. Minimum N main AI records in domain required before comparison.

## 16. Win Rate / Profitability Matrix (Final)

```
                盈利率 > 0        盈利率 ≈ 0        盈利率 < 0
胜率 > 动态线    🟢 最佳           🟡 及格(无奖惩)    🔴 最大扣分
胜率 < 动态线    🟠 存活(不鼓励)    🟠 双弱           🔴 双倍扣分
```

**Key Rules**:
1. Negative profitability = largest penalty weight (regardless of win rate)
2. High win rate + flat profitability = passing grade (allowed but not rewarded)
3. Low win rate + high profitability = survive (not encouraged), win rate cannot breach hard floor
4. Win rate HAS VETO POWER for Expert promotion (not for ranking survival)

**Anti-Conservatism Penalties** (3 mechanisms):
1. Platform detection (stagnation: no ELITE in 126 days + stable WR + insight drought)
2. Abstention penalty (excessive cash-holding reduces score)
3. Reset trigger (6 months no EXCELLENT + 3 months WR flat + 3 months no Insight → reset eligible)

**Tiered Elimination** (matches shadow's decision horizon):
- Stage 1: temporary debuff (reduced Flash quota × 1 eval period)
- Stage 2: demotion + debuff
- Stage 3: challenger replacement

Full transparency: all shadows know their rank and the rules.

## 17. Key Architectural Decisions Made

1. Catfish → Ecosystem Auditor (mechanism, not shadow)
2. Temp Event → Form C milestone-triggered recorder (mechanism, not shadow)
3. Beta quantitative → Parameter layer (mechanism, not shadow)
4. Beta qualitative → Full Pro shadow (1-2 per hypothesis)
5. All shadows default to Pro model
6. Expert promotion requires beating main AI in domain
7. Dynamic win rate line (needs formula design)
8. Single-agent evolution mechanism for Daredevils (needs research)

