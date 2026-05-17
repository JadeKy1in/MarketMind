# Red Team Audit: Heuristic News Workflow — Investment Logic Review

**Audit target**: `docs/superpowers/plans/2026-05-17-heuristic-news-workflow.md`
**Supporting research**: `heuristic-workflow-1-analyst-patterns.md`, `heuristic-workflow-3-signal-verification.md`
**Audit date**: 2026-05-17
**Auditor role**: Investment Logic Auditor
**Scope**: LOGIC / INVESTMENT METHODOLOGY only (not code quality, not architecture, not token efficiency)

---

## Executive Summary

The plan correctly diagnoses the current pipeline's flaws (no browsing, no verification chain, Flash wastes tokens on irrelevant news) and proposes a structurally sound direction (progressive disclosure, HVR loop, layered verification). However, **the plan as specified would produce an engine that looks like an analyst's workflow but thinks like a confirmation-bias machine**. Six critical gaps must be addressed before implementation:

1. No expectation-gap analysis (the single most important analyst heuristic is missing)
2. Overlapping verification layers create an illusion of independence (L1 and L3 measure the same thing)
3. Adversarial self-check is a placeholder with zero methodology
4. No structural protection against post-hoc rationalization
5. Lead-lag relationships are treated as optional rather than core to verification routing
6. Druckenmiller/Soros/Dalio frameworks are invoked but their core philosophical commitments are absent

---

## Findings

### Finding 1: CRITICAL — Missing Expectation Gap Analysis

**Location**: Phase 2 (HVR loop), entire verification pipeline
**Research basis**: Analyst patterns §3, Signal verification §5.2

**What the plan does**: Forms hypotheses from top-scored Flash headlines, then verifies them against market data and sources.

**What it should do**: Before verifying ANY claim, establish the consensus expectation baseline. Per Research 1:

> *"The market doesn't react to what happened — it reacts to the delta between what happened and what was already discounted."*

Without this step, the AI cannot distinguish between:
- **Scenario A**: "ECB keeps rates on hold" → already fully priced → no tradable signal
- **Scenario B**: "ECB keeps rates on hold" → market expected a cut → surprise hawkish signal
- **Scenario C**: "ECB keeps rates on hold" → market feared a hike → relief rally signal

The same headline produces three diametrically opposite signals depending on expectations. The plan's 4-layer verification can confirm the FACT of the headline but cannot assess whether the delta from consensus is meaningful. This is the single most important analyst heuristic — Bloomberg terminal analysts spend their morning establishing "what's priced in" before reading a single news item in depth.

**Recommended fix**: Add an **Expectation Baseline step** between Phase 1 (hypothesis formation) and Phase 2 (verification). For each hypothesis, the AI must explicitly answer:
1. What was the consensus expectation before this news? (sell-side estimates, economist forecasts, recent price action)
2. What is the delta between the news and consensus?
3. Is this delta large enough to move prices, or is it noise?

Without this step, the pipeline will generate "signals" from information the market already knows.

---

### Finding 2: CRITICAL — Verification Layers 1 and 3 Are Not Independent

**Location**: Phase 2, 4-layer verification weighting (30/25/25/20)
**Research basis**: Signal verification §2.4, §2.6, §4

**What the plan does**: Assigns 30% weight to Layer 1 (Market Ground Truth: FedWatch, futures, bond yields) and 25% to Layer 3 (Market Data Validation: bond yields, credit spreads, commodity prices). Total: 55% of confidence comes from market pricing data.

**The problem**: These layers measure the same underlying construct — "what does the market price?" — through slightly different instruments. Research 3 §2.6 shows:
- Layer 1: "Check bond yields (macro claims)"
- Layer 3: "Bond yields validate rate claims"

A rate-cut claim confirmed by FedWatch (L1) AND 10Y yields (L3) is NOT two independent confirmations — it is one confirmation measured twice. This creates an illusion of multi-layer validation that inflates confidence scores. The research itself acknowledges this circularity by listing bond yields under both layers.

**Consequence**: A claim backed by strong futures pricing but zero independent source corroboration could score up to 55% confidence (30% L1 full pass + 25% L3 partial pass). This meets the "≥2 layers" criterion and approaches the 0.7 threshold using only market data — which is the same data that the plan's own anti-overfitting rule says is "a timing filter, not a signal source."

**Recommended fix**: Either (a) merge L1 and L3 into a single "Market-Based Verification" layer weighted at 30-35%, or (b) redefine L3 to be genuinely distinct — e.g., "Cross-Asset Triangulation" (rates AND equities AND credit AND FX must align, not just bond yields) or "Flow & Positioning" (options flow, block trades, sector ETF rotation). Then add a new layer for expectation gap (5-10%) and source trust tiering (15-20%).

---

### Finding 3: CRITICAL — Adversarial Self-Check Is a Placeholder

**Location**: Phase 4 ("反对意见（Adversarial self-check）")
**Research basis**: Analyst patterns §2 (bear case first), §6 (Hunterbrook model); Signal verification §6.4

**What the plan specifies**: Three Chinese characters and two English words with zero methodology, no checklist, no required output structure, no enforcement mechanism.

**What a real adversarial check requires** (from the research):

1. **The bear case must be built FIRST**, not appended to the output. Research 1 §2 and the cognitive decision tree (Q7): "Try to kill the thesis" happens BEFORE quantitative modeling and memo writing, not after.
2. **Specific falsification criteria**: For each link in the logic chain, what specific data point would break this link?
3. **Devil's Advocate agent**: LinqAlpha (cited in the research) uses a dedicated adversarial LLM agent on AWS Bedrock to stress-test theses. The plan's "self-check" by the same AI that built the thesis is methodologically unsound — you cannot reliably audit your own cognitive biases.
4. **Roulette Wheel trap check**: For each claim, the AI must explicitly answer: "Could a different explanation produce the same observable data?" (Research 1 §3)
5. **Information exclusivity check**: Per Mandelman's three criteria — is the information true, significant, AND exclusive to you? If the information is public and widely known, there is no edge (Research 1 §6).
6. **Anchoring bias check**: Is this thesis influenced by 52-week highs/lows? (Birru 2015, cited in Research 1 §3)

**Consequence**: Without a real adversarial check, the pipeline is a thesis-generation engine with a rubber-stamp "review" step. Every thesis will pass because the reviewer is the same model that wrote it.

**Recommended fix**: The adversarial check must be a **separate LLM call** with a dedicated system prompt that (a) receives the logic chain but NOT the confidence score, (b) is instructed to find the strongest possible counter-argument, (c) must produce at least one scenario where the thesis breaks, and (d) its output must be visible in the final report. If the adversarial agent finds a plausible break scenario, confidence is capped at 0.6 regardless of verification layers.

---

### Finding 4: HIGH — No Structural Protection Against Post-Hoc Rationalization

**Location**: Entire Phase 2-3 flow
**Research basis**: Analyst patterns §3 (Roulette Wheel trap), §5 (Druckenmiller: "listen to the market"); Signal verification §5.2

**What the plan does**: Phase 1 forms hypotheses from Flash-scored titles. Phase 2 then "verifies" those hypotheses by calling tools. Phase 3 links confirmed hypotheses into a logic chain.

**The structural problem**: The hypotheses are formed from the SAME news headlines that are being verified. The verification search is directed by the hypothesis — meaning the AI is asking "find evidence that supports my hunch" rather than "what does the totality of evidence say?" This is the classic confirmation-bias pipeline, now automated.

Consider the sequence:
1. Flash scores "ECB keeps rates on hold" as market_impact=7
2. AI forms hypothesis: "ECB may be forced to hike → EUR bullish"
3. AI searches for: rate futures showing hike probability, ECB statements with hawkish language, EUR/USD uptrend
4. AI finds confirming evidence (it searched for it!) → confidence score rises
5. AI does NOT systematically search for: dovish ECB statements, weakening EU data, EUR/USD resistance levels, reasons hikes might NOT happen

This is not verification — it is directional search dressed as verification.

**The research warns about this explicitly**: Research 1 §3 documents the "Roulette Wheel" trap — a trading desk that kept an Excel macro generating plausible-sounding explanations for random price moves. Much of Bloomberg/CNBC's real-time "news explanation" is post-hoc narrative construction. The plan's pipeline, without safeguards, automates exactly this pattern.

**What the research says should happen**: The cognitive decision tree (Research 1 §8) puts "TRY TO KILL THE THESIS" (Q7) BEFORE building the model and writing the memo. The verification step should actively search for disconfirming evidence with equal effort to confirming evidence.

**Recommended fixes**:
1. **Pre-registration**: Before any verification tool calls, the AI must write down (a) the hypothesis, (b) what specific data would confirm it, and (c) what specific data would falsify it. This is a write-once, immutable record.
2. **Mandatory disconfirming search**: For every hypothesis, at least one tool call must explicitly search for evidence that contradicts the hypothesis.
3. **Separate context windows**: The hypothesis-formation phase and the verification phase should use separate LLM calls with separate system prompts to prevent the model from "remembering" why it formed the hypothesis and selectively reading evidence.
4. **Contradiction weighting**: Evidence that contradicts the hypothesis should carry 1.5x weight in the confidence calculation vs. confirming evidence. This counteracts the natural tendency of LLMs (and humans) to overweight confirming data.
5. **"Failure to confirm" is not "refine"**: The current HVR loop has V → R (Verify → Refine). If verification fails, the default should be "abandon" (cut confidence below 0.3), not "refine to a weaker version of the same thesis." Druckenmiller's discipline: "wipe the slate clean any day" — if price action contradicts, CUT.

---

### Finding 5: HIGH — Lead-Lag Relationships Are Treated as Optional, Not Core

**Location**: Phase 2 HVR loop ("深化：查领先指标（HY 利差、PMI 等）")
**Research basis**: Signal verification §4 (detailed lead-lag hierarchy)

**What the plan does**: Mentions lead-lag indicators only in the "deepening" branch of the HVR loop — an optional step when the AI decides to go deeper. The 4-layer verification does not include lead-lag as a mandatory check.

**What the research says**: Lead-lag relationships are the most powerful verification tool for specific claim types. Research 3 §4.4 provides a mapping:

| Claim Type | Check This First | Lead Time |
|---|---|---|
| "Fed will cut/hike" | Bond yields, Fed Funds futures | 6-12 months |
| "Recession coming" | Yield curve (10Y-2Y), HY spreads | 12-18 months |
| "Economy slowing" | PMI New Orders | 1-3 quarters |
| "Market correction" | HY credit spreads | 9-12 months |
| "China recovering" | Copper, BDI | 3-5 months / weeks |

**The problem**: For a claim like "market selloff coming," the plan would verify through Layer 1 (market data — where are we now?) and Layer 2 (source corroboration — do other sources say selloff?). But the MOST POWERFUL verification is Layer 3's credit spread check — HY spreads lead equity drawdowns by 9-12 months. If HY spreads are narrow and stable, a "selloff coming" claim should be heavily discounted regardless of how many news sources repeat it.

The plan's verification is claim-type-agnostic: every claim gets the same 4 layers in the same order. But different claim types require different verification primitives. A rate claim needs FedWatch; a recession claim needs the yield curve; a commodity claim needs BDI and copper. The plan's one-size-fits-all approach dilutes the power of lead-lag verification.

**Recommended fix**: Add a **claim-type routing layer** between claim extraction and verification. Based on the claim type (rate, recession, inflation, growth, commodity, single-stock), route to the appropriate leading indicator first. The confidence scoring should weight lead-lag confirmation MORE heavily than same-period market data for claims with well-established leading indicators.

Specifically:
- Rate claims: FedWatch + yield curve check is MANDATORY, not optional
- Recession claims: HY spread + yield curve check is MANDATORY
- Inflation claims: Copper + breakeven rates is MANDATORY
- Growth claims: PMI New Orders is MANDATORY

A claim that FAILS its leading indicator check should be capped at confidence 0.4 regardless of source corroboration.

---

### Finding 6: HIGH — Druckenmiller/Soros/Dalio Frameworks Are Cherry-Picked

**Location**: Entire plan (claims to be based on Research 1 which covers all three)
**Research basis**: Analyst patterns §5

**What the plan gets right**:
- Dalio's principle of explicit, auditable rules (the pipeline is rules-based)
- Druckenmiller's multi-signal confirmation concept (the 4 layers)
- Soros's general notion of questioning one's own thesis (the adversarial check placeholder)

**What is cherry-picked or missing**:

**Druckenmiller — "if price contradicts, cut immediately" is inverted**:
Druckenmiller's core discipline: form thesis → build starter position → if price moves WITH thesis, pile in → if price CONTRADICTS, cut immediately. The plan's HVR loop says "Verify → if contradicted → Refine." This is the opposite of Druckenmiller's approach. He does not "refine" a contradicted thesis — he abandons it. The plan's "refine" step encourages the AI to modify the hypothesis to fit contradictory data rather than accepting that the thesis was wrong.

**Druckenmiller — price action disruption is not accounted for**:
Druckenmiller explicitly warns that passive/algorithmic investing has disrupted the correlation between price action and news. He now runs machine-driven strategies "purely to receive their signals as one more input" because price no longer reliably validates news. Yet the plan gives market price data the HIGHEST weight (30% L1 + 25% L3 = 55%). This is precisely the signal Druckenmiller says is increasingly unreliable.

**Soros — reflexivity is completely absent**:
Soros's entire framework is reflexivity: the two-way feedback between perception and reality that creates boom/bust cycles. The plan has zero reflexivity checks:
- No check for whether market perception is creating a self-reinforcing feedback loop
- No identification of "false trends" — beliefs founded on false assumptions
- No boom/bust cycle stage detection
- The "insecurity analyst" concept (constantly watching for discrepancies) is reduced to a single-line placeholder

**Dalio — principle evolution and error-based learning are absent**:
Dalio's framework is about encoding principles AND continuously refining them after every mistake. The plan's pipeline is static — it has no mechanism for:
- Tracking when a verified signal was wrong and updating weights
- Believability-weighted decisions (different sources/agents have different track records on different topics)
- "You make the move, it makes the move. You compare and refine" — the human-machine partnership

The plan mentions the shadow ecosystem but explicitly isolates it from the main AI — this is the opposite of Dalio's approach where multiple perspectives debate openly.

**Dalio — historical pattern match risk is unaddressed**:
Dalio's critical warning: "If you don't understand the algorithm and the future differs from the past, you're in big trouble." The plan's Layer 4 (Historical Pattern Match, 20%) directly exposes the pipeline to this risk, with no discussion of non-stationarity safeguards.

**Recommended fixes**:
1. Replace "Refine" in the HVR loop with a proper triage: Confirmed → proceed; Contradicted → abandon (capped at 0.3); Partially supported → refine with explicit documentation of what changed
2. Add a reflexivity check as a mandatory verification dimension: "Does this market perception create a feedback loop that changes the underlying fundamentals?"
3. Add an error-tracking database: every signal that reaches confidence ≥ 0.7 should be recorded with its outcome. Weights should be recalibrated quarterly based on actual predictive accuracy, not theoretical reliability.
4. Add a non-stationarity flag to Layer 4: when the current regime differs significantly from the historical pattern's regime, Layer 4 confidence is capped at 50% of its nominal score.

---

### Finding 7: HIGH — Missing Source Trust Tiering in Confidence Calculation

**Location**: Phase 2 confidence calibration
**Research basis**: Analyst patterns §4 (Information Edge Hierarchy); Signal verification §5.2 (Source trust tiering), §6.4 (Anti-Pattern #2)

**What the plan does**: Flash's output includes `source_tier` (1-3), but this is used only for triage prioritization. The 4-layer confidence scoring applies the same weights (30/25/25/20) regardless of whether Layer 2 corroboration comes from SEC EDGAR filings (Tier 1) or Twitter (Tier 3).

**What the research says**: Source trust tiering is MANDATORY. Research 3 §6.4 explicitly lists "Equal-weighting all sources" as an anti-pattern:

> *"A primary SEC filing and a Twitter rumor are not equal evidence."*

Research 1 §4 provides the Information Edge Hierarchy:
- Sell-side research / data subscriptions → edge decays immediately
- Expert networks → edge decays in weeks
- Commissioned primary research → edge decays in quarters
- Proprietary panels → edge decays in years

A claim corroborated by 3 Tier-1 sources (SEC filing + Bloomberg wire + Reuters wire) is fundamentally different from a claim corroborated by 3 Tier-3 sources (Twitter + Reddit + blog post). The current weighting treats them identically.

**Consequence**: The pipeline could generate high-confidence signals from social media echo chambers. A rumor repeated across 5 Twitter accounts would score higher on Layer 2 than a fact reported by one Bloomberg wire — but the Twitter reports are not independent (they're derivative) and not trustworthy.

**Recommended fix**: Multiply Layer 2's score by a source trust factor:
- Tier 1 (regulatory filings, exchange data, major wires): multiplier = 1.0
- Tier 2 (established research firms, verified press): multiplier = 0.7
- Tier 3 (self-reported, social media, unverified): multiplier = 0.3

Also: source independence must be verified. 5 Twitter accounts repeating the same rumor are 1 source, not 5. Research 1 §4 explicitly warns: "treating high-volume derivative mentions as independent verification is a fallacy."

---

### Finding 8: HIGH — Missing Atomic Claim Decomposition

**Location**: Phase 2 HVR loop (treats "a hypothesis" as the unit of verification)
**Research basis**: Signal verification §6.4 (Anti-Pattern #1)

**What the plan does**: The HVR loop has the AI form a hypothesis like "ECB 可能在下次会议加息 25bp" and then verify it holistically through the 4 layers.

**What the research says**: Research 3 §6.4 explicitly warns:

> *"Verifying the headline, not the atomic claims: A headline 'Fed likely to cut rates as economy slows' contains TWO claims — (a) Fed will cut rates, (b) economy is slowing. Each needs independent verification."*

The plan's Phase 3 example exhibits this exact problem. The logic chain step "欧洲 PMI 连续 3 个月 >55 → 经济基本面支持加息" contains the implicit claim "European PMI > 55 for 3 months" — this is a separate claim that should be independently verified before being used as evidence for the rate hypothesis.

Without atomic decomposition:
- A partially true hypothesis cannot be partially scored (it's pass/fail)
- Supporting claims go unverified, creating a house of cards
- The AI can bootstrap confidence by citing its own unverified claims as evidence for higher-level claims

**Recommended fix**: Before entering the HVR loop, decompose each hypothesis into atomic claims. Each atomic claim must pass its own verification. A hypothesis's confidence is the product of its atomic claim confidences (not the sum — one false atomic claim should collapse the chain). The AFEV framework cited in Research 3 achieves SOTA on 5 benchmarks with this approach.

---

### Finding 9: MEDIUM — Missing Regime Detection

**Location**: Entire verification pipeline
**Research basis**: Signal verification §2.4 (state-dependent response), §4.5 (caveats)

**What the plan does**: Verification treats all market environments identically. Layer 4 (Historical Pattern Match) implicitly assumes patterns are stable across regimes.

**What the research says**: Andersen et al. found that equity markets react differently to the SAME news depending on economic state:
- Expansions: bad news has POSITIVE impact (discount rate effect dominates)
- Recessions: bad news has NEGATIVE impact (cash flow effect dominates)

This means the same headline ("Fed raises rates") should be interpreted DIFFERENTLY in expansion vs. recession. The plan's verification pipeline doesn't check which regime we're in before interpreting signals.

Additionally, Research 3 §4.5 documents that China's structural shift from manufacturing-led to services-led growth has altered the reliability of commodity-linked leading indicators. Historical patterns (Layer 4) from the manufacturing-led era may not apply to the current regime.

**Recommended fix**: Add a regime classification step before verification. At minimum, classify as Expansion / Slowdown / Contraction / Recovery (Goldman Sachs framework cited in Research 1 §2). Use this to:
1. Adjust interpretation of market data verification (L1/L3)
2. Weight Layer 4 historical patterns by regime similarity (not just pattern similarity)
3. Flag when the current regime has no close historical analog (cap Layer 4 at bonus, not base score)

---

### Finding 10: MEDIUM — Confidence Calibration Has No Out-of-Sample Testing Plan

**Location**: Phase 2 confidence thresholds (0.7/0.4)
**Research basis**: Signal verification §5.5 (Budescu & Du 2007), §6.4 (Anti-Pattern #6)

**What the plan does**: Sets explicit thresholds (≥0.7 = trade, 0.4-0.7 = monitor, <0.4 = abandon) with no plan to calibrate them against actual outcomes.

**What the research says**: Research 3 §6.4 explicitly warns:

> *"Static confidence thresholds: Confidence thresholds should be calibrated against historical outcomes and updated periodically."*

Budescu & Du (2007) found that investors' probability judgments are internally consistent but often miscalibrated. Structured scoring frameworks outperform intuition but still require calibration against real outcomes.

The plan's 0.7 threshold is arbitrary. There is no evidence that 0.7 is the optimal trade-off between false positives (acting on noise) and false negatives (missing real signals). For some claim types, 0.6 might be optimal; for others, 0.85.

**Recommended fix**: Add a calibration requirement:
1. Before deploying, backtest the pipeline on 6-12 months of historical news with known outcomes
2. Calculate precision/recall at each threshold for each claim type
3. Set claim-type-specific thresholds based on precision-recall trade-off
4. Recalibrate quarterly as new outcome data accumulates
5. Track calibration error (predicted confidence vs. actual accuracy) and publish as a dashboard metric

---

### Finding 11: MEDIUM — Missing Catalyst Timing and Event Calendar Integration

**Location**: Entire workflow
**Research basis**: Analyst patterns §1 (Step 6: Catalyst calendar)

**What the plan does**: No mention of event calendars, earnings dates, FOMC meeting schedules, or regulatory decision timelines.

**What the research says**: Real analysts maintain a "catalyst calendar" tracking earnings dates, FDA/regulatory decisions, conferences, product launches, and contract expirations. This is Step 6 of the full analyst workflow — after quantitative modeling, before memo writing.

For news-driven strategies, timing is critical. A correct signal ("Fed will cut rates") arriving the day AFTER the FOMC meeting is worthless. A correct signal arriving 2 months before the meeting has time to be acted on. The plan's verification doesn't account for event proximity.

**Recommended fix**: For claims with known event dates (FOMC meetings, earnings, economic releases), add a timing factor to confidence:
- If the claim's event is ≤2 days away: information is likely stale, confidence capped at 0.5
- If the claim's event is 2-14 days away: normal scoring
- If the claim's event is >14 days away: higher uncertainty, confidence reduced by 10%
- If the claim has NO identifiable event date: flag as "no catalyst visibility," reduce by 15%

---

### Finding 12: MEDIUM — Missing Insider Activity and Flow Analysis

**Location**: Verification pipeline
**Research basis**: Analyst patterns §1 (Step 6: Full Picture Check), §4 (Cross-Referencing Chain 3)

**What the plan does**: The 4-layer verification covers market data (L1/L3), source corroboration (L2), and history (L4). It does not include insider activity, options flow, block trades, or institutional positioning.

**What the research says**: The "Full Picture Check" (Research 1 Step 6) includes:
- Unusual options activity
- Block trades
- 13F filings
- Insider buying/selling (SEC-reported)
- Short interest / float

These are among the most powerful signals because they show what people with the MOST information are doing with their own capital. A corporate insider selling ahead of good news is a stronger signal than 3 news sources reporting that news.

The cross-referencing chain for company-specific news (Research 1 §4, Chain 3) explicitly includes: "Check insider filings (any recent buying/selling?)" as a core step.

**Recommended fix**: Add a "Flow & Positioning" dimension to Layer 3 (or make it a new verification check). For company-specific claims, require checking insider activity before the claim reaches confidence ≥ 0.7. If insiders are selling while the claim is bullish, confidence is capped at 0.5 regardless of other layers.

---

### Finding 13: LOW — Confidence Score Calculation Is Underspecified

**Location**: Phase 2 confidence calibration
**Research basis**: Signal verification §5.3, §5.4

**What the plan specifies**: 
- Weights: L1=30%, L2=25%, L3=25%, L4=20%
- Thresholds: ≥0.7 AND ≥2 layers → trade; 0.4-0.7 → monitor; <0.4 → abandon

**What is not specified**:
1. Is each layer scored as binary (pass/fail) or continuous (0.0-1.0)?
2. If continuous, what constitutes "enough" to count a layer as "confirmed" for the "≥2 layers" requirement?
3. Does the weighted sum produce the final confidence, or is there an additional aggregation step?
4. How do contradiction penalties work? (L1 says strong confirmation, L3 says strong contradiction → what score?)
5. Is there a time decay factor? (Research 3 §6.4: "A verified claim from 3 weeks ago is no longer verified.")
6. Is there a minimum evidence requirement per layer? (You can't "pass" Layer 2 with 0 sources found.)

**Example of ambiguity**: A hypothesis where:
- L1 (FedWatch): 90% confirmation → 0.9 × 0.3 = 0.27
- L2 (sources): 2 independent sources found → partial? full? weight contribution unclear
- L3 (market data): bond yields contradict → 0.0 × 0.25 = 0.0
- L4 (history): 60% historical match → 0.6 × 0.2 = 0.12

Total: 0.27 + (L2 unknown) + 0.0 + 0.12. If L2 gets 0.25 full credit, total = 0.64. This is below 0.7 but above 0.4 — "monitor." But this hypothesis has a DIRECT market contradiction (L3=0.0)! Should a contradicted hypothesis really be worth monitoring?

**Recommended fix**: The scoring specification must answer: (1) continuous vs. binary per layer, (2) contradiction penalty rules, (3) time decay formula, (4) minimum evidence floor per layer, (5) how the "≥2 layers confirmed" criterion interacts with the weighted sum. Until these are specified, the confidence score is not implementable.

---

### Finding 14: LOW — Shadow Ecosystem Isolation Undermines Dalio's Multi-Perspective Model

**Location**: Section 5 (Shadow ecosystem interaction)
**Research basis**: Analyst patterns §5 (Dalio: believability-weighted decisions)

**What the plan does**: Explicitly isolates shadows from the main AI: "主 AI 的启发式搜索结果不同步给影子" and "ELITE 影子在 Gate 2 按领域触发参与，看到的是用户讨论内容（可能包含主 AI 的逻辑链），但不影响其独立判断."

**What the research says**: Dalio's framework is built on multiple perspectives debating openly. The "Dot Collector" lets colleagues rate each other, and decisions are weighted by believability on each topic. The goal is "idea meritocracy where the best ideas win out over human bias."

**The tension**: The plan wants shadows to be independent (to avoid contamination) but also wants a Dalio-style multi-perspective system. These goals conflict. If shadows never see the main AI's analysis, they can't challenge it. If they only see it indirectly through user discussion, the challenge is delayed and filtered.

This is not necessarily wrong — independence has value for preventing groupthink — but the plan should acknowledge the trade-off explicitly rather than claiming Dalio's framework while architecting against it.

**Rating as LOW** because the isolation is a valid architectural choice (preventing contamination may be more important than debate for a system that can't trade), but the philosophical inconsistency should be noted.

---

## What the Plan Got RIGHT

To be clear: the plan's structural direction is sound and several elements are well-conceived:

1. **Progressive disclosure (3-level triage)**: Flash does minimal scoring, Pro does deep work only on high-impact items. This correctly mirrors how analysts skim headlines before diving deep. The token budget (~9,500) is reasonable.

2. **HVR loop concept**: The iterative hypothesize-verify-refine cycle correctly models the non-linear nature of real investigative research. Analysts don't follow a linear pipeline — they loop, backtrack, and refine. The plan captures this.

3. **Multi-layer verification**: While the specific layers and weights need revision, the concept of requiring multiple independent verification dimensions before acting is solid. The research strongly supports that single-source/single-dimension signals are noise.

4. **Confidence thresholds with explicit tiers**: Having clear decision thresholds (trade/monitor/abandon) is better than a continuous "sort of confident" output. The exact thresholds need calibration, but the tiered structure is correct.

5. **"Don't act" is a valid output**: Phase 4 requiring equal-depth论证 for "don't act" recommendations is excellent. This prevents the pipeline from always finding a reason to act — a common failure mode in trading systems.

6. **No reinforcement of shadow bias**: Keeping shadows independent from the main AI's analysis prevents herding. This is a genuinely good design choice for the specific MarketMind context (analysis-only, no trading).

7. **Affected asset chain mapping**: The Phase 3 example correctly traces first, second, and third-order effects (ECB → EUR → DAX → export stocks). This is exactly what real analysts do.

8. **Token efficiency**: The plan correctly identifies that Flash's current "equal-depth extraction on all 50 news items" wastes tokens on low-signal content.

9. **Tool mapping**: Flash's output includes `suggested_tools` and `affected_assets` — this is operationally useful and shows awareness that different claims need different verification tools.

10. **Research-grounded**: The plan cites all 4 research documents and the logic chain directly reflects the cognitive decision tree from Research 1, even if incompletely.

---

## Priority Summary

| # | Finding | Rating | Must Fix Before Implementation? |
|---|---------|:------:|:---:|
| 1 | Missing expectation gap analysis | CRITICAL | YES |
| 2 | L1 and L3 are not independent | CRITICAL | YES |
| 3 | Adversarial self-check is a placeholder | CRITICAL | YES |
| 4 | No protection against post-hoc rationalization | HIGH | YES |
| 5 | Lead-lag treated as optional | HIGH | YES |
| 6 | Druckenmiller/Soros/Dalio cherry-picked | HIGH | Recommend |
| 7 | Missing source trust tiering | HIGH | YES |
| 8 | Missing atomic claim decomposition | HIGH | YES |
| 9 | Missing regime detection | MEDIUM | Recommend |
| 10 | No calibration plan for thresholds | MEDIUM | Recommend |
| 11 | Missing catalyst timing | MEDIUM | Recommend |
| 12 | Missing insider activity/flow analysis | MEDIUM | Consider |
| 13 | Confidence calculation underspecified | LOW | YES |
| 14 | Shadow isolation vs. Dalio multi-perspective | LOW | No |

---

**Audit disposition**: The plan CAN proceed to implementation if the 3 CRITICAL findings and 5 HIGH findings are addressed. The recommended approach is:
1. First: Restructure the verification layers (merge L1/L3, add expectation gap, add source trust tiering) — addresses Findings 1, 2, 7
2. Second: Add structural anti-confirmation-bias mechanisms (pre-registration, disconfirming search, separate adversarial agent) — addresses Findings 3, 4
3. Third: Add claim-type routing for lead-lag verification (different claim types → different required checks) — addresses Finding 5
4. Fourth: Add atomic claim decomposition before HVR loop — addresses Finding 8
5. Fifth: Specify the confidence calculation formula completely — addresses Finding 13
6. Sixth: Revise the Druckenmiller/Soros/Dalio integration to be faithful to their core philosophies rather than surface-level feature extraction — addresses Finding 6

Implementation should NOT begin until at least Findings 1-5, 7-8, and 13 are addressed in a revised plan.
