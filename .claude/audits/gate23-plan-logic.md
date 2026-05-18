# Red Team: Gate 2/3 Logic & Investment Methodology Audit

**Auditor**: Red Team Logic/Investment Methodology
**Subject**: `.claude/plans/gate23-architecture.md`
**Date**: 2026-05-18
**Verdict**: PLAN HAS MATERIAL GAPS — 6 of 6 prompted questions yield substantive findings, plus 9 additional issues uncovered. Do not proceed to implementation without addressing findings marked CRITICAL.

---

## Prompted Questions

### Q1: Half-Kelly — Is It Conservative Enough for an Advisory System?

**Finding: The plan defaults to half-Kelly without justifying why it skipped quarter-Kelly, and the research document itself calls quarter-Kelly "the conservative baseline." The hard caps (25% single position, 80% directional) are institutional pod-shop levels, not retail advisory levels.**

The plan's own research base (`.claude/research/gate23-decision-frameworks.md` §2.1) states: *"Quarter-Kelly is the conservative baseline."* The plan uses half-Kelly as the default without addressing this contradiction.

Why this matters for an AI advisory system specifically:

1. **The AI has no skin in the game.** Kelly assumes the bettor bears the consequences. Here, the AI recommends, the user executes. This agency gap should push sizing toward the conservative end — the AI should be more careful with someone else's capital than it would be with its own.
2. **Win probability inputs are uncalibrated.** The plan feeds `win_probability` from "resonance DSR or user override." DSR is a statistical significance measure (probability that observed Sharpe isn't selection bias), NOT a forward win probability. Conflating these is a category error. See finding I below.
3. **The conviction_score doubles as a Kelly input**, but Kelly already uses win_probability. If conviction = 0.75 and win_prob = 0.65, the formula double-counts the user's belief. See finding A below.
4. **Hard caps are calibrated for institutions, not retail.** 25% per position + 40% sector + 80% directional means a user could be 80% long with 3 overlapping sector positions — one sector rotation wipes out most of the portfolio. For a system that positions itself as "advisory," this is recklessly permissive.

**Recommendation**: Default to quarter-Kelly as the baseline. Make the Kelly fraction a user-configurable parameter (0.25, 0.33, 0.50) with a warning when the user selects >0.33. Reduce hard caps: single position 15%, sector 30%, directional 60%. These are still aggressive for retail but at least defensible.

**Severity**: HIGH

---

### Q2: Conviction Calibration — Does the Plan Prevent AI Anchoring?

**Finding: The plan GUARANTEES anchoring. The AI presents 6 layers of curated evidence (Steps 2.1-2.6) BEFORE asking for conviction (Step 2.7). There is no pre-evidence baseline, no randomization, no debiasing mechanism of any kind.**

The sequence is:
1. Steps 2.1-2.6: AI presents evidence summary (L1-L4, Red Team, resonance, fragility, shadows, regime analogues, signal conflicts) — ALL curated by the AI
2. Step 2.7: "Given what we've found, how strongly do you believe?"
3. AI follow-up questions are leading: "What would make you wrong?" (implies user SHOULD be confident), "What additional evidence would move you to STRONG?" (frames MODERATE as a deficiency)

This is a textbook anchoring cascade:
- The AI selects which evidence to present and how to phrase it
- The AI's language (even "signal conflicts" vs "analyst disagreement") frames the interpretation
- The conviction options have numerical scores (STRONG = >=0.75) that feed directly into position sizing — so the AI's framing of evidence flows straight into capital allocation
- There is no mechanism to detect when the user is simply agreeing with the AI's framing rather than forming independent conviction

**Specific gap**: The plan never captures the user's PRIOR conviction (before seeing AI evidence). Without a pre/post delta, there's no way to know if the AI changed the user's mind or just confirmed their existing bias. Both are useful to know, and they imply different risk postures.

**Recommendation**:
1. Capture user's prior conviction BEFORE presenting evidence (Step 2.0): "Before seeing the analysis, what's your current lean on this direction?"
2. Present evidence layers in a user-selected order (let the user choose which layer to examine first)
3. After evidence review, ask for posterior conviction
4. Display the delta: "Your conviction shifted from X to Y after reviewing the evidence"
5. Remove the numerical score mapping from conviction labels — store STRONG/MODERATE/WEAK as categories, not forced floats
6. Add a calibration question: "What specific piece of evidence most influenced your conviction?"

**Severity**: CRITICAL — anchoring bias is the single most well-documented cognitive bias in decision-making, and this plan has zero debiasing mechanisms.

---

### Q3: Shadow Consensus — False Consensus from Methodology Convergence?

**Finding: The shadow consensus display ("7 of 12 relevant shadows agree") treats shadows as independent observations, but they are not independent. They share news inputs, base models (DeepSeek), system prompt architecture, and — critically — Phase I will explicitly converge their methodologies. No statistical correction is mentioned.**

Problems:

1. **Shared inputs create structural correlation.** All shadows see the same news_items. If the news is uniformly bullish, all shadows will be bullish — this is input correlation, not genuine consensus.
2. **Same base model.** All shadows route through the same DeepSeek Flash/Pro models. Same training data, same biases, same cutoff. They are one observer wearing 15 hats, not 15 independent observers.
3. **Phase I distillation creates a convergence doom loop.** Layer 6 ("Cross-shadow methodology distillation") will explicitly share successful analytical patterns across shadows. As shadows converge on methodology, "consensus" becomes tautological — they agree because they think alike, not because the signal is strong.
4. **Keyword-based domain matching is crude.** A user mentioning "gold rallied today" triggers the gold shadow, but if the user is discussing gold as an inflation hedge within a bond thesis, the gold shadow's opinion may be contextually irrelevant.
5. **No multiple-comparison correction.** If you have 12 shadows each with a 5% false-positive rate, the probability that at least one shadow "confirms" by chance is ~46%. This is not accounted for.

**Recommendation**:
1. Display "independent perspectives" count — number of shadows whose analysis uses methods that diverged >N steps ago in the methodology DAG
2. Add a "methodology similarity" score next to the consensus tally
3. Track and display input-source overlap (shadows that used the same news articles)
4. Implement a Phase I gate: if methodology similarity across shadows exceeds a threshold, flag the consensus as "potentially inflated by methodological convergence"
5. Use keyword matching as a first pass but add a relevance check (does the shadow's opinion actually address the user's specific question?)

**Severity**: MEDIUM today (shadows are independent), escalates to HIGH when Phase I Layer 6 is built. The plan needs a forward-compatibility clause.

---

### Q4: Fragility Threshold Margin — Is 0.001 Sufficient?

**Finding: The question exposes a deeper category error in the plan. The fragility scanner monitors MACRO-SYSTEMIC thresholds (VIX, bank reserves, yield levels). The plan's stop-loss validation treats these as if they produce INSTRUMENT-SPECIFIC price zones. They do not.**

The plan (Step 3.3) shows:
```
Proposed stop-loss: $182.50
Fragility zone (from fragility_scanner): $175.00 - $180.00
CHECK: Stop-loss ($182.50) is ABOVE fragility zone
```

But the fragility scanner (`fragility_scanner.py`) produces:
- A `FragilityReport` with `overall_fragility_score` (0-1)
- Alerts on MACRO thresholds like VIX > 35, bank_reserves < 2.7T, US10Y > 4.5%
- NOTHING about instrument-specific price zones

The fragility scanner has no concept of "$175.00 - $180.00" for any instrument. This would require:
1. Mapping macro fragility to instrument-level implied volatility or expected drawdown
2. Computing instrument-specific fragility bands from the systemic score
3. Validating that the mapping is calibrated (it isn't and can't be — see below)

**On the specific precision question**: All 12 fragility thresholds in `config/fragility_thresholds.py` are single-point values:
- `vix = 35` — chosen because it's a round number, not because of empirical validation
- `bank_reserves = 2.7` — estimated from Fed H.4.1, no confidence interval
- `us10y_yield = 4.5` — another round number with no empirical basis stated

None have error bars, confidence intervals, or validation history beyond a `last_validated` timestamp. The question "is 0.001 margin sufficient?" rests on the false premise that the threshold itself is precise to 0.001. It isn't. The thresholds are heuristics with unknown measurement error — the margin of safety needs to be proportional to the estimation error, not an arbitrary epsilon.

**Recommendation**:
1. Fix the category error: fragility scanner produces systemic scores, NOT instrument price zones. Do not claim it does.
2. For instrument-level stop-loss validation, use ATR-based or volatility-based bands (already available in L3 green-light analysis) — these are empirically derived from the instrument's own price history.
3. Add a "fragility overlay" check: if systemic fragility score > 0.5, recommend wider stops (e.g., 1.5x ATR instead of 1x ATR) to account for regime-dependent volatility expansion.
4. Add confidence intervals to fragility thresholds. If the interval is unknown, flag the threshold as "low-confidence estimate."
5. Never validate stop-loss with a single-point comparison against an estimated threshold. Use a buffer zone: `stop_loss > threshold + buffer`, where `buffer = max(2 * ATR, 0.05 * price)`.

**Severity**: CRITICAL — the plan claims a validation (stop-loss above fragility zone) that the fragility scanner cannot perform. This is a design error that would produce a runtime failure or, worse, a silently meaningless check.

---

### Q5: Correlation Overlay — How Are Correlations Computed?

**Finding: The plan reduces correlation to a single float with zero specification of methodology, window length, regime handling, or non-linearity. The research document explicitly covers non-linear correlation and dendrogram clustering — none of which appears in the plan.**

The plan's `compute_position_size()` signature accepts `correlation_to_portfolio: float` and applies `correlation_adj = 1.0 - correlation_to_portfolio * 0.5`. That's the entire correlation model.

What's missing:

1. **Window length.** Rolling 60-day? 252-day? Exponentially weighted? Short windows are noisy; long windows miss regime changes. The choice matters enormously — a 60-day correlation of 0.3 could be 0.8 on a 252-day window.
2. **Regime-dependent correlation.** During stress events (VIX > 30), all risk assets converge to correlation ~0.8-0.9. A position that appears diversifying in calm markets becomes perfectly correlated in the scenario that matters most (the drawdown). The research document explicitly warns about this ("dendrogram clustering for hidden relationships") but the plan ignores it.
3. **Correlation metric.** Pearson (linear) vs. Spearman (rank) vs. Kendall (tail dependence) — not specified. Pearson is useless for tail-risk assessment.
4. **Stability.** Is the correlation stable or trending? A position with correlation trending from 0.2 → 0.6 is very different from one stable at 0.4.
5. **Look-ahead bias.** If correlations are computed on the same data used to generate the signal, the adjustment is circular.

**On the specific formula `correlation_adj = 1.0 - correlation_to_portfolio * 0.5`**: This means a position with 0.80 correlation gets a 0.60 multiplier — it still gets 60% of the Kelly-sized position. For an advisory system warning about concentration risk, this is too permissive. A correlation of 0.80 should trigger a "do you really want to add to this factor?" prompt, not a gentle 40% reduction.

**Recommendation**:
1. Specify: 252-day rolling Spearman (rank) correlation as baseline, with 60-day as a "current regime" overlay
2. Add a stress-correlation check: compute correlation during the last VIX > 30 period and display it separately
3. Add a correlation trend: is it rising, falling, or stable?
4. Make correlation_adj more aggressive: `1.0 - correlation^2` for >0.5, or flag positions >0.7 for explicit user override
5. Add a "correlation regime warning" when VIX > 25: "Note: during elevated volatility, correlations typically converge toward 1.0. Your diversification assumptions may not hold."

**Severity**: HIGH — a core risk parameter is undefined, and the research document already contains the answer the plan ignores.

---

### Q6: Gate 2 → Gate 3 Data Flow — User Changes Mind Between Gates

**Finding: The plan handles MODIFY as a Gate 2 outcome (return to Gate 1), but has no mechanism for the user reconsidering their conviction DURING Gate 3. The conviction_score is locked at Gate 2 time and flows unidirectionally into position sizing.**

Realistic scenario: User passes Gate 2 with STRONG conviction. During Gate 3 ticket creation, while filling in the stop-loss field, the user realizes the risk/reward isn't as favorable as they thought. Their conviction has dropped to MODERATE. But the system already locked conviction_score = 0.85 at Gate 2, and this flows into `compute_position_size()` with no way to revise it.

Additional flow gaps:

1. **Market data staleness.** Gate 2 completes at 09:35. The user gets distracted. They return to Gate 3 at 15:45. Prices have moved 2%. The entry level from L3 is stale, but the plan's validation check (`|entry - current_price| / current_price < 5%`) is an assertion check, not a correction mechanism. The user would see "entry level OK" when it's actually 4.8% stale.
2. **Mid-Gate 3 crash.** The plan saves checkpoints after each gate completes, but not mid-gate. If the user fills in 7 of 10 ticket fields and the session dies, all 7 fields are lost.
3. **Kill criteria trigger between gates.** If a kill criterion triggers between Gate 2 completion and Gate 3 execution (e.g., EUR/USD breaks below the kill threshold), the system doesn't check. `monitor_kill_criteria()` is a standalone function — nothing calls it between gates.
4. **No "conviction decay" concept.** Conviction is treated as a point-in-time measure. In practice, conviction decays: a decision you were 80% confident about at 9 AM might be 60% by 3 PM as you think about it more. The system has no way to model or detect this.

**Recommendation**:
1. Add a "recalibrate conviction" step at the START of Gate 3: "Your conviction at Gate 2 was STRONG (0.85). After reviewing the ticket, is this still accurate?"
2. Add a market data freshness check at Gate 3 entry: if market data is >15 minutes old, re-fetch and flag any price moves >1% since Gate 2.
3. Save mid-gate progress to the session checkpoint (partial ticket fields)
4. Run `monitor_kill_criteria()` at Gate 3 entry and before Gate 3 completion
5. Add a `conviction_freshness` field to DecisionTicket: minutes elapsed since ConvictionRecord was created. Flag if >60 minutes.

**Severity**: HIGH — the happy path is fine, but the real world is full of interruptions, second thoughts, and inter-gate market moves. An advisory system that can't handle "I changed my mind" is not fit for purpose.

---

## Additional Findings (Unprompted)

### A. CRITICAL: Conviction Score Double-Counts in Kelly Formula

The plan feeds both `conviction_score` and `win_probability` into `compute_position_size()`. The Kelly formula uses `win_probability` as W. But `conviction_score` is ALSO a belief-in-winning measure — the user's subjective probability that the direction is correct. These are measuring the same thing from different sources (statistical vs. subjective). Using both as separate inputs to the same formula is double-counting.

The Kelly formula: `K% = W - (1 - W) / R`

If `conviction_score` = 0.75 and `win_probability` = 0.65, what does the formula actually represent? The user believes the trade has a 75% chance but the statistical model says 65%. The system uses both numbers but doesn't define their relationship. Is conviction an override? A weight? A confidence-in-the-estimate measure?

**Fix**: Conviction should NOT be a separate input to the Kelly formula. Instead:
- Use `win_probability` from DSR/statistical analysis as the Kelly W
- Use `conviction_score` to determine the Kelly FRACTION: quarter-Kelly for WEAK, half-Kelly for MODERATE, half-Kelly for STRONG (not full Kelly)
- Or: use conviction to widen/narrow the recommended range band, not the point estimate

### B. HIGH: Pre-Trade Checklist Is Partially Unenforceable

The checklist (Step 3.5) has 6 checks:

| Check | Enforceable? | Issue |
|-------|:---:|-------|
| Kill criteria have monitoring hooks | PARTIAL | `extract_kill_criteria()` sets `data_source` to "FRED:GENERIC" or "news_search:GENERIC" for most criteria — these are NOT programmatically monitorable. The check would pass (data_source is set) but the monitoring is fake. |
| Stop-loss above fragility zone | NO | Category error — fragility scanner doesn't produce instrument price zones (see Q4) |
| Position size within limits | YES | Pure arithmetic |
| No conflicting open positions | YES | Portfolio check is straightforward |
| Entry within market range | YES | But the 5% threshold is coarse — 4.9% stale is "OK" |
| Decision ticket fields complete | YES | Schema validation |

Two of six checks cannot be meaningfully enforced today. The checklist creates a false sense of safety.

### C. HIGH: Position Sizing Uses L3 Point Estimates as Distribution Parameters

The Kelly formula requires `avg_gain_pct` and `avg_loss_pct` (to compute R = gain/loss ratio). The plan sources these from "L3 target vs entry" and "L3 stop-loss vs entry" — single-point estimates:

- `avg_gain_pct` = (target_price - entry) / entry
- `avg_loss_pct` = (entry - stop_loss) / entry

But these are NOT averages. They are point estimates with no variance. The actual distribution of outcomes has fat tails — the stop-loss might not fill (gapping), the target might be hit but with slippage. Using point estimates in Kelly produces systematically overconfident bet sizes.

The point estimate R = 2.0 (gain/loss = 2:1) implies the gains and losses are symmetric around their means, which is almost never true in financial markets.

**Fix**: At minimum, widen the loss estimate by slippage assumption (1-2% for liquid instruments, 5%+ for illiquid). Better: present the Kelly computation as a range using best/worst case R ratios.

### D. MEDIUM: Volatility Percentile Data Source Is Undefined

`compute_position_size()` accepts `volatility_percentile: float` with the comment "from fragility scanner or market data." The fragility scanner reports an `overall_fragility_score` (0-1), not a volatility percentile. The fragility scanner monitors 12 thresholds and produces a weighted average — this is not a volatility metric. The data source is unspecified and may not exist in the current codebase.

### E. MEDIUM: Heat Budget Adjustment Is Too Aggressive

```python
heat_adj = min(1.0, (0.25 - existing_heat) / 0.25)
```

At 20% existing heat, `heat_adj = 0.20` — an 80% reduction. This means the second position in a portfolio gets sized at 20% of what Kelly recommends, regardless of whether it's correlated or uncorrelated with the first position. A portfolio with two perfectly uncorrelated 12.5% positions (total heat 25%) is actually BETTER diversified than a single 25% position, but this formula penalizes the second position identically regardless of diversification benefit.

The formula doesn't distinguish between:
- Adding to the same factor (concentration risk — should be penalized)
- Adding a diversifying position (reduces portfolio risk — should be rewarded)

### F. MEDIUM: No Liquidity/Slippage Constraint

The plan mentions portfolio and sector concentration limits but nothing about instrument liquidity. A 14.5% position in a $50M market-cap stock could require buying 5-10x the daily volume — impossible without massive market impact. The research document (§3.1) references "ADV-based checks, liquidity screening, NBBO comparison" from FINRA Rule 15c3-5, but none of this appears in the plan.

### G. LOW: Win Probability from DSR Is Invalid

The plan says win_probability comes "from resonance DSR or user override." DSR (Deflated Sharpe Ratio) measures the probability that an observed Sharpe ratio is statistically significant after accounting for selection bias (multiple testing). It answers: "Is this backtest result likely to be real or overfit?"

It does NOT answer: "What is the probability this trade will be profitable?"

These are fundamentally different questions. A strategy can have DSR = 0.99 (almost certainly not overfit) but still lose money 45% of the time if the edge is small. Conversely, a strategy with DSR = 0.50 could win 70% of trades if the signal is genuinely predictive but has high variance.

**Fix**: Either (a) calibrate a mapping from DSR to empirical win rate using backtest data, or (b) keep DSR as a separate "signal quality" metric and ask the user to estimate win probability independently.

### H. LOW: Shadow Domain Keyword Overlap

The `DOMAIN_KEYWORDS` mapping in `elite_participation.py` has overlapping triggers:
- "gold" is in both `gold` and `metals` domains
- "credit" is in both `bonds` and `financials`
- "rate" matches `bonds` ("rate") and `fx` ("carry") — and "carry" isn't a keyword, but the point stands

A user saying "gold prices and credit spreads" would trigger 4 shadows (gold, metals, bonds, financials). The plan's "7 of 12 relevant shadows" count could inflate from keyword overlap alone.

### I. LOW: The Plan References `PipelineOutput` Dataclass but the Fields Are Inconsistent

`PipelineOutput` lists:
- `l1: Layer1Result` — exists in `decision.py`
- `l2: Layer2Result` — exists
- `l3: Layer3BatchResult` — exists
- `red_team: RedTeamReport` — exists
- `resonance: ResonanceResult` — exists
- `fragility: FragilityReport` — exists
- `regime: RegimeMapping` — does this exist? Need to verify against `regime_mapper.py`
- `signal_conflicts: list[SignalConflict]` — exists in `decision.py`
- `hypotheses: list[HypothesisResult]` — exists

The `regime` field references `RegimeMapping` but the existing code in `regime_mapper.py` may use a different type name. This is minor but suggests the plan wasn't validated against current code.

---

## Summary

| # | Finding | Severity |
|---|---------|:---:|
| Q1 | Half-Kelly too aggressive for advisory; hard caps at institutional levels | HIGH |
| Q2 | Zero debiasing mechanisms; AI anchors user via evidence ordering | **CRITICAL** |
| Q3 | Shadow independence will degrade under Phase I; no statistical correction | MEDIUM |
| Q4 | Fragility scanner can't produce instrument price zones; category error | **CRITICAL** |
| Q5 | Correlation undefined; ignores regime change despite research doc warning | HIGH |
| Q6 | No mechanism for inter-gate mind-changing or market moves | HIGH |
| A | Conviction score double-counted with win_probability in Kelly | **CRITICAL** |
| B | 2 of 6 pre-trade checklist items unenforceable | HIGH |
| C | Point estimates used as distribution parameters in Kelly | HIGH |
| D | Volatility percentile data source undefined | MEDIUM |
| E | Heat budget adjustment penalizes diversification | MEDIUM |
| F | No liquidity/slippage constraint | MEDIUM |
| G | DSR mapped to win probability — different statistical constructs | LOW |
| H | Shadow keyword overlap inflates consensus counts | LOW |
| I | PipelineOutput field name may not match current code | LOW |

**3 CRITICAL, 5 HIGH, 4 MEDIUM, 3 LOW**

The CRITICAL findings (Q2, Q4, A) are blocking — they represent design errors that would produce wrong or misleading outputs at runtime. The HIGH findings (Q1, Q5, Q6, B, C) are significant gaps that would degrade the quality of investment decisions but wouldn't crash the system.

**Bottom line**: The plan captures the right STRUCTURE (two sequential gates, evidence display, decision ticket, checklist) but gets the DETAILS wrong in ways that matter for investment outcomes. The anchoring problem (Q2) alone is sufficient grounds to redesign the Gate 2 conviction flow. The fragility/stop-loss category error (Q4) means a core safety check cannot function as described. The conviction/Kelly double-count (A) means position sizes will be systematically miscalibrated.

**Recommendation**: Fix the 3 CRITICAL findings before any code is written. Address the 5 HIGH findings before Phase 4 integration. The MEDIUM and LOW findings can be deferred but should be tracked as issues.
