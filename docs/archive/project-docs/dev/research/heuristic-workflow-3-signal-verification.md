# Heuristic Workflow 3: Progressive Signal Verification

**Research completed**: 2026-05-17
**Purpose**: Design an automated pipeline that transforms raw news into investment signals through progressive data verification.
**Related phase**: Phase E — Signal Verification Pipeline

---

## Table of Contents

1. [News to Signal Extraction Patterns](#1-news-to-signal-extraction-patterns)
2. [Data Verification Chains](#2-data-verification-chains)
3. [Multi-Source Signal Fusion](#3-multi-source-signal-fusion)
4. [Lead-Lag Relationships](#4-lead-lag-relationships)
5. [Confidence Scoring](#5-confidence-scoring)
6. [Synthesized Pipeline Architecture](#6-synthesized-pipeline-architecture)

---

## 1. News to Signal Extraction Patterns

### 1.1 State of the Art: From Sentiment to Structured Events

The field has moved decisively beyond simple sentiment polarity. Current SOTA (2025-2026) emphasizes **fine-grained event types, causal chains, and multi-hop relationships**.

#### Key Frameworks

| Framework | Approach | Performance |
|---|---|---|
| **Janus-Q** (Feb 2026) | End-to-end event-driven trading via Hierarchical Gated Reward Model; 62,400 articles annotated with 10 event types + CAR labels | +102% Sharpe, +17.5% direction accuracy vs. LLM baselines |
| **NEXUS** (2025) | Multi-modal: fuses RoBERTa/FinBERT/BGE/Llama2 text encoders with price dynamics, 2M+ articles across 15 years of S&P 500/NASDAQ 100 | +0.427 daily Sharpe (S&P 500), +0.338 (NASDAQ 100) |
| **Event-Aware Sentiment Factors** (Aug 2025) | LLM assigns 70+ multi-label event categories (Rumor/Speculation, Retail Investor Buzz, Brand Boycott) to tweets | Some labels yield Sharpe as low as -0.38 (contrarian signals) |
| **LLM-Enhanced Multi-Causal Mining** (2025) | Fine-tuned LLaMA + GNN-based event-centric graph reasoning for multi-cause, multi-effect chains | +5-10% F1 over 10 baselines |

#### Critical Finding: Delayed Price Assimilation

NEXUS empirically confirmed that **markets do not instantly price news**. This creates a genuine window for event-driven strategies — the verification pipeline has time to work before the signal decays.

#### The Sentiment-to-Signal Conversion Math (CFA Institute, Jan 2025)

The most rigorous published methodology uses a three-stage conversion:

**Stage 1 — Daily Sentiment Score (raw)**:
```
S = sum[p(hi) - n(hi)] / sum[p(hi) + n(hi)]
```
Where p(hi) = 1 if headline positive, n(hi) = 1 if negative. Bounded [-1, 1], symmetric, scale-invariant.

**Stage 2 — Cumulative Sentiment (noise reduction)**:
Accumulate over rolling window d=20 days. Reduces daily noise significantly.

**Stage 3 — Detrended Signal (the key innovation)**:
```
DS(t) = Sd(t) - mean(Sd over window)
```
Subtracting the rolling mean isolates the *deviation* from trend — this is what drives trading. Positions: Long = max(DS, 0), Short = min(DS, 0).

**Backtest results** (Detrended vs. Buy & Hold):
- Sharpe: 0.88 vs. 0.79
- Sortino: 1.06 vs. 1.02
- Calmar: 0.52 vs. 0.45

### 1.2 How Professional Terminal Analysts Structure News Monitoring

Bloomberg/Reuters terminal workflows follow a disciplined structure:

| Practice | Detail |
|---|---|
| **Tier 1 sources** | Bloomberg, Reuters, Dow Jones wires + SEC EDGAR RSS |
| **Keyword filtering** | Ticker, 8-K, guidance, CEO, M&A, bankruptcy; macro: Fed, CPI, PCE, GDP |
| **Volume/price thresholds** | Alert only if intraday move >3% on >2x 30-day avg volume |
| **Mobile push discipline** | Cap at 3 pushes/sector/day; off-hours Do Not Disturb |
| **Timeboxed routine** | 30-min pre-market scan, 5-10 min open, 15-min post-release blocks |
| **Triangulation** | Require 3-5 independent sources (wire + primary filing + sector outlet) before acting |
| **Trade journal** | Log all signals, actions, and outcomes for continuous threshold tuning |

Bloomberg's AI evolution (2025-2026):
- **Document Search & Analysis**: Natural language queries across 400M+ documents with structured, attributed responses
- **ASKB conversational AI**: Multi-agent system returning BQL (Bloomberg Query Language) code with annotated visualizations
- **AI-Powered Research Summaries**: Comparative analysis across companies/sectors with source citations

### 1.3 Production Tools Available

- **`alphasig`** (PyPI, 2025): Extracts causal/structural relationships from SEC filings beyond sentiment — supply-chain dependency graphs, risk factor escalation, M&A language detection, management tone shifts. Outputs timestamped, backtestable Parquet/DuckDB signals.
- **LSEG MarketPsych**: Patented NLP engine converting 100+ sentiment dimensions (emotions, financial language, topics) into structured time-series updated every 60 seconds. Covers 16,000+ global stocks with 20+ years of backtesting.
- **Semantic Finance** (YC Launch): Real-time AI-powered news API that filters noise using LLMs, trade data, social engagement, and anomalous price/volume changes.

### 1.4 Critical Design Principles (Synthesized)

1. **Causal masking is mandatory** — never allow future information leakage in temporal models
2. **Walk-forward validation** — rolling monthly windows with expanding training sets; not random train/test splits
3. **Two-day lag** — apply weights from t-2 to account for next-day execution reality
4. **Detrend before trading** — raw sentiment is too noisy; cumulative + detrended scores required
5. **Data quality > model complexity** — the primary bottleneck across projects is sparse/low-fidelity news data, not architecture
6. **Social media sentiment half-life ~2 hours** — requires different aggregation windows than traditional news

---

## 2. Data Verification Chains

### 2.1 The Core Problem

When an LLM extracts a claim from news (e.g., "Fed likely to cut rates in June"), that claim is an *NLP artifact* — not a verified fact. The verification chain transforms it into a *calibrated signal* by triangulating against independent ground-truth sources.

### 2.2 CME FedWatch Tool as Ground Truth for Rate Expectations

**What it is**: A market-based barometer translating 30-Day Federal Funds (ZQ) futures contract prices into implied probabilities for FOMC rate actions.

**Core formula**:
- Implied Rate = 100 - Futures Price
- P(Hike) = [EFFR(End of Month) - EFFR(Start of Month)] / 25bps

**Key methodological assumptions**:
1. Rate changes are always in multiples of 25 bps
2. EFFR cannot go below zero
3. EFFR reacts proportionally to target rate changes
4. No-meeting months serve as anchors for the probability tree
5. Binary probability trees chain across successive FOMC meetings

**How to use as verification**:
- Extract claim: "Market expects rate cut in June"
- Query FedWatch: What is the futures-implied probability of a cut at the June FOMC meeting?
- Verify: If FedWatch shows >60% probability, the claim is *market-confirmed*. If <40%, the claim is *divergent from market pricing* — which may itself be a signal.

**Verification accuracy caveat**: FedWatch is NOT a forecasting tool — it's a direct reflection of traded futures prices. Its "accuracy" depends on how well the market prices future policy. Schwab's analysis: "Inaccurate forecasts shouldn't be viewed as an indictment of the FedWatch Tool... which is dependent on inputs from the market."

**Overlaying the Dot Plot**: FedWatch allows overlaying FOMC dot plot projections vs. futures-implied year-end rates — this comparison reveals divergence between Fed officials' projections and market expectations, itself a tradable signal.

### 2.3 Cross-Referencing Multiple News Sources

#### FinVet: Multi-Agent Financial Misinformation Detection (Oct 2025)
- **Architecture**: Dual RAG pipelines + external fact-checking agents with confidence-weighted voting
- **Processing Tiers**:
  - High confidence: Direct metadata extraction
  - Moderate confidence: Hybrid context-model reasoning
  - Low confidence: Pure LLM analysis
- **Performance**: F1 score 0.85 on FinFact dataset, outperforming standalone RAG by 37%

#### FactCheck in Finance: Multilingual Event Detection (2021)
- Unsupervised clustering for event extraction → cross-lingual linking → transformer-based credibility scoring
- Adversarial BERT achieved 0.894 F1 on M&A event prediction
- Key pattern: The same event reported in English and Chinese with consistent details = high confidence

#### ApudFlow: Multi-Source News Validation Pipeline
```
Source Collection → Content Comparison → Credibility Scoring → Consensus Detection → Discrepancy Flagging
```
Features: source credibility metrics, consensus strength scoring, real-time validation, automated fact-checking workflows.

#### GDELT + Decentralized Social Media (Nostr) Risk Detection (2026)
- Combined GDELT global news database with Nostr (decentralized social media)
- Finding: News data provides stable event-driven signals; decentralized social media enables earlier risk detection
- Combined approach improves systematic risk prediction

#### Plocamium Holdings: Closed-Loop Intelligence Pipeline
- Ingests 172+ RSS feeds and APIs (NewsAPI.ai, Mediastack)
- ML momentum scoring + entity extraction + BICS classification + KMeans clustering
- Composite **Plocamium Signal Index (PSI)** measuring narrative disruption via: attention cascade, narrative embedding drift, graph spectral shift, sentiment-momentum divergence, source concentration (HHI)

### 2.4 Using Market Data to Validate News Claims: "News vs. Markets" Divergence

This is one of the most powerful verification mechanisms. The principle:

> **Markets move on *surprises relative to expectations*, not on the headline itself.**

#### Why Bond Markets Are the Best Truth Validator

Research strongly supports bonds as the most news-sensitive asset class:
- Kerssenfischer & Schmeling (2021): ~50% of all stock and bond movements trace to identifiable news events
- Fleming & Remolona (1999); Andersson et al. (2009): Macroeconomic news reactions are more pronounced in government bonds than equities
- The 10-year benchmark bond is the most liquid instrument and the policy target — making it the "most important candidate to absorb news information" (Banerjee & Pradhan, 2021)

#### Types of News-Market Divergence Signals

| Divergence Type | Signal | Interpretation |
|---|---|---|
| **News-Yield Divergence** | Positive headline, yields fall | Market skepticism; news may be overblown |
| **Political Claim Divergence** | Policy announcement, no yield move | Announcement lacks credibility or already priced in |
| **Cross-Market Divergence** | Equities rally, bonds don't confirm | Equity overreaction; bond market is the "adult in the room" |
| **Sentiment Divergence** | News sentiment positive, yields declining | Narrative vs. reality split (potential stagflation signal) |
| **Yield Curve Divergence** | Short-end reacts, long-end doesn't | Market parsing timing vs. magnitude differently |

#### Detection Methodology

```
Step 1: Establish baseline correlation (rolling correlation: economic surprises vs. yields)
Step 2: Categorize the news (confirmed by multiple sources? official channel? fundamental or noise?)
Step 3: Detect divergence:
  - Direction: Did yields move as expected given the news?
  - Magnitude: Is the yield move proportional to the surprise?
  - Persistence: Does the yield reaction persist beyond 15-60 min?
  - Cross-asset check: Are equities, FX, credit confirming or contradicting?
Step 4: If divergence persists across 2+ of the above checks → signal generated
```

#### State-Dependent Response (Advanced)

Andersen et al. found that equity markets react *differently to the same news depending on economic state*:
- **Expansions**: Bad news has *positive* impact (discount rate effect dominates)
- **Recessions**: Bad news has *negative* impact (cash flow effect dominates)

This state-dependent response is itself a divergence signal — and a regime classifier.

### 2.5 LLM Claim Verification: Multi-Step Pipelines

#### AFEV: Atomic Fact Extraction and Verification (2025)
1. Decompose complex claims into atomic facts using LLM
2. Fine-grained evidence retrieval per atomic fact
3. Adaptive verification of each atomic fact
4. Aggregate atomic verdicts into claim-level confidence
- **Achieves SOTA on 5 benchmarks**

#### Hybrid Fact-Checking: KG + LLM + Web Search (EMNLP 2025)
Three-step modular pipeline:
1. Knowledge Graph retrieval (DBpedia) — structured facts
2. LM-based classification — semantic judgment
3. Web search agent as fallback — current information
- **F1 of 0.93 on FEVER**

#### SeQwen: Sequential Financial Claim Verification (COLING 2025)
- Two-stage fine-tuning: classification → explanation generation
- Uses Qwen, Mistral, Gemma-2 for financial domain
- **F1 of 0.8283 on FIN-FACT financial claims dataset**

#### DEFAME: Dynamic Evidence-Based Fact-Checking (ICML 2025)
- Six-stage zero-shot MLLM pipeline for text+image claims
- Dynamically selects tools and search depth
- New SOTA on VERITE, AVeriTeC, MOCHEG

### 2.6 Recommended Verification Chain Architecture

For each claim extracted from news:

```
CLAIM EXTRACTED (LLM)
    │
    ├──→ VERIFICATION LAYER 1: Market Ground Truth
    │    Check CME FedWatch (rate claims), futures curves (commodity claims),
    │    bond yields (macro claims), options implied vol (event risk claims)
    │
    ├──→ VERIFICATION LAYER 2: Multi-Source Corroboration
    │    Search 3+ independent news sources for the same event.
    │    Score consistency of reporting. Flag conflicting narratives.
    │
    ├──→ VERIFICATION LAYER 3: Market Data Validation
    │    Check if related markets moved in the expected direction.
    │    Bond yields validate rate claims. Credit spreads validate risk claims.
    │    Copper validates China demand claims. BDI validates trade claims.
    │
    ├──→ VERIFICATION LAYER 4: Historical Pattern Match
    │    Has this claim pattern occurred before? What was the outcome?
    │    Use RAG over historical claims database.
    │
    └──→ CONFIDENCE SCORING
         Weighted aggregation of Layers 1-4 → calibrated confidence score
```

---

## 3. Multi-Source Signal Fusion

### 3.1 Ensemble Methods for Heterogeneous Signals

#### MSIF-OEM Framework (Zhao et al., 2025)
- Parallel Transformer encoder architecture for fusing OHLCV, LOB, TAQ, and market snapshot data
- Ensemble Stochastic Gradient Descent (ESGD) for online ensemble learning
- Key insight: Different data types get different attention heads, then fused in shared space

#### E-3T: Heterogeneous Ensemble of Temporal Transformers (2025)
- Integrates Temporal Fusion Transformer (TFT), SeTT, and rSeTT
- Quantile stacking with quantile regression for heterogeneous ensemble
- 63.16% directional accuracy on DJIA stocks
- Knowledge distillation for production deployment

#### Stacking-Bagging-Vote (SBV) with Kalman Filter (2022)
- Combines Bagging-Vote and Stacking ensembles
- Stock data preprocessed through Kalman filter before feeding to ensemble
- Interactive fusion optimization at both data and model levels
- One of few papers directly combining Kalman + ensemble for financial signals

### 3.2 Bayesian Updating from Multiple Evidence Sources

#### UKF-NARX Hybrid (Abdulkadir et al.)
- Unscented Kalman Filter (UKF) + NARX neural network
- Trained with Bayesian regulation
- Directly addresses chaotic, non-linear financial time series
- Pattern: Kalman for state estimation → Bayesian neural net for prediction

#### ReGEN-TAD: Generative Ensemble for Anomaly Detection (Martinez, 2025)
- Convolutional-transformer architecture with ensemble scoring
- Multiple diagnostic signals: predictive inconsistency, reconstruction degradation, latent distortion, volatility shifts
- Calibrated aggregation without labeled data
- Highly relevant for **alternative data quality monitoring** and regime-change detection

### 3.3 Kalman Filters for Time-Series Signal Fusion

The Kalman filter is ideal for fusing signals with different update frequencies and noise characteristics:

**Use case**: Fuse daily news sentiment (noisy, high-frequency) with weekly macro indicators (clean, low-frequency) and real-time market data (instantaneous, medium-noise).

**Kalman fusion architecture**:
```
State vector: [true_signal, trend, volatility]
Observation 1: news sentiment (daily, noise σ_n)
Observation 2: market data (intraday, noise σ_m)
Observation 3: macro indicator (weekly, noise σ_p)

Kalman update:
  Predict: x_t = F * x_{t-1} (state transition)
  Update: x_t = x_t + K * (z_t - H * x_t) (correct with observation)
  Kalman gain K weights observations by their noise covariance
```

### 3.4 How Professional Quant Funds Combine Alternative + Traditional Data

#### Multi-Horizon Trading Signal System (Nair, 2025)
- Integrates Google Trends sentiment proxies + technical momentum + volatility metrics
- Random Forest + XGBoost ensemble
- Achieves 64.2% accuracy, 8.3% annualized alpha (Sharpe 1.42)
- Pattern: alternative data for alpha signal, traditional data for timing

#### Hybrid GenAI + ML for Alternative Data (Buvanachandran, 2025)
- LLMs extract financial indicators from unstructured alternative data (corporate discourse, digital platforms)
- Traditional ML normalizes, validates, and quantifies predictive correlations
- Architecture: LLM for extraction → ML for calibration → ensemble for fusion

#### CEEMDAN + Boosting Ensemble with MCS Selection (Garai & Paul, 2023)
- CEEMDAN decomposition to create orthogonal subseries
- Random Forest + Kernel Ridge Regression + AdaBoost-LSTM/GRU
- Model Confidence Set (MCS) for ensemble selection
- Pattern: Decompose to isolate signal components → ensemble per component → MCS to select best

### 3.5 Practical Fusion Architecture

```
                    ┌─────────────────────────────┐
                    │     SIGNAL FUSION ENGINE     │
                    └─────────────────────────────┘
                                    │
        ┌───────────────┬───────────┼───────────┬───────────────┐
        │               │           │           │               │
   NEWS SIGNALS    MARKET DATA   MACRO DATA   ALT DATA      SOCIAL
   (NLP score)     (yields,vol)  (PMI,CPI)    (trends,sat)  (sentiment)
        │               │           │           │               │
        └───────────────┴─────┬─────┴───────────┘───────────────┘
                              │
                    ┌─────────▼─────────┐
                    │  KALMAN FILTER    │  ← State-space fusion
                    │  (noise removal,  │     with time-varying
                    │   gap filling)    │     observation noise
                    └─────────┬─────────┘
                              │
                    ┌─────────▼─────────┐
                    │ BAYESIAN ENSEMBLE │  ← Bayesian Model Averaging
                    │ (weighted by      │     over component models
                    │  posterior prob)  │
                    └─────────┬─────────┘
                              │
                    ┌─────────▼─────────┐
                    │ OUTPUT: Fused     │
                    │ Signal + Posterior│
                    │ Confidence Score  │
                    └───────────────────┘
```

**Key design rules**:
1. Kalman filter for time-alignment and noise reduction (signals arrive at different frequencies)
2. Bayesian model averaging for ensemble weights (avoids overfitting to recent performance)
3. MCS (Model Confidence Set) for pruning underperforming signal sources
4. Online learning for adapting to regime changes

---

## 4. Lead-Lag Relationships

### 4.1 The Economic Indicator Hierarchy

Understanding which indicators LEAD or LAG news events is critical for the "check related indicators" verification step. This hierarchy determines what to verify against and in what order.

```
LEADING (6-18 months ahead)     COINCIDENT              LAGGING (confirming)
─────────────────────────────   ────────────            ───────────────────
Yield Curve (10Y-2Y)            GDP                     Unemployment Rate
Credit Spreads (HY)             Industrial Production   CPI (headline)
PMI New Orders                  Personal Income         Labor Costs
Building Permits                Manufacturing Sales     Commercial Loans
Stock Prices (S&P 500)          Retail Sales            Prime Rate
Consumer Expectations                                   
BDI (Baltic Dry Index)                                  
Copper Prices                                           
M2 Money Supply                                         
```

### 4.2 Detailed Lead-Lag Chains

#### Bond Yields → Fed Decisions (LEADING, ~6-12 months)

Research by Seip & Zhang (2022), covering 1977-2019:
- Fed funds rate leads GDP ~63% of the time
- The yield curve (10Y-2Y spread) is the "leading-est of leading indicators" — added to Conference Board LEI in 1996
- Yield curve inversion typically signals recession 12-18 months in advance
- **Critical insight**: The bond market often "leads" the Fed — long-term yields begin falling before the Fed cuts, as markets price in future policy
- In 2024-2025: Fed cut short-term rates but 10-year yields rose ~60bps — bond market's longer-term outlook diverging from Fed actions

**Verification application**: When news claims "Fed will cut rates," check whether bond yields have already priced this in. If they have, the news is stale.

#### PMI → GDP (LEADING, 1-3 quarters)

- PMI is a leading indicator; GDP is coincident
- PMI year-over-year correlates with GDP at ~0.88 (2005-present, China data)
- **Internal lead-lag within PMI**: New Orders leads Production leads Employment
- **New Orders minus Inventories spread**: Premier leading sub-indicator within PMI
- The Fed's FCI-G (Financial Conditions Impulse on Growth) often leads ISM Manufacturing PMI — financial conditions tighten/loosen before PMI responds

**Verification application**: When news claims "economy slowing," verify by checking if PMI New Orders has been declining for 1-3 months. If PMI is still strong, the claim is premature.

#### High-Yield Spreads → Equity Drawdowns (LEADING, 9-12 months)

One of the most reliable leading indicators in financial markets:

- Credit markets are more sensitive to economic shocks than equity markets
- HY spreads typically widen 9-12 months before equities price in the same distress
- **Historical evidence**: HY spreads successfully anticipated every U.S. recession since the 1970s
- **Threshold alert**: Sustained widening of 300+ bps from cycle lows = strong recession/market correction signal
- **Recovery sequence**: Credit markets bottom and recover BEFORE equities during recessions

**Key events**:
| Event | HY Spread Behavior | Equity Outcome |
|---|---|---|
| 2000 Dot-Com | Spreads widened early 2000 | Nasdaq/S&P declined later |
| 2007-08 GFC | Spreads widened by mid-2007 | S&P crash fully materialized 2008 |
| 2020 COVID | Spreads soared early 2020 | S&P crashed ~34% March 2020 |
| 2022 Bear Market | Sharp spread widening | S&P fell ~24% |

**Verification application**: When news claims "market selloff coming," verify by checking HY spreads. If spreads are narrow and stable, the claim is not yet credit-market-confirmed.

#### Baltic Dry Index → Global Trade/Commodities (LEADING, weeks-months)

- BDI tracks shipping rates for dry bulk commodities (iron ore, coal, grain) across 50+ global routes
- Considered an "early warning system" for global economic activity
- BDI leads commodity prices (iron ore, copper) — BDI turns before industrial metals
- Heavily influenced by Chinese demand cycles (China is the world's largest dry bulk commodity importer)
- BDI is a proxy leading indicator for Chinese economic momentum

#### Copper ("Dr. Copper") → Chinese Economic Activity (LEADING, 3-5 months)

- Copper's correlation strongest with China + Europe M2 growth (r=0.48) and China + US industrial production (r=0.70)
- Copper leads PPI by 3-5 months, thus leading bond market reflation pricing
- **Copper/Gold ratio** historically tight correlation with US 10-year yields
- When copper/gold and yields diverge, yields tend to "catch up" to copper signal
- Copper peaks before oil by 2-9 months

**Verification application**: When news claims "China economy recovering," verify copper prices. Rising copper + rising BDI = confirmation. Rising copper + falling BDI = mixed signal, reduce confidence.

### 4.3 The Causal Chain (Simplified)

```
Chinese Credit Impulse (+18mo lead)
        │
        ▼
Baltic Dry Index (weeks-months lead)
        │
        ▼
Copper Prices (3-5mo lead to PPI)
        │
        ▼
PMI New Orders (1-3q lead to GDP)
        │
        ▼
Bond Yields (6-12mo lead to Fed)
        │
        ▼
Fed Policy Rate (reacts, then feeds back)
        │
        ▼
GDP (coincident) → Unemployment (lagging)
```

### 4.4 Summary Lead-Lag Table for Verification Pipeline

| Claim Type | Check This Indicator First | Expected Lead | Confidence Boost If |
|---|---|---|---|
| "Fed will cut/hike" | Bond yields (2Y, 10Y), Fed Funds futures | 6-12 months | Yields already moving in direction implied by claim |
| "Recession coming" | Yield curve (10Y-2Y), HY spreads | 12-18 months | Both inverted/yielding + widening |
| "Economy slowing" | PMI New Orders | 1-3 quarters | New Orders declining for 2+ months |
| "Market correction" | HY credit spreads | 9-12 months | Spreads widening beyond 300bps from lows |
| "China recovering" | Copper, BDI | 3-5 months (Cu), weeks (BDI) | Both rising in tandem |
| "Commodities rally" | BDI, China credit impulse | 18 months (credit), weeks (BDI) | BDI rising, credit expanding |
| "Inflation rising" | Copper, breakeven rates, PPI | 3-5 months | Copper and breakevens both rising |
| "Earnings beat" | PMI Production, ISM Employment | 1-3 months | PMI components trending up |

### 4.5 Caveats

1. **Divergences happen**: Copper/gold ratio and 10Y yields have diverged for extended periods (2017, 2020, 2024). When they diverge, it may signal a regime change.
2. **China structural shift**: China's move from manufacturing-led to services-led growth has altered reliability of commodity-linked leading indicators.
3. **Supply-side distortions**: Ship oversupply (BDI), tariff-driven input prices (PMI), stockpile effects (copper) can temporarily break lead-lag relationships.
4. **Financial conditions indices**: The Fed's FCI-G now provides more sophisticated composite leading signals incorporating multiple variables.

---

## 5. Confidence Scoring

### 5.1 The Altss Confidence Scoring Framework

The most comprehensive published framework for institutional investment thesis confidence scoring is the **Altss Taxonomy**, used by endowments, pensions, and fund-of-funds for evidence-based allocation decisions.

#### Core Components

| Component | Description |
|---|---|
| **Signal taxonomy** | Clear definitions of what signal classes exist |
| **Evidence requirements** | What proof is needed for each signal class |
| **Weight calibration** | Weights grounded in historical outcomes, not preference |
| **Time decay** | Older signals lose strength unless refreshed |
| **Bias controls** | Preventing relationship bias from overpowering evidence |
| **Auditability** | Ability to explain why a score changed |

The framework explicitly separates:
- **Confidence** (likelihood) from **Value** (position size) from **Timing** (when)
- Tracks uncertainty as "a score plus the evidence that supports it"

### 5.2 Evidence Weighting — "Preponderance of Evidence"

This is where the "preponderance of evidence" concept is operationalized:

**Source trust tiering**:
- **Primary**: Official filings (SEC EDGAR), direct confirmation, exchange data
- **Secondary**: Major wires (Bloomberg, Reuters), established research firms
- **Tertiary**: Self-reported, social media, unverified sources

**Corroboration rules**:
- Multiple independent sources increase confidence (the "preponderance" test)
- Conflicting sources reduce confidence proportionally
- Consensus detection: when 3+ independent sources agree, confidence shifts non-linearly upward
- Discrepancy flagging: when equally credible sources disagree, flag for human review

**Other evidence factors**:
- **Recency weighting**: Decay curves with explicit "as-of" dates
- **Specificity scoring**: Precise claims ("Fed will cut 25bps in June") beat vague statements ("Fed likely to ease")
- **Conflict resolution**: Precedence and tie-breaker logic

### 5.3 Confidence Score Calculation

A proposed scoring formula adapted from the Altss framework:

```
Confidence = f(
    verification_layers_passed,  # how many of the 4 layers confirmed
    source_trust_tier,            # primary > secondary > tertiary
    source_count,                 # number of independent confirming sources
    evidence_recency,             # time decay factor
    consistency_score,            # agreement among sources
    market_confirmation,          # did related markets confirm?
    historical_pattern_match      # has this pattern been predictive before?
)
```

**Proposed scoring tiers**:

| Score | Name | Criteria | Action |
|---|---|---|---|
| **0.9-1.0** | HIGH | 4/4 verification layers passed, 3+ primary sources, market confirmed, historical pattern matched | Full position size |
| **0.7-0.89** | MODERATE | 3/4 layers passed, 2+ independent sources, market directionally consistent | Reduced position size |
| **0.5-0.69** | LOW | 2/4 layers passed, at least 1 primary source, market not contradicting | Monitoring only |
| **0.3-0.49** | SPECULATIVE | 1/4 layers passed, single source, market ambiguous | Watchlist, no action |
| **0.0-0.29** | UNVERIFIED | No verification layers passed, single unverified source | Discard or flag for review |

### 5.4 Verification Layer Weights (Proposed)

Based on the relative reliability of each verification mechanism:

```
Layer 1 (Market Ground Truth):   30% weight  ← Hardest to fake; real-money bets
Layer 2 (Multi-Source Corroboration): 25%  ← Independent confirmation
Layer 3 (Market Data Validation): 25%   ← "News vs. Markets" divergence check
Layer 4 (Historical Pattern Match): 20% ← "Has this worked before?"
                                        ────
                                        100%
```

**Rationale**: Market ground truth (FedWatch, futures pricing) gets highest weight because it reflects actual capital allocation, not just words. Multi-source corroboration and market data validation are tied — they measure different dimensions (narrative consistency vs. price action consistency). Historical pattern match gets lowest weight due to non-stationarity risk.

### 5.5 Academic Underpinnings

**Budescu & Du (2007)** — "Coherence and Consistency of Investors' Probability Judgments" (Management Science):
- Investors' probability judgments are internally consistent but often miscalibrated
- Structured scoring frameworks outperform intuitive judgment

**Brenner et al.** — Random Support Theory:
- Models calibration using discriminability (alpha) and focal bias (beta) parameters
- Evidence strength maps to probability judgments in stock forecasting

**Harvey (via Advisor Perspectives)**:
- Evidence-based investing requires higher statistical significance thresholds due to p-hacking
- When many independent sources are tested, evidence must meet higher bars

### 5.6 The "How Many Independent Sources?" Question

**Bloomberg terminal analyst best practice**: 3-5 independent sources (wire + primary filing + sector outlet) before acting.

**Altss corroboration rule**: Multiple independent sources increase confidence non-linearly. The jump from 1 to 2 sources provides the largest marginal confidence gain. Diminishing returns after 5 sources.

**Recommended tier system**:
- 1 source: Unverified (cannot act)
- 2 sources: Tentative (monitoring only)
- 3 sources: Confirmed (can act with reduced size)
- 4+ sources: Strongly confirmed (full size if other layers pass)
- 5+ sources: Diminishing returns (information already priced in)

---

## 6. Synthesized Pipeline Architecture

### 6.1 End-to-End Data Flow

```
RAW NEWS INGEST
    │
    ▼
┌─────────────────────────────────────┐
│  STAGE 1: CLAIM EXTRACTION          │
│  ─────────────────────────          │
│  - LLM extracts atomic claims       │
│  - AFEV-style decomposition         │
│  - Assigns event type labels        │
│  - Assigns affected tickers/assets  │
│  - Records source + timestamp       │
├─────────────────────────────────────┤
│  Output: [{claim, type, tickers,    │
│            source, timestamp}]       │
└─────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────┐
│  STAGE 2: VERIFICATION LAYER 1      │
│  Market Ground Truth                │
│  ─────────────────────              │
│  - Rate claims → CME FedWatch       │
│  - Commodity claims → futures curve │
│  - Macro claims → bond yields       │
│  - Event risk → options implied vol │
│  - FX claims → forward curve        │
├─────────────────────────────────────┤
│  Output: {claim, market_confirm,    │
│           divergence_flag, score_l1}│
└─────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────┐
│  STAGE 3: VERIFICATION LAYER 2      │
│  Multi-Source Corroboration         │
│  ──────────────────────────         │
│  - Search 3+ independent sources    │
│  - Cross-reference same event       │
│  - FinVet-style fact-checking       │
│  - Score source trust tier          │
│  - Flag conflicting narratives      │
├─────────────────────────────────────┤
│  Output: {claim, sources_found,     │
│           consensus_score, score_l2}│
└─────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────┐
│  STAGE 4: VERIFICATION LAYER 3      │
│  Market Data Validation             │
│  ──────────────────────             │
│  - Check lead-lag indicators        │
│  - "News vs. Markets" divergence    │
│  - Credit spread check              │
│  - Bond yield check                 │
│  - Commodity signal check           │
│  - Cross-asset confirmation         │
├─────────────────────────────────────┤
│  Output: {claim, market_direction,  │
│           divergence_signal,        │
│           lead_lag_check, score_l3} │
└─────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────┐
│  STAGE 5: VERIFICATION LAYER 4      │
│  Historical Pattern Match           │
│  ────────────────────────           │
│  - RAG over historical claims DB    │
│  - Pattern similarity scoring       │
│  - Outcome distribution lookup      │
│  - Regime similarity check          │
├─────────────────────────────────────┤
│  Output: {claim, similar_patterns,  │
│           historical_accuracy,      │
│           regime_match, score_l4}   │
└─────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────┐
│  STAGE 6: CONFIDENCE SCORING        │
│  ─────────────────────────         │
│  - Weighted aggregation L1-L4       │
│  - Time decay factor applied        │
│  - Source trust factor applied      │
│  - Corroboration bonus/malus        │
│  - Divergence penalty               │
├─────────────────────────────────────┤
│  Output: {claim, confidence_score,  │
│           confidence_tier,          │
│           evidence_trail,           │
│           recommended_action}       │
└─────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────┐
│  STAGE 7: SIGNAL FUSION             │
│  ────────────────────               │
│  - Kalman filter for time alignment │
│  - Bayesian ensemble weighting      │
│  - Cross-signal synergy detection   │
│  - Position sizing from confidence  │
├─────────────────────────────────────┤
│  Output: [{signal, direction,       │
│            size, confidence,         │
│            evidence_summary}]        │
└─────────────────────────────────────┘
```

### 6.2 Key Design Decisions

1. **Atomic claim decomposition first**: Don't verify the entire article; decompose into atomic claims and verify each independently. A single article may contain 1 true claim and 1 false claim — they must be scored separately.

2. **Market ground truth has primacy**: Layer 1 verification (FedWatch, futures, options) is the hardest to fake because it reflects real capital allocation. It gets the highest weight (30%).

3. **Lead-lag indicators as verification, not prediction**: The primary use of lead-lag relationships in this pipeline is to validate or refute claims, not to generate original forecasts.

4. **Confidence scoring is calibrated, not heuristical**: Scores are based on how many independent verification layers a claim passes, weighted by the reliability of each layer. The threshold to act (0.7+) means at least 2 layers must confirm.

5. **Divergence is a signal, not a failure**: When news claims and market data diverge, that is itself a signal — it may indicate market skepticism, an information asymmetry, or a regime change.

6. **Online learning**: The historical pattern match (Layer 4) should continuously update as new outcomes are observed, improving calibration over time.

### 6.3 Technology Stack Recommendations

| Stage | Technology |
|---|---|
| Claim Extraction | LLM with few-shot prompting (FinBERT, GPT-4, Claude) |
| Layer 1 (Market Truth) | CME FedWatch API, futures data (Bloomberg/Yahoo), options chain data |
| Layer 2 (Corroboration) | NewsAPI, GDELT, Mediastack, web search RAG |
| Layer 3 (Market Validation) | Bond yield data, credit spread data, commodity prices, FX rates |
| Layer 4 (Historical Pattern) | Vector DB (Chroma/Pinecone), claims database (PostgreSQL) |
| Confidence Scoring | Weighted scoring engine (Python) |
| Signal Fusion | Kalman filter (filterpy), Bayesian ensemble (PyMC, scikit-learn) |
| Orchestration | Temporal workflow engine (Temporal.io, Prefect, Airflow) |

### 6.4 Anti-Patterns to Avoid

1. **Verifying the headline, not the atomic claims**: A headline "Fed likely to cut rates as economy slows" contains TWO claims — (a) Fed will cut rates, (b) economy is slowing. Each needs independent verification.

2. **Equal-weighting all sources**: A primary SEC filing and a Twitter rumor are not equal evidence. Source trust tiering is mandatory.

3. **Ignoring time decay**: A verified claim from 3 weeks ago is no longer verified. Explicit time decay in scoring.

4. **Acting on single-source claims**: No matter how credible the source, a single-source claim should never trigger action. Minimum 2 independent sources.

5. **Fusing signals without time-alignment**: News sentiment (daily), market data (intraday), and macro indicators (weekly/monthly) arrive at different frequencies. Kalman filter or equivalent time-alignment is required before fusion.

6. **Static confidence thresholds**: Confidence thresholds should be calibrated against historical outcomes and updated periodically.

---

## Sources

### News → Signal Extraction
- [Janus-Q: End-to-End Event-Driven Trading via Hierarchical-Gated Reward Modeling](https://arxiv.org/abs/2602.19919v2)
- [NEXUS: A multi-modal framework for capturing financial news interactions in market forecasting](https://www.sciencedirect.com/science/article/abs/pii/S0957417426013242)
- [Event-Aware Sentiment Factors from LLM-Augmented Financial Tweets](https://arxiv.org/html/2508.07408v1)
- [LLM-enhanced multi-causal event causality mining in financial texts](https://link.springer.com/article/10.1007/s44443-025-00330-w)
- [BlackRock: The macro decoder — using LLMs to read the world's economic narrative](https://www.blackrock.com/institutions/en-us/insights/thought-leadership/investment-actions/macro-decoder)
- [Using ChatGPT to Generate NLP-Driven Investment Strategies - CFA Institute](https://blogs.cfainstitute.org/investor/2025/01/07/using-chatgpt-to-generate-nlp-driven-investment-strategies/)

### Data Verification Chains
- [CME FedWatch Tool Methodology](https://beta.cmegroup.com/articles/2023/understanding-the-cme-group-fedwatch-tool-methodology.html)
- [FinVet: RAG and External Fact-Checking Agents for Financial Misinformation](https://arxiv.org/html/2510.11654v1)
- [Fact Check: Analyzing Financial Events from Multilingual News Sources](https://ar5iv.labs.arxiv.org/html/2106.15221)
- [Multi-Source News Validation and Fact-Checking - ApudFlow](https://apudflow.com/articles/multi-source-news-validation/)
- [AFEV: Atomic Fact Extraction and Verification](https://www.sciencedirect.com/science/article/abs/pii/S0957417425041879)
- [Hybrid Fact-Checking: KG + LLM + Search](https://browse-export.arxiv.org/abs/2511.03217)
- [DEFAME: Dynamic Evidence-based Fact-checking with Multimodal Experts](https://proceedings.mlr.press/v267/braun25b.html)
- [SeQwen: Sequential Financial Claim Verification](https://arxiv-org.ezproxy.obspm.fr/html/2412.00549v1)
- [How News Move Markets - Quantpedia](https://ibkrcampus.com/campus/ibkr-quant-news/quantpedia-how-news-move-markets/)
- [News Sentiment and Bonds - Alpha Architect](https://alphaarchitect.com/news-sentiment-and-bonds/)

### Multi-Source Signal Fusion
- [MSIF-OEM: Multi-Source Information Fusion and Online Ensemble Modeling](https://www.sciencedirect.com/science/article/abs/pii/S095741742504151X)
- [Stacking-Bagging-Vote with Kalman Filter - JCA](http://www.joca.cn/CN/Y2022/V42/I1/280)
- [E-3T: Heterogeneous Ensemble Method with Temporal Transformers](https://ojs.revistagesec.org.br/secretariado/article/view/5361)
- [ReGEN-TAD: Interpretable Ensemble for Anomaly Detection](https://ar5iv.labs.arxiv.org/html/2603.07864)
- [UKF-NARX: Ensemble Kalman Filter + Bayesian Neural Network](https://rd.springer.com/chapter/10.1007/978-3-319-13817-6_8)
- [Multi-Horizon Trading Signal System Using Alternative Data](https://rstudio-pubs-static.s3.amazonaws.com/1366254_0f2efe5e5ed145788d8b810f317eb007.html)
- [Hybrid GenAI + ML for Alternative Data Signal Detection](https://jisem-journal.com/index.php/journal/article/view/13330)
- [CEEMDAN + Boosting Ensemble with MCS Selection](https://www.sciencedirect.com/science/article/pii/S2667305323000273)

### Lead-Lag Relationships
- [The GDP, US Treasury Yield, and Federal Funds Rate: who follows whom - Seip & Zhang 2022](https://www.sciencedirect.com/org/science/article/abs/pii/S1757638521000493)
- [Credit Spreads: The Canary in the Coalmine for Markets - Investing.com](https://za.investing.com/analysis/credit-spreads-the-canary-in-the-coalmine-for-markets-200610156)
- [Yield Spreads Suggest The Risk Isn't Over Yet - Advisor Perspectives](https://www.advisorperspectives.com/commentaries/2025/04/14/yield-spreads-risk-isnt-over)
- [Has the credit versus equities recession playbook changed? - Schroders](https://www.schroders.com/en-us/us/non-resident-clients/insights/has-the-credit-versus-equities-recession-playbook-changed-/)
- [Copper / Gold Ratio Screaming - Ainslie Bullion](https://ainsliebullion.com.au/News-Resources/Article/Copper-Gold-Ratio-Screaming/ID/4217)
- [BDI暴跌与中国经济](http://csoa.cn/doc/6047.jsp)
- [Shipping gauge shows iron ore, copper prices heading for fall - Mining.com](https://www.mining.com/shipping-gauge-shows-iron-ore-copper-prices-heading-fall)
- [Copper > 5 = Yields > 5 - All Star Charts](https://www.allstarcharts.com/supercycle-report/2025-10-09/copper-5-yields-5)
- [Credit Spreads - RiskBridge Advisors](https://www.riskbridgeadvisors.com/2025/03/17/spreads/)

### Confidence Scoring
- [Confidence Scoring Framework - Altss Taxonomy](https://altss.com/taxonomy/confidence-scoring-framework)
- [Evidence Weighting - Altss Taxonomy](https://altss.com/taxonomy/evidence-weighting)
- [Source Confidence - Altss Glossary](https://altss.com/glossary/source-confidence)
- [Coherence and Consistency of Investors' Probability Judgments - Budescu & Du 2007](https://econpapers.repec.org/article/inmormnsc/v_3a53_3ay_3a2007_3ai_3a11_3ap_3a1731-1744.htm)
- [Evidence Based Investing is Dead. Long Live Evidence Based Investing! - Advisor Perspectives](https://www.advisorperspectives.com/articles/2017/10/02/part-2-evidence-based-investing-is-dead-long-live-evidence-based-investing)

### Professional Workflows
- [Bloomberg Launches AI-Powered Research Tool for Terminal Users - A-Team](https://a-teaminsight.com/blog/bloomberg-launches-ai-powered-research-tool-for-terminal-users/)
- [Bloomberg Terminal gains conversational AI interface - The DESK](https://www.fi-desk.com/bloomberg-terminal-gains-conversational-ai-interface/)
- [Investors to Streamline Alpha-Generating Research with Bloomberg's Latest AI Offering](https://www.bloomberg.com/professional/insights/press-announcement/investors-to-streamline-alphagenerating-research-with-bloombergs-latest-ai-offering/)

---

**Research completed**: 2026-05-17  
**Next step**: Use these findings to design the Phase E Signal Verification Pipeline architecture
