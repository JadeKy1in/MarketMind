# Red Team: Shadow System Logic Audit

**Auditor**: Red Team Logic/Investment Methodology
**Date**: 2026-05-18
**Subject**: `shadow-system-comprehensive-plan.md`
**Severity**: CRITICAL — this system will trade real money.

---

## 1. Few-Shot Echo Chamber: Recency Bias Creates Perma-Bull Shadows

**What the plan says** (Section 3.2):

> 影子启动时: 查询 per-shadow skills/: 最近 3 个成功分析 → 注入 system prompt: "你过去成功分析过以下情况: [3个few-shot]"

**What breaks**:

The retrieval is purely recency-based — "最近3个" — not relevance-based, not regime-diverse. In a sustained bull market, all 3 recent successes will be bullish. The shadow's system prompt is primed with 3 bullish examples, making it more likely to interpret ambiguous signals as bullish, more likely to produce bullish predictions, and more likely to succeed (because the bull market bails out bad reasoning).

**Echo chamber dynamics**:
1. Bullish few-shots prime the shadow to see bullish patterns
2. Bullish predictions during a bull market succeed at above-random rates (even with flawed reasoning)
3. New bullish successes displace older, potentially bearish successes in the "最近3个" window
4. The few-shot window becomes progressively more concentrated → echo chamber deepens

**Why the existing safeguards don't help**:
- The Persona lock (Section 2) controls the decision *framework*, not how examples prime pattern recognition. Few-shot learning works precisely because it shapes output — that's the whole point of Sarukkai et al.'s finding.
- The Ecosystem Auditor's direction concentration check (Section 4) triggers at 80%+ agreement *across shadows*. A single Gold Expert shadow's internal bias won't trigger it.
- The collusion detector tracks *between-shadow* agreement, not *within-shadow* path dependency.

**Recommended fix**: Retrieve few-shot examples by *regime diversity*, not recency. Stratify the skill store by market regime (risk-on/risk-off/volatility-regime) and sample one example from each of the 3 most recent *distinct* regimes. If the shadow's skill store lacks regime diversity (all skills from one regime), flag this as a blind-spot alert in the Ecosystem Auditor.

**Severity**: HIGH — creates systematic directional bias in per-shadow analysis, undetectable by existing cross-shadow monitors.

---

## 2. STAR Error Decomposition: Confuses Luck with Skill

**What the plan says** (Section 3.1):

```
错误 → STAR 错误分解
  Evidence 阶段: 我用了什么数据？
  Hypothesis 阶段: 我的假设是什么？
  Analysis 阶段: 我的推理链条对吗？
  Decision 阶段: 决策阈值合理吗？
  → 生成反事实修复建议 → 存入 lessons/
```

**What the code actually does** (`reflection_agent.py:32-40`):

The implemented root cause taxonomy has 7 categories: `MISSING_DATA`, `FLAWED_CHAIN`, `REGIME_CHANGE`, `OVERCONFIDENCE`, `CORRECT_REASONING`, `BLACK_SWAN`, `DATA_SOURCE_ERROR`. There is no `WRONG_REASONING_BUT_LUCKY` for successes.

**The fundamental problem**: Financial markets have approximately 50% signal-to-noise ratio for directional predictions over short horizons. Half of all prediction outcomes are noise-driven. The system treats `outcome == methodology_quality`, which means it trains on noise half the time.

**Problem A: Successes are automatically promoted**

Section 3.1: `正确 → 保存为 Skill` — no quality gate. The reflection agent runs for successes too (prompt asks "推理过程是否真的合理？还是只是运气好？") but the plan's pipeline is `正确 → 保存为 Skill` unconditionally. A lucky-but-wrong-reasoning success gets saved as a validated Skill and fed back as a future few-shot example, compounding the error.

**Problem B: STAR is conceptual, not implemented**

The plan describes a 4-stage STAR decomposition (Evidence → Hypothesis → Analysis → Decision) with *counterfactual repair suggestions* at each level. The actual `reflection_agent.py` uses a flat 7-category taxonomy with a single `updated_belief` string. If the shadow analyzes gold correctly (real rates down → gold up) but gold falls because of a surprise margin-call liquidation cascade: STAR should identify that Evidence, Hypothesis, and Analysis were all correct, and only the Decision timing was unlucky. The actual code would classify this as... `BLACK_SWAN`? `MISSING_DATA`? Neither accurately captures "right reasoning, wrong outcome."

**Problem C: The system punishes methodology for outcomes**

If a shadow's methodology is genuinely sound (true win rate 62%) but suffers a 3-loss streak (probability: 5.5%), all 3 losses get STAR-decomposed and stored as `lessons/`. On the next startup, these 3 "lessons" are injected ("上次黄金预测我错了——因为忽略了央行购金"), even though the shadow didn't ignore central bank buying — it just got 3 coin flips wrong. The methodology is now contaminated with noise-driven corrections.

**Recommended fix**:
1. Add `WRONG_REASONING_LUCKY` to the root cause taxonomy for successes.
2. Gate skill promotion on the reflection agent confirming the reasoning was sound (require `CORRECT_REASONING` root cause before promoting to Skill).
3. For failures, require the reflection agent to distinguish between "methodology failed" and "methodology was correct, outcome was noise." Only methodology failures should modify the methodology.
4. Implement the actual 4-stage STAR decomposition as described — the plan is better than the code here.

**Severity**: CRITICAL — outcome-based learning in a stochastic domain creates a noise-amplification loop. This is the single most dangerous flaw in the system.

---

## 3. FORGE Population Broadcast: Collusion Detector Cannot Distinguish Consensus from Contagion

**What the plan says** (Section 4):

> FORGE 人口广播模式: Examples 格式 → 同领域影子（最详细，收益最高）

**The scenario**: FORGE broadcasts a successful skill pattern to all 8 Gold-domain shadows. They all incorporate it. On the next gold rally signal, all 8 independently analyze the same data with the same skill injected and reach the same bullish conclusion.

**What the collusion detector sees** (`collusion_detector.py`):

The `detect_methodology_convergence()` function checks:
1. Jaccard similarity of `methodology_provenance` (ancestor methodology IDs) — HIGH, because all 8 now share the broadcast methodology in their lineage
2. Position agreement over overlapping days — HIGH, because they all adopted the same skill

The detector would flag this as "methodology_collusion" (severity ESCALATED) and log: "Shadows share XX% methodology lineage and agree on >80% of positions for N+ days. This is methodology collusion, not independent validation."

**The false-positive problem**: The detector CANNOT distinguish between:
- (a) 8 shadows independently analyzing the same data and correctly reaching the same conclusion (genuine consensus)
- (b) 8 shadows herding because they all ingested the same broadcast skill (methodology contagion)

Both produce identical observable signatures: high agreement + shared methodology lineage. The detector uses `market_signal_strength` to distinguish convergence from herding for DIRECTION agreement (Section 3 of collusion_detector.py), but this signal-based filtering is NOT applied to methodology convergence detection. The methodology convergence function (`detect_methodology_convergence`, line 267) checks only lineage similarity + position overlap — no market signal test.

**The philosophical problem**: After a skill broadcast, the shadows' analyses are no longer independent even if they would have reached the same conclusion without the broadcast. The detector measures observables (lineage + output correlation), not counterfactuals (what would they have concluded without the broadcast?).

**False-positive rate estimate**: Unknown and unknowable. The detector has no calibration data, no historical baseline for "normal" methodology convergence rates, and no mechanism to distinguish genuine consensus from skill contagion.

**Recommended fix**:
1. Apply the same market_signal_strength filter to methodology convergence detection that you apply to direction agreement detection.
2. Track the *source* of methodology lineage entries — distinguish "self-discovered" from "broadcast-received" provenance. Only flag convergence when the overlap comes from broadcast (contagious) sources.
3. Add a "quarantine period" after broadcast: shadows that received a broadcast skill are excluded from collusion checks for N days while the skill integrates. After N days, re-check: if they still agree, it was consensus; if agreement drops, it was contagion.

**Severity**: MEDIUM — the detector works in the right direction (flags excessive convergence), but without regime-aware filtering it will generate false alarms whenever shadows correctly agree on an obvious signal.

---

## 4. Cold Start: Domain Template Encodes Regime Bias, 50 Predictions Not Enough to Unlearn

**What the plan says** (Section 6):

> 新影子（<50 个已验证预测）→ 使用领域模版（PASS）。
> 50 个预测后 → 个性化 Skill 库启动。
> 100 个预测后 → 方法论可以开始迭代（AgentDevel 发布流程激活）。

**What breaks**:

The domain template was designed at a point in time, by a human, during a specific market regime. The template encodes the designer's mental model, which is shaped by the regime visible during design (2024-2025: strong equity bull market, gold at all-time highs, AI euphoria).

**Transfer problem**: A new shadow created during a bear market (VIX>30, credit spreads blowing out, flight-to-safety) applies a template designed during a bull market. The template's indicator weights, confirmation thresholds, and risk limits are all calibrated on bull-market data. The shadow spends its first 50 predictions applying wrong-regime templates to current-regime data.

**50 predictions is a LOT of wrong predictions**: A shadow that analyzes daily but only finds 1-2 actionable predictions per week needs 25-50 weeks to hit 50. That's 6-12 months of real time where the shadow is systematically biased by its template and CANNOT adapt — no personalized skills, no methodology iteration, no customized few-shots.

**The Bayesian haircut compounds this**: `h(N,T) = T/(T+8+24×ln(N))` penalizes low-N shadows. A cold-start shadow with N=10 predictions gets a ~0.72 haircut even if all 10 were correct. Combined with regime-biased templates, this creates a perverse incentive: to survive long enough to hit 50 predictions, the shadow must be conservative (low risk, low return), which triggers the anti-conservatism penalties designed to prevent exactly that behavior.

**Recommended fix**:
1. Regime-tag the template: when was it designed, what regime was it calibrated for? Flag template-regime mismatch at initialization.
2. Lower the cold-start threshold for regime-shifted environments: if the current VIX is >2 standard deviations from the template's calibration regime, activate personalized skills at 25 predictions instead of 50.
3. Add a "regime adaptation" phase (predictions 0-20) where the shadow's methodology prompt explicitly warns: "You were calibrated in a [regime_type] regime. Current conditions are [current_regime]. Your template assumptions may not apply."
4. Exempt cold-start shadows from anti-conservatism penalties (plateau detection, abstention penalty, reset trigger) — they ARE being conservative because they're learning, and that's correct behavior.

**Severity**: HIGH — creates a systematic first-50-predictions bias that the shadow may never fully recover from (the skills it builds in its first 50 are built on biased foundations).

---

## 5. AgentDevel Flip-Centered Gating: Asymmetric Blocking Rule Rejects Good Methodologies

**What the plan says** (Section 3.3):

> 新方法论 → 历史回测（vs 旧方法论在相同数据上）
> 任何旧方法正确→新方法错误的案例 → 阻断
> 旧方法错误→新方法正确 → 记录改进
> 净改进 > 0 且无灾难性退化 → 晋升

**Problem 1: The blocking rule is ruinously conservative**

The rule "any old-correct/new-wrong case → block" means one bad-luck outcome blocks a genuinely better methodology. Calculate the probability:

A methodology with a true 65% directional accuracy (very good for financial markets) is tested against 10 validation cases. The old methodology was correct on ~6 of them (its true rate). The new methodology is applied to those 6. The probability the new methodology gets ALL 6 right: 0.65^6 ≈ 7.5%. 

**A methodology with a 65% true win rate has a 92.5% chance of being blocked by this rule.** The system will almost never approve methodology improvements.

**Problem 2: The validation data IS the training data**

The plan says "历史回测（vs 旧方法论在相同数据上）" — same data. There is no mention of cross-validation folds, time-series splits, walk-forward testing, or any out-of-sample methodology. This means methodologies are tested on the same data the old methodology was optimized on. If the old methodology overfit (which it almost certainly did, given the Bayesian haircut acknowledges this), the new methodology is tested against an overfit baseline on the same overfit data.

**Problem 3: Regime-locked validation sets**

If the available validation data comes from a single regime (e.g., the gold shadow's 10 most recent predictions were all during a rally), a methodology optimized for the opposite regime gets rejected despite being objectively better. The plan has no regime-stratified validation split.

**Problem 4: Asymmetric gating**

The rule `any old-correct/new-wrong → block` has no counterpart: `any old-wrong/new-correct → fast-track`. If the new methodology is correct on ALL cases the old was wrong on, but wrong on ONE case the old was right on, the new methodology is blocked. The system measures: how many times is the new method worse? It should measure: on net, is the new method better?

**Recommended fix**:
1. Replace the "any regression → block" rule with a statistical test: is the new method significantly better (McNemar's test on paired predictions, p<0.10)?
2. Require time-based walk-forward validation: train on first 70% of data, validate on last 30%. Never test on data the old methodology was optimized on.
3. Stratify validation by market regime: if the validation set is 100% bull market, the test is invalid for methodology approval.
4. Minimum N for validation: require at least 20 paired predictions (old vs. new on same data) before proceeding. With N<20, the statistical power is too low to make any decision — just hold.
5. Keep the "no catastrophic degradation" rule but define it operationally: new method's win rate on any single month of validation data must not be <30% (below chance after costs).

**Severity**: CRITICAL — this gate will block approximately 90%+ of valid methodology improvements due to sample noise. The system will stagnate methodologically.

---

## 6. Skill Retrieval: Embedding Similarity Retrieves Textual Neighbors, not Functional Analogues

**What the plan says** (Section 6):

> 影子启动时: 检索自己的领域 RAG → 加最近的 3 个成功分析作 few-shot 示例

Section 3.2 mentions "embedding similarity" as the retrieval mechanism.

**The fundamental problem**: Text embedding similarity (cosine distance in a transformer embedding space) measures co-occurrence patterns from pre-training data, not causal relevance in investment contexts.

**Concrete example**:

Current market condition: "Gold falling despite escalating geopolitical tensions — safe-haven bid absent, DXY surging on rate-hike repricing."

A textually similar skill that gets retrieved: "Gold ETF outflow analysis during Middle East tensions: GLD saw $450M outflow in the week following Iran escalation, confirming institutional de-risking." — similar words (gold, geopolitical, tensions, outflow), but functionally IRRELEVANT if today's dynamic is about rate expectations, not ETF mechanics.

The functionally relevant skill that does NOT get retrieved: "DXY surge despite Fed rate-cut expectations: in March 2025, the dollar rallied 2.3% while rate-cut odds rose to 85%, driven by European capital flight into US assets. Gold fell 4.1% despite 'risk-off' narrative." — different words (DXY, Fed, rate-cut, European capital flight vs. gold, geopolitical, tensions), but the same underlying dynamic: safe-haven paradox, dollar strength overriding traditional gold-safe-haven correlation.

The embedding space cannot capture this functional equivalence because it's trained on surface-form co-occurrence, not causal structure.

**The crowding problem**: After 6 months, a shadow has 100+ skills. The embedding space gets crowded:
- Skills cluster by textual domain (gold → gold ETF, gold miners, gold futures) rather than by causal pattern (safe-haven paradox, real-rate sensitivity, momentum breakdown)
- Top-K retrieval (K likely 3-5) returns skills from the same narrow textual cluster
- Cross-domain analogies (a pattern in energy markets that applies to gold) are SYSTEMATICALLY missed because they're in a different shadow's store entirely

**What the plan doesn't specify**:
- Embedding model (OpenAI text-embedding-3-large vs. all-MiniLM-L6-v2 — quality difference is massive)
- Re-embedding strategy (are 6-month-old skills re-embedded with newer models?)
- Relevance threshold (what similarity score is "too low to use"?)
- Re-ranking (cross-encoder validation after embedding retrieval)
- Cross-domain retrieval (can the Gold shadow access Copper shadow's skill store?)

**Recommended fix**:
1. Replace pure embedding similarity with a two-stage pipeline: embedding retrieval (wide recall) → cross-encoder re-ranking (precision). This is the standard approach for RAG quality.
2. Add functional tags to skills at creation time: tag the causal mechanism (e.g., `real_rate_sensitivity`, `safe_haven_paradox`, `momentum_breakdown`) in addition to the asset domain. Retrieve by functional tag match, not text similarity.
3. Lower the retrieval K: with 100+ skills, retrieving 3 is too few for diversity but the right number for context window. Instead: retrieve 15 by embedding, re-rank by cross-encoder, select 3 most causally relevant.
4. Implement cross-domain retrieval: when the Gold shadow's own skill store lacks a matching pattern, query sibling shadow stores tagged with the same causal mechanism.
5. Track retrieval quality: for each retrieved skill, after the prediction outcome is known, score whether the retrieved skill was actually relevant (human review or automated via outcome correlation). Feed this back to improve retrieval.

**Severity**: MEDIUM today (shadows are new, stores are small), but CRITICAL at scale (after 12+ months of operation with 200+ skills per shadow). This is a compounding problem — retrieval quality degrades as the store grows.

---

## Summary of Findings

| # | Finding | Severity | Mechanism Affected |
|:---:|------|:---:|------|
| 1 | Few-shot echo chamber: recency-based retrieval creates perma-bull bias | HIGH | Memento-Skills + Few-Shot Injection |
| 2 | STAR confuses luck with skill: outcome-based learning amplifies noise | **CRITICAL** | STAR Decomposition + Skill Promotion |
| 3 | Collusion detector cannot distinguish consensus from contagion | MEDIUM | FORGE Broadcast + Methodology Convergence |
| 4 | Cold start template encodes regime bias, 50 predictions is too many | HIGH | Domain Template + Cold Start Threshold |
| 5 | Flip-centered gating has 92.5% false-rejection rate for valid improvements | **CRITICAL** | AgentDevel Methodology Release |
| 6 | Embedding retrieval is textual, not functional — degrades at scale | MEDIUM→CRITICAL | Skill Retrieval + RAG |

**Bottom line**: Findings 2 and 5 are show-stoppers. The system has two critical flaws: (a) it cannot distinguish luck from skill, which means it learns from noise in a stochastic domain, and (b) its methodology improvement gate has a false-rejection rate so high that valid improvements will almost never pass. These two flaws together mean the system will amplify noise while blocking genuine learning. Do not deploy to real money without addressing both.

**Overall assessment**: The architecture is thoughtful and the intra-team safeguards (isolation, challengers, ecosystem auditor) are well-designed. But the *learning mechanisms* — which are the entire point of the shadow ecosystem vs. a static analysis pipeline — contain fundamental statistical errors that will cause the system to degrade over time rather than improve.
