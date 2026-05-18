# Phase H v2 Architecture — Red Team Logic Audit

**Auditor**: Red Team Logic / Investment Methodology
**Date**: 2026-05-18
**Subject**: `phase-h-revised-architecture.md` (v2)
**References**: `phase-h-comprehensive-architecture.md` (v1), `asset-class-routing-design.md` (research)
**Status**: 4 CRITICAL, 4 HIGH, 2 MEDIUM findings

---

## Executive Summary

The v2 plan correctly identifies the two CRITICAL findings from v1 (C1: universal balance-sheet lens, C2: US-centric entity model), and the asset-class routing addition is directionally correct. However, the v2 implementation collapses the research document's 9-asset-class taxonomy into 5 coarse buckets, losing the very distinctions the research argued are essential. Three of the five collapsed categories apply wrong decomposition lenses to at least one sub-asset, and the plan omits EM Macro entirely — a class the research estimated covers ~7% of hypotheses. The keyword-matching router has no disambiguation logic for ambiguous terms, no multi-asset hypothesis handling, and no confidence scoring. Four of the remaining v1 fixes are cosmetic: they acknowledge problems without solving them.

---

## CRITICAL Findings

### C1: 9-Class Research Taxonomy Collapsed to 5 — Wrong Lenses for 4 Asset Categories

**Evidence**: The research document (`asset-class-routing-design.md`) defines 9 distinct asset classes, each with its own decomposition lens, entity types, and data sources. The v2 plan's `ASSET_CLASS_TAXONOMY` has only 5 entries.

| Research Class | Research Lens | v2 Mapping | v2 Lens | Problem |
|---|---|---|---|---|
| AC3: Gold | Real rate + reserve diversification + physical flow | COMMODITIES | `supply_demand_inventory` | Gold has no meaningful supply/demand balance. Its dominant explanatory variable is real rates (TIPS yields). Applying oil-style S&D decomposition to gold produces nonsense: "gold inventory drawing down" is not why gold moves. |
| AC5: Natural Gas | Storage trajectory vs 5-year norm + weather | COMMODITIES | `supply_demand_inventory` | Natural gas is a domestic market driven by storage deviation from 5-year average and HDD/CDD weather forecasts. It has no OPEC, no global benchmark, no geopolitical supply disruption channel. Collapsing it into the same lens as crude oil ignores the single most important variable (weather). |
| AC6: Agriculture | USDA WASDE supply/demand + weather + trade | COMMODITIES | `supply_demand_inventory` | Agricultural commodities are annual-cycle goods governed by acreage, yield, and WASDE reports. The "inventory" concept is fundamentally seasonal (pre-harvest vs post-harvest), not continuous like crude stocks. Applying the same lens misses the crop cycle entirely. |
| AC9: EM Macro | Dollar cycle + capital flow push/pull + China credit impulse | **MISSING** | Falls through to generic/fallback | EM is ~7% of hypotheses. The v2 taxonomy has no EM category — hypotheses mentioning EEM, emerging markets, or EM carry trade will either be misrouted to US_EQUITIES (wrong entity types, wrong lens) or hit the fallback path with degraded analysis quality. |

**Impact**: ~32% of estimated hypotheses (Gold 8% + Nat Gas 5% + Ag 5% + EM 7% + portions of other mismatches) receive a decomposition lens that is either partially wrong (COMMODITIES for gold) or completely wrong (missing EM). This is not a minor taxonomy dispute — the decomposition output for gold under `supply_demand_inventory` will be actively misleading, identifying "supply deficits" and "inventory draws" as drivers when gold moves on real rates and central bank reserve behavior.

**Recommendation**: Either (a) expand the v2 taxonomy to all 9 classes from the research, or (b) if 9 is too many for Phase H, split COMMODITIES into at minimum three sub-lenses (gold/precious metals with real-rate lens, energy with physical S&D, agriculture with WASDE/seasonal lens) and add EM as a 6th top-level class. Gold cannot share a decomposition lens with crude oil — this is the exact same category error the v2 was designed to fix, just at one level of granularity up.

### C2: Keyword Router Has No Disambiguation — "Gold" in Equity Context Routes Wrong

**Evidence**: The v2 plan describes routing as "ticker match > keyword density > LLM classification (fallback)." Keywords are matched as literal substrings. The research document's 6-step routing tree (Section 3.1) includes a self-check step (Step 6: "Would a professional macro analyst use this lens for this hypothesis?") and confidence scoring — neither appears in the v2 plan.

**Failure cases**:
1. "Gold buying by retail investors signals risk-off, driving SPY lower" — "gold" keyword matches COMMODITIES. The primary asset is SPY (equities). The hypothesis is about equity market direction, with gold buying as an *indicator*, not the prediction target. The COMMODITIES lens would decompose gold S&D instead of equity flows.
2. "Oil price spike from OPEC+ cut crushes airline stocks" — "oil" and "crude" match COMMODITIES. But primary prediction target is airline equities. Should route to US_EQUITIES with oil as secondary driver.
3. "Strong dollar from hawkish Fed: gold falls, EEM falls, SPY corrects" — Multiple keywords (dollar, gold, EEM, SPY). Which class wins? The v2 plan provides no tiebreaker logic.
4. "Treasury issuance shift to bills steepens the curve" — "Treasury" → US_FIXED_INCOME. This is correct. But "European equities rally on ECB dovish surprise" — no "European equities" keyword match in any class. "equities" would match US_EQUITIES by keyword substring, routing European equities to a US-centric entity model (wrong).

**Root cause**: The v2 router has no concept of "primary prediction target" vs "causal driver." It matches any keyword in the hypothesis text and picks the highest-density class, without determining what asset the hypothesis is actually making a prediction about.

**Recommendation**: Implement the research document's full 6-step routing tree with (a) explicit primary target identification, (b) secondary driver tagging, (c) confidence scoring, and (d) the self-check step. The "LLM classification fallback" should be the primary classifier for ambiguous cases, not a last resort — an LLM can distinguish "gold is the prediction target" from "gold is mentioned as an indicator" in ways keyword matching cannot.

### C3: Multi-Asset Hypotheses — No Handling at All

**Evidence**: The research document dedicates Section 4 entirely to multi-asset hypothesis handling, with rules for primary-secondary decomposition, token budget guards (max 2 secondary classes), and worked examples. The v2 plan contains zero mention of multi-asset hypotheses.

The team lead's example — "EUR weakness helps European exporters (equities) and hurts USD-denominated gold (commodities)" — exposes the gap:

- Under v2: keyword match finds "EUR" → FX, "equities" → US_EQUITIES (wrong region), "gold" → COMMODITIES. Three-way tie. No resolution mechanism. Router either picks the highest-density class (FX, because "EUR" appears) and ignores the equity/gold predictions, or falls through to the fallback.
- Under research design: Identify primary targets (European equities, gold), secondary driver (EUR weakness). Apply AC2 lens with European entity overlay to equities, AC3 (gold) real-rate lens to gold, both receiving EUR directional force as input.

The v2's flat 5-class taxonomy fundamentally cannot express "this hypothesis is about A, driven by B." Every multi-asset hypothesis — which are among the most valuable macro hypotheses — will be misrouted or flattened to single-asset analysis.

**Recommendation**: Add multi-asset handling before implementation. At minimum: (a) detect when a hypothesis spans >1 asset class via LLM classification, (b) identify which asset is the primary prediction target, (c) apply the primary class's lens and feed secondary class directional forces as inputs, (d) enforce the research document's 2-secondary-max guard. Without this, the most sophisticated macro hypotheses get the worst analysis.

### C4: Pre-1985 Qualitative Data Does Not Fix Regime Mapping Bias

**Evidence**: The v2 regime mapper fix says: "加预 1985 定性数据层（1970s 滞胀、Volcker 时代、大萧条）作为手动标注的 regime 记录" and "变量加权：CPI 主导的 regime 中 CPI 权重 ×2."

**Why this doesn't work**: The regime mapper uses 7-variable Euclidean distance search on numerical data. Pre-1985 "qualitative" records have no numerical values for S&P 500 YoY, 10Y-2Y spread, WTI YoY, copper YoY, T-bill yield, VIX, or equity-bond correlation. You cannot compute Euclidean distance between a numerical vector (current market) and a qualitative label ("stagflation").

The options are:
1. **Backfill numerical approximations** for pre-1985: FRED has some pre-1985 data (Fed Funds from 1954, 10Y from 1962, CPI from 1947, S&P 500 from 1928). But VIX didn't exist, WTI wasn't a global benchmark, copper pricing was different. The data exists partially but the approach needs specification — which series get proxied with what?
2. **Use the qualitative records as a separate overlay**: When the quantitative mapper finds no close analogue (all similarity scores < 0.7), check qualitative records for regime descriptions that match the current macro narrative. This is a complementary path, not a fix to the Euclidean distance.
3. **Just disclose the limitation**: The v2's disclosure ("模型仅基于 1985-2025 数据训练") is honest, but then admit that the 1970s stagflation risk — which is exactly the scenario the mapper was asked to assess — cannot be quantitatively measured by this system.

The v2 plan papers over this by suggesting qualitative data + variable weighting together fix the bias. The variable weighting (CPI ×2) applies to the quantitative search and might help a little if inflation starts rising within the 1985-2025 dataset. But the core problem — the training window excludes the most important inflation regime in modern history — is unsolved by the proposed fixes.

**Recommendation**: Either (a) commit to backfilling numerical data for the 7 variables to 1970 (feasible for ~5 of the 7 with FRED data, needs proxy selection for the rest), or (b) replace the "qualitative data" language with an honest design: a separate qualitative regime narrative bank that fires when quantitative similarity is low. The current language promises something the Euclidean distance method cannot deliver.

---

## HIGH Findings

### H1: Conflict Detection Thresholds Are Arbitrary — Analysis Paralysis Risk Is Real

**Evidence**: The v2 conflict detection uses `one signal >0.6 and another <0.4` as the contradiction threshold. With 6 modules, each producing directional signals for each hypothesis, the expected number of conflict pairs is:

- 6 modules → C(6,2) = 15 pairwise comparisons per hypothesis
- With ~3 ACTIONABLE hypotheses per session: 45 conflict checks
- At a 0.6/0.4 threshold, if signals are uniformly distributed, ~20% of pairs will flag as conflicts → ~9 conflicts per session

Nine "ANALYST_DISAGREEMENT" flags presented to the user with no resolution framework. The plan says "标记为 ANALYST_DISAGREEMENT 并呈现给用户在 decision card 中作为风险提示" — but presenting 9 unresolved conflicts is not "risk提示", it's a todo list of analysis the system started but didn't finish.

**The research document's approach is better**: The `NetDirectionalForce` unifies sub-component conflicts *internally* before surfacing to the user. Internal conflicts are resolved by identifying which component dominates (the `primary_component` field). Only when the top-level direction is genuinely ambiguous does the `conflict_flag` fire. This reduces user-facing conflicts from dozens to the few that actually matter.

**Recommendation**: Implement the research document's `NetDirectionalForce` with internal conflict resolution. Only surface conflicts to the user when the unified direction is genuinely ambiguous (direction = "CONFLICTING"), not for every sub-component disagreement. Add a "resolution confidence" field so the user can see whether the system barely resolved the conflict or resolved it decisively.

### H2: MONITOR Sampling = 1 Is an Arbitrary Limit That Misses Systematic Tail Risk

**Evidence**: The v2 says "从 MONITOR 的高 bear_case_confidence 假设中抽样 1 个做反向情景." No justification for sampling exactly 1.

**Why 1 is wrong**: If a session has 5 MONITOR hypotheses, each with bear_case_confidence > 0.8, sampling 1 means 4 high-confidence bear cases are never tested. The tail risk the scenario forecaster was designed to catch might be concentrated in the unsampled 4.

The choice of 1 appears to be a token-budget constraint masquerading as a design decision. The research document has a principled approach to depth tiers (Section 7: Full/Standard/Light/Physical-only) and a token budget guard for multi-asset (Section 4.4: max 2 secondary classes). The MONITOR sampling needs the same principled treatment:

- If the goal is to test "what if the bear case is right," sample all MONITOR hypotheses above a bear_case_confidence threshold (e.g., >0.7), not an arbitrary count
- If token budget is the constraint, budget for it explicitly: "max 3 reverse scenarios per session" is a budget decision; "sample 1" pretends it's a statistical choice

**Recommendation**: Replace "sample 1" with a threshold-based rule: all MONITOR hypotheses with bear_case_confidence > 0.7 get reverse scenario analysis, capped at 3 for token budget. If there are more than 3, sample the 3 with highest bear_case_confidence and note the others as "not stress-tested."

### H3: Fragility Threshold Staleness — 90 Days Measures the Wrong Thing

**Evidence**: The v2 adds `last_validated` to each threshold and flags thresholds not validated in 90 days as STALE.

**The problem**: `last_validated` tracks when a human reviewed the *threshold definition* (e.g., "is $2.7T still the right reserve threshold?"). It does not track when the *current value* was last fetched. A threshold can be "validated" yesterday but reference market data that is 2 weeks stale.

More importantly, different thresholds age at fundamentally different rates:
- **ON RRP < $50B**: ON RRP dropped from $2.5T to near-zero in ~18 months. The crossing of intermediate thresholds ($500B, $200B, $100B) happened in weeks. A 90-day validation cycle would miss the entire depletion.
- **VIX > 35**: This threshold is structural — VIX above 35 always means panic, regardless of when you last reviewed it. 90 days is unnecessarily frequent.
- **10Y approaching 4.5% as "political pain threshold"**: This is a narrative threshold, not a structural one. If a new administration signals tolerance for higher yields, the threshold becomes meaningless overnight. 90 days is too slow.

**Recommendation**: Add a `data_freshness` field separate from `last_validated`. Categorize thresholds by decay rate: (a) structural thresholds (VIX 35, SOFR-IORB 25bp) — validate quarterly, (b) flow-dependent thresholds (ON RRP, reserve levels) — validate weekly automatically against latest data, (c) narrative thresholds (political pain levels, policy triggers) — flag as "narrative-dependent, verify against current policy context" on every run.

### H4: Mechanism Glossary Escape Hatch — No Verification That LLMs Actually Use It

**Evidence**: The v2 adds to every Pro prompt: "如果遇到你无法确认的机制或工具，明确说'我无法确认该机制的具体运作方式'，不要猜测或编造名称."

**Why this is insufficient**: LLMs hallucinate mechanisms confidently even when instructed not to. The instruction reduces hallucination rate marginally (studies show ~5-15% reduction from such prompts) but does not eliminate it. Without a post-generation verification step, the system has no way to know whether the LLM used the escape hatch when it should have.

Worse: if the LLM invents a mechanism name that happens to match a real but irrelevant mechanism in the glossary, the output looks validated but is wrong. Example: LLM hallucinates "SLR recalibration will boost bank Treasury buying" — SLR is in the glossary, so it passes a naive check, but the statement about current SLR policy might be completely fabricated.

**Recommendation**: Add a post-generation verification step: after every Pro response mentioning mechanisms, (a) extract all mechanism names from the output, (b) check each against the glossary, (c) for any mechanism NOT in the glossary, flag the output with "UNVERIFIED MECHANISM: <name>" and downgrade its confidence contribution, (d) for mechanisms IN the glossary, verify the directional claim matches the glossary's `directional` field. This makes the escape hatch enforceable rather than aspirational.

---

## MEDIUM Findings

### M1: European Equities, Chinese Bonds, EM — No Country Overlay on Asset Class

The v2 taxonomy is US-centric at the asset class level: `US_FIXED_INCOME`, `US_EQUITIES`. The entity types for FX include Japanese and European entities, which is good. But:

- "European equities rally on ECB rate cut" → keyword "equities" maps to US_EQUITIES with entity types RETAIL, INSTITUTIONAL, CORPORATE_BUYBACK, FOREIGN_INVESTOR, HEDGE_FUND. European equities have different dominant entities (European insurers, global asset managers, sovereign wealth funds) and different flow dynamics (no buyback culture comparable to US).
- "Chinese bonds rally on PBoC easing" → "bonds" might match US_FIXED_INCOME keywords ("国债" matches), but Chinese bonds have PBoC, Chinese banks, Stock Connect, and SAFE as dominant entities — none of which are in the US_FIXED_INCOME entity list.

The v1 plan acknowledged this in its changelog ("日元用 BoJ/GPIF/散户，欧股用 ECB/机构/出口商"), and the research document's AC7 (FX) and AC9 (EM) frameworks handle jurisdiction-appropriate entities. But the v2 *implementation* taxonomy has no mechanism for country overlays on equity or fixed income classes.

**Recommendation**: Add a `region` field to the routing result. `US_EQUITIES + region=EU` selects European entity types and data sources. `US_FIXED_INCOME + region=CN` selects Chinese entity types. This is a 20-line extension to the taxonomy that prevents systematic misclassification of non-US hypotheses.

### M2: Routing "LLM Fallback" Is Unspecified and Untested

The v2 says routing priority is "ticker match > keyword density > LLM classification (fallback)." There is zero specification of:
- What prompt the LLM fallback uses
- What the expected accuracy of LLM classification is
- Whether a wrong LLM classification is recoverable downstream
- How often the fallback fires (if keyword density has a threshold, what is it?)

If keyword density is the primary mechanism and LLM is only the fallback, then the quality of routing depends almost entirely on the keyword list quality. The keyword lists in the v2 taxonomy are extremely short (3-8 keywords per class) and mostly English-only. A hypothesis in Chinese about 国债 will match, but one about "yield curve control" or "duration risk" will match nothing.

**Recommendation**: Either (a) expand keyword lists significantly (30-50 per class, bilingual) and make LLM classification the PRIMARY router for medium/low confidence cases, or (b) define explicit test scenarios: run the router against 100 historical MarketMind hypotheses, measure classification accuracy, and publish the confusion matrix before Phase H-1 begins.

---

## Confirmed Fixes (v1 → v2 Improvements That Actually Work)

These v2 fixes are sound and should proceed:

| Finding | Fix | Verdict |
|---|---|---|
| Architecture C1 | investigation_loop 918→486 lines | Confirmed working in codebase (486 lines) |
| Architecture C2 | HypothesisResult flows to decision | Confirmed — fields present in investigation_types.py |
| Security H-SEC-1 | input_guard wired to gateway | Confirmed as completed in changelog |
| Security H-SEC-2 | MAX_PRO_CALLS_PER_SESSION=30 | Directionally correct; 30 is a reasonable first-pass limit |
| Security H-SEC-3 | macro_data exceptions logged | Confirmed as completed |
| Architecture C2 | app.py 971→76 lines | Confirmed working (76 lines in codebase) |
| Cross-module H7 | Signal conflict detection in decision.py | Directionally correct if fixed per H1 above |
| Modularity | All new modules ≤ 500 lines | Size estimates look realistic (150-450 lines) |

---

## Summary Matrix

| ID | Severity | Finding | Must Fix Before Implementation? |
|---|---|---|---|
| C1 | CRITICAL | 9-class research → 5-class implementation; wrong lenses for gold/gas/ag/EM | YES — implement full taxonomy or document which classes are deferred and why |
| C2 | CRITICAL | Keyword router lacks disambiguation; "gold" in equity context routes wrong | YES — implement research document's 6-step routing tree |
| C3 | CRITICAL | No multi-asset hypothesis handling; every cross-asset hypothesis misrouted | YES — add primary-secondary decomposition before Phase H-1 |
| C4 | CRITICAL | Pre-1985 qualitative data cannot feed Euclidean distance; fix is cosmetic | YES — either backfill numerical data or redesign as qualitative overlay |
| H1 | HIGH | Arbitrary conflict thresholds create 9+ unresolved conflicts per session | YES — implement NetDirectionalForce with internal resolution |
| H2 | HIGH | MONITOR sampling=1 is arbitrary; misses systematic tail risk | Recommended — use threshold-based rule |
| H3 | HIGH | 90-day threshold staleness measures wrong thing; uniform across all thresholds | Recommended — per-threshold decay categorization |
| H4 | HIGH | No verification that LLM uses escape hatch; hallucination still likely | Recommended — add post-generation mechanism verification |
| M1 | MEDIUM | No country overlay for non-US equity/fixed-income hypotheses | Deferrable — add region field as extension |
| M2 | MEDIUM | LLM fallback router unspecified; keyword lists too short | Deferrable — expand keyword lists, add accuracy testing |

**Overall assessment**: The v2 plan is a genuine improvement over v1 — the asset-class routing concept is correct, and the C1/C2 diagnosis was accurate. But the implementation collapses the research into a coarser taxonomy that reintroduces the same category error at one level of granularity up (C1). The keyword router is too simple for the disambiguation problem (C2). Multi-asset hypotheses — among the most valuable in macro analysis — are completely unhandled (C3). And the pre-1985 fix is a promise the Euclidean distance method cannot keep (C4).

**Recommendation**: Do not begin Phase H-0 until C1-C4 are addressed. H1-H4 should be addressed during implementation (H1 before Phase H-4, H2-H4 before their respective modules). M1-M2 can be deferred to Phase H+1.
