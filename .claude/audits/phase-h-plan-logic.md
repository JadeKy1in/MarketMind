# Red Team Audit: Phase H Comprehensive Architecture — Logic / Investment Methodology

**Date**: 2026-05-18
**Auditor**: Red Team (Logic / Investment Methodology)
**Plan audited**: `.claude/plans/phase-h-comprehensive-architecture.md`
**Supporting research**: `.claude/research/pipeline-methodology-gap.md` (10-dimension gap analysis)
**Focus**: Causal decomposition validity across asset classes, flow framework geographic bias, regime mapper structural bias, scenario forecaster verdict filter, fragility threshold staleness, mechanism glossary update mechanism, cross-module conflict resolution, time-horizon conflicts, over-measurement risk

---

## Executive Summary

**Verdict: NOT READY** — 2 CRITICAL, 5 HIGH, 5 MEDIUM, 2 LOW findings. The plan correctly diagnoses the pipeline's analytical gaps and proposes structurally coherent modules. However, it applies a **universal analytical lens** (balance-sheet causal decomposition, US-centric flow entities, US-equity-centric regime data) to what is described as a multi-asset analysis system. Three modules embed structural biases that will systematically produce misleading outputs for non-US, non-equity assets. Two modules have no update or staleness-detection mechanisms, guaranteeing they will rot post-deployment. The plan has no cross-module conflict resolution — independent signals accumulate but never synthesize. Most critically, the scenario forecaster filters by verdict rather than by risk, potentially suppressing warning signals from non-ACTIONABLE hypotheses. The plan needs methodological redesign before implementation begins.

---

## Findings

### Finding 1: CRITICAL — Causal Decomposition Applies a Universal Balance-Sheet Lens to Incompatible Asset Classes

**Location**: Plan Section 二, Module 1 (`causal_decomposition.py`)
**Plan text**: `asset_side_factors`, `liability_side_factors`, `net_liquidity_impact`
**Research basis**: Methodology gap analysis Dimension 1

**What the plan proposes**: Decompose every hypothesis into asset-side and liability-side factors, computing a `net_liquidity_impact` from -1 (draining) to +1 (injecting). The structure is explicitly borrowed from balance-sheet analysis of the Federal Reserve system.

**The problem**: The asset/liability framework is valid for exactly ONE use case: analyzing Federal Reserve monetary operations and their impact on US fixed-income markets. For other asset classes, the framework produces nonsensical or misleading decompositions:

| Asset Class | Can "asset side" and "liability side" be meaningfully defined? | What replaces the balance-sheet lens? |
|---|---|---|
| **US Treasuries / MBS** | YES — Fed balance sheet, Treasury TGA, bank reserves | The plan's framework applies here |
| **US Equities (S&P 500)** | Partially — corporate balance sheets exist, but liquidity transmission through the Fed is indirect. Asset-side = corporate buybacks, liability-side = debt issuance. Does not map cleanly. | Earnings, discount rates, buyback flows, sector rotation |
| **European Equities (DAX, Euro Stoxx)** | NO — ECB balance sheet is relevant, but plan's framework assumes Fed-centric asset-side decomposition (Treasuries, MBS, repo). ECB holds different assets (CSPP, PEPP). | ECB policy transmission, EUR strength, EU fiscal policy, export sector exposure |
| **Commodities (oil, copper, soybeans)** | NO — commodities do not have balance sheets. There is no "asset side" or "liability side" of crude oil. | Supply/demand balance, inventory levels (EIA, LME, etc.), physical flows, backwardation/contango |
| **Crypto (BTC, ETH)** | NO — crypto networks do not have balance sheets in the Fed sense. | Exchange reserves (on-chain), stablecoin flows, hash rate, network activity, ETF flows |
| **FX (EUR/USD, USD/JPY)** | Partially — but TWO central bank balance sheets interact (ECB + Fed, BoJ + Fed). The plan's single-entity assumption breaks down. | Interest rate differentials, carry trade dynamics, cross-currency basis, current account balances |

**Concrete failure example**: The pipeline analyzes a hypothesis "Soybean futures will rise on China demand recovery." The causal decomposition module is invoked. It receives a commodity hypothesis and searches for "asset_side_factors" and "liability_side_factors" of ... what? Soybeans have no balance sheet, no reserves, no TGA. The LLM (prompted with the balance-sheet system prompt) will either (a) hallucinate asset/liability factors that don't exist ("asset side: Chinese strategic reserves drawing down"), (b) force-fit unrelated concepts into the asset/liability frame, or (c) return near-zero scores for both sides because nothing matches, producing a `net_liquidity_impact` of ~0 — which is misleading because the real drivers (weather, Chinese demand, Brazilian supply) are entirely legitimate but invisible to the framework.

**The plan's implicit assumption**: The plan was generated from reference methodology that analyzed US Treasury markets through a Fed balance-sheet lens. The gap analysis (Dimension 1) explicitly frames the problem in Fed-balance-sheet terms: "asset side: Fed holdings of Treasuries, MBS, repo / liability side: currency, reserves, TGA, ON RRP." This lens was generalized to "decompose ALL hypotheses" without asset-class discrimination.

**Recommended fix**: The causal decomposition module must include **asset-class routing** before decomposition logic is applied:

1. Classify the hypothesis by asset class (equity, fixed income, commodity, FX, crypto).
2. Route to the appropriate decomposition framework:
   - **Fixed income (US)**: Asset/liability balance-sheet decomposition (current design)
   - **Equities**: Earnings + discount rate + buyback + fund-flow decomposition (not balance-sheet)
   - **Commodities**: Supply + demand + inventory + geopolitics decomposition
   - **FX**: Dual-central-bank + carry trade + current-account decomposition
   - **Crypto**: On-chain (exchange reserves, hash rate, active addresses) + off-chain (ETF flows, regulatory) decomposition
3. Only invoke `net_liquidity_impact` for asset classes where "liquidity" (in the Fed reserves sense) is a valid concept.
4. For non-fixed-income asset classes, replace `net_liquidity_impact` with a domain-appropriate net directional force (e.g., `net_supply_demand_balance` for commodities, `net_carry_pressure` for FX).

Without this routing, the module is **valid for ~15% of hypotheses (US fixed income) and produces noise for the other 85%**.

---

### Finding 2: CRITICAL — Flow Decomposition Uses US-Centric Entity Types That Do Not Generalize

**Location**: Plan Section 二, Module 2 (`flow_decomposition.py`)
**Plan text**: 5 entity types: `US_HOUSEHOLD | US_INSTITUTIONAL | FOREIGN_OFFICIAL | FOREIGN_PRIVATE | FED`
**Research basis**: Methodology gap analysis Dimension 3

**What the plan proposes**: Classify every market flow by entity type — who is buying/selling what, and why. The 5 entity types are drawn from the US Treasury market reference analysis.

**The problem**: The entity types are defined from the perspective of "who owns US Treasuries." When applied to non-US assets, the framework collapses into meaningless categories:

| Asset Being Analyzed | What "FOREIGN_OFFICIAL" means | What it SHOULD mean |
|---|---|---|
| **US Treasuries** | Japanese MoF, Chinese SAFE buying US debt | Correct — this is what the framework was designed for |
| **European equities (DAX)** | "Foreign official" from WHOSE perspective? A US investor buying DAX is "foreign private" to the DAX. An ECB official buying would be ... domestic official? The framework has no EU-centric entity model. | ECB, European households (high savings rate), European pension funds, US institutional (largest foreign buyer of DAX), Chinese sovereign wealth funds |
| **Chinese bonds** | "FOREIGN_OFFICIAL" = non-Chinese central banks buying CGBs via Bond Connect. But what about the PBoC itself? Chinese state banks? Chinese households? | PBoC, Chinese state banks (primary dealers), Chinese households (via wealth management products), foreign official (via Bond Connect/CIBM), foreign private (hedge funds via swap) |
| **Japanese Yen (USD/JPY)** | "FED" is one entity. But what about the BoJ? The GPIF (Japan's $1.5T pension fund)? Japanese retail (Mrs. Watanabe)? | BoJ (YCC operator), GPIF (largest domestic allocator), Japanese banks (carry trade), Japanese retail (FX margin traders), US hedge funds (carry trade counterparty) |
| **Gold** | Who are the entities? Central banks (foreign official), ETF holders (US institutional), Indian households (not in the 5 types at all), Chinese retail (not in the 5 types) | Central banks (gold reserve buyers), ETF flows (GLD, IAU), futures speculators (COMEX), physical buyers (India, China, Turkey), producers (mining companies hedging) |

**Concrete failure example**: Analyzing "Japanese Yen will weaken to 160 as BoJ maintains YCC." The flow decomposition prompted with the 5 US entity types asks: which entity is buying/selling? The most relevant entities are:
- **BoJ** (buying JGBs, maintaining YCC — NOT in the entity list)
- **Japanese retail** (selling JPY, buying USD for carry trade — NOT in the entity list)
- **GPIF** (allocating to foreign assets, selling JPY — NOT in the entity list)
- **US hedge funds** (buying JPY as carry-trade counterparty — only entity in the list)

The model would classify 3 of 4 dominant entities as "missing" or "other" while over-weighting the 1 entity that happens to fit the US-centric framework. The resulting `flow_imbalance` would be systematically wrong.

**The deeper architectural issue**: The plan's entity model assumes the **US dollar is the numeraire currency** and the **US Treasury market is the reference asset**. This is evident from the entity naming: `FOREIGN_OFFICIAL` and `FOREIGN_PRIVATE` are defined by their relationship to the US. For a genuinely multi-asset pipeline (which MarketMind claims to be, given it analyzes EUR, commodities, crypto, etc.), the entity model must be asset-centric, not US-centric.

**Recommended fix**: Replace the hardcoded 5-type US entity model with a **configurable entity registry** keyed by asset class:

```python
ENTITY_REGISTRY = {
    "US_TREASURIES": [FED, US_HOUSEHOLD, US_INSTITUTIONAL, FOREIGN_OFFICIAL, FOREIGN_PRIVATE],
    "EUR_ASSETS": [ECB, EU_HOUSEHOLD, EU_INSTITUTIONAL, EU_GOVERNMENT, FOREIGN_INSTITUTIONAL, FOREIGN_OFFICIAL],
    "JPY_ASSETS": [BOJ, GPIF, JP_HOUSEHOLD, JP_BANKS, FOREIGN_HEDGE_FUNDS, FOREIGN_OFFICIAL],
    "CNY_ASSETS": [PBOC, CN_STATE_BANKS, CN_HOUSEHOLD, FOREIGN_OFFICIAL, FOREIGN_PRIVATE],
    "COMMODITIES": [PRODUCERS, PHYSICAL_BUYERS, ETF_FLOWS, SPECULATORS, CENTRAL_BANKS],
    "CRYPTO": [EXCHANGE_RESERVES, ETF_FLOWS, MINERS, STABLECOIN_ISSUERS, RETAIL],
}
```

The flow decomposition module should:
1. Identify which asset class the hypothesis relates to.
2. Load the appropriate entity model from the registry.
3. Prompt the LLM with the entity model SPECIFIC to that asset class.
4. Produce `FlowAttribution` using the asset-class-appropriate entity taxonomy.

If the entity model for a given asset class is unknown or incomplete, the module should produce `entities_available: False` and explain why — rather than forcing US-centric entities onto an incompatible market.

Additionally, when a hypothesis involves cross-border flows (e.g., "Japanese investors buying US Treasuries"), the flow attribution should use a **dual-entity model**: Japanese entities (from JPY registry) AND US entities (from Treasury registry), with clear labeling of which entity model each attribution comes from.

---

### Finding 3: HIGH — Regime Mapper Embeds a Self-Fulfilling Equity Bullish Bias

**Location**: Plan Section 二, Module 3 (`regime_mapper.py`)
**Plan text**: "7 变量：S&P 500 同比、10Y-2Y 利差、WTI 同比、铜同比、T-bill 收益率、VIX 水平、股债相关性"; "数据：1985-2025 月度"
**Research basis**: Methodology gap analysis Dimension 2; Dalio's warning about historical pattern matching when futures differ from past

**What the plan proposes**: A 7-variable Euclidean distance model trained on 1985-2025 monthly data, searching for historical periods similar to current conditions. Output includes `forward_3m_equity`, `forward_6m_equity`, `forward_12m_equity` — forward equity returns from similar historical periods.

**Problem 1 — S&P 500 Y/Y as an input variable**: The 7 variables include S&P 500 YoY return. This means the similarity search IS influenced by current equity returns. When stocks are up 20% YoY (a strong year), the "most similar" periods will be other strong years when stocks were also up ~20% YoY. In those similar periods, forward returns were LIKELY positive because bull markets tend to persist in the short-to-medium term. This is not regime identification — it is **momentum disguised as regime analysis**.

**Concrete failure mode**: Current conditions (2026-05): S&P up 15% YoY, VIX at 18, 10Y-2Y spread +50bp, WTI at $65. The Euclidean search finds 1995, 2017, and 2019 as top analogues — all mid-cycle bull markets with positive forward equity returns. The model confidently predicts positive forward equity returns based on "historical regime similarity."

But if the 7 variables did NOT include S&P 500, the analogues might be very different. The identical macro conditions (10Y-2Y, WTI, copper, T-bill, VIX) could have occurred in late 2007 (before the GFC) or mid-2000 (before the dot-com crash) — but those periods had DIFFERENT S&P 500 Y/Y values and are therefore excluded from similarity. The inclusion of equity returns in the input vector **filters out structurally similar regimes that had different equity outcomes**, guaranteeing the model will "find" bullish analogues whenever stocks are already up.

**Problem 2 — 1985-2025 is predominantly disinflationary**: The training window excludes the 1970s stagflation era entirely. Every regime in the training data exists in a fundamentally disinflationary macro environment. The model has no concept of:
- Persistent inflation above 5% for multiple years
- Stagflation (rising inflation + falling growth)
- Wage-price spirals
- Commodity supply shocks that are not transitory
- Central banks losing credibility

If 2026-2028 enters a genuinely different regime (sustained inflation from tariffs/deglobalization + slowing growth), the regime mapper will have ZERO relevant analogues. The `top_analogues` list may contain the "most similar" periods, but with Euclidean distance so high that the similarity is meaningless. The plan's mitigation — "fallback to keyword heuristic" — is not a real mitigation; keyword heuristic is what the plan explicitly criticizes as inadequate ("固定关键词 → 固定概率（`rate_cut=0.65`），不是真正的历史对比").

**Problem 3 — Euclidean distance assumes all variables matter equally**: In a disinflationary regime (1982-2020), equities, bonds, and commodities were loosely correlated — all 7 variables had roughly similar importance for regime classification. In a stagflationary regime, the dominant regime-defining variables shift: CPI, WTI, and T-bill rate become 3-5x more important than the other 4 variables. Euclidean distance (which weights all dimensions equally) will produce high similarity scores for periods that match on the wrong variables and diverge on the critical ones. A period with "similar VIX, similar 10Y-2Y, similar S&P" but "very different inflation" would rank as similar when it is fundamentally a different regime.

**Recommended fix** — Three-part intervention:

1. **Remove S&P 500 Y/Y from the input vector**. Replace with a non-equity macro variable: CPI YoY or PCE YoY. Equity returns are the OUTPUT we want to predict, not an INPUT to the regime classifier. Including it creates circular reasoning that invalidates the module's purpose.

2. **Extend the training window to 1970-2025 using reconstructed data** where FRED series are unavailable. At minimum, include 1973-1982 (stagflation era). Accept that some series (VIX) did not exist before 1990 — use known proxies (realized volatility computed from daily price data). Accept missing data rather than ignoring the most important out-of-sample regime.

3. **Replace Euclidean distance with regime-weighted distance**. Define regime-defining variables per macro regime and weight them 3-5x higher in the distance calculation:
   - **Inflationary regime** (CPI > 4%): Weight CPI, WTI, T-bill at 3x; discount VIX and stock-bond correlation
   - **Deflationary/recession regime** (GDP < 0, CPI < 1%): Weight 10Y-2Y, VIX, T-bill at 3x
   - **Goldilocks regime** (GDP > 2%, CPI 1-3%): Equal weights (current default)

4. **Add an "out-of-sample" flag**. When the current macro vector has no historical analogue with distance < 0.3 (normalized), flag `regime_confidence: "LOW — no close historical analogue."` In this state, forward return projections should be suppressed and the module should output "regime is unprecedented in training data."

---

### Finding 4: HIGH — Scenario Forecaster Filters by Verdict, Not by Risk — Suppressing the Most Dangerous Scenarios

**Location**: Plan Section 二, Module 4 (`scenario_forecaster.py`)
**Plan text**: "仅对 ACTIONABLE 判定运行（~1-3 个假设/会话），控制 token 成本"
**Research basis**: Methodology gap analysis Dimension 6

**What the plan proposes**: Run conditional scenario analysis (base/upside/downside trees) ONLY for hypotheses that reach ACTIONABLE verdict. The stated rationale is token cost control (~1-3 hypotheses per session).

**The problem**: The verdict — ACTIONABLE, MONITOR, HIGH_CONTENTION, DISCARD, PRICED_IN — classifies hypotheses by **actionability**, not by **risk**. A hypothesis with a MONITOR verdict (confidence 0.4-0.7) can embed a catastrophic downside scenario that the user SHOULD be warned about. By filtering on verdict, the plan suppresses scenario analysis for precisely the hypotheses where "what if this goes wrong?" matters most.

**Concrete failure examples**:

| Hypothesis | Verdict | Confidence | Why Scenario Analysis is Needed | Suppressed by Plan? |
|---|---|---|---|---|
| "S&P 500 will rally to 6500 on AI productivity boom" | ACTIONABLE | 0.78 | Base/upside/downside are all within normal range | NO — scenario analysis runs |
| "ON RRP approaching zero, repo market could seize up" | MONITOR | 0.62 | The 5% downside scenario is a 2019-style repo crisis with -15% equity drawdown. The user needs to see this branch. | **YES — scenario analysis suppressed** |
| "Chinese property debt restructuring will succeed or fail on PBOC's next move" | HIGH_CONTENTION | N/A (bear=0.58, bull=0.55) | The down-branch involves a cascade of developer defaults with cross-border contagion. The user should see the tree. | **YES — scenario analysis suppressed** |
| "ECB will hold rates, EUR/USD stays range-bound" | PRICED_IN | 0.45 | Low confidence, but the scenario analysis might reveal a 15% probability of ECB surprise cut → -5% EUR flash crash | **YES — scenario analysis suppressed** |

The worst-case scenario for a MONITOR verdict (systemic risk, black swan) is often MORE dangerous than the worst-case for an ACTIONABLE verdict (normal market drawdown). The ACTIONABLE-only filter is optimizing for the WRONG variable — it minimizes token cost while maximizing the probability of missing catastrophic tail-risk scenarios.

**The deeper methodological error**: The plan conflates two independent dimensions:
1. **Signal confidence** (how sure are we this will happen?) → drives verdict
2. **Tail risk** (how bad could it be IF it happens, or IF the opposite happens?) → drives scenario analysis

These are orthogonal. A low-confidence signal can have catastrophic tail risk. A high-confidence signal can have benign tail risk. Filtering scenario analysis on the first dimension means you never analyze tail-risk scenarios for low-confidence signals, which is precisely where tail risk is most important to understand.

**Recommended fix**:

1. **Run scenario forecaster on ALL non-DISCARD verdicts** (ACTIONABLE + MONITOR + HIGH_CONTENTION). The token cost increase is modest — instead of 1-3 hypotheses getting scenarios, 3-5 get them. The MONITOR/HIGH_CONTENTION hypotheses typically cluster around fewer condition variables, so scenario branches tend to be shallower.

2. **Prioritize scenario analysis by tail-risk, not by confidence**:
   - After the initial HypothesisResult is generated, compute a `tail_risk_flag` (from fragility scanner or from a quick Pro prompt: "Does this hypothesis, if wrong, imply a >10% drawdown in any major asset class?").
   - Run scenario analysis FIRST for tail-risk-flagged hypotheses, regardless of verdict.
   - Non-tail-risk ACTIONABLE hypotheses get scenarios second (current behavior).

3. **For HIGH_CONTENTION hypotheses specifically**: The scenario tree should show BOTH paths — what happens if the bull case is right AND what happens if the bear case is right — each with their own conditional branching. HIGH_CONTENTION is BY DEFINITION a scenario where both outcomes are plausible, making it the most natural candidate for branching scenario analysis.

4. **Token budget**: If token cost is a hard constraint, cap scenarios at the 5 hypotheses with the highest `tail_risk_flag * (1 - confidence)` product — i.e., the signals that are both dangerous AND uncertain, which is the alpha of risk management.

---

### Finding 5: HIGH — Fragility Scanner Has No Staleness Detection and No Update Mechanism

**Location**: Plan Section 二, Module 5 (`fragility_scanner.py`), config/fragility_thresholds.py
**Plan text**: "阈值库 (`config/fragility_thresholds.py`)：初始 ~15 条，来自专业文献"; "谁维护这些？怎么更新？" (auditor's questions 5, explicitly asked by the user prompt)
**Research basis**: Methodology gap analysis Dimension 10

**What the plan proposes**: 15 hardcoded fragility thresholds (bank reserves, 10Y yield, ON RRP, SOFR-IORB spread, HYG-LQD spread, VIX, etc.) stored in a Python config file. When a threshold is crossed or within 5% of crossing, generate a warning with cascade chain.

**The problem**: Financial system thresholds are NOT constants. They drift with market structure, policy changes, and regime shifts. A threshold that was meaningful in 2024 can be irrelevant or misleading in 2026.

**Concrete staleness examples**:

| Threshold | Value in Plan | Why It May Be Stale |
|---|---|---|
| ON RRP | $50B (below = buffer exhausted) | ON RRP peaked at $2.5T in mid-2023 and has been draining. By 2026-05, ON RRP could already be at $0 — making the threshold moot. OR, a new facility (SRF, standing repo) could replace ON RRP as the primary buffer, making the threshold measure the wrong variable. |
| Bank Reserves | $2.7T (below = SOFR spike) | The "lowest comfortable level of reserves" (LCLoR) shifts over time. The Fed's 2019 experience recalibrated this to ~$1.5T, but post-SVB (March 2023), the banking system's reserve demand may have shifted. The $2.7T figure comes from a specific historical period and is NOT a structural constant. |
| 10Y Yield | 4.5% (above = political pain) | "Political pain threshold" is a function of fiscal policy, not market structure. A Republican administration with a tax-cut agenda may have a HIGHER tolerance for rising yields than a Democratic administration. The threshold is administration-dependent. |
| SOFR-IORB Spread | +25bp (above = repo crisis) | The spread that triggers dealer balance sheet stress depends on regulatory capital requirements (SLR, GSIB surcharge), which change every few years. Post-2024 Basel III endgame implementation, the stress threshold may shift. |
| VIX | 35 (above = panic selling) | The VIX "panic" threshold drifts with market structure. In the 2010s, 35 was panic. Post-2020, with 0DTE options and VIX ETN structural flows, 35 may be the "new 25." Conversely, in a low-vol regime, 25 might already signal stress. |

**The update problem**: The plan provides no mechanism for:
1. **Who** reviews and updates thresholds (human analyst? automated data check?)
2. **When** thresholds are reviewed (quarterly? after market events? never?)
3. **How** thresholds are validated (what data confirms a threshold is still correct?)
4. **What triggers** a review (a threshold being crossed without consequence? a crisis activating an unlisted threshold?)
5. **Versioning** of thresholds (if threshold changes from $2.7T to $2.2T, is the old value archived with justification?)

Without these mechanisms, the fragility scanner will produce increasingly stale warnings — flagging thresholds that no longer matter and missing thresholds that have become critical.

**Concrete failure mode**: In 2024, ON RRP drainage from $2.5T to near-zero was a critical market narrative. By 2026-05, ON RRP has been near zero for a year and markets have adapted. The scanner continues to flag "ON RRP below $50B — last liquidity buffer exhausted" as a CRITICAL warning every session. The user sees this warning every day, learns to ignore it, and misses an actual new fragility that develops (e.g., "standing repo facility utilization exceeds capacity" or "dealer Treasury inventory approaching VaR limits" — neither of which is in the original 15-threshold list).

**Recommended fix** — Three-part intervention:

1. **Add metadata to every threshold**:
```python
@dataclass
class FragilityThreshold:
    metric: str
    current_value: float          # fetched at runtime
    threshold_value: float
    threshold_source: str         # "FRB_NY_staff_report_2024_Q3" or "JPM_fixed_income_weekly_2025_01"
    threshold_as_of: str          # "2024-09-15" — when was this threshold established?
    last_validated: str           # "2026-01-10" — when was it last confirmed still relevant?
    validation_method: str        # "manual_review" | "event_confirmed" | "auto_stale_check"
    direction: str
    crossed: bool
    cascade: list[str]
    relevance_confidence: float   # 0-1 — how confident are we this threshold still matters?
```

2. **Implement staleness heuristics**:
   - If `threshold_as_of` is > 18 months ago and `last_validated` is > 12 months ago → flag as "STALE — review recommended"
   - If a threshold is crossed but the predicted cascade does NOT materialize within 30 days → reduce `relevance_confidence` by 0.3
   - If a market event occurs (repo spike, equity drawdown >5%) and NONE of the existing thresholds predicted it → flag "missing threshold" for analyst review
   - Each session, print: "N of M thresholds validated within 12 months. K thresholds flagged as stale."

3. **LLM-assisted threshold maintenance**:
   - Once per quarter (or after major Fed/regulatory events), prompt Pro: "Review the current fragility thresholds. Based on recent market structure changes (list them), are any thresholds obsolete? Should any new thresholds be added?" 
   - The LLM PROPOSES changes but does not auto-apply them. Proposed changes go to a human review queue.
   - If a new Fed facility is created (e.g., 2020-style emergency facilities), the mechanism glossary update (Finding 6) should trigger a corresponding fragility threshold review.

---

### Finding 6: HIGH — Mechanism Glossary Is Static with No "Unknown Mechanism" Escape Hatch

**Location**: Plan Section 二, Module 0 (`mechanism_glossary.py`)
**Plan text**: "映射：机制名 → {描述, 数据源, 方向含义, 相关机制}"; "所有 Pro 级 prompt 的 system prompt 追加"
**Research basis**: Methodology gap analysis Dimension 5

**What the plan proposes**: 40 hardcoded mechanism entries (eSLR, IORB, FIMA, TGA, RRP, SWIFT, FX basis, etc.) embedded into system prompts. When the LLM encounters a mechanism name in analysis, it uses the glossary definition.

**Problem 1 — No "unknown mechanism" signal**: The glossary is a lookup table embedded in the system prompt. When the LLM encounters a mechanism NOT in the glossary, it has three options: (a) use its training-data knowledge (which may be outdated), (b) infer from context (which may be wrong), or (c) say "I don't know." The system prompt encourages option (a) or (b) because the instruction says "使用标准术语" — it pressures the LLM to use glossary terms rather than admitting ignorance.

**Concrete failure mode**: The Fed creates a new facility in 2026 (call it "Term Liquidity Backstop" or TLB). The LLM encounters "TLB usage surged this week to $200B" in a news headline. TLB is NOT in the 40-entry glossary. The LLM, prompted to "use standard terminology and map each mechanism to its data source and asset price implications," does one of:
- **Hallucinates**: Maps TLB to the closest glossary entry (FIMA repo, SRF) and applies those directional implications, producing a confident but wrong analysis
- **Skips it**: Ignores TLB because it's not in the glossary, missing the most important flow of the week
- **Misleads**: Uses its training data (cut off ~Jan 2026) where TLB doesn't exist, treats it as a typo or non-event

None of these outcomes are acceptable for a system that claims to provide institutional-quality macro analysis.

**Problem 2 — No update trigger**: The Fed routinely creates, modifies, and sunsets facilities. During the 2020 COVID crisis alone: PMCCF, SMCCF, TALF, MLF, PPPLF, MSLP — six new facilities in 3 months. During the 2023 SVB crisis: BTFP. The plan's 40-entry glossary is frozen at creation time. There is no mechanism for:
- Detecting that a new facility/program has been announced
- Flagging that an existing glossary entry's description is outdated
- Proposing new entries for human review
- Deprecating entries for sunsetted facilities

**Problem 3 — Configuration as prompt, not as tool**: The plan embeds the glossary into system prompts (a text string injection). This means the LLM must parse, recall, and correctly apply glossary definitions entirely through its attention mechanism — the same mechanism that hallucinates. A more reliable approach would make the glossary a **tool** that the LLM can query: "When you encounter an unfamiliar mechanism name, call `lookup_mechanism("TLB")` to retrieve its definition. If the lookup returns 'unknown,' flag it and proceed with caution."

**Recommended fix**:

1. **Add an "unknown mechanism" protocol**: Extend the system prompt with:
   > "When you encounter an institutional mechanism or facility name that is NOT in the mechanism glossary, do NOT infer its meaning. Instead, explicitly state: 'Note: [mechanism name] is not in the mechanism glossary. Analysis below uses general knowledge which may be incomplete.' Flag unknown mechanisms for analyst review."

2. **Make the glossary queryable at runtime**:
   - Expose `lookup_mechanism(name: str) -> Mechanism | None` as a tool call
   - Return structured data (description, data_source, directional, related) rather than relying on prompt-embedded recall
   - If `None` is returned, the LLM can branch: search for the mechanism name in recent news, or flag it

3. **Add a staleness check**:
   - Each glossary entry has `last_updated: str` and `regulatory_status: str` ("active" | "sunsetted" | "modified")
   - Before each session, run a lightweight check: "Are any glossary entries flagged as sunsetted? List them."
   - If sunsetted mechanisms appear in current analysis, flag as potential error

4. **Automated gap detection**: Once per week (or on `--maintenance` flag), run a Pro prompt:
   > "Review the past week's financial news. Are there any new Federal Reserve facilities, regulatory programs, or institutional mechanisms mentioned that are NOT in the current glossary? If yes, draft proposed glossary entries with description, data source, and directional implications."
   
   Draft entries go to human review. This closes the loop between "the world changed" and "the glossary knows about it."

---

### Finding 7: HIGH — Cross-Module Conflict Resolution Does Not Exist

**Location**: Plan Section 三 (Pipeline Integration), Section 二 Modules 1-6
**Plan text**: Causal decomposition and flow decomposition run in parallel (`asyncio.gather`). All modules produce independent dataclass outputs attached to `HypothesisResult` as optional fields.
**Research basis**: N/A — this is a synthesis gap not covered by the gap analysis

**What the plan does**: Six modules each produce independent analytical outputs. Causal decomposition says one thing (e.g., "TGA rising = liquidity draining, NET BEARISH"). Flow decomposition says another (e.g., "foreign official buying = supportive, NET BULLISH"). Both are attached to the same `HypothesisResult` as optional fields. The `decision.py` stage receives all of them.

**What the plan does NOT do**: There is no synthesis step. No conflict detection. No resolution logic. No weighted aggregation. The modules operate as **independent analytical silos** that never speak to each other.

**Concrete failure example**: The pipeline analyzes "US 10Y yields will fall." Six modules produce:

| Module | Signal | Direction | Net Impact |
|---|---|---|---|
| Causal Decomposition | TGA drawdown releases reserves → lower funding costs → rates fall | BULLISH (for bond prices) | +0.6 |
| Flow Decomposition | Foreign official selling long-end, US institutional buying short-end → curve steepening, but long-end selling means yields RISE | BEARISH (for bond prices) | -0.4 |
| Regime Mapper | 1995 analogue: mid-cycle, rates fell 100bp over next 12 months | BULLISH | +0.7 |
| Fragility Scanner | Bank reserves approaching $2.7T threshold → if crossed, SOFR spikes → short-term rates SPIKE, long-end uncertainty | UNCERTAIN (volatile) | +0.1 risk overlay |
| Cross-Border | Japanese institutions reducing Treasury holdings → selling pressure on long-end → yields RISE | BEARISH | -0.5 |
| Scenario Forecaster | Base case: yields fall 50bp. Downside: tariff-driven inflation pushes yields +100bp. | BULLISH base, BEARISH tail | Conditional |

The six modules collectively produce: 2 bullish, 2 bearish, 1 uncertain, 1 conditional. The current `HypothesisResult` stores all six as independent optional fields. There is no `cross_module_consensus` field, no `signal_divergence_score`, no `dominant_signal`. The decision stage receives six independent objects and has no specified logic for how to combine them.

**What happens in practice**: The decision stage's `generate_decision()` function currently processes `HypothesisResult.confidence` + `verdict` + `layer_1-4_narratives`. It has NO code for consuming `causal`, `flow`, `regime_mapping`, `scenario_tree`, or `fragility_report`. The plan's compatibility proof (§五, "与 decision.py 不冲突") says:

> "新增字段为可选 — decision 如果不需要因果/资金流/情景树，直接忽略"

This is the problem, not the proof. If decision "directly ignores" the new fields, the modules produce output that is never used. If decision DOES consume them, there is no specification for HOW to combine conflicting signals. Either way, the signals pile up without synthesis.

**The methodological blind spot**: Professional macro analysts do NOT accumulate independent signals. They engage in **thesis-driven synthesis**: the signals that align with the dominant thesis are integrated; the signals that contradict force a thesis revision or a hedging strategy. The plan assumes that more signals = better analysis, but without a synthesis mechanism, more signals = more confusion.

**Recommended fix** — Add a synthesis module between the enhanced modules and the decision stage:

1. **New module**: `pipeline/signal_synthesis.py` (~200 lines)
   - Accepts: `HypothesisResult` (with all new optional fields populated) + `FragilityReport`
   - Produces: `SynthesisResult` dataclass

2. **SynthesisResult structure**:
```python
@dataclass
class SynthesisResult:
    dominant_signal: str          # "BULLISH" | "BEARISH" | "MIXED" | "UNCERTAIN"
    signal_alignment: float       # 0 (完全分歧) to 1 (完全一致) — how much do modules agree?
    conflicting_pairs: list[tuple[str, str, str]]  # [(module_A, signal_A, module_B, signal_B)]
    # e.g., [("causal_decomposition", "BEARISH (TGA draining)", "flow_decomposition", "BULLISH (foreign buying)")]
    weighted_net_score: float     # weighted average of module signals, with weights based on module reliability per asset class
    synthesis_narrative: str      # Pro-generated paragraph explaining the net picture: "The modules disagree on..."
    recommended_confidence_adjustment: float  # how much to adjust the original confidence based on module alignment
    # If all modules agree → +0.05; if modules are split 3-3 → -0.15; if modules overwhelmingly disagree → cap at 0.5
```

3. **Conflict resolution rules**:
   - If signal alignment > 0.7 (most modules agree) → decision proceeds with adjusted confidence
   - If signal alignment 0.3-0.7 (mixed) → decision proceeds but confidence penalty applied; decision card includes "module disagreement" warning
   - If signal alignment < 0.3 (modules fundamentally disagree) → verdict is demoted (ACTIONABLE → MONITOR, MONITOR → HIGH_CONTENTION) regardless of individual module confidence
   - Module weights vary by asset class: flow decomposition gets 2x weight for FX (where flows dominate), causal decomposition gets 2x weight for fixed income (where balance-sheet mechanics dominate), regime mapper gets higher weight for equities (where regime effects are strongest)

4. **Time-horizon tagging** (connects to Finding 8): Each module's signal should carry a `time_horizon` tag (days, weeks, months, quarters). The synthesis should only aggregate signals on compatible time horizons. A weekly flow signal should not be averaged with a quarterly regime signal — they should be reported as "near-term: BEARISH (flow, 1-2 weeks)" and "medium-term: BULLISH (regime, 3-12 months)."

---

### Finding 8: MEDIUM — Time-Horizon Confusion Across Modules

**Location**: Plan Sections 二 (Modules 2, 3, 5), 三 (Pipeline Integration)
**Plan text**: Flow uses TIC data (6-week lag); Fragility uses daily FRED; Regime uses monthly data (1985-2025); Scenario produces 3-6 month timelines
**Research basis**: N/A — cross-module temporal consistency

**What the plan acknowledges**: The plan's risk matrix (Section 七) acknowledges:
> "TIC 数据 6 周滞后导致跨境流分析过时" — rated HIGH probability, LOW impact
> Mitigation: "明确标注'结构性参考，非时机信号'"

**What the plan does NOT acknowledge**: The modules operate on fundamentally different time horizons, but their outputs converge on the same `HypothesisResult` object without time-horizon labeling:

| Module | Data Frequency | Effective Horizon | Signal Type |
|---|---|---|---|
| Causal Decomposition | N/A (LLM-generated) | Structural (months to quarters) | Slow-moving structural force |
| Flow Decomposition | TIC monthly (6-week lag) | Structural (quarters) | Structural positioning |
| Regime Mapper | Monthly (1985-2025) | Medium-term (3-12 months) | Regime-conditional forecast |
| Scenario Forecaster | N/A (LLM-generated) | Variable (3-6 months typical) | Conditional forecast |
| Fragility Scanner | Daily (FRED) | Near-term (days to weeks) | Proximity-to-threshold warning |
| Cross-Border | TIC monthly + BIS quarterly | Structural (quarters) | Structural flow |

**Concrete failure example**: The pipeline analyzes a hypothesis with a 2-4 week time window. The fragility scanner (daily data, near-term) says "VIX at 33, approaching 35 threshold — HIGH FRAGILITY." The regime mapper (monthly data, 3-12 month horizon) says "1995 analogue, forward 6-month equity returns +12% — BULLISH." The flow decomposition (6-week lagged TIC data) says "foreign official buying in March suggests structural support — MODERATELY BULLISH."

A user asking "should I buy this for a 2-4 week trade?" sees three signals: HIGH FRAGILITY (near-term, bearish) + BULLISH (medium-term, regime) + MODERATELY BULLISH (structural, flow). The regime signal is the most confident (+0.7) but the least relevant to a 2-4 week horizon. The fragility signal is the most relevant to a 2-4 week horizon but carries the least confidence (it hasn't crossed the threshold yet). Without time-horizon tagging, the user cannot correctly weight these signals — and the AI has no mechanism to do it for them.

**The deeper issue**: The plan adds modules because they fill analytical gaps, but never asks "what time horizon is the user operating on?" Different users have different horizons:
- A day trader using MarketMind: 1-5 day horizon → fragility scanner matters, regime mapper is irrelevant
- A portfolio manager: 3-6 month horizon → regime mapper + scenario forecaster matter, daily fragility is noise
- A macro strategist: 6-18 month horizon → structural flow + regime matter, daily data is irrelevant

The modules' time-horizon diversity is a feature — it enables multi-horizon analysis. But without explicit horizon tagging, it becomes a bug — signals from incompatible horizons are presented as if they're all relevant at the same time, to the same user, for the same decision.

**Recommended fix**:

1. **Add `time_horizon` to every module output**:
   - `CausalDecomposition`: `time_horizon = "structural"` (quarters)
   - `FlowAttribution`: `time_horizon = "structural"` (quarters, due to TIC lag)
   - `RegimeMapping`: `time_horizon = "medium_term"` (3-12 months)
   - `ScenarioTree`: each branch has its own timeline (explicit in plan)
   - `FragilityReport`: `time_horizon = "near_term"` (days to weeks, based on daily data)
   - `CrossBorderFlowReport`: `time_horizon = "structural"` (quarters)

2. **In the synthesis step (Finding 7), group signals by horizon**:
   - Near-term signals (days-weeks): Fragility + any scenario branches with <1 month timeline
   - Medium-term signals (1-6 months): Regime + scenario branches
   - Structural signals (6+ months): Causal + Flow + Cross-border

3. **Match signals to the hypothesis's time window**:
   If `HypothesisResult.time_window = "2-4周"`, the synthesis should:
   - Weight near-term signals at 0.6, medium-term at 0.3, structural at 0.1
   - Flag: "Note: structural signals suggest [X], but these operate on 3-12 month horizons — they may not manifest within your 2-4 week window."

4. **For each decision card in `decision.py`**, display signals grouped by time horizon with explicit horizon labels. A user who wants a 2-week trade should not be shown a 12-month regime signal with equal visual weight.

---

### Finding 9: MEDIUM — Over-Measurement Risk with No Signal Aggregation or Prioritization

**Location**: Plan Sections 二 (all modules), 四 (HypothesisResult expansion)
**Plan text**: HypothesisResult expanded from 9 to 20 fields (9 existing + 11 new). All new fields optional with defaults.
**Research basis**: Behavioral finance — choice overload, analysis paralysis

**What the plan delivers**: 6 new modules, each producing independent analytical output. After enhancement, each hypothesis carries:
- Original 9 fields (hypothesis, expectation_gap, verification, refined, confidence, bear_case, bear_confidence, verdict, logic_chain)
- 8 new narrative fields (direction, core_logic, risk_level, time_window, layer_1-4_narratives)
- 3 new complex dataclass fields (causal, flow, scenario_tree)
- Plus external modules (regime_mapping replaces Layer 4, fragility_report feeds into decision separately)

That is **20+ analytical data points per hypothesis**, with 3-5 hypotheses per session = **60-100 analytical data points presented to the user or fed into the decision stage**.

**The plan's own architecture principle is violated**: The plan states (Section 零) "渐进增强：新模块增强现有分析，不替代。旧代码路径保留为 fallback." This means old signals + new signals accumulate without any pruning or prioritization.

**What happens at the decision stage**: The decision stage receives an enriched `HypothesisResult` with 20 fields. The plan says (§五, "与 decision.py 不冲突"):
> "新增字段为可选 — decision 如果不需要因果/资金流/情景树，直接忽略"

This is the **ignore-them-if-you-want** approach to signal aggregation. But who decides which signals to use and which to ignore? The `decision.py` module has no weights, no prioritization logic, no "which modules are most reliable for this hypothesis type" routing. It either uses all signals (analysis paralysis) or ignores new ones (wasted computation). There is no middle path.

**Concrete failure mode**: The pipeline produces:
- 3 hypotheses with ACTIONABLE verdict
- Each has: causal decomposition (6+ factors), flow attribution (5 entities), regime mapping (5 analogues + 3 anti-analogues), scenario tree (3 branches with conditions), fragility overlay (5+ warnings)
- Total = 3 * (6 + 5 + 8 + 3 + 5) = ~81 discrete analytical claims

The `decision.py` module's `generate_decision()` function currently produces a `DecisionOutput` with decision_cards that have ~5-8 fields each. Where do 81 new analytical claims go? If they're all surfaced, the output is unreadable. If they're all ignored, the modules are wasted compute. If they're selectively surfaced, who defines the selection criteria?

**The missing mechanism**: The plan has no **signal prioritization** layer. Professional analysts prioritize by:
1. **Novelty**: Is this signal telling me something the market hasn't priced? (expectation gap)
2. **Reliability**: Has this type of signal been accurate historically for this asset class? (track record)
3. **Actionability**: Does this signal change my positioning, or just confirm what I already know? (decision impact)
4. **Urgency**: Does this signal require action now, or can I wait for confirmation? (time decay)

None of these prioritization criteria exist in the plan.

**Recommended fix**:

1. **Add a signal prioritization step** between module outputs and decision input. After all modules produce their outputs but before they reach `decision.py`, run a `_prioritize_signals()` function that:
   - Assigns each module output a priority score: `priority = novelty * reliability * actionability * urgency`
   - Only the top-K signals (K=5 per hypothesis, or top-15 across all hypotheses) are forwarded to the decision stage with full detail
   - The remaining signals are summarized in a single "Additional Supporting/Contradicting Signals" section with one-line summaries

2. **Define module reliability weights per claim type** (connects to Finding 1's asset-class routing):
   - For rate claims: causal decomposition weight = 0.8, flow decomposition = 0.4, regime mapper = 0.6
   - For commodity claims: causal decomposition = 0.2 (balance-sheet lens doesn't apply), flow decomposition = 0.5, regime mapper = 0.7
   - For FX claims: flow decomposition = 0.8, causal decomposition = 0.5, cross-border = 0.7
   
   Modules with low reliability for a given claim type should have their signals down-weighted or suppressed entirely.

3. **Decision stage interface contract**: `decision.py` must be MODIFIED (not just "directly ignore new fields") to:
   - Accept the prioritized, weighted synthesis result (from Finding 7)
   - Surface the 3-5 highest-priority signals in the decision card
   - Include a "Signal Confidence" section showing how much the decision is supported by the enhanced modules vs. the baseline pipeline
   - If enhanced modules collectively disagree with the baseline (original confidence vs. synthesis net score diverge by >0.2), flag "ANALYTICAL DISAGREEMENT" as a decision card warning

Without this, the "enhancement" is architectural decoration — modules that run and produce output that no downstream stage is designed to consume.

---

### Finding 10: MEDIUM — Counter-Intuitive Discovery and Consensus-Break Analysis Were Dropped from the Plan

**Location**: Absent from plan (compare with methodology gap analysis Dimensions 4 and 9)
**Plan text**: No mention of counter-intuitive signal detection or consensus-break structure
**Research basis**: Methodology gap analysis Dimensions 4 ("Counter-Intuitive Discovery") and 9 ("Consensus Narratives → Break Structure")

**What the gap analysis recommends**: Two of the 10 dimensions identified as missing from the current pipeline are:
- **Dimension 4**: Actively hunt for conditions where surface narrative and underlying mechanics diverge. Produce multi-step explanations of WHY the counter-intuitive pattern exists.
- **Dimension 9**: First establish "what most people think" (consensus narrative), then systematically dismantle it with evidence. Create analytical tension and resolution.

**What the plan includes**: Neither dimension appears in the 6-module architecture. The plan prioritizes 1 (causal), 2 (flow), 3 (regime), 4 (scenario), 5 (fragility), 6 (cross-border) — dropping the two dimensions most directly tied to generating alpha.

**Why this matters**: In professional macro analysis, the highest-value signals are those where the market consensus is WRONG. The plan's modules (causal decomposition, flow decomposition, regime mapping) all analyze "what is happening." None analyze "what the market THINKS is happening vs. what is ACTUALLY happening." Without the consensus-break structure, the pipeline can produce thoroughly analyzed, multi-module-verified consensus signals — signals that are already priced in.

A pipeline that maps flow entities, decomposes balance-sheet causality, finds historical analogues, builds scenario trees, and scans for fragility — but never asks "does the market already know this?" — will produce the world's most sophisticated analysis of fully discounted information.

**Recommended fix**: These two dimensions should be integrated as a pre-analysis step, not dropped:

1. **Consensus extraction** (insert before HVR loop, ~50 lines in `investigation_loop.py`):
   After hypothesis formation, prompt Pro: "For each hypothesis, what is the current market consensus? What would a Bloomberg-survey consensus economist predict? What has the market already priced?" Store as `consensus_view: str` and `expectation_gap_measure: float`.

2. **Counter-intuitive flag** (insert during causal/flow decomposition):
   After decomposition produces signals, ask: "Do ANY of these signals contradict the consensus view identified above?" If yes, flag as `counter_consensus: True` and promote the hypothesis. A counter-consensus signal with high confidence is the most valuable output the pipeline can produce.

3. **Narrative break structure** (in decision card output):
   For any hypothesis where `counter_consensus=True`, the decision card should use the "Consensus → But Actually → Therefore" structure:
   > "Consensus believes [X]. But the data shows [Y]. Therefore [Z] — a positioning opportunity that most of the market has not yet acted on."

These additions require no new module — they are prompt-level changes to `investigation_loop.py` and `decision.py`, consistent with the plan's own "zero blast radius" approach (Module 0).

---

### Finding 11: MEDIUM — Parallel Execution Within HVR Loop Is Conceptually Incoherent

**Location**: Plan Section 三 (Pipeline Integration)
**Plan text**: "因果分解 + 资金流分解在 HVR 循环内并行运行（`asyncio.gather`）"
**Research basis**: HVR loop semantics (`investigation_loop.py`)

**What the plan proposes**: Run causal decomposition and flow decomposition in parallel within the HVR (Hypothesize → Verify → Refine) loop.

**The problem**: The HVR loop is **iterative and stateful**. Each V→R cycle modifies the hypothesis based on verification findings. The refined hypothesis in cycle N+1 is DIFFERENT from the hypothesis in cycle N. If causal and flow decomposition run on the INITIAL hypothesis (before HVR begins), they produce signal based on a hypothesis that may be refined or abandoned. If they run on the REFINED hypothesis (which changes each cycle), they must be re-run each cycle, multiplying token cost.

The plan specifies they run "within the HVR loop" but the pipeline diagram shows them BEFORE the HVR verification cycle, as pre-processing steps:

```
stage_2b_investigation
        │
  ┌─────┼──────┐
  │     │      │
[因果] [资金流] [HVR验证+对抗]
```

This positioning suggests they run ONCE, before HVR verification begins, on the initial hypothesis. But then the HVR cycle refines the hypothesis — making the causal/flow decomposition stale, since they were produced from a hypothesis that no longer exists.

**The conceptual incoherence**: Either:
1. Causal and flow decomposition run once on the initial hypothesis → their output is based on a hypothesis that may be refined away → output is stale before it's used
2. Causal and flow decomposition re-run each HVR cycle → token cost is 3-5x what the plan estimates → cost mitigation ("use Flash for cost control") breaks down

The plan's cost mitigation relies on running these modules once (using Flash to keep token cost low). But the architecture places them in a loop that, by design, iterates. The two are incompatible.

**Recommended fix**: Run causal and flow decomposition ONCE, AFTER the HVR loop completes and the hypothesis has been refined to its final form. This means:
- The modules operate on the FINAL hypothesis (not the initial draft)
- They run exactly once per hypothesis (cost control holds)
- Their output cannot be stale because the hypothesis won't change again

Update pipeline diagram to:

```
stage_2b_investigation
        │
   [HVR循环: 假设 → 验证 → 精炼]  ← 迭代直到稳定
        │
   [条件预测树]  ← 仅 ACTIONABLE
        │
   [Gate 1]
        │
   ┌────┼────┐
   │    │    │
[因果] [资金流]  ← 对精炼后假设运行，确定最终信号
   │    │    │
   └────┼────┘
        │
stage_3_layer1 ...
```

This also resolves the time-horizon issue: causal/flow decomposition (structural signals, months horizons) naturally belong AFTER the near-term HVR verification, not before it.

---

### Finding 12: MEDIUM — Regime Mapper Replaces Layer 4 But Changes Its Contract

**Location**: Plan Section 二, Module 3 (regime_mapper.py)
**Plan text**: "替换 `verify_claim_historical()` 的实现，但保持相同函数签名"; "返回的 float 仍可参与加权置信度计算"
**Research basis**: Verification chain semantics

**What the plan proposes**: Replace the Layer 4 implementation (keyword-to-probability heuristic) with a genuine historical regime search, while maintaining the same function signature — returning a float that feeds into weighted confidence calculation.

**The contract mismatch**: The old Layer 4 returns a **probability** (0-1) representing "how often do claims like this play out historically?" A score of 0.65 on "rate_cut" means "65% of rate cut claims in history were correct." This is a base rate.

The new Regime Mapper returns a **similarity-weighted forward return projection** — "the most similar historical regimes showed +8% equity returns over the next 6 months." This is NOT a probability. It is a conditional forecast.

You cannot feed a regime-conditional return projection (e.g., +8% over 6 months) into the same weighted confidence formula (30/25/25/20) that previously consumed a base-rate probability (e.g., 0.65). The two numbers mean completely different things and operate on different scales:
- Old Layer 4: 0.0 (never happens) to 1.0 (always happens) — a probability
- New Regime Mapper: Could be -0.20 (forward returns -20%) to +0.30 (forward returns +30%) — a return projection

If the weighted formula does `confidence += layer4_return * 0.20`, a +8% return projection contributes +0.016 to confidence — a negligible amount that is washed out by other layers. If the formula normalizes the return projection to a probability (e.g., `sigmoid(forward_return)`), the mapping is lossy and arbitrary.

**Recommended fix**: Do NOT replace the Layer 4 function signature. Instead:

1. **Keep Layer 4 as-is** for base-rate probability (the keyword heuristic — it is a placeholder but it's the right TYPE of output for this layer).
2. **Add the regime mapper as a NEW capability**, NOT as a Layer 4 replacement. Its output (`RegimeMapping`) should feed into:
   - The decision stage as a contextual input (not a confidence contributor)
   - The scenario forecaster as a calibration check ("does our base case align with historical regime analogues?")
   - The synthesis step (Finding 7) as one of several independent signals
3. If the old Layer 4 is genuinely inadequate (which it is), replace it with a computation that still produces a **probability**, not a return projection — e.g., "What % of similar claims in similar regimes were correct within their time window?" This retains the existing contract while upgrading the computation.

---

### Finding 13: LOW — Module Order Does Not Match Dependency Chain

**Location**: Plan Section 六 (Implementation Phases), Section 二 (Module Overview)
**Plan text**: Phase H-2: Mechanism Glossary → H-3: Causal + Flow → H-4: Regime + Scenario → H-5: Fragility + Cross-Border

**The issue**: The implementation order is only partially aligned with dependency chains:

| Module | Depends On | Phase Assigned | Dependency Available? |
|---|---|---|---|
| Mechanism Glossary | Nothing | H-2 | N/A |
| Causal Decomposition | Mechanism Glossary (for prompt enrichment) | H-3 | YES (from H-2) |
| Flow Decomposition | Mechanism Glossary | H-3 | YES |
| Regime Mapper | regime_library.py (new config) | H-4 | Creates in same phase |
| Scenario Forecaster | Causal Decomposition (for condition variables) | H-4 | YES (from H-3) |
| Fragility Scanner | Causal + Flow (for threshold-context matching per hypothesis) | H-5 | YES (from H-3) |
| Cross-Border | Flow Decomposition (for entity data), cross_border.py gateway | H-5 | YES (from H-3) |

The order is largely correct. However, the synthesis step (Finding 7) — which is NOT in the plan — depends on ALL modules being complete, since it must know all signal types to aggregate them. The synthesis should be Phase H-6, after all modules are integrated.

Additionally, the plan's Phase H-4 includes Scenario Forecaster, which the plan says "仅对 ACTIONABLE 判定运行." But ACTIONABLE verdict depends on the HVR loop, which is in `investigation_loop.py`. If the Scenario Forecaster is wired after HVR completes (as Finding 11 recommends), it has no dependency on Causal Decomposition — it only depends on the finalized HypothesisResult.verdict. The plan's dependency claim ("depends on causal decomposition for condition variables") is overstated — scenario condition variables can be identified without causal decomposition.

**Rating as LOW** because the ordering is mostly correct and the dependency issues are resolvable during implementation. The primary risk is that the synthesis step (not in the plan) would need to be retrofitted.

---

### Finding 14: LOW — Chart Reasoning Dimension Dropped Without Justification

**Location**: Absent from plan (compare with methodology gap analysis Dimension 8)
**Plan text**: No mention of chart reasoning or chart specifications
**Research basis**: Methodology gap analysis Dimension 8 ("Charts as Reasoning Tools")

**What the gap analysis recommends**: Add chart-reasoning to the text pipeline: "For each step in your logic chain, describe what chart would prove or disprove this step. What would the x-axis be? What would the y-axis be? What shape would confirm vs. refute the claim?" Store as `ChartSpec` objects.

**What the plan delivers**: No chart-reasoning module. The dimension is silently dropped from the 6-module architecture.

**Why it was dropped**: Likely because chart rendering (Phase E, future work) was de-prioritized and the text-only chart specifications were bundled with it. But the gap analysis explicitly separated Phase D (text chart specs, ~40-60 lines) from Phase E (actual rendering). The text-only chart specification step is low-cost, zero-dependency, and improves reasoning quality by forcing structured variable isolation — which would benefit ALL other modules by making their causal chains more explicit.

**Recommended fix**: Add a lightweight `_chart_reasoning_step()` to the HVR loop (~40 lines in `investigation_loop.py`):
- After each logic chain step, prompt Pro: "What chart would prove or disprove this specific claim? X-axis, Y-axis, what shape confirms vs. refutes?"
- Store `ChartSpec` objects (text-only, no rendering) in the `HypothesisResult.logic_chain`
- These chart specs serve as explicit, testable sub-claims that downstream modules can verify
- No rendering. No matplotlib. No ASCII-only violation.

---

## Additional Findings

### A. Gate 1 Interaction Incompatibility (MEDIUM)

The plan's pipeline integration (Section 三) shows:
```
[Gate 1: 用户确认]
       │
stage_3_layer1 → stage_4_layer2_layer3 → ...
```

But the enhanced hypothesis cards (from the parallel Gate 1 interaction design plan, `gate1-interaction-design.md`) show L1/L2/L3/L4 evidence ON the card. If causal decomposition and flow decomposition run in Stage 2b (BEFORE Gate 1), their output should appear on the Gate 1 hypothesis cards. The Phase H plan does not address how enhanced analytical depth integrates with the Gate 1 user interaction design. Two plans (Gate 1 UI and Phase H enhancement) are being developed in parallel with no integration specification.

### B. Methodology Gap Dimensions 4 and 9 Priority Inversion (MEDIUM)

The gap analysis prioritized:
1. Mechanism Naming (Priority 1)
2. Causal Decomposition (Priority 2)
3. Flow Tracking (Priority 3)
4. Historical Regime (Priority 4)
5. Conditional Forecasting (Priority 5)
6. **Counter-Intuitive + Consensus Break (Priority 6)**
7. Fragility Analysis (Priority 7)

The plan's module list matches priorities 1-5 and 7, but drops priority 6 (counter-intuitive + consensus break). These two dimensions are dropped despite being identified as HIGH value — they generate edge by finding where consensus is wrong. The plan prioritizes analytical DEPTH (causal, flow, regime) over analytical DIFFERENTIATION (counter-consensus). A pipeline that produces deeply analyzed consensus signals is more sophisticated but not more profitable.

---

## Summary Table

| # | Severity | Category | Issue |
|---|:---:|---|---|
| 1 | **CRITICAL** | Causal Decomposition | Universal balance-sheet lens applied to all asset classes; produces nonsense for commodities, crypto, FX. No asset-class routing. |
| 2 | **CRITICAL** | Flow Decomposition | US-centric 5-entity model (US_HOUSEHOLD, US_INSTITUTIONAL, FOREIGN_OFFICIAL, FOREIGN_PRIVATE, FED) does not generalize to non-US assets. Missing BoJ, GPIF, PBoC, commodity producers, crypto exchanges. |
| 3 | **HIGH** | Regime Mapper | S&P 500 Y/Y in input vector creates self-fulfilling bullish bias. 1985-2025 excludes stagflation era. Euclidean distance weights all 7 variables equally even when CPI dominates regime classification. |
| 4 | **HIGH** | Scenario Forecaster | Filters by ACTIONABLE verdict, not by tail risk. MONITOR/HIGH_CONTENTION hypotheses with catastrophic downside scenarios get no scenario analysis. Category error: filtering on confidence when risk is the relevant variable. |
| 5 | **HIGH** | Fragility Scanner | 15 hardcoded thresholds with no staleness detection, no update mechanism, no versioning. ON RRP $50B threshold may be moot by 2026. No "who maintains these?" answer. |
| 6 | **HIGH** | Mechanism Glossary | 40 static entries with no "unknown mechanism" escape hatch. LLM will hallucinate definitions for new Fed facilities not in the glossary. No update trigger when Fed creates new facilities. |
| 7 | **HIGH** | Cross-Module Conflict | Six modules produce independent signals with no synthesis step. Causal decomposition can say BEARISH while flow decomposition says BULLISH — both stored as optional fields, neither resolved. Decision stage told to "ignore if not needed." |
| 8 | **MEDIUM** | Time-Horizon Confusion | Modules operate on days (fragility), weeks (scenario), months (regime), quarters (flow, causal) — all converge on same HypothesisResult without horizon tagging. Near-term fragility and medium-term regime signals are presented with equal weight. |
| 9 | **MEDIUM** | Over-Measurement | 6 new modules produce 60-100 discrete analytical claims per session. No prioritization, no aggregation. Decision stage has no defined consumption logic. Risk of analysis paralysis. |
| 10 | **MEDIUM** | Counter-Intuitive Discovery | Dimensions 4 and 9 from gap analysis (counter-intuitive signals, consensus-break structure) dropped from plan. Highest-alpha analytical patterns omitted. |
| 11 | **MEDIUM** | HVR Parallel Execution | Causal/flow decomposition positioned "within HVR loop" but run in parallel — incoherent with iterative HVR semantics. Either stale (run once on initial hypothesis) or over-budget (re-run per cycle). |
| 12 | **MEDIUM** | Regime Mapper Contract | Replaces Layer 4's probability output (base-rate float) with a return projection (forward equity returns). These are not the same type and cannot feed the same confidence formula. |
| 13 | **LOW** | Module Ordering | Implementation order mostly correct. Missing synthesis step (Finding 7) as Phase H-6. Minor dependency overstatements (scenario forecaster does not need causal decomposition). |
| 14 | **LOW** | Chart Reasoning | Dimension 8 from gap analysis (text chart specs) dropped without justification. Low-cost, high-value addition to reasoning quality. |

---

## What the Plan Got RIGHT

To be clear: the plan's structural direction is sound and several design choices are strong:

1. **Pipeline insertion points are well-chosen**: Causal + flow decomposition in Stage 2b (before Gate 1), fragility in Stage 7b (between Resonance and Decision), regime mapper replacing the known-broken Layer 4. Each module has a clear "why here" rationale.

2. **Backward compatibility is genuinely maintained**: All new fields on `HypothesisResult` have defaults. The `None`-optional pattern for complex fields allows clean degradation. The plan correctly identifies that this does not break existing tests.

3. **Token cost awareness**: The plan explicitly limits expensive operations (scenario forecaster to ACTIONABLE only, flow decomposition uses Flash, cross-border is "silently skip if unavailable"). Cost discipline is methodologically correct — unlimited Pro calls would make the pipeline economically unsustainable.

4. **Shadow ecosystem isolation**: Maintaining the rule that enhanced analysis output is NOT shared with shadows prevents anchoring contamination. This is the right architectural choice.

5. **Gate 1 placement**: Running causal + flow decomposition BEFORE Gate 1 means the user sees enhanced analysis at the decision point. This is correct — the user should make the investment decision with the best available information.

6. **Mechanism naming as Priority 1**: The plan correctly identifies that precise institutional vocabulary in system prompts is zero-blast-radius, zero-cost, and unlocks better analysis from all downstream modules. This is the right first step.

7. **Graceful degradation**: Every module has a fallback (data unavailable → skip, Pro returns unparseable → None, regime data unloaded → keyword heuristic). This matches the existing pipeline's degradation philosophy.

8. **The gap analysis correctly diagnosed what was missing**: The 10-dimension assessment accurately identifies the pipeline's analytical deficiencies. The plan maps to 7 of 10 dimensions, which is a reasonable first pass.

---

## Path to Approval

The plan requires revision addressing all CRITICAL and HIGH findings before implementation begins. Specifically:

**1. Asset-class routing (CRITICAL 1, 2)**:
- Add `_classify_asset_class()` to route causal decomposition to the appropriate framework (balance-sheet for FI, supply/demand for commodities, dual-central-bank for FX, on-chain for crypto)
- Replace the 5 US-centric entity types with an asset-class-keyed entity registry
- Modules must declare when they cannot produce valid analysis for a given asset class (output `applicable: False`)

**2. Regime mapper de-biasing (HIGH 3)**:
- Remove S&P 500 Y/Y from the 7-variable input vector; replace with CPI/PCE
- Extend training window to 1970-2025 to include stagflation
- Implement regime-weighted distance (variable weights depend on which regime we appear to be in)
- Add "out-of-sample" flag when no historical analogue exists

**3. Scenario forecaster risk-based triggering (HIGH 4)**:
- Run scenario analysis on ALL non-DISCARD verdicts (ACTIONABLE + MONITOR + HIGH_CONTENTION)
- Prioritize by tail-risk, not by confidence
- For HIGH_CONTENTION, show BOTH bull and bear branching trees

**4. Fragility scanner maintenance (HIGH 5)**:
- Add metadata to every threshold: source, as_of, last_validated, relevance_confidence
- Implement staleness heuristics and quarterly review trigger
- LLM-assisted gap detection (new facilities → proposed thresholds)

**5. Mechanism glossary update mechanism (HIGH 6)**:
- Add "unknown mechanism" protocol: flag rather than hallucinate
- Make glossary queryable at runtime as a tool call
- Add staleness check and automated gap detection

**6. Cross-module synthesis (HIGH 7, MEDIUM 8, 9)**:
- Add `pipeline/signal_synthesis.py` with conflict detection and weighted aggregation
- Time-horizon tag every module output; group signals by horizon in synthesis
- Add signal prioritization (novelty * reliability * actionability * urgency)
- Modify `decision.py` to consume synthesis output (not raw module outputs)

**7. Reincorporate dropped dimensions (MEDIUM 10)**:
- Add consensus extraction and counter-intuitive flagging as prompt-level changes (~100 lines in investigation_loop.py)

**8. Fix HVR integration timing (MEDIUM 11)**:
- Move causal + flow decomposition to AFTER HVR loop completion (operate on refined hypothesis)

**9. Fix regime mapper contract (MEDIUM 12)**:
- Do not replace Layer 4's probability output; add regime mapper as a separate capability feeding synthesis

---

**Next Step**: Plan author revises based on these findings. Revised plan requires a follow-up Red Team review before any implementation begins. The 2 CRITICAL and 5 HIGH findings must be resolved in the revised plan. MEDIUM findings should be addressed or explicitly deferred with rationale.
