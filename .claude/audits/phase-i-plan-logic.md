# Red Team Logic/Investment Methodology Audit: Phase I Self-Evolving Architecture

**Date**: 2026-05-18 | **Auditor**: Red Team Logic | **Subject**: `phase-i-self-evolving-architecture.md`
**Verdict**: BLOCKED — 12 findings, 5 CRITICAL, 4 HIGH. The architecture has the right shape but missing defenses mean it will amplify errors at least as efficiently as it amplifies skill.

---

## Summary

The 6-layer architecture is directionally correct and well-grounded in the research. Layer 1 (time-anchored predictions) and Layer 2 (Brier scoring) are solid foundations lifted directly from proven prediction-market methodology. The problems start at Layer 3 and compound upward: the plan has no mechanism to prevent the system from learning noise, no circuit breakers to stop error propagation, and a calibration cold-start period that guarantees the first 2-3 weeks of analyses are systematically overconfident.

The specific concern: **this architecture will learn random patterns at least as fast as it learns real ones**, and once a false pattern enters EntityMemory (Layer 4), the prompt-injection mechanism at analysis time (Layer 4 retrieval) will make the system more confident about the false pattern, which produces more "confirming" predictions, which reinforces the false pattern in a tight feedback loop that no existing mechanism can break.

---

## CRITICAL Findings

### C1. Self-Fulfilling Bias Loop — No Statistical Gate on Pattern Storage

**Finding**: EntityMemory stores `recurring_patterns` (e.g., "黄金在3月季节性走强") with ZERO statistical validation. A pattern detected from 3 data points and a pattern detected from 30 are treated identically by the retrieval mechanism — both get injected into future analysis prompts.

**Why this is catastrophic**: The feedback loop is:
1. EntityMemory learns "gold goes up in March" from N=3 years (could be pure noise)
2. Next March analysis: prompt includes "you've observed gold tends to rise in March"
3. Shadow AI, primed by this hint, produces a bullish gold prediction
4. If gold happens to rise (50/50 coin flip), the prediction scores well
5. Layer 3 produces a CORRECT_REASONING lesson; Layer 4 strengthens the pattern
6. Next year: pattern is now "validated" by 4 data points, injected with higher confidence
7. System becomes progressively more confident in a coin-flip pattern

**The plan's stated guard is**: "根因分类区分 REGIME_CHANGE — 环境变化时标记旧教训为过期." This does NOT apply — a random seasonal pattern that was never real to begin with is not a regime change. Regime change detection can only detect that the environment CHANGED, not that the original pattern was spurious.

**What's missing**:
- Minimum sample size (N≥20) before a pattern qualifies for prompt injection
- Statistical significance test (p<0.05, or at minimum a binomial test against base rate)
- Out-of-sample holdout: patterns discovered on months 1-12 must validate on months 13-18 before injection
- Causation requirement: the pattern must be linked to a causal mechanism ("gold up in March because Indian wedding season jewelry demand"), not just correlation
- Blind pattern detection: the system should NOT tell the shadow what pattern it thinks exists. Instead, it should ask "does gold have a seasonal pattern?" and compare the shadow's answer to the stored pattern. If they disagree, flag the stored pattern as suspect.

**Recommendation**: Add a `PatternValidator` that gates pattern storage behind: (a) N≥12 independent observations, (b) binomial p<0.05 against 50% base rate, (c) at least one causal mechanism linking the pattern to a structural driver, (d) out-of-sample validation on held-out periods. Without this, EntityMemory is a random-number-generator amplifier.

### C2. Regime Change Detection Runs AFTER Failure, Not Before

**Finding**: The REGIME_CHANGE root cause in Layer 3 is assigned POST-MORTEM — after the prediction expires and fails. The ReflectionAgent receives the failed prediction + actual result + original analysis, and retroactively classifies it as REGIME_CHANGE. But by the time this happens:

- Layer 2 has already scored the prediction as wrong (Brier penalty applied to shadow's calibration tracker)
- Layer 4 has already absorbed the wrong causal assumptions during the analysis period
- Layer 5's calibration coefficients are contaminated by a prediction that was DOA due to regime shift

**The plan says nothing about PRE-PREDICTION regime change detection.** This is a glaring omission because the infrastructure exists: `regime_mapper.py` already computes 7-variable Euclidean distance to historical regimes and produces bias warnings. This module runs DURING analysis but is not wired to a pre-expiry alert mechanism.

**What's missing**:
- A `RegimeMonitor` cron job that runs daily, re-checks the regime vector for each active prediction, and if the regime has shifted by >threshold, triggers EARLY resolution as REGIME_CHANGE (not FAILURE)
- Differentiation between "prediction was wrong because reasoning was bad" (FLAWED_CHAIN, score penalty deserved) vs "prediction was wrong because the world changed under it" (REGIME_CHANGE, NO score penalty — the prediction was valid under the prior regime)
- The EntityMemory must store regime-context alongside lessons: "ECB is hawkish" is only true for regime ID=R_2026_Q1. When regime shifts to R_2026_Q2, the lesson is NOT retrieved.

**Recommendation**: Wire `regime_mapper.py` as a pre-expiry guard. For every active PredictableHypothesis, recompute the regime vector weekly. If distance(current_regime, prediction_regime) > threshold, auto-resolve as REGIME_CHANGE_EXPIRED with no Brier penalty and no lesson extraction. The prediction was valid when made; the environment invalidated it.

### C3. Calibration Cold Start — First Month Is Systematically Overconfident

**Finding**: The plan requires N≥50 predictions before Platt scaling activates. At 3-5 ACTIONABLE predictions per session (daily), that's 10-17 sessions (2-3 weeks). During this period, ALL confidence scores are uncalibrated.

**What the research says**: KalshiBench (Nel, Dec 2025): "ALL frontier LLMs are systematically overconfident. At 90%+ confidence, models are wrong 15-32% of the time. Reasoning-enhanced models showed WORSE calibration." The plan's own research states: "推理增强反而加剧过度自信" (reasoning enhancement exacerbates overconfidence).

MarketMind uses Pro (reasoning-enhanced) for analysis. So during cold start, a shadow that outputs 0.85 confidence on a gold prediction actually has ~0.68-0.75 probability of being right. The system will display 0.85 to the user. This is misleading by 10-17 percentage points.

**But the real problem is deeper**: N≥50 is for the MAIN system. Each SHADOW produces its own predictions. A domain-specific shadow (shadow_gold_expert) might only produce 1 gold prediction every 2-3 sessions. Reaching N≥50 predictions for that specific shadow on that specific entity takes months, not weeks. During that entire period, that shadow's scores feed into:
- Reputation tracking (Layer 2 — but reputation doesn't account for calibration)
- Methodology distillation (Layer 6 — uncalibrated shadows can appear skilled by luck)
- EntityMemory (Layer 4 — wrong confidence levels stored as "lessons")

**What the plan says**: "前期使用保守默认系数" (use conservative default coefficients). This is hand-waving. What are the conservative defaults? 0.85→0.65? 0.90→0.70? On what evidence?

**What's missing**:
- A research-backed prior: the KalshiBench data says LLMs at 80%+ are ~15% overconfident. Start with an across-the-board 0.85x multiplier on all confidence scores until per-shadow calibration data exists.
- Per-shadow cold-start handling: use the ensemble median calibration as a prior. If the median shadow's 0.80 confidence means 0.70 accuracy, apply that same mapping to new shadows until their individual data accumulates.
- Transparent reporting: the confidence output should include `confidence_raw: 0.85, confidence_calibrated: N/A (cold start, using ensemble prior → 0.72)`. The user deserves to know when calibration is active vs. cold-start.

**Recommendation**: Implement cold-start calibration from day 1 using the ensemble-wide KalshiBench prior (0.85x multiplier for confidence ≥0.70, 0.90x for confidence <0.70). Replace with per-shadow Platt scaling as data accumulates. Display calibration status to the user. This is a ~15 line change that prevents a month of overconfident output.

### C4. Entity Memory — Single Decay Factor Cannot Handle Heterogeneous Expiration

**Finding**: The plan has one `memory_freshness: float` per EntityMemory object. But different entity types need different decay rates:

| Entity Type | Knowledge Half-Life | Example |
|---|---|---|
| Central bank stance | 2-8 weeks (next meeting) | "ECB is hawkish" |
| Seasonal commodity pattern | 1-5 years (structural) | "Gold up in March" |
| Technical support/resistance | Until level breaks | "EUR/USD support at 1.05" |
| Geopolitical risk | Days to weeks | "Middle East tensions" |
| Structural macro trend | 6-24 months | "De-globalization" |

A single `memory_freshness` decays ALL lessons at the same rate. Either fast-decaying lessons become stale before they should (if using a slow rate), or slow-decaying lessons persist long after they're wrong (if using a fast rate). The plan's §十一 acknowledges "实体记忆膨胀" (memory bloat) but proposes a fixed "最近 20 条教训" retention policy — which is count-based, not relevance-based.

**The plan mentions per-lesson `decay_factor` in Layer 3 but never defines how it's computed or updated.** The StructuredLesson struct has a `decay_factor` field, but there's no mechanism to set different decay rates for different entity types.

**What's missing**:
- Entity-type-specific decay curves: central_bank lessons decay with half-life=4 weeks; sector lessons with half-life=12 weeks; seasonal_pattern with half-life=52 weeks
- Event-triggered invalidation: a key_level lesson (support at 1.05) should be marked as "tested_and_broken" when the price breaks below 1.05, overriding the time-based decay
- The `memory_freshness` should be a function, not a scalar: `freshness(lesson, current_date, entity_events_since_lesson)`

**Recommendation**: Replace the scalar `memory_freshness` with a per-lesson freshness function: `freshness = base_decay[entity_type] * event_invalidation_factor`. Define base_decay per entity_type in config. Wire event-triggered invalidation: when a key level is breached, when a central bank changes policy, when a geopolitical event resolves — mark related lessons as expired regardless of time.

### C5. Methodology Distillation — No Skill-vs-Luck Decomposition

**Finding**: The expertise discovery trigger is "Brier分数持续优于中位数 20%+" — but outperformance in a trending market is luck, not skill. A shadow that is permabullish on gold during a 6-month gold bull market will have excellent Brier scores. When Layer 6 distills its methodology ("分析黄金时，以下框架被证明有效：..."), it's distilling an artifact of market conditions, not analytical skill.

The plan's 5-step verification (改善→保留，恶化→回滚) only catches this if the market regime changes — and even then, the "rollback" only removes the methodology injection, it doesn't undo the damage to shadows that already absorbed it.

**The existing codebase has a pattern for this**: `ael_evolution.py` (already implemented) uses treatment/control groups with statistical comparison. But the Phase I plan doesn't reference or reuse this pattern.

**What's missing**:
- Alpha/beta decomposition: decompose shadow performance into market-direction return (beta — what any permabull would get) and residual (alpha — what the shadow's unique analysis adds). Only distill from shadows with positive and statistically significant alpha (p<0.05, t-stat>2.0)
- Minimum track record: ≥30 predictions, ≥2 different market regimes (at minimum, one trending and one ranging), ≥6 months of data
- Methodology content validation: before distilling, ask the successful shadow "what is your analytical framework?" and ask an independent Pro call "is this a real methodology or just a directional bias?" If flagged as directional bias, skip distillation.
- Distillation control group: when a methodology is distilled to 50% of eligible shadows, leave the other 50% unmodified for 2 cycles. Compare performance. If the treatment group doesn't outperform by p<0.10, the methodology is not skill.

**Recommendation**: Borrow the treatment/control architecture from `ael_evolution.py`. Require alpha decomposition before expertise discovery triggers. Add methodology content validation via independent Pro review. This turns Layer 6 from a bias amplifier into a skill amplifier.

---

## HIGH Findings

### H1. Root Cause Taxonomy — Not MECE, Overlapping Categories Will Produce Inconsistent Labels

**Finding**: The 6 categories fail the MECE standard (mutually exclusive, collectively exhaustive):

| Overlap | Problem |
|---|---|
| MISSING_DATA vs FLAWED_CHAIN | If missing China PMI data caused an incorrect ECB→EUR causal chain, is the root cause MISSING_DATA (the gap) or FLAWED_CHAIN (the result)? The agent has no tie-breaking rule. |
| MISSING_DATA vs REGIME_CHANGE | If a new policy framework makes old data irrelevant, is that MISSING_DATA (missing the new framework data) or REGIME_CHANGE (the environment changed)? |
| CORRECT_REASONING vs OVERCONFIDENCE | These are on different axes. A prediction can be CORRECT_REASONING (direction right) AND OVERCONFIDENT (confidence 0.91, actual probability 0.70) simultaneously. The taxonomy forces a single choice. |

**Missing categories**:
- **TIMING_ERROR**: Right direction, wrong timing window. "EUR/USD will rise" — it does rise, but 2 weeks after the prediction window closed. Currently this would be classified as FAILURE with no nuance about WHY.
- **SOURCE_QUALITY**: The prediction was based on a low-quality or outdated source, not a reasoning error per se. The research file (§5 on Closed-Loop RAG) explicitly calls for source credibility tracking — but the root cause taxonomy doesn't account for it.
- **MAGNITUDE_ERROR**: Direction correct, magnitude wildly wrong. Distinct from CORRECT_REASONING (which captures both direction AND reasoning quality). CORRECT_REASONING currently bundles "幅度低估" into it, but "低估" (underestimated) is very different from "推理正确" (correct reasoning). If I predict EUR/USD goes up 0.5% and it goes up 5%, my reasoning was NOT correct — I missed the force magnitude entirely.
- **MODEL_BIAS**: Systematic LLM behavior (over-weighting recent news, anchoring to round numbers, etc.) that is not domain-specific overconfidence. The KalshiBench finding that reasoning-enhanced models amplify overconfidence is a MODEL_BIAS, not OVERCONFIDENCE per shadow.

**Recommendation**: Restructure as a two-axis taxonomy: (1) Error Source: DATA_GAP | REASONING_ERROR | REGIME_SHIFT | SOURCE_QUALITY | MODEL_BIAS | EXTERNAL_SHOCK, (2) Error Type: DIRECTION_WRONG | TIMING_WRONG | MAGNITUDE_WRONG | CONFIDENCE_MISCALIBRATED. Allow multiple labels. The ReflectionAgent should assign source+type pairs, not a single category. This makes retrieval at analysis time much more precise ("show me past MISSING_DATA errors on tech stocks" vs "show me TIMING_WRONG errors on any sector").

### H2. Compounding Error Propagation — Zero Circuit Breakers Between Layers

**Finding**: The plan has exactly one quality gate in the entire 6-layer pipeline: Layer 6's "如果改善→保留；如果恶化→回滚" on methodology distillation. There are no other circuit breakers. A single error propagates as follows:

```
Layer 2: Predicted gold UP with 0.85 confidence, Brier score computed as FAILURE
         BUT: the Brier score is wrong because the resolution data was fetched
         from the wrong source (e.g., futures close vs spot close)
    ↓
Layer 3: ReflectionAgent analyzes "why did we get gold wrong?" 
         Produces FLAWED_CHAIN lesson: "rate cut expectations were overstated"
         BUT: the actual reason was a black swan (geopolitical event), 
         which the agent didn't detect because it only sees the original analysis text
    ↓
Layer 4: EntityMemory stores "gold analysis blind spot: rate cut impact assessment"
         This is a FALSE lesson. The real blind spot was geopolitical risk.
    ↓
Layer 6: If the gold shadow's Brier scores are good (by luck in a trending market),
         the FALSE lesson gets distilled to other shadows as methodology:
         "When analyzing gold, scrutinize rate cut expectations more carefully"
         Other shadows now waste analytical effort on the wrong thing.
```

**The specific missing circuit breakers**:

| Layer Boundary | Circuit Breaker Needed | Why |
|---|---|---|
| Layer 2→3 | If Brier > 0.5 (prediction was near-random), skip ReflectionAgent. The reasoning was too wrong to learn from. | Garbage in, garbage out. |
| Layer 3→4 | Only store lessons with `relevance_score ≥ 0.3`. Lessons with lower scores are noise. | The plan defines relevance_score but never thresholds it. |
| Layer 3→4 | Cross-reference: if 3+ shadows made the same error on the same entity, it's likely a genuine blind spot, not a one-off mistake. If only 1 shadow made the error, store as low-confidence lesson. | Consensus of errors is a signal. |
| Layer 4→6 | Only distill from shadows with N≥30 predictions AND p<0.05 superiority vs median AND ≥2 different market regimes. | Luck filtering. |
| Layer 5→output | If calibration drifts by >0.15 in one week, freeze that shadow's calibration and flag for human review. | Drift this fast means something broke. |
| Cross-layer | Shadow-level kill switch: if a shadow's trailing 10-prediction Brier exceeds 0.35, mark it as CONTAMINATED. Its contributions to EntityMemory and methodology distillation are paused until Brier returns below 0.30. | Stop the bleed. |

**Recommendation**: Add explicit circuit breakers at each layer boundary. The design principle is: **default to NOT learning, and only store/retrieve when quality thresholds are met.** The current architecture defaults to LEARNING from everything, which means it learns from noise by default.

### H3. Layer 4 Prompt Injection Creates Anchoring Bias

**Finding**: The EntityMemory retrieval mechanism injects past lessons into the analysis system prompt: "你过去分析 EUR/USD 时，以下教训值得注意：...". This is functionally equivalent to telling a human analyst "here's what you got wrong last time" before they start their new analysis. Research on analyst anchoring (documented in the multi-agent research file §3.1, CONSENSAGENT paper) shows this type of pre-analysis framing induces confirmation bias — the analyst looks for evidence that confirms the past lesson's framing rather than approaching the problem fresh.

**The specific concern**: If the system learned "ECB policy is the key driver for EUR/USD" from past lessons, and the current market is being driven by tariff policy (a different driver), the EUR/USD analysis will over-weight ECB policy and under-weight tariffs because the prompt primed it toward ECB. The system has self-anchored to its own past mental model.

**The research supports this**: The "Can LLMs Really Debate?" paper (Nov 2025) found that "majority pressure suppresses independent correction." Here, the majority pressure comes from the system's own past — its stored lessons act as a pseudo-majority that suppresses fresh analysis.

**What should happen instead**:
- Retrieval should happen AFTER the shadow produces its initial analysis, as a calibration check: "Here's your analysis. Now check it against these past lessons. Do any of them suggest you're repeating a known error?"
- Or: retrieval should be adversarial — load past lessons, but also load a counter-lesson: "You previously believed X about EUR/USD. What evidence would prove X is now wrong?"
- The existing `catfish_agent.py` pattern (minority-opinion enforcement) should be applied to EntityMemory retrieval: when ≥80% of stored lessons point in one direction, force a contrarian review.

**Recommendation**: Move EntityMemory retrieval from pre-analysis prompt injection to post-analysis calibration check. If it must remain pre-analysis, counter-balance each retrieved lesson with an explicit request to find evidence that the lesson no longer applies. This is a one-paragraph prompt change that prevents the most insidious form of self-anchoring.

### H4. The N≥50 Requirement Ignores Per-Shadow Per-Entity Sparsity

**Finding**: The plan treats N≥50 as a system-wide threshold, but calibration must be per-shadow per-entity to be meaningful. Here's the math:

- 21 shadows, each specialized in 1-3 entities
- Main AI produces 3-5 ACTIONABLE predictions per session
- Shadow predictions are produced in parallel and may or may not align with main AI predictions
- A gold-specialized shadow might produce 1 prediction every 2-3 sessions on gold
- To reach N≥50 on gold alone: 100-150 sessions (3-5 months of daily operation)
- For a shadow that covers 3 entities, reaching N≥50 on each: potentially 6+ months

Meanwhile, the shadow's uncalibrated confidence scores are being used for:
- Methodology distillation eligibility (Layer 6)
- EntityMemory lesson storage (Layer 4)
- Cross-shadow reputation (implied, though not explicitly weighted in the plan)

The plan doesn't address what happens when calibration is available for the main AI (N≥50 across all entities) but NOT for individual shadows. Should the main AI's calibration coefficients be applied as a prior for shadows? Should uncalibrated shadows be excluded from Layer 6 distillation?

**Recommendation**: Define a calibration readiness tier system:
- **Tier 0** (N<10): Ensemble prior calibration only. Shadow excluded from Layer 6 distillation.
- **Tier 1** (10≤N<50): Per-shadow cross-entity calibration (one Platt scaling fit across all entities for this shadow). Shadow included in Layer 6 with down-weighted contribution.
- **Tier 2** (N≥50): Per-shadow per-entity calibration (separate Platt scaling per entity). Full Layer 6 eligibility.
Document these tiers explicitly so future sessions know what to expect.

---

## MEDIUM Findings

### M1. Prediction Extraction by Flash — Quality vs Automation Trade-off

Layer 1 proposes using Flash to auto-extract PredictableHypothesis from Pro's complex reasoning output. The concern: Pro produces nuanced, multi-factor analysis with conditional statements ("EUR/USD will rise IF ECB cuts rates AND US payrolls miss"). Flash extraction of a binary prediction from this text risks:
- Stripping conditionals: "EUR/USD will rise" (dropping the IF clauses)
- Over-simplifying the time window: Pro says "likely in the next 1-3 months, with the catalyst likely at the June ECB meeting" → Flash extracts "30 days" because that matches the template
- Misidentifying the verification metric: Pro discusses EUR/USD in context of trade-weighted euro → Flash extracts "EUR/USD close price" which is the bilateral rate, not TWI

**Mitigation**: Add a verification step — after Flash extraction, send the structured prediction back to the analysis text in a validation prompt: "Here is the prediction I extracted from your analysis. Does it accurately represent your view?" This is a single Flash call that catches extraction errors before they enter the scoring system.

### M2. Layer 6 Distillation Timing — Weekly Is Too Frequent

The plan schedules methodology distillation weekly. But with 3-5 actionable predictions per day and 21 shadows, meaningful per-shadow performance changes accumulate slowly. Weekly distillation risks:
- Over-fitting to the most recent predictions (recency bias in methodology selection)
- Churn — methodologies flip-flop between "good" and "bad" based on small-N performance
- Alert fatigue — the user sees weekly methodology changes, stops paying attention

The existing `ael_evolution.py` uses MONTHLY debrief cycles for exactly this reason. The research file §(Less is more) explicitly notes: "AEL's finding that the simplest variant (reflection + memory) outperformed more complex designs."

**Recommendation**: Monthly distillation, not weekly. Align with the existing AEL cycle.

### M3. SQLite as Sole Storage — No Migration Strategy for Schema Evolution

The plan proposes SQLite for prediction history, lessons, entity memory, and calibration data. The `PredictableHypothesis` schema has 13 fields — some will change as the system evolves (e.g., adding regime_id, calibration_tier, source_ids). SQLite has limited ALTER TABLE support. Without a migration strategy, schema changes will require manual intervention or data loss.

The existing codebase uses SQLite in `shadow_state.py` with explicit CREATE TABLE IF NOT EXISTS statements. The Phase I plan should include an `learning_store.migrate()` function that handles schema versions.

### M4. Missing Feedback Loop: Gate 1/2/3 Human Annotations

The multi-agent learning research file (§2.3) explicitly calls for structured human annotations at Gates 1/2/3 to feed into the learning loop. The user already reviews analyses at these gates. The plan has no mechanism to capture "user overrode this prediction" or "user flagged this analysis as missing X factor" as structured training signals. This is free ground truth being discarded.

---

## Architecture Assessment (Per-Layer)

| Layer | Design Quality | Key Gap | Fix Priority |
|:---:|:---:|---|---|
| **Layer 1** (Predictions) | Solid — follows prediction-market schema | Flash extraction quality (M1) | Before I-1 commit |
| **Layer 2** (Scoring) | Solid — Brier decomposition is correct | Per-shadow per-entity sparsity (H4) | Before I-2 commit |
| **Layer 3** (Post-Mortem) | High risk — learns from noise | No circuit breaker to gate reflection (H2), non-MECE taxonomy (H1) | Before I-3 commit |
| **Layer 4** (Memory) | High risk — pollution amplifier | Anchoring bias in prompt injection (H3), single decay factor (C4), no statistical gate on patterns (C1) | Before I-4 commit |
| **Layer 5** (Calibration) | Direction correct, cold start broken | Cold start overconfidence (C3), per-entity sparsity (H4) | Before I-5 commit |
| **Layer 6** (Distillation) | Highest risk — bias amplifier | No skill-vs-luck decomposition (C5), too frequent (M2), no control groups | Before I-6 commit |

---

## Consolidated Requirements for Plan v2

These must be addressed before the plan proceeds to implementation:

### Must-Fix (CRITICAL → must be in v2 plan)
1. **Statistical gate on pattern storage** (C1): N≥12, p<0.05, causal mechanism required, out-of-sample validation
2. **Pre-expiry regime change detection** (C2): Wire regime_mapper.py as cron job, auto-resolve regime-shifted predictions without Brier penalty
3. **Cold-start calibration from day 1** (C3): Ensemble KalshiBench prior (0.85x), transparent calibration status display
4. **Entity-type-specific decay curves** (C4): Replace scalar freshness with per-type half-life functions + event-triggered invalidation
5. **Alpha decomposition before distillation** (C5): Separate skill from luck, minimum 30 predictions + 2 regimes + 6 months

### Should-Fix (HIGH → address before respective sub-phase commit)
6. **MECE taxonomy + two-axis classification** (H1)
7. **Circuit breakers at every layer boundary** (H2)
8. **Post-analysis retrieval instead of pre-analysis injection** (H3)
9. **Calibration readiness tier system** (H4)

### Nice-to-Fix (MEDIUM → can defer to Phase I bug bash)
10. Flash extraction verification loop (M1)
11. Monthly distillation cadence (M2)
12. SQLite migration strategy (M3)
13. Gate 1/2/3 annotation capture (M4)

---

## Bottom Line

The Phase I plan proposes a system that will learn. The question is WHAT it will learn. Without the fixes above, the expected outcome is:

- **Months 1-2**: Uncalibrated overconfidence (C3) + noise injected as patterns (C1) = systematically overconfident AND systematically wrong about WHY it's wrong
- **Months 3-4**: Calibration activates (Platt after N≥50) but the calibration coefficients are fitted on data contaminated by early noise → calibration is miscalibrated
- **Months 5-6**: Layer 6 distills methodologies from shadows that look skilled but are lucky (C5) → other shadows adopt noise-amplified frameworks → herd convergence
- **Month 7+**: Regime change happens. System is blindsided (C2) because all 6 layers learned the old regime's patterns with high confidence. The failure is larger than if no learning had occurred.

This is the worst-case scenario: **a learning system that makes predictions WORSE than no learning, with higher confidence.** The risk section (§十一) lists exactly one relevant mitigation for this entire class of failure ("过度拟合历史模式" → REGIME_CHANGE标记), which we've shown (C2) doesn't work because regime change is detected AFTER failure.

**The architecture can work, but it needs the 5 critical fixes in the v2 plan before any implementation begins.** The building blocks exist in the codebase (regime_mapper.py, ael_evolution.py's treatment/control, catfish_agent.py's minority enforcement) — they just need to be wired into the architecture.
