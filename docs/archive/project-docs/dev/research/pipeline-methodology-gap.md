# MarketMind Pipeline vs. Professional Macro Analysis — Gap Analysis

**Date**: 2026-05-18
**Compared against**: Reference macro analysis methodology (investment_analysis_sample.md)
**Status**: Gap analysis complete — 10 dimensions assessed

---

## Summary

MarketMind's current pipeline (v2.0, 10 stages from scout through archive) is a competent signal-processing system with verification, adversarial challenge, and statistical validation. However, when compared against professional macro investment analysis methodology, the pipeline lacks the analytical depth, institutional mechanism knowledge, and multi-directional causal reasoning that characterize expert analysis. Of the 10 dimensions assessed, **4 are CRITICAL gaps**, **6 are MAJOR gaps**, and **0 are Minor**. The pipeline is strong at verifying whether a claim is supported by data, but weak at *generating* the kind of layered, mechanism-specific, entity-tracked analysis that the reference methodology demonstrates.

---

## Dimension-by-Dimension Analysis

### 1. Multi-Layer Causal Chain (Asset/Liability Dual-Direction)

**Reference capability**: Simultaneously traces causal chains through both the asset side (Fed holdings: Treasuries, MBS, repo) and liability side (currency in circulation, bank reserves, TGA, ON RRP) of the Fed balance sheet. Derives conclusions from how changes on one side propagate to the other.

**Current pipeline**: The HVR investigation loop (`investigation_loop.py`) generates hypotheses and verifies them through the 4-layer verification chain (`verification_chain.py`), but the verification layers treat a claim as a monolithic proposition. There is no decomposition lens — no ability to say "this claim has an asset-side mechanism and a liability-side mechanism, and they produce opposing forces." The `verification_chain.py` Layer 1 (Market Pricing) checks COT positioning and ticker prices but has no concept of balance sheet decomposition. Layer 2 (Fundamental Data) queries FRED/EIA/BLS for individual indicators but never cross-references asset-side vs. liability-side data.

**Gap severity**: CRITICAL

**Recommendation**: Build a new `pipeline/causal_decomposition.py` module (~200-300 lines). This module should:
1. Accept a hypothesis and identify whether it has asset-side and liability-side dimensions.
2. Map each dimension to specific data series (asset side: Treasury holdings by maturity, MBS holdings, repo; liability side: reserves, TGA balance, ON RRP, currency).
3. Assign directional weights per side (e.g., "asset side contraction is negative for liquidity, liability side TGA drawdown is positive").
4. Produce a `CausalDecomposition` dataclass with `asset_side_score`, `liability_side_score`, and `net_directional_force`.
5. Integrate into `investigation_loop.py` so each hypothesis gets decomposed before entering the HVR cycle.

Wire this as a new phase option in `pipeline-manifest.yaml` Stage 3 (Layer 1) — it enhances rather than replaces the existing analysis.

### 2. Historical Cycle Comparison (Regime Mapping)

**Reference capability**: Maps the current macro regime against historical analogues — 1951 (Treasury-Fed Accord), 1979-1982 (Volcker-era quantity control), 1982-2008 (Greenspan-era rate control), 2008-present (QE-era quantity dominance). Each regime is defined by: (a) which policy tool was dominant (rates vs. quantities), (b) the geopolitical backdrop, (c) the consequence for asset prices.

**Current pipeline**: `verification_chain.py` Layer 4 (Historical Pattern) is a fixed-base-rate heuristic. It maps keywords to hardcoded probabilities: `rate_cut → 0.65`, `recession → 0.35`, `oil_spike → 0.50`. There is no regime database, no cycle-analog search, no temporal-context matching. The code comment explicitly calls this "a conservative placeholder pending that database." The `resonance.py` module (DSR/CSCV/PBO) performs statistical validation of signal portfolios but does not compare current conditions to historical regimes.

**Gap severity**: CRITICAL

**Recommendation**: Build `pipeline/regime_mapper.py` (~250-350 lines) to replace the placeholder Layer 4. This should:
1. Define ~6-8 macro regimes with structured metadata: `{regime_id, years, dominant_tool, rate_regime, quantity_regime, geopolitical_context, asset_class_performance}`.
2. Accept a hypothesis + current macro data and compute cosine similarity against each regime.
3. Return the top-3 closest regimes with historical base rates (what % of similar claims played out in that regime).
4. Integrate as the new implementation of Layer 4, replacing the fixed-vocabulary heuristic in `verify_claim_historical()`.

Regime definitions should be stored in a new `config/regime_library.py` (data module, exempt from single-entry-point rule) that can be progressively enriched.

### 3. "Who Is Buying What" Entity-Level Flow Tracking

**Reference capability**: Decomposes every market flow by entity: (a) US households (direct + via trusts/non-profits), (b) US financial institutions, (c) foreign official (central banks), (d) foreign private (hedge funds via Cayman Islands), (e) the Fed itself. Tracks each entity's Treasury holdings by maturity bucket (bills, notes, bonds). Explains *why* each entity is buying (e.g., "foreign institutions buy short-term Treasuries because the FX swap-hedged yield is positive").

**Current pipeline**: The pipeline has no concept of entity-level flow decomposition. The `scout.py` collects news, `flash_preprocessor.py` extracts signals, `layer2_fundamental.py` identifies sectors and tickers — but none of these modules ask "who is buying/selling what, and why." The `verification_chain.py` Layer 3 (Multi-Source News) counts independent sources but doesn't attribute claims to entity-level flows. The COT data in Layer 1 captures speculative positioning in futures but not cash-market flow by entity type.

**Gap severity**: CRITICAL

**Recommendation**: Build `pipeline/flow_decomposition.py` (~200-300 lines). This should:
1. Define entity categories as a structured enum: `{US_HOUSEHOLD, US_INSTITUTIONAL, FOREIGN_OFFICIAL, FOREIGN_PRIVATE, FED, US_TREASURY}`.
2. For each hypothesis, prompt Pro to identify which entities are on the buy-side and sell-side for the relevant asset class.
3. Integrate with `gateway/macro_data.py` to pull Treasury International Capital (TIC) data, Fed H.4.1 release (factor table), and Fed Z.1 Financial Accounts for entity-level holdings.
4. Produce `FlowAttribution` objects: `{entity, asset_class, direction, estimated_size, rationale}`.
5. Surface as a new section in the Layer 2 output, feeding into the decision synthesis.

Note: TIC data has a ~6-week lag but provides the authoritative cross-border flow picture. H.4.1 is weekly. Z.1 is quarterly. Accept the lag — the reference methodology uses lagged data for structural understanding, not timing.

### 4. Counter-Intuitive Discovery (Consensus-Violating Signals)

**Reference capability**: Actively hunts for conditions where the surface narrative and the underlying mechanics diverge. Examples: "balance sheet is shrinking but stocks are rising — because Treasury (not Fed) is now the liquidity provider through bill issuance." Produces multi-step explanations of *why* the counter-intuitive pattern exists, not just that it contradicts consensus.

**Current pipeline**: `investigation_loop.py` has a `_determine_verdict()` function that returns `HIGH_CONTENTION` when `bear_confidence > bear_discount * main_confidence`. This is a single-dimension, pairwise comparison: if the bear case is strong relative to the bull case, label it contentious. The contradiction detection in `verification_chain.py` (`_detect_contradiction()`) checks if one layer scores high while another scores low. Both are reactive — they detect disagreement, but they don't *actively search for* counter-intuitive patterns. A genuinely counter-intuitive market condition (like "QT + rallying equities") may have high confidence on all layers and never trigger contradiction detection.

**Gap severity**: MAJOR

**Recommendation**: Extend `investigation_loop.py` (~80-120 line addition) with a new `_counter_intuitive_scan()` function:

1. After the Pre-Act planning phase, add a dedicated Pro prompt: "For each hypothesis, identify what the consensus narrative predicts and whether any observable data contradicts it. Look specifically for: (a) price moves in the opposite direction of what fundamentals would predict, (b) flows that contradict stated policy intent, (c) correlations that have inverted relative to historical norms."
2. For hypotheses flagged as potentially counter-intuitive, run `_expectation_gap_check()` but with the inverted question: "What % of market participants would be *surprised* by this claim?"
3. Add `counter_intuitive_score: float` and `consensus_narrative: str` fields to `HypothesisResult`.
4. Promote counter-intuitive hypotheses with high confidence to a new verdict tier: `COUNTER_CONSENSUS_ACTIONABLE` — these are the highest-value signals because they represent edge that the market hasn't priced.

This requires no new module — it's an enhancement within `investigation_loop.py`.

### 5. Specific Mechanism Naming (Institutional Terminology)

**Reference capability**: Names precise institutional mechanisms: eSLR (supplementary leverage ratio exemption), IORB (interest on reserve balances), FIMA (Foreign and International Monetary Authorities repo facility), TGA (Treasury General Account), RRP (overnight reverse repo), SWIFT, FX basis swaps, yield curve steepening vs. flattening dynamics. Each mechanism is defined and its causal role in the chain is explained.

**Current pipeline**: The LLM prompts throughout the pipeline use generic language. The `_PRE_ACT_SYSTEM` prompt says "formulate a SPECIFIC, FALSIFIABLE hypothesis" but doesn't instruct the model to name institutional mechanisms. The `verification_chain.py` has data-source mappings (`_KEYWORD_FRED_MAP`, `_KEYWORD_EIA_MAP`, `_KEYWORD_COT_MAP`) but these map to data series, not to institutional mechanisms. The `layer2_fundamental.py` output is structured as `macro_quadrant`, `sector_shortlist`, `ticker_candidates` — all about *what* to trade, not *what mechanism* drives the trade.

**Gap severity**: MAJOR

**Recommendation**: Modify the system prompts in three files (~20-40 lines total):

1. **`investigation_loop.py` `_PRE_ACT_SYSTEM`**: Add a rule: "Each hypothesis must name at least one specific institutional mechanism (e.g., 'FIMA repo facility,' 'eSLR exemption,' 'IORB-EFFR spread,' 'FX swap basis,' 'cross-currency basis'). Do NOT use vague terms like 'liquidity injection' — name the precise channel."

2. **`layer2_fundamental.py` `LAYER2_SYSTEM_PROMPT`**: Add a new output field `mechanisms: [str]` requiring 2-4 named mechanisms driving each macro quadrant assignment.

3. **`verification_chain.py`**: Extend the keyword-to-datasource dictionaries to include mechanism names as search targets. When a hypothesis mentions "eSLR" or "FIMA," route to specific verification logic.

Also create `config/mechanism_glossary.py` (~50-80 lines) — a data module mapping mechanism names to: description, data source for tracking, directional implication for asset prices, and related mechanisms. This feeds into prompt enrichment.

### 6. Conditional Forecasting (Branching Scenarios)

**Reference capability**: Produces conditional forecasts with explicit branching logic: "To shrink the balance sheet, the Fed must first cut rates for approximately one year, restructure bank regulations (eSLR, stress tests, discount window), and bifurcate the TGA account — *if* these conditions are met, QT can proceed; *if not*, rate cuts alone will be insufficient." The forecast is a tree, not a point estimate.

**Current pipeline**: `HypothesisResult` produces a scalar `confidence` (0-1 float), an `expectation_gap` (float), and a flat `verdict` string (ACTIONABLE/MONITOR/DISCARD/PRICED_IN/HIGH_CONTENTION). The `_hvr_cycle()` function refines a hypothesis iteratively but converges toward a single refined hypothesis — it never branches into "if A then X, if B then Y." The `decision.py` synthesis stage produces `DecisionOutput` with `decision_cards`, each card having a `confidence` and `rationale` but no conditional branches.

**Gap severity**: MAJOR

**Recommendation**: Build `pipeline/scenario_forecaster.py` (~200-300 lines). This module should:

1. Accept a `HypothesisResult` that has reached ACTIONABLE verdict.
2. Prompt Pro to identify 2-3 key condition variables that determine whether the hypothesis plays out (e.g., "10Y yield stays below 4.5%," "Congress passes regulatory reform," "USDJPY stays above 140").
3. For each condition combination, produce a conditional forecast: `{conditions: {var: state}, probability: float, outcome: str, confidence: float, timeline: str}`.
4. Produce a `ScenarioTree` dataclass with `base_case`, `upside_case`, `downside_case`, each with conditions, probabilities, and confidence.
5. Integrate as Stage 7.5 (between Resonance and Decision), feeding into `generate_decision()` so decision cards include conditional reasoning.

Add `scenario_tree` as an optional field to `HypothesisResult` and populate it for ACTIONABLE verdicts only (to control token cost).

### 7. Cross-Border Capital Flows

**Reference capability**: Tracks cross-border capital flows through multiple channels: (a) SWIFT payment system flows, (b) FX swap / cross-currency basis markets, (c) basis trades (long cash Treasuries / short Treasury futures) by hedge funds, (d) sovereign wealth fund allocations, (e) FIMA repo facility usage. Explains how Japanese and European institutions buying US assets affects both US and local markets simultaneously.

**Current pipeline**: The `macro_data.py` gateway provides COT positioning data (ES, CL, GC, NG futures), FRED indicators (BDI, GSCPI), and EIA inventory data. None of these capture cross-border flows. The `scout.py` fetches from ~33 news sources but no source provides systematic cross-border flow data (TIC data, SWIFT volumes, BIS banking statistics, cross-currency basis). The `source_independence.py` module groups sources by ownership but doesn't distinguish geographic or jurisdictional coverage.

**Gap severity**: CRITICAL

**Recommendation**: Three-part intervention:

1. **New data gateway**: Build `gateway/cross_border.py` (~200-300 lines) to fetch:
   - US TIC monthly data (Treasury.gov — free, CSV)
   - BIS Locational Banking Statistics (BIS API — free, JSON)
   - Cross-currency basis spreads (Bloomberg/Reuters terminal or free FRED series `EXJPUS` for JPY, `EXUSEU` for EUR)
   - FIMA repo usage (Fed H.4.1 Table 1a — weekly, free)

2. **New pipeline module**: Build `pipeline/cross_border_analyzer.py` (~200-250 lines) that:
   - Accepts the L1 narrative result and current hypothesis list
   - Computes flow direction by entity/country/asset class
   - Flags anomalies (e.g., "Japan selling despite positive carry," "Cayman Islands holdings surging")
   - Produces `CrossBorderFlowReport` with per-channel findings

3. **Integrate into verification chain**: Add as a new optional verification layer (Layer 5: Cross-Border Flows, weight 0.10) in `verification_chain.py`, reducing the other weights proportionally or keeping it as a supplementary "contextual" layer that doesn't affect weighted confidence but enriches the final report.

### 8. Charts as Reasoning Tools

**Reference capability**: Treats each chart as a logical step in an argument chain. The methodology moves from "chart showing Fed balance sheet vs. S&P 500" to "chart showing asset-side composition changes" to "chart showing who buys what maturity" — each chart isolates one variable, advances the argument by one step, and the series of charts collectively proves a multi-step thesis.

**Current pipeline**: The `multimodal_adapter.py` (gateway) can ingest images, PDFs, and screenshots via Gemini Flash. However, the analysis pipeline itself is text-only: it produces text hypotheses, text verification results, and text decision cards. It never generates visual reasoning or references charts as logical building blocks. The output format (Markdown reports) is ASCII-only per design constraints, which precludes embedded charts.

**Gap severity**: MAJOR

**Recommendation**: Two-phase approach:

**Phase D (current)**: Add chart-reasoning to the text pipeline without generating actual images:
1. In `investigation_loop.py`, add a `_chart_reasoning_step()` that prompts Pro: "For each step in your logic chain, describe what chart would prove or disprove this step. What would the x-axis be? What would the y-axis be? What shape would confirm vs. refute the claim?" (~40-60 line addition)
2. Store chart specifications as `ChartSpec` objects in the `HypothesisResult.logic_chain` — these are machine-readable chart descriptions (not rendered images).
3. In `decision.py`, surface the most impactful chart specs in the decision rationale.

**Phase E (future)**: Build a lightweight chart renderer using `matplotlib` (already a dependency) that takes `ChartSpec` objects and renders PNGs. This would be a new `pipeline/chart_renderer.py` (~200 lines) triggered only when `--charts` flag is passed. The ASCII-only constraint for Markdown reports remains; charts would be supplementary files in the archive.

### 9. "Consensus Narratives → Break" Structure

**Reference capability**: First establishes what "most people think" (the consensus narrative: "the Fed is shrinking its balance sheet, which is bearish for stocks"), then systematically dismantles it by showing what is actually happening ("the Fed is shrinking, but Treasury is expanding bill issuance, which provides equivalent liquidity — here's the proof"). The structure creates analytical tension and resolution.

**Current pipeline**: The pipeline has no explicit "consensus narrative" layer. The `layer1_narrative.py` produces narrative analysis (`event_grade`, `matrix_quadrant`, `sentiment`, `cascade_tracking`) but describes *what is happening*, not *what people think is happening* vs. *what is actually happening*. The `red_team.py` adversarial challenge attacks the analysis, but it attacks from a skeptical angle — it doesn't establish "here's what the market believes" as a baseline to deviate from.

**Gap severity**: MAJOR

**Recommendation**: Add a new pre-analysis step within `investigation_loop.py` (~60-80 line addition):

1. **Consensus extraction**: After Pre-Act planning generates hypotheses, for each hypothesis, prompt Pro: "What is the current market consensus on this topic? What would a 'consensus investor' predict? Be specific about the consensus mechanism (e.g., 'The consensus believes QT = lower equities because it removes a buyer')."

2. **Gap measurement**: For each hypothesis, compare the consensus prediction with the verification results. Compute `consensus_deviation`: how far the verified claim deviates from the consensus expectation.

3. **Narrative structure**: Add fields to `HypothesisResult`:
   - `consensus_view: str` — what most people think
   - `actual_evidence: str` — what the data shows
   - `consensus_deviation: float` — 0-1 score of how much the evidence diverges from consensus

4. Surface these in `decision.py` output as "Narrative Break" cards — the highest-value insights are those where consensus is wrong.

This leverages Dimension 4 (counter-intuitive discovery) and Dimension 6 (conditional forecasting) — the consensus break is strongest when it's conditional ("consensus is right IF rates stay high, but IF rates fall in 3 months, consensus is dead wrong").

### 10. System Vulnerability Identification (Fragility Analysis)

**Reference capability**: Identifies specific fragility points in the financial system with threshold values: "bank reserves below $2.7 trillion triggers liquidity stress," "10-year yield above 4.5% triggers a presidential policy reversal," "ON RRP falling to zero removes the last liquidity buffer." Each fragility point has: (a) a specific metric, (b) a threshold value, (c) a mechanism explaining what happens when crossed, and (d) a cascading failure chain showing second-order effects.

**Current pipeline**: The pipeline has no fragility analysis module. `resonance.py` (DSR/CSCV/PBO) validates whether signals have predictive structure — it asks "is this signal real?" not "where does the system break?" The `red_team.py` adversarial challenge identifies logical flaws and missing evidence but doesn't search for systemic thresholds. The `decision.py` synthesis considers confidence and risk levels but doesn't model cascading failures.

**Gap severity**: CRITICAL

**Recommendation**: Build `pipeline/fragility_scanner.py` (~250-350 lines). This module should:

1. **Threshold library**: Create `config/fragility_thresholds.py` (~100 lines) — a data module with known fragility points:
   ```python
   FRAGILITY_POINTS = [
       {"metric": "bank_reserves", "threshold": 2.7e12, "unit": "USD",
        "direction": "below", "mechanism": "Liquidity stress — repo rates spike above IORB",
        "cascade": ["repo_spike", "dealer_balance_sheet_stress", "equity_correlation_breakdown"]},
       {"metric": "us10y_yield", "threshold": 4.5, "unit": "percent",
        "direction": "above", "mechanism": "Political pain threshold — triggers policy reversal",
        "cascade": ["tariff_concession", "fed_dovish_pivot", "dollar_weakness"]},
       # ... ~15-20 such entries
   ]
   ```

2. **Scanner**: For each hypothesis, check whether it implies crossing any known fragility thresholds. If the hypothesis says "rates will rise to 5%," scan whether this crosses the 4.5% political threshold, the 5.5% mortgage stress threshold, etc.

3. **Cascade modeler**: For crossed thresholds, prompt Pro to generate a 3-step cascade chain: "If bank reserves fall below $2.7T, what happens first? Second? Third? What assets are most exposed at each step?"

4. **Integration**: Feed `FragilityReport` into the Red Team stage (`red_team.py`) as a target for adversarial attack, and into `decision.py` as a risk overlay on decision cards. A decision card that would otherwise recommend a buy should carry a warning if the position is exposed to a fragility threshold within 5% of the current level.

This is a net-new capability with no precedent in the current pipeline — it requires a new module, new config, and integration into two existing stages.

---

## Priority Roadmap

Based on dependency chains and blast radius, the recommended build order is:

| Priority | Dimension | New/Modified Files | Est. Lines | Rationale |
|:---:|------|------|:---:|------|
| 1 | **#5 Mechanism Naming** | `investigation_loop.py` (prompt edit), `layer2_fundamental.py` (prompt edit), `config/mechanism_glossary.py` (new) | ~100 | Zero blast radius — prompt edits only. Enables all other dimensions by giving the LLM precise vocabulary. |
| 2 | **#1 Causal Decomposition** | `pipeline/causal_decomposition.py` (new), `investigation_loop.py` (integration) | ~250 | Foundation for Dimensions 3, 6, 10. Without decomposition, other modules can't attach to specific causal channels. |
| 3 | **#3 Flow Tracking** | `pipeline/flow_decomposition.py` (new), `gateway/macro_data.py` (TIC + H.4.1) | ~300 | Data dependency on gateway changes. Needed before Dimension 7 (cross-border flows) can work. |
| 4 | **#2 Historical Regime** | `pipeline/regime_mapper.py` (new), `config/regime_library.py` (new), `verification_chain.py` (replace L4) | ~350 | Replaces a placeholder implementation. No interdependencies. |
| 5 | **#6 Conditional Forecasting** | `pipeline/scenario_forecaster.py` (new), `investigation_loop.py` (integration), `decision.py` (integration) | ~300 | Depends on #1 (causal decomposition) for condition variables. |
| 6 | **#4 Counter-Intuitive + #9 Consensus Break** | `investigation_loop.py` (extend), `decision.py` (extend) | ~150 | Two dimensions, same module. Both are prompt-level changes to `investigation_loop.py`. |
| 7 | **#10 Fragility Analysis** | `pipeline/fragility_scanner.py` (new), `config/fragility_thresholds.py` (new), `red_team.py` (integration) | ~350 | Depends on #1 and #3 for threshold-context matching. |
| 8 | **#7 Cross-Border Flows** | `gateway/cross_border.py` (new), `pipeline/cross_border_analyzer.py` (new), `verification_chain.py` (new layer) | ~500 | Largest effort. Depends on #3 (flow tracking) for entity-level data. |
| 9 | **#8 Charts as Reasoning** | `investigation_loop.py` (extend), `pipeline/chart_renderer.py` (new, Phase E) | ~250 | Independent of other dimensions. Can be done anytime. Phase D (text chart specs) is lower priority. |

---

## What the Pipeline Already Does Well

These capabilities should be preserved and are competitive with professional analysis:

1. **Adversarial self-check** (#4 partially): The mandatory bear case generation (`_adversarial_bear_check()`) with a dedicated skeptical persona is genuinely good practice. Many analysts skip this step.

2. **Source independence verification** (#3 partially): The `source_independence.py` ownership-group deduplication prevents Sybil-attack consensus fabrication. This is sophisticated and uncommon.

3. **Multi-layer verification with graceful degradation**: Each of the 4 verification layers degrades to 0.50 on API failure rather than crashing. The layer independence check (`_detect_contradiction()`) correctly identifies when data sources disagree.

4. **Statistical signal validation**: `resonance.py` (DSR/CSCV/PBO) provides genuine statistical rigor that many professional analysts skip entirely.

5. **Shadow ecosystem independence**: The information broadcast rules (shadows only see raw news, not main AI analysis) prevent anchoring bias — this is a thoughtful design pattern that mirrors how good investment teams prevent groupthink.
