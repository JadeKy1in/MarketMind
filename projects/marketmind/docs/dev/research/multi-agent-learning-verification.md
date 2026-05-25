# Multi-Agent Learning & Prediction Verification for Investment AI

**Date**: 2026-05-18
**Status**: Research complete — 10 sources synthesized
**Purpose**: Identify scoring, feedback, and evolution mechanisms applicable to MarketMind's 21-shadow-agent ecosystem

---

## Executive Summary

Three-tier framework for turning MarketMind's shadow ecosystem into a learning system:

| Tier | Function | Key Insight |
|:---:|---|---|
| **Scoring** | Measure "better" | Brier score is the gold standard; calibration > confidence |
| **Feedback** | Close the loop | TextGrad-style outcome attribution + human-in-loop annotations |
| **Evolution** | Agents improve | Self-play debate + cross-agent knowledge distillation + backtest-driven weight updates |

Each tier can be implemented independently and incrementally. Scoring comes first — you cannot improve what you cannot measure.

---

## 1. SCORING MECHANISMS — How to Measure "Better"

### 1.1 Brier Score (Binary Predictions)

The dominant scoring rule in forecasting tournaments (Good Judgment Project, Metaculus, ForecastBench). For binary events:

```
BS = (1/N) * sum((forecast_i - outcome_i)^2)
```

where forecast_i is the predicted probability (0.0–1.0) and outcome_i is the actual result (0 or 1).

**Key properties:**
- **0.0** = perfect accuracy
- **0.25** = perpetual 50/50 guess (maximally uninformed)
- **Quadratic penalty**: a 0.99 forecast that resolves false costs 0.98; a 0.55 forecast that resolves true costs ~0.20. **Overconfidence is punished far harder than honest uncertainty.**

**Application to MarketMind**: Every shadow's directional call (bullish/bearish on an asset) can be expressed as a probability. When the timeline expires (e.g., "gold will rise 2% in 30 days"), the binary outcome is observed and a Brier score computed per shadow, per asset class.

### 1.2 Brier Decomposition (Calibration + Resolution)

The Brier score can be decomposed into three components:

```
BS = Calibration - Resolution + Uncertainty
```

- **Calibration**: Do 80%-confidence predictions come true 80% of the time?
- **Resolution**: How much do forecasts discriminate between events that happen vs. don't?
- **Uncertainty**: Inherent unpredictability of the outcome (fixed for a given dataset)

This decomposition tells you **why** a shadow scores poorly: overconfidence (bad calibration) vs. inability to discriminate (bad resolution).

### 1.3 Asset-Class-Weighted Brier

MarketMind has 21 shadows distributed across asset classes. Proposed scoring:

```
Shadow_Score = sum(w_c * BS_c for c in asset_classes) / sum(w_c)
```

Where `w_c` = inverse of asset-class volatility (more predictable classes get higher weight). This prevents a shadow that's excellent at bonds but terrible at crypto from being penalized by the more volatile class.

### 1.4 Current State: LLMs vs. Humans

From ForecastBench (2025):
- Superforecasters: Brier **0.074–0.115** (varies by question set)
- Best LLM (GPT-4.5): Brier **0.101–0.145**
- Scaffolded AI ensemble (AIA Forecaster): Brier **0.075–0.110** — statistically indistinguishable from superforecasters on smaller sets

Linear extrapolation suggests LLM–superforecaster parity by **late 2026**. The gap is closing fast.

### 1.5 Sharpe-Adjusted Scoring (Financial Domain)

For investment-specific scoring, combine Brier with risk-adjusted return:

```
Composite_Score = alpha * (1 - BS) + (1-alpha) * Sharpe_normalized
```

This penalizes shadows that are directionally right but produce uninvestable volatility.

---

## 2. FEEDBACK MECHANISMS — How to Close the Loop

### 2.1 Outcome-Based Feedback (Predict → Wait → Verify → Learn)

The core cycle. Every shadow hypothesis generates a **structured prediction record**:

```python
{
    "shadow_id": "s7_gold",
    "timestamp": "2026-05-18T14:00:00Z",
    "asset": "XAUUSD",
    "direction": "bullish",
    "confidence": 0.72,
    "horizon_days": 30,
    "key_reasons": ["real rates falling", "central bank buying", "geopolitical risk"],
    "resolves_at": "2026-06-17T14:00:00Z",
    "resolved_outcome": null,  # filled at resolution
    "brier_score": null         # computed at resolution
}
```

When the horizon expires, the outcome is compared to the prediction, the Brier score is computed, and the shadow receives a **scorecard** — not just the score, but a decomposition showing which features of its analysis contributed to error.

### 2.2 Feature-Level Error Attribution (TextGrad Pattern)

The MENTOR framework (Zhejiang University, 2025) uses **Textual Gradient Descent (TextGrad)** — a technique where LLM agents receive **natural-language feedback** on which reasoning steps were wrong, not just a numerical score.

Applied to MarketMind: When a shadow's gold prediction resolves wrong, the system can back-propagate:
- "Your thesis cited falling real rates, but real rates actually rose 15bp during the period. Source quality was low — you relied on a 3-week-old Fed speech."
- "You missed China's gold import data which showed a 40% drop. This was covered by shadow_s3_china but not surfaced to you."

This is **feature-level attribution** — telling the agent *which part of its analysis* was wrong, not just *that* it was wrong.

### 2.3 Human-in-the-Loop Feedback (Gate 1/2/3 Annotations)

The user already reviews analyses at Gates 1/2/3. This feedback can be structured:

| Gate | Feedback Type | Learning Signal |
|------|---|---|
| Gate 1 (news selection) | "This article is noise" / "Good catch" | Source-quality weight update |
| Gate 2 (analysis review) | "You missed X factor" / "Good point about Y" | Reasoning-gap annotation |
| Gate 3 (decision) | Override: accept/reject/modify | Direct preference signal for RL |

Each annotation becomes a structured training record: `{shadow_id, gate, annotation_type, content, timestamp}`.

### 2.4 Cross-Shadow Feedback (Consensus/Dissent Signals)

When 18/21 shadows are bullish on gold and 3 are bearish, and the bears are right:

- **Dissent bonus**: The 3 dissenting shadows get a positive weight adjustment for that asset class
- **Consensus penalty**: The 18 are not individually penalized (crowd error, not individual error), but the **aggregate consensus weight** is reduced for that asset class

When a minority view is consistently correct, the system should amplify minority voices in future rounds.

### 2.5 Backtesting-as-Feedback (PredictionMarketBench Pattern)

PredictionMarketBench (arXiv, Jan 2026) provides deterministic replay of historical data with maker/taker semantics. For MarketMind, the analogous approach:

- **Historical replay**: Run shadows against historical data where outcomes are known (e.g., "what would shadow_s7 have said about gold on June 15, 2024?")
- **Blind backtest**: Scrub dates from news articles, feed them to shadows, compare predictions to known outcomes
- **Walk-forward validation**: Train shadow weights on 2023–2024 data, validate on 2025 data, test on 2026 live data

This is distinct from live scoring — it allows rapid iteration without waiting for real-world timelines to expire.

---

## 3. EVOLUTION MECHANISMS — How Agents Actually Improve

### 3.1 Multi-Agent Debate for Refinement

The strongest finding from 2024–2025 research: **diverse agent debate produces better reasoning than any single agent.**

Key papers and their findings:

| Paper | Finding |
|---|---|
| **Diversity of Thought** (arXiv:2410.12853) | Diverse model combinations (Gemini-Pro + Mixtral + PaLM) **outperform GPT-4** after 4 debate rounds (91% vs 82% on GSM-8K) |
| **MADKE** (Neurocomputing, 2025) | Shared retrieval knowledge pool breaks "cognitive islands"; surpasses GPT-4 by +1.26% across 6 datasets |
| **CONSENSAGENT** (2025) | Dynamically detects and mitigates sycophancy (agents agreeing too easily); SOTA on 6 reasoning benchmarks |
| **Can LLMs Really Debate?** (Nov 2025) | Intrinsic reasoning strength + group diversity are the dominant success drivers; majority pressure suppresses independent correction |

**Application to MarketMind**: Before finalizing a Gate 2 analysis, run a structured debate between shadows that disagree. The debate transcript becomes input to the final analysis. Disagreement is a feature, not a bug.

### 3.2 Self-Play for Continuous Improvement

Self-play (agents competing against evolving versions of themselves) is emerging as the most scalable improvement paradigm:

| Framework | Mechanism | Result |
|---|---|---|
| **SPIRAL** (ICLR 2026) | Zero-sum self-play with role-conditioned advantage estimation | +10% across 8 reasoning benchmarks |
| **MARSHAL** (Tsinghua, 2025) | Multi-game self-play RL; role-aware, round-level credit assignment | +10% AIME, +7.6% GPQA-Diamond |
| **MACA** (2025) | Multi-agent debate as RL training signal; majority/minority preference learning | +26.87% debate effect, +21.51% individual accuracy |

**Application to MarketMind**: Shadows can be assigned adversarial roles in a self-play setup. Shadow A constructs a bull case, Shadow B constructs a bear case, and the outcome resolves which reasoning was stronger. The "winning" reasoning patterns are reinforced.

### 3.3 Knowledge Distillation: 21 Shadows → 1 Compact Model

SMAGDi (NeurIPS 2025) shows that a 40B-parameter multi-agent system can be distilled into a **6B-parameter student model** while retaining 88% accuracy. The key technique: modeling debate traces as directed interaction graphs and using contrastive reasoning + embedding alignment.

**Application to MarketMind**: After N rounds of shadow operation, distill the collective reasoning patterns into a lightweight "MarketMind Core" model. This is not about replacing shadows — it's about creating a fast, cheap approximation for low-stakes decisions.

### 3.4 Domain-Specific Weight Evolution

Each shadow maintains per-asset-class weights that evolve based on outcomes:

```python
# After each resolution cycle
for shadow in shadows:
    for asset_class in shadow.tracked_classes:
        recent_brier = compute_brier(shadow, asset_class, window=last_10_predictions)
        baseline_brier = average_brier(all_shadows, asset_class)
        
        if recent_brier < baseline_brier:  # shadow is better than average
            shadow.weights[asset_class] *= 1.05  # amplify
        else:
            shadow.weights[asset_class] *= 0.95  # attenuate
        
        # Clip to prevent extreme divergence
        shadow.weights[asset_class] = clamp(shadow.weights[asset_class], 0.1, 3.0)
```

This is a simple exponential moving average of relative performance. It does not require model retraining — just weight updates.

### 3.5 Federated Methodology Transfer (Without Raw Analysis Sharing)

Shadows should share **methodology insights** without sharing raw analysis (which could create groupthink).

**Pattern**: Shadow A is consistently good at gold. Shadow B is consistently good at tech stocks. They don't share their specific analyses — they share their **reasoning frameworks**:

- Shadow A → System: "When analyzing gold, I prioritize: (1) real rates, (2) central bank reserves, (3) COMEX positioning, in that order."
- System → Shadow B: "Gold experts in the ecosystem prioritize these 3 factors. Try incorporating them."

This is **selective methodology transfer** — domain-specific heuristics, not raw opinions. It preserves diversity while allowing best practices to propagate.

### 3.6 The Full Architecture

```
PREDICT ──→ WAIT ──→ VERIFY ──→ LEARN ──→ UPDATE ──┐
   │                                                   │
   │  Shadows produce structured                       │
   │  predictions with confidence,                     │
   │  reasons, and timelines                           │
   │                                                   │
   ▼                                                   │
WAIT (timeline expires)                                │
   │                                                   │
   ▼                                                   │
VERIFY (compare prediction to outcome)                 │
   │                                                   │
   ├── Brier score per shadow per asset class          │
   ├── Feature-level error attribution (TextGrad)      │
   ├── Human annotation at Gates 1/2/3                 │
   └── Cross-shadow dissent/consensus signals          │
   │                                                   │
   ▼                                                   │
LEARN ─────────────────────────────────────────────────┘
   │
   ├── Per-shadow weight evolution (EMA)
   ├── Methodology transfer (domain heuristics)
   ├── Debate transcripts for Gate 2 enrichment
   └── Periodic distillation to Core model
   │
   ▼
UPDATE ──→ (next cycle)
```

---

## 4. Implementation Priority

| Priority | Mechanism | Effort | Impact | Dependencies |
|:---:|---|---|---|---|
| **P0** | Structured prediction records + Brier scoring | Low | Foundation for everything | None |
| **P1** | Per-shadow weight evolution (EMA) | Low | Immediate improvement signal | P0 |
| **P2** | Cross-shadow dissent bonus | Low | Prevents groupthink | P0 |
| **P3** | Feature-level error attribution (TextGrad) | Medium | Tells agents *why* they were wrong | P0, shadow analysis structured |
| **P4** | Multi-agent debate at Gate 2 | Medium | Improves analysis quality | P0 |
| **P5** | Human annotation pipeline (Gates 1/2/3) | Medium | Ground truth for RL | Gate workflow exists |
| **P6** | Historical backtesting (blind) | High | Rapid iteration without waiting | P0, historical data |
| **P7** | Federated methodology transfer | High | Cross-pollination without groupthink | P0, P1 |
| **P8** | Knowledge distillation to Core model | High | Fast/cheap for low-stakes decisions | P0, P1, sufficient data |

---

## 5. Key References

1. **Diversity of Thought** (arXiv:2410.12853) — Diverse model debate outperforms GPT-4
2. **MADKE** (Neurocomputing 2025) — Knowledge-enhanced multi-agent debate
3. **SMAGDi** (NeurIPS 2025) — 40B → 6B distillation with 88% retention
4. **SPIRAL** (ICLR 2026) — Self-play zero-sum RL for multi-agent reasoning
5. **MARSHAL** (Tsinghua 2025) — Multi-game self-play with role-aware credit assignment
6. **MACA** (2025) — Multi-agent consensus alignment via debate RL
7. **MENTOR** (Zhejiang 2025) — TextGrad outcome feedback for financial event prediction
8. **ForecastBench** (2025) — Brier scoring benchmarks; superforecasters vs LLMs
9. **PredictionMarketBench** (arXiv 2026) — Deterministic backtesting for prediction agents
10. **Good Judgment Project** (2011–present) — Superforecaster methodology and calibration
11. **CONSENSAGENT** (2025) — Anti-sycophancy in multi-agent debate
12. **Can LLMs Really Debate?** (Nov 2025) — Controlled study of debate drivers
13. **DOWN** (April 2025) — Adaptive debate activation, 6x efficiency gain
14. **Self-Improving Analyst Agent** (ICML 2025) — 44.5% → 81.3% via outcome learning
