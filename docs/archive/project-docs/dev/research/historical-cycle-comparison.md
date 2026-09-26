# Historical Cycle Comparison: Systematic Methods for Investment Analysis

**Written**: 2026-05-18
**Status**: Research complete
**Purpose**: Informing MarketMind's historical context layer -- methods for comparing current market conditions to historical analogues

---

## 1. Executive Summary

Financial markets do not follow a single, stable distribution. They oscillate between distinct "regimes" where means, volatilities, and correlations change abruptly. The goal of systematic historical comparison is to answer: "What past period does today most resemble, and what happened next?"

Across the literature, a clear direction emerges: the field is moving away from rigid, binary regime labels (e.g., "we are in a bear market") toward **continuous, distance-based measures of historical similarity** that produce probabilistic, rather than deterministic, forward-looking scenarios.

This document surveys five major approaches, their methodologies, their data requirements, and how each could be operationalized within MarketMind's pipeline.

---

## 2. Major Frameworks

### 2.1 Man Group / Mulliner-Harvey Regime Model (2025)

**Source**: Mulliner, Harvey, Xia & Fang, "Regimes, Systematic Models and the Power of Prediction," Man Group / Duke University, March 2025.
**Links**: [Man Group](https://www.man.com/insights/regimes-systematic-models-power-of-prediction) | [Alpha Architect coverage](https://alphaarchitect.com/regime-detection/)

**Methodology**:
- Uses **7 economic state variables**: S&P 500, yield curve slope (10Y-2Y), crude oil, copper, T-bill yields, equity volatility (VIX), stock-bond correlation
- Computes **Euclidean distance** between the current month's vector and every historical month's vector
- Identifies both "regimes" (most similar periods) and "anti-regimes" (least similar periods)
- Non-parametric -- no pre-defined regime categories; similarity is continuous, not binary
- Period: 1985-2024 monthly data

**Key findings**:
- Strategy going long during similar regimes and short during dissimilar ones produced alpha exceeding **3 standard deviations from zero**
- Sharpe ratio of 0.82
- Profitable in **80% of years**
- "Anti-regimes" carry independent predictive power -- contrarian positioning during dissimilar periods also works

**Operationalization for MarketMind**:
- Maintain a rolling vector of the same 7 variables (or a market-appropriate subset)
- On each analysis run, compute Euclidean distance to every month since ~1985
- Return top-N historical analogues with their subsequent 3/6/12-month forward returns
- Add "anti-regime" analysis: what happens when conditions are maximally dissimilar?

---

### 2.2 Verdad Capital -- Analogous Market Moments + GMM Regime Clustering (2024)

**Source**: Satterthwaite, Schatz & Laskov, Verdad Capital, June-August 2024.
**Links**: [Analogous Market Moments](https://verdadcap.com/archive/analogous-market-moments) | [Classifying Economic Regimes](https://verdadcap.com/archive/classifying-economic-regimes) | [On the Brink](https://verdadcap.com/archive/on-the-brink)

**Methodology**:
- **Part 1 -- Analogue search**: Converts macro data at each point in time into a vector; uses Euclidean distance (L2 norm) to find historically similar moments
- Input signals: high-yield spreads, inflation, stock-bond correlation, yield curve, and other predictive data
- **Part 2 -- Regime clustering**: Applies **Gaussian Mixture Model (GMM)** to daily macroeconomic data (1962-2024) to group periods into regimes

**Four distinct regimes identified**:
| Regime | Characteristics | Implication |
|--------|----------------|-------------|
| **Growth** | Moderate rates, upward-sloping curve, subdued vol | Risk-on: equities, credit |
| **Inflation** | High inflation, elevated rates, high bond vol | Commodities, TIPS, gold |
| **Precarious** | Compressed HY spreads, depressed vol, flat/inverted curve, rising stock-bond correlation | High fragility; small shocks can trigger crisis |
| **Crisis** | High risk aversion, significantly elevated volatility | Defensive: bonds, cash, gold |

**Key insight**: The June 2024 analogue search found the 8 closest historical periods were 2019, 2007, 2000, 1995, 1989, 1979, 1973, and 1969 -- 4 of which preceded major market crashes within 12 months. This represents the probabilistic nature of the approach.

**Operationalization for MarketMind**:
- Run a GMM classifier on MarketMind's macro data to assign each analysis day to one of four regimes
- Within the identified regime, run Euclidean-distance analogue search for more granular comparison
- Report: "Today's conditions are in the [X] regime, most similar to [date 1], [date 2], [date 3]"

---

### 2.3 Bridgewater / Ray Dalio -- Template-Based Historical Framework

**Source**: Dalio, *A Template for Understanding Big Debt Crises* (2018); Bridgewater Associates methodology.
**Links**: [Dalio: 500-year investment framework](https://www.mitrade.com/zh/insights/news/live-news/article-2-1619394-20260409) | [Dalio debt cycle interview](https://www.marketplace.org/story/2018/09/25/dalio-debt-cycle)

**Five interlocking frameworks**:

**(a) Dual Debt Cycles**:
- Short-term (5-8 years): Standard business credit cycle
- Long-term (50-75 years): Debt/GDP ratchets upward each short cycle until monetary policy space is exhausted
- Key dashboard: Debt/GDP ratio, interest expense/government revenue, real interest rates

**(b) Four Economic Seasons** (growth direction x inflation direction):
| Season | Growth | Inflation | Best Assets | Worst Assets |
|--------|--------|-----------|-------------|--------------|
| Spring | Up | Down | Equities | Commodities |
| Summer | Up | Up | Commodities, TIPS | Long bonds |
| Autumn | Down | Up | Gold, real assets | Equities, long bonds |
| Winter | Down | Down | Long bonds, cash | Commodities |

**(c) All-Weather Portfolio**: Risk-parity across 30% stocks / 40% long bonds / 15% intermediate bonds / 7.5% gold / 7.5% commodities, designed to survive all seasons without requiring correct regime timing.

**(d) World Order Cycle**: 500-year study of major empire rise/decline. Pattern: reserve currency dominance -> overreach -> debt accumulation -> money printing -> shift from financial to real assets (gold).

**(e) Six-Stage Debt Crisis Template**: Early cycle -> Bubble -> Top -> Depression -> Deleveraging -> Normalization. "Beautiful deleveraging" balances austerity, money printing, debt restructuring, and wealth redistribution.

**Operationalization for MarketMind**:
- Categorize current conditions into Dalio's four-season quadrant (a simple 2x2: growth x inflation direction)
- Maintain a debt-cycle dashboard: debt/GDP, interest/revenue ratio, real rates
- When "Autumn" or "Winter" signals fire, trigger a gold/real-asset comparison against historical gold bull markets
- The four-season framework is the simplest to implement -- it requires only growth and inflation trend signals

---

### 2.4 Reinhart & Rogoff -- Crisis Taxonomy & Benchmark Trajectories (2009)

**Source**: Reinhart & Rogoff, *This Time Is Different: Eight Centuries of Financial Folly*, Princeton University Press, 2009.
**Link**: [Rogoff research summary](https://rogoff.scholars.harvard.edu/research-summary)

**Methodology**:
- Database: ~800 years, 66 countries, covering sovereign debt, banking, inflation, and currency crises
- Crisis identification via quantitative thresholds + historical narrative
- **Prototypical crisis sequence**: Excessive debt -> asset price inflation -> "this time is different" syndrome -> confidence collapse -> banking crisis -> sovereign debt explosion (+86% on average in 3 years) -> protracted recovery (unemployment elevated 4-5 years)

**Benchmark post-crisis trajectories** (the quantitative heart of the framework):
| Variable | Magnitude | Duration |
|----------|-----------|----------|
| Housing price decline | ~35% (peak-to-trough) | ~6 years |
| Equity price decline | ~55% | ~3.5 years |
| Unemployment rise | ~7 pp | ~4 years |
| Government debt increase | ~86% | 3 years |
| Output decline | varies | ~2 years |

**Key contribution**: The "this time is different" syndrome -- the pervasive belief that "old rules no longer apply" during booms -- is the primary mechanism that blinds investors to historical patterns. The framework quantifies the consequences.

**Operationalization for MarketMind**:
- Build a "crisis proximity" indicator comparing current debt levels, asset price run-ups, and credit expansion to pre-crisis benchmarks
- When multiple indicators breach pre-crisis thresholds, flag elevated historical risk
- Use post-crisis trajectories as a "what if" scenario generator: "If this is a banking crisis analogue, housing would be expected to decline ~35% over 6 years"

---

### 2.5 State Street / Kritzman et al. -- Mahalanobis Distance Relevance Weighting (2023)

**Source**: Kritzman, Page & Turkington, "Portfolio Construction When Regimes Are Ambiguous," State Street Associates, November 2023.
**Link**: [State Street research](https://globalmarkets.statestreet.com/research/portal/insights/article/b79d4877-dcdb-4186-9011-26861aa9bbfe)

**Methodology**:
- Argues regime labels are **not binary yes/no answers** but are inherently ambiguous
- Uses **Mahalanobis distance** (which accounts for correlations between variables, unlike Euclidean) to measure statistical relevance of past periods
- Expected risk and return are computed as **weighted averages** of the relevant past, where weights decay with distance
- All historical periods contribute, but more similar periods contribute more weight

**Key advantage over Euclidean distance**: Mahalanobis distance accounts for the fact that a 1-standard-deviation move in the yield curve may be far less common than a 1-standard-deviation move in inflation, and adjusts the distance metric accordingly.

**Operationalization for MarketMind**:
- Implement Mahalanobis distance as an improvement over simple Euclidean matching
- Weight historical outcomes by relevance rather than treating the top-N analogues as a discrete set
- Report: "Weighted forward return (all history, relevance-weighted): +X% over next 12 months"

---

### 2.6 FactSet / S&P DJI -- 4-Quadrant Growth-Inflation Regime Map

**Source**: FactSet Research; S&P Dow Jones Indices.
**Links**: [FactSet: Mapping Asset Returns to Economic Regimes](https://insight.factset.com/mapping-asset-returns-to-economic-regimes-a-practical-investors-guide) | [S&P: Factor Performance Across Macroeconomic Cycles](https://www.spglobal.com/spdji/en/education/article/a-historical-perspective-on-factor-index-performance-across-macroeconomic-cycles/)

**Methodology**:
- Two signals: OECD Composite Leading Indicator (CLI) for growth direction, CPI trend for inflation direction
- Regimes: Growing (growth up, inflation down), Heating (up/up), Slowing (down/up), Stagflation (down/down)
- Regimes persist for a minimum of three months to filter noise
- Maps asset-class performance across each regime using data from 1958-2025

**Key findings**: Asset-class returns are strongly regime-dependent, validating the premise that regime-aware allocation materially outperforms static allocation.

**Operationalization for MarketMind**: Straightforward to implement -- requires only CLI and CPI data. Can provide a "current regime" label with historical asset-class return distributions for the same regime.

---

## 3. Regime Detection Models: Technical Approaches

### 3.1 Markov-Switching Models (the workhorse)

**Key references**: Hamilton (1988); Kritzman, Page & Turkington (2012, *Financial Analysts Journal*); O'Sullivan (2022, Maynooth University PhD thesis).

**How it works**: An unobserved regime variable follows a first-order Markov process. Each regime has its own mean, variance, and correlation structure. The model estimates transition probabilities between regimes.

**Empirical performance** (Kupelian, Stevens Institute / BofA Merrill Lynch):
| Method | Sharpe Ratio | Max Drawdown |
|--------|:---:|:---:|
| 60/40 Static | 0.24 | 32.2% |
| MSM Regime MV | 0.71 | 1.45% |
| MPC + MSM | 0.71 | 1.36% |

**Key practitioner insight** (Goodarzi & Meinerding, 2023, Bundesbank): Models trained on **macroeconomic data** (not asset returns) produce more robust, investable allocations, especially after extreme events. Models trained on return data tend to identify "extreme" regimes after crises, leading to excessive hedging demands.

**Python libraries**: `hmmlearn` (GaussianHMM, GMMHMM), `pomegranate`, `statsmodels` (MarkovAutoregression). Note: `hmmlearn` has compatibility issues with numpy >= 2.0; pin `numpy==1.26.4`.

**Open-source implementations**: [Sakeeb91/market-regime-detection](https://github.com/Sakeeb91/market-regime-detection) (HMM + GMM + change-point detection + walk-forward validation); [tobemo/Rolling-Regime-Detection](https://github.com/tobemo/Rolling-Regime-Detection) (rolling HMM with adaptive state count).

### 3.2 Gaussian Mixture Models (unsupervised clustering)

**Key reference**: Verdad Capital (2024); Wang (2025, Yale).

**How it works**: Fits a mixture of multivariate Gaussian distributions to macro/return data. Each component is a "regime." Unlike HMM, GMM does not model temporal persistence -- each observation is assumed independent. This is both a limitation (no regime momentum) and a feature (no lookahead bias from transition probabilities).

### 3.3 Change-Point Detection + Hierarchical Clustering

**Key reference**: Bucci & Ciciretti (2022, *Economic Modelling*); Mulliner et al. (2025).

**How it works**: Bayesian Online Change-Point Detection (BOCPD) identifies structural breaks in time series. Hierarchical clustering then groups pre- and post-break periods into regime families. Among variance-switching methods, hierarchical clustering achieved the highest regime detection accuracy in head-to-head tests.

**Python libraries**: `ruptures` (offline change-point detection), `bocd` (Bayesian online), `tsmoothie` (smoothing + change detection).

### 3.4 Machine Learning Classifiers

**Key reference**: Hinterlang & Hollmayr (2021/2022), Bundesbank.

**How it works**: Train classifiers (AdaBoost, random forest, XGBoost) on **simulated data** from Markov-switching DSGE models. The classifier learns to map observable macro variables to unobservable regime states.

**Finding**: AdaBoost achieved ~90% accuracy vs. logistic regression at ~53%. The approach is novel because it uses DSGE simulations (not historical data) as training data, sidestepping the small-sample problem in macro regime classification.

### 3.5 Multiplicative Indicator Saturation (MIS)

**Key reference**: SSRN working paper (2024), applied to Taylor Rule regimes.

**How it works**: Allows **any parameter to vary individually at any point in time**. Unlike Markov-switching (where all parameters shift simultaneously), MIS permits individual parameters (e.g., inflation coefficient in a Taylor rule) to shift independently. Detects regime changes at a granular, parameter-by-parameter level.

---

## 4. "This Time Is Different" vs. "History Rhymes": The Core Tension

The phrase "this time is different" originates from Reinhart & Rogoff (2009) and describes the **syndrome** -- the pervasive belief during booms that "old rules of valuation no longer apply." The tension between this syndrome and the aphorism "history rhymes but never repeats" defines the analytical challenge.

### Framework for distinguishing "different" from "rhyming":

| Signal | Suggests "History Rhymes" | Suggests "This Time Is Different" |
|--------|---------------------------|----------------------------------|
| **Structural drivers** | Debt/GDP, credit growth, asset price inflation follow historical pre-crisis patterns | New technology, new policy framework, or new market structure with no precedent |
| **Correlation structure** | Asset-class correlations match a known regime | Correlations break down (e.g., stock-bond correlation flips sign unexpectedly) |
| **Policy response** | Central bank reaction function is consistent with historical analogues | Policy framework has changed (e.g., QE, yield curve control, MMT) |
| **Volatility regime** | VIX term structure matches historical analogues | Volatility behavior has no close historical match |
| **Similarity distance** | Euclidean/Mahalanobis distance to some historical period is low | Minimum distance to all historical periods is high (>2 SD above mean) |

**Operationalizing the distinction**: If the minimum historical distance (across all variables) is below a calibrated threshold, the system reports "regime identified: most similar to [period]" with probabilistic forward scenarios. If the distance exceeds the threshold (i.e., no close analogues exist), the system reports "no close historical analogue -- this time may be different" and flags elevated uncertainty.

---

## 5. Data Sources & Tools for Implementation

### 5.1 Macro Data APIs

| Source | Coverage | Key Series | Python Access |
|--------|----------|------------|---------------|
| **FRED** (Federal Reserve) | US macro, 1950s-present | GDP, CPI, unemployment, yield curve, industrial production, LEI, credit spreads | `fredapi`, `pandas-datareader`, `tcs-macro-pulse` |
| **World Bank API** | Global, 1960-present | GDP, inflation, debt/GDP by country | `wbgapi` |
| **OECD Data** | OECD countries, 1960-present | Composite Leading Indicator (CLI), CPI | `pandas-datareader` |
| **BIS Statistics** | Global, 1970s-present | Credit-to-GDP gaps, debt service ratios | Direct download + pandas |
| **yfinance** | Market prices, 1950s-present (varies) | S&P 500, VIX, sector ETFs, bond ETFs | `yfinance` |

### 5.2 Open-Source Python Tools

| Tool | Purpose | Link |
|------|---------|------|
| **hmmlearn** | Gaussian HMM for regime classification | `pip install hmmlearn` |
| **pomegranate** | Probabilistic models including HMM, GMM, Bayesian networks | `pip install pomegranate` |
| **ruptures** | Offline change-point detection (PELT, BinSeg, etc.) | `pip install ruptures` |
| **scikit-learn** | GaussianMixture, KMeans, DBSCAN for clustering-based regime detection | `pip install scikit-learn` |
| **MacroTrace** | Vintage-aware FRED data (revision history, "as of" queries) | [github.com/john-ramsey/macrotrace](https://github.com/john-ramsey/macrotrace) |
| **AutoRegime** | One-liner HMM/BOCPD regime detection with 6 regime labels | [github.com/KANYINSOLA-OGUNBANJO/-AutoRegime](https://github.com/KANYINSOLA-OGUNBANJO/-AutoRegime) |
| **market-regime-detection** | Full HMM + GMM + walk-forward + backtesting framework | [github.com/Sakeeb91/market-regime-detection](https://github.com/Sakeeb91/market-regime-detection) |
| **Market-Cycle-Predictor** | YAML-config-driven ML pipeline with FRED data | [github.com/wookie76/Market-Cycle-Predictor-Python-FRED-yfinance](https://github.com/wookie76/Market-Cycle-Predictor-Python-FRED-yfinance) |

### 5.3 Key Macro Series for MarketMind's Regime Vector

A recommended minimum viable vector (inspired by Man Group + Verdad + Dalio):

| Variable | FRED Series | Why It Matters |
|----------|-------------|----------------|
| S&P 500 level (or log return) | `SP500` | Broad equity market |
| Yield curve slope | `T10Y2Y` (10Y - 2Y Treasury) | Recession probability, credit cycle position |
| Crude oil | `DCOILWTICO` (WTI) | Inflation input, global demand proxy |
| High-yield credit spread | `BAMLH0A0HYM2` | Risk appetite, credit cycle |
| VIX | `VIXCLS` | Fear gauge, volatility regime |
| CPI YoY | `CPIAUCSL` (compute YoY) | Inflation regime |
| Unemployment rate | `UNRATE` | Labor market, Sahm Rule input |
| Stock-bond correlation | Compute from SP500 + TLT returns (rolling 60-day) | Diversification regime |
| Real interest rate | `DFII10` (10Y TIPS yield) | Monetary stance, gold trigger |
| Fed Funds Rate | `DFEDTAR` / `DFF` | Policy rate position |

---

## 6. Operationalizing Historical Comparison in MarketMind

### 6.1 Architecture: The Historical Comparison Layer

MarketMind's current pipeline is event-driven (analyze news, detect themes, score impact). The historical comparison layer would be a **parallel pipeline** that:

1. **Maintains a regime vector** updated daily from FRED + market data
2. **Classifies current regime** using a lightweight GMM or 4-quadrant growth/inflation model
3. **Finds historical analogues** via Euclidean or Mahalanobis distance to all months since ~1960
4. **Produces a historical context report** that frames the current event analysis

### 6.2 Output Structure (proposed)

```
# Historical Context Report
## Current Regime
- Classification: [Growth / Inflation / Precarious / Crisis] (Verdad 4-regime)
- Dalio Season: [Spring / Summer / Autumn / Winter]
- Confidence: High / Medium / Low

## Closest Historical Analogues
1. [Month/Year] -- Euclidean distance: X.XX -- Forward 12m S&P 500: +Y%
2. [Month/Year] -- Euclidean distance: X.XX -- Forward 12m S&P 500: +Y%
3. [Month/Year] -- Euclidean distance: X.XX -- Forward 12m S&P 500: -Z%

## Weighted Forward Scenario (Mahalanobis-weighted, all history)
- 12-month equity return: central estimate +X%, range [A, B]
- 12-month bond return: central estimate +Y%, range [C, D]

## Regime-Specific Risk Flags
- Debt/GDP at levels historically associated with [crisis type]
- Yield curve inversion duration approaching [N] months (historical median before recession: ~12 months)
- Stock-bond correlation at [level] -- historically implies [diversification breakdown / normal hedging]

## Analogous Event Patterns
- [Event type X] in similar historical regimes typically preceded [outcome Y] within [timeframe]
- "This time is different" check: Minimum historical distance [Z] -- [above/below] 2-SD threshold
```

### 6.3 Implementation Roadmap (Phased)

**Phase 1 -- Minimal Viable Historical Context (2-4 weeks)**:
- Implement the 4-quadrant growth/inflation regime classifier (CLI + CPI)
- Compute Euclidean distance from current regime vector to historical months
- Return top-5 analogues with forward returns
- Wire into MarketMind's report generation as a new section

**Phase 2 -- Regime Clustering (2-4 weeks)**:
- Train GMM on 1960-present macro data for automated regime discovery
- Implement "this time is different" distance threshold
- Add Dalio four-season overlay
- Add crisis-proximity indicators (Reinhart-Rogoff benchmarks)

**Phase 3 -- Advanced Models (4-8 weeks)**:
- Implement HMM for probabilistic regime state estimation
- Add Mahalanobis distance weighting for all-period relevance
- Add anti-regime analysis (most dissimilar periods)
- Backtest regime-based allocation signals against benchmarks

### 6.4 Key Design Decisions

1. **Regime vector variables**: Start with the 10 key FRED series (Section 5.3). Add or remove based on signal contribution analysis.
2. **Distance metric**: Start with Euclidean (simpler, transparent). Upgrade to Mahalanobis in Phase 3.
3. **Historical window**: 1960-present (captures post-Bretton Woods floating-rate era, multiple cycles). Can extend with long-term historical data (Shiller data back to 1871).
4. **Update frequency**: Daily regime vectors; full re-clustering monthly (regime transitions are slow).
5. **Confidence calibration**: Report distance percentiles, not raw distances. "Today is closer to 2007 than 95% of all historical months" is more interpretable than "distance = 1.23."

---

## 7. Key Caveats & Limitations

1. **Regimes are identified in hindsight**: GMM and HMM use full-sample data to label historical regimes. Real-time regime identification is harder and noisier. Out-of-sample walk-forward validation is essential. Most published results use in-sample data.

2. **Stationarity cannot be assumed**: The underlying economic structure changes over time (e.g., the transition from manufacturing to services, the rise of passive investing, post-2008 QE). A "similar" inflation print in 1975 and 2025 may mean very different things for markets.

3. **Small-sample problem in macro**: There are only ~15 US recessions since WWII and ~3 long-term debt cycle peaks. Statistical significance for rare events is inherently limited. The methodology is probabilistic, not deterministic.

4. **Survivorship and data quality**: FRED data before ~1960 has spotty coverage, and some key series (VIX, HY spreads) only go back to the 1990s. Historical comparisons for pre-1990 regimes must use a reduced variable set.

5. **Analyst overrides matter**: The frameworks above are decision-support tools, not automated trading signals. The most sophisticated practitioners (Dalio, Verdad, Man Group) all emphasize model humility and human oversight.

---

## 8. Key Sources

- Mulliner, Harvey, Xia & Fang (2025), "Regimes, Systematic Models and the Power of Prediction," Man Group / Duke University. [Link](https://www.man.com/insights/regimes-systematic-models-power-of-prediction)
- Satterthwaite, Schatz & Laskov (2024), "Analogous Market Moments" and "Classifying Economic Regimes," Verdad Capital. [Link](https://verdadcap.com/archive/analogous-market-moments)
- Dalio, R. (2018), *A Template for Understanding Big Debt Crises*, Bridgewater Associates.
- Reinhart, C. & Rogoff, K. (2009), *This Time Is Different: Eight Centuries of Financial Folly*, Princeton University Press.
- Kritzman, Page & Turkington (2012), "Regime Shifts: Implications for Dynamic Strategies," *Financial Analysts Journal*. [Link](https://rpc.cfainstitute.org/research/financial-analysts-journal/2012/regime-shifts-implications-for-dynamic-strategies-corrected)
- Kritzman, Page & Turkington (2023), "Portfolio Construction When Regimes Are Ambiguous," State Street Associates. [Link](https://globalmarkets.statestreet.com/research/portal/insights/article/b79d4877-dcdb-4186-9011-26861aa9bbfe)
- O'Sullivan (2022), "Empirical Analysis of Regime-Focused Asset Allocation Strategies within a Markov Switching Framework," Maynooth University PhD thesis. [Link](https://mural.maynoothuniversity.ie/id/eprint/16915/)
- Goodarzi & Meinerding (2023), "Asset Allocation with Recursive Parameter Updating and Macroeconomic Regime Identifiers," Bundesbank.
- FactSet, "Mapping Asset Returns to Economic Regimes: A Practical Investor's Guide." [Link](https://insight.factset.com/mapping-asset-returns-to-economic-regimes-a-practical-investors-guide)
- S&P Dow Jones Indices, "A Historical Perspective on Factor Index Performance Across Macroeconomic Cycles." [Link](https://www.spglobal.com/spdji/en/education/article/a-historical-perspective-on-factor-index-performance-across-macroeconomic-cycles/)
- Cobham et al., "Monetary Policy Frameworks Since Bretton Woods," *Review of World Economics*. [Link](https://link.springer.com/article/10.1007/s10290-023-00517-1)
- Hinterlang & Hollmayr (2021), "Classification of Monetary and Fiscal Dominance Regimes Using Machine Learning Techniques," Bundesbank. [Link](https://www.sciencedirect.com/science/article/abs/pii/S0164070422000623)
- Wang (2025), "What Makes a Good Macro Regime? A Comparative Evaluation of Clustering-Based and Markov-Switching Models," Yale. [Link](https://csec.yale.edu/senior-essays/fall-2025/what-makes-good-macro-regime-comparative-evaluation-clustering-based-and)
