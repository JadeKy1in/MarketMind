# Balance Sheet Decomposition & Capital Flow Frameworks

**Compiled**: 2026-05-18 01:45 UTC
**Purpose**: Reference for upgrading MarketMind from surface-level sentiment analysis to deep structural macro analysis
**Status**: Research complete — ready for architecture integration

---

## 1. Fed Balance Sheet Decomposition (H.4.1 Report)

### Core Framework

The Fed's H.4.1 weekly release is the primary input for systematic balance sheet decomposition.

**Key decomposition methodology** (Fed FEDS Note, Feb 2026):

```
Delta log(SOMA/NGDP) = Delta log(SOMA) - Delta log(RealGDP) - Delta log(PriceLevel)
```

Three factors driving balance sheet reduction:
| Factor | Nature | Signal |
|--------|--------|--------|
| Active security runoff | Policy-driven (FOMC decisions) | Primary QT signal |
| Real GDP growth | Passive dilution (denominator growth) | Economic cycle indicator |
| Inflation (price level) | Passive dilution | Reduces real debt burden |

**Liability-side decomposition** (the actionable side for liquidity analysis):

| Component | ~% of Liabilities | Investment Signal |
|-----------|:---:|---|
| Currency in Circulation | ~29% | Stable; not a swing factor |
| ON RRP (RRPONTSYD) | 0-17% | Falling = liquidity entering markets |
| TGA (WTREGEN) | ~10% | Rising = draining reserves; Falling = injecting |
| Reserve Balances | ~42% | Core credit creation capacity |
| Other Deposits | ~2% | Foreign official, GSE deposits |

### PICA-Strategy Scorecard (for operationalization)

| Data Point | FRED Code | Frequency | Update |
|------------|-----------|-----------|--------|
| Fed Total Assets | WALCL | Weekly (Wed) | Thu 4:30pm ET |
| ON RRP Volume | RRPONTSYD | Daily | ~Next day |
| TGA Balance | WTREGEN | Weekly | Thu |
| Reserve Balances | WRBWFRBL | Weekly | Thu |
| SOMA Holdings | WSHOSHO | Weekly | Thu |

### Composite Liquidity Proxy

```
Net Liquidity = WALCL - RRPONTSYD - WTREGEN
```
- Expansion zone: Net Liquidity rising, RRPONTSYD falling faster than WALCL
- Contraction zone: Net Liquidity falling, TGA rising while RRP near zero
- Tipping point: RRPONTSYD ~0 + TGA rising + WALCL falling (reserves directly drained)

### Key Signal Thresholds

| Indicator | Signal |
|-----------|--------|
| Reserves/GDP > 10% | Abundant liquidity |
| Reserves/GDP 8-10% | Ample liquidity |
| Reserves/GDP < 8% | Possible funding stress |
| SOFR - ON RRP rate > 0.05% | Interbank funding stress |
| ON RRP near zero | Buffer exhausted; reserves directly exposed |

**Sources**:
- [Fed FEDS Note: A Decomposition of Balance Sheet Reduction](https://www.federalreserve.gov/econres/notes/feds-notes/a-decomposition-of-balance-sheet-reduction-20260202.html)
- [Fed H.4.1 Release](https://www.federalreserve.gov/releases/h41/)
- [NY Fed Liberty Street Economics: ON RRP and Balance Sheet Runoff](https://libertystreeteconomics.newyorkfed.org/2022/04/the-feds-balance-sheet-runoff-and-the-on-rrp-facility/)

---

## 2. Capital Flow & Entity-Level Tracking

### 2.1 TIC SLT: Cross-Border Flow Tracking

The Treasury International Capital (TIC) system is the authoritative source for tracking who is buying what across borders.

**Bertaut-Judson methodology** (Fed FEDS Notes, 2022/2023):

```
SLT Estimated Transactions = Delta(SLT Holdings) - Valuation Change - Other Changes
```

**Post-February 2023**: Expanded TIC SLT directly collects transactions data attributed to the country of the *ultimate buyer/seller*, eliminating the legacy "transactions bias" (a $1.5+ trillion discrepancy for official Treasury flows 2012-2020).

**Entity-Level Signals Extractable from TIC**:

| Entity Group | Security | Signal |
|---|---|---|
| Foreign Official (FOI) | U.S. Treasuries | Reserve diversification / dollar sentiment |
| Foreign Private | U.S. Equities | Risk appetite / flow momentum |
| Foreign Private | U.S. Corporates | Reach for yield |
| U.S. Investors | EM Bonds | Carry trade proxy |
| Caribbean Centers | All | Hedge fund positioning |

**Leading Indicator**: Duke University Plutonium Project (2002) found TIC net flow data predicted country equity returns with ~3-month lag.

**Data Lag**: ~6 weeks for monthly data; revisions up to 24 months. Not for tactical timing -- best for strategic/cyclical positioning.

### 2.2 Z.1 Flow of Funds: Sectoral Balances

The Fed's Z.1 "Financial Accounts of the United States" (quarterly) provides the macro identity:

```
(Private Sector Balance) + (Government Balance) + (Foreign Sector Balance) = 0
```

**Key Tables for Investment Analysis**:
- **F.4** — Saving and Investment by Sector (the sectoral balances identity)
- **D.1-D.3** — Credit Market Debt by instrument and sector
- **L.6** — Household Balance Sheets
- **IMAs** — Integrated Macroeconomic Accounts

**Signal Extraction**:
| Sector Shift | Implication |
|---|---|
| Gov't dissaving + private deleveraging | Fiscal support = risk asset tailwind |
| Private balance turning negative | Late-cycle warning (households borrowing heavily) |
| Foreign inflows shrinking | Dollar/Treasury yield implications |
| Corporate bond vs bank loan mix shift | Credit cycle turning point |

**Limitations**: ~10-week data lag; statistical discrepancies from NIPA aggregates; uses residence basis not nationality.

### 2.3 BIS Global Liquidity Indicators (GLIs)

Tracks international credit to non-bank borrowers in USD, EUR, JPY:

**Components**:
| Row | Component |
|---|---|
| 1 | Foreign currency credit to non-residents (USD/EUR/JPY) |
| 2 | Cross-border credit to residents in those currencies |
| 3 | Cross-border + local foreign currency credit (all other currencies) |

**Key Metric**: USD credit to non-banks outside the US (~$13.2 trillion as of Q4 2024).

**Three Phases** (BIS Quarterly Review, Dec 2023):
1. 2000-2009: Surging bank credit, USD/EUR loans to advanced economies
2. 2009-2021: Shift to bond markets, more dollar credit to EMEs
3. 2021-present: Potential contraction in foreign currency credit amid tightening

**Limitations**: No asset-side data; no derivatives/hedging data; residence basis only.

**Sources**:
- [Fed: Measuring U.S. Cross-Border Securities Flows (Oct 2023)](https://www.federalreserve.gov/econres/notes/feds-notes/measuring-u-s-cross-border-securities-flows-new-data-and-a-guide-for-researchers-20231002.html)
- [Fed: Estimating U.S. Cross-Border Securities Flows (Feb 2022)](https://www.federalreserve.gov/econres/notes/feds-notes/estimating-u-s-cross-border-securities-flows-ten-years-of-the-tic-slt-20220218.html)
- [BIS Global Liquidity Indicators](https://www.bis.org/statistics/gli.htm)
- [Fed Z.1 Financial Accounts](https://www.federalreserve.gov/releases/z1/)
- [Treasury TIC System](https://home.treasury.gov/data/treasury-international-capital-tic-system-home-page)

---

## 3. Liquidity Mechanism Analysis

### 3.1 Core Transmission Channels

| Mechanism | How It Works | Monitoring |
|-----------|-------------|------------|
| **QT Drain** | Fed lets securities mature without reinvesting → liability side shrinks → drains reserves or ON RRP | WALCL delta vs. RRPONTSYD delta vs. WRBWFRBL delta |
| **TGA Mechanics** | Treasury issues debt → TGA rises → drains reserves/ON RRP; Treasury spends → TGA falls → injects liquidity | WTREGEN week-over-week |
| **ON RRP Buffer** | MMFs shift cash between ON RRP and T-bills | RRPONTSYD daily; T-bill auction sizes |
| **Repo Stress** | SOFR spikes above ON RRP rate; Fed Funds-IORB spread turns positive | SOFR vs. RRPONTSYD rate; DFF-IORB spread |

### 3.2 Repo Market Structure

| Facility | Rate | Purpose |
|---|---|---|
| ON RRP (RRPONTSYD) | Floor rate | Absorb excess cash; MMF liquidity buffer |
| Standing Repo Facility (SRF) | Ceiling rate | Backstop for banks against Treasury collateral |
| IORB | Policy rate floor | Interest on reserve balances held by banks |

**Key Monitoring**: SOFR volatility, SOFR-IORB spread, and ON RRP balance trends jointly indicate funding stress before it appears in risk assets.

### 3.3 Pre-2019 Repo Crisis Pattern

Warning sequence before Sept 2019 repo crisis:
1. ON RRP near zero (buffer gone)
2. TGA rising (tax receipts draining reserves)
3. SOFR spiking above IORB
4. Intraday Fed Funds volatility

This pattern is reproducible as a monitoring rule.

**Sources**:
- [How Liquidity Drives Markets: SOFR, TGA, and Reserves](https://za.investing.com/analysis/how-liquidity-drives-markets-sofr-tga-and-reserves-200619143)
- [Liquidity Is Still Plentiful](https://trium-capital.com/trium-talks/liquidity-is-still-plentiful/)
- [Fed: Central Bank Balance-Sheet Trilemma (Jan 2026)](https://www.federalreserve.gov/econres/notes/feds-notes/the-central-bank-balance-sheet-trilemma-accessible-20260114.htm)

---

## 4. Cross-Border Capital Flow Frameworks

### 4.1 Covered Interest Parity (CIP) Deviation Framework

The cross-currency basis (CCB) is the primary barometer of dollar funding stress:

- **Negative dollar basis**: Synthetic dollar borrowing via FX swaps is more expensive than direct dollar borrowing. Signals dollar scarcity.
- **Persistent since 2008**: CIP violations are now structural, driven by hedging demand, balance sheet constraints, and reduced arbitrage capital.

### 4.2 Key Monitoring Methodologies

| Approach | Description |
|---|---|
| **BIS "Missing Debt"** | FX swap/forward notional exceeds on-balance-sheet dollar debt (~$25T off-balance-sheet vs. ~$13T on). Use BIS OTCD + LBS + CPIS data. |
| **CLS Settlement Data** | Real-time aggregated interbank FX swap positions across 18 currencies. US banks act as pivotal intermediaries. |
| **TVP-VAR Connectedness** | Dynamic spillover network across G10 CCBs. EUR and JPY bases are net-transmitters (large USD funding gaps). |
| **Purified CIP (IMF)** | Uses supranational bonds (EIB, KfW) to strip out credit risk from EM CIP deviations. |
| **CCB Term Structure** | Short-term CCB (<6 months) drives sovereign bond flows; Fed swap lines reduce short-tenor bases. |

### 4.3 Causal Link: CCB --> Capital Flows

ECB Working Paper (Kubitza, Sigaux & Vandeweyer, 2024/2025): A widening USD-EUR CCB *causes* euro-area investors to reduce USD bond holdings. Effect is strongest for investors with FX rollover risk and hedging mandates. This means the CCB is a *causal* determinant of capital flows, not merely a symptom.

### 4.4 Carry Trade Monitoring

BIS methodology for sizing carry trades using BIS derivatives statistics:
- Track net long/short positions by currency
- Monitor funding currency (JPY, CHF) vs. target currency (EM, AUD, NZD) positioning
- Volatility-adjusted carry-to-risk ratios

**Sources**:
- [BIS: Covered Interest Parity Lost (2016)](https://www.bis.org/publ/qtrpdf/r_qt1609e.htm)
- [BIS: FX Swaps and Forwards — Missing Global Debt](https://www.bis.org/publ/qtrpdf/r_qt1709e.htm)
- [ECB: Implications of CIP Deviations for Capital Flows](https://www.ecb.europa.eu/pub/pdf/scpwps/ecb.wp3017.en.pdf)
- [Macrosynergy: Understanding Dollar Cross-Currency Basis](https://macrosynergy.com/research/understanding-the-dollar-cross-currency-basis/)
- [BIS: Bank Positions in FX Swaps — Insights from CLS](https://www.bis.org/publ/qtrpdf/r_qt2309b.htm)
- [BIS: Sizing Up Carry Trades](https://www.bis.org/publ/qtrpdf/r_qt2409y.htm)

---

## 5. "Who Backstops What" — The Liquidity Backstop Hierarchy

Systematic framework for identifying which entity must step in at each stress level:

| Layer | Entity | Role | Constraint |
|---|---|---|---|
| **Tier 1** | Dealer Banks | Day-to-day Treasury market liquidity; repo intermediation | SLR (Supplementary Leverage Ratio) — risk-insensitive capital floor |
| **Tier 2** | Flexible Investors (hedge funds) | Absorb sell orders when dealers are balance-sheet constrained | Withdraw liquidity during extreme stress ("dash for cash" — costs rise 38%) |
| **Tier 3** | CCPs (FICC) | Counterparty risk netting; multilateral repo clearing | Procyclical margin calls can amplify stress |
| **Tier 4** | Federal Reserve (SRF) | Pre-arranged backstop via Standing Repo Facility | Moral hazard; reserved for extreme stress |
| **Tier 5** | Federal Reserve (Emergency) | Section 13(3) facilities (CPFF, PDFF, etc.) | Only activated in systemic crises |

### Programmable Monitoring Rules

```
If SLR binding (6/8 GSIBs constrained) AND Treasury issuance accelerating:
    -> Tier 1 backstop narrowing (watch SOFR vol)
If ON RRP near zero AND TGA rising AND SOFR-ON RRP spread widening:
    -> Tier 4 activation risk rising (check SRF usage from H.4.1 Table 1)
If BIS CCB widening across G10 AND dealer balance sheets declining:
    -> Cross-border dollar funding stress (monitor Fed swap line usage)
```

**Sources**:
- [Brookings: Enhancing Liquidity of the U.S. Treasury Market Under Stress](https://www.brookings.edu/articles/enhancing-liquidity-of-the-u-s-treasury-market-under-stress/)
- [BoE: Investors as a Liquidity Backstop in Corporate Bond Markets (2025)](https://www.bankofengland.co.uk/working-paper/2025/investors-as-a-liquidity-backstop-in-corporate-bond-markets)
- [FSF: Addressing Leverage Capital for Large Banks](https://fsforum.com/past-due-notice-addressing-leverage-capital-for-large-banks-to-restore-treasury-market-functioning/)

---

## 6. Pozsar's "Money View" Ecosystem

Zoltan Pozsar's framework is the most comprehensive analytical taxonomy for the modern financial system structure.

### 6.1 The Four-Goal Model

| Player | Goal / Rigidity | Instrument |
|--------|----------------|------------|
| **CIOs** (pension funds, SWFs, FX reserve managers) | Reduce underfundedness; nominal promises to beneficiaries | Long-term bonds, private assets |
| **Risk Portfolio Managers** (hedge funds, separate accounts) | Beat benchmarks via leverage, shorting, derivatives | Levered strategies, derivatives |
| **Cash Portfolio Managers** (institutional cash pools ~$7T) | Preserve capital; avoid credit/duration/liquidity risk | Repos, T-bills, money market instruments |
| **Dealer Banks** | Intermediation between cash and risk managers | Matched-book repo, market-making |

### 6.2 Key Analytical Principles

1. **Risk intermediation, not credit intermediation**: Modern banks intermediate credit, duration, and liquidity risks between cash pools and levered managers -- not deposits into loans.
2. **Repo as working capital**: Repo markets provide working capital for asset managers, analogous to Bagehot's real bills for merchants.
3. **Three satellite accounts needed beyond Flow of Funds**: Flow of Collateral, Flow of Risk, Flow of Eurodollar.
4. **Reverse maturity transformation**: How collateral is "mined" and reused through dynamic chains, creating hidden interconnectedness.

### 6.3 Macro Root Causes

Shadow banking as "the financial economy reflection of real economy imbalances":
- Global imbalances (managed FX regimes accumulating dollar reserves)
- Income inequality (corporate cash hoards)
- Asset management consolidation (centralized liquidity)

### 6.4 Operational Takeaways for MarketMind

- **Institutional profiling**: Map each entity type to its balance-sheet rigidities and instrument demand patterns
- **Collateral chain tracking**: Monitor repo volumes, reuse rates, and haircuts as leading stress indicators
- **Cash pool dynamics**: Track MMF AUM, ON RRP usage, and T-bill auctions to infer real-time liquidity preferences

**Sources**:
- [Pozsar: Shadow Banking — The Money View (OFR WP 14-04, 2014)](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2476415)
- [Pozsar & Singh: Nonbank-Bank Nexus (IMF WP, 2011)](https://www.imf.org/external/pubs/ft/wp/2011/wp11289.pdf)

---

## 7. Composite Indicator Frameworks

### 7.1 Net Liquidity Index (Practitioner Standard)

```
NetLiquidity = Fed_Assets - ON_RRP - TGA
```

Variants:
- **CLRC (Composite Macro Regime Score)**: Z-score of Net Liquidity YoY, combined with DXY, VIX, credit spreads (HYG/LQD), stablecoin flows. Output: Risk-ON (>+0.8) / Risk-OFF (<-1.0).
- **Liquidity Regime Oscillator**: 0-100 scale from WALCL/TGA/RRP + DXY/HYG-LQD/SPHB-SPHQ, normalized and double-smoothed.
- **Daily Scorecard**: Discrete rule-based scoring (each component -1/0/+1) with SOFR-IORB, TGA trend, RRP delta, DXY, HYG/LQD.

### 7.2 Daily Scoring Example

| Component | Condition | Score |
|-----------|-----------|:---:|
| TGA weekly trend | Sustained high / rising | -1 |
| Reserves trend | Declining | -1 |
| ON RRP delta | Fell >$100B in week and >$200B remaining | +1 |
| ON RRP delta | Near zero (<$100B) | 0 |
| SOFR - IORB | > 0.05% | -1 |
| DXY trend | Strengthening (DXY up) | -1 |
| HYG/LQD trend | Weakening (credit stress) | -1 |

### 7.3 Key Data Sources for Automation

| Indicator | Source | Frequency |
|-----------|--------|-----------|
| Fed H.4.1 (all components) | FRED / federalreserve.gov | Weekly |
| ON RRP volume | FRED RRPONTSYD | Daily |
| Cross-currency basis | Bloomberg / BIS / Macrosynergy | Daily |
| TIC data (capital flows) | Treasury TIC SLT | Monthly |
| Z.1 Flow of Funds | FRED / federalreserve.gov | Quarterly |
| BIS GLIs | BIS statistics | Quarterly |
| OTC derivatives | BIS OTCD | Semi-annual |

---

## 8. Operationalization Roadmap for MarketMind

### Phase 1: Foundation Monitors (can build now from FRED API)

1. **Fed Balance Sheet Monitor**: Pull H.4.1 components weekly; compute Net Liquidity; track ON RRP buffer depletion rate; generate alert when ON RRP < $100B and TGA rising.
2. **Repo Stress Detector**: Monitor SOFR-ON RRP spread and Fed Funds-IORB spread daily; log pre-2019 pattern match score.
3. **TGA Flows Monitor**: Track WTREGEN week-over-week alongside Treasury auction calendar; infer liquidity impact of auction settlement dates.

### Phase 2: Cross-Border Monitors (monthly/quarterly cadence)

4. **TIC Flow Decomposition**: Use expanded TIC SLT data; extract official vs. private flows by country; compute trend divergence signals (e.g., FOI selling Treasuries while private buying equities).
5. **Z.1 Sectoral Balances**: Compute quarterly sectoral surplus/deficit; flag regimes (e.g., private sector deficit + government deficit = "twin deficit" warning).
6. **BIS GLI Tracker**: Monitor USD credit to non-banks outside US; alert on contraction phase transitions.

### Phase 3: Advanced Monitors (requires more data infrastructure)

7. **Cross-Currency Basis Monitor**: Track USD cross-currency basis across G10 + key EM pairs; compute connectedness using rolling VAR; flag systemic dollar funding stress.
8. **Collateral Chain Stress**: Monitor repo volumes, haircuts, and reuse rates from OFR/NY Fed data.
9. **Backstop Hierarchy Score**: Composite metric from SLR binding status, ON RRP buffer level, SRF usage, and CCB widening.

### Architecture Principle

Each monitor should be a self-contained module with:
- Single data pipeline (FRED/API -> storage -> signal generation)
- Clear alert thresholds (configurable)
- Output format compatible with MarketMind's existing SessionContext
- No cross-module imports (follows extraction rules from CLAUDE.md)

---

## Key References (Organized by Topic)

**Fed Balance Sheet**:
- [Fed FEDS Note: Decomposition of Balance Sheet Reduction (Feb 2026)](https://www.federalreserve.gov/econres/notes/feds-notes/a-decomposition-of-balance-sheet-reduction-20260202.html)
- [Fed H.4.1 Release](https://www.federalreserve.gov/releases/h41/)

**TIC / Capital Flows**:
- [Fed: Guide for Researchers on Cross-Border Securities Flows (Oct 2023)](https://www.federalreserve.gov/econres/notes/feds-notes/measuring-u-s-cross-border-securities-flows-new-data-and-a-guide-for-researchers-20231002.html)

**Liquidity Mechanics**:
- [Fed: Central Bank Balance-Sheet Trilemma (Jan 2026)](https://www.federalreserve.gov/econres/notes/feds-notes/the-central-bank-balance-sheet-trilemma-accessible-20260114.htm)
- [NY Fed: Balance Sheet Runoff and ON RRP (2022)](https://libertystreeteconomics.newyorkfed.org/2022/04/the-feds-balance-sheet-runoff-and-the-on-rrp-facility/)

**FX Swaps / Cross-Border**:
- [BIS: Covered Interest Parity Lost (2016)](https://www.bis.org/publ/qtrpdf/r_qt1609e.htm)
- [BIS: FX Swaps — Missing Global Debt (2017)](https://www.bis.org/publ/qtrpdf/r_qt1709e.htm)
- [ECB: CIP Deviations and Capital Flows (2025)](https://www.ecb.europa.eu/pub/pdf/scpwps/ecb.wp3017.en.pdf)
- [BIS: Sizing Up Carry Trades (2024)](https://www.bis.org/publ/qtrpdf/r_qt2409y.htm)
- [Macrosynergy: Understanding Dollar Cross-Currency Basis](https://macrosynergy.com/research/understanding-the-dollar-cross-currency-basis/)

**Backstop Framework**:
- [Brookings: Enhancing Treasury Market Liquidity Under Stress](https://www.brookings.edu/articles/enhancing-liquidity-of-the-u-s-treasury-market-under-stress/)
- [BoE: Investors as Liquidity Backstop (2025)](https://www.bankofengland.co.uk/working-paper/2025/investors-as-a-liquidity-backstop-in-corporate-bond-markets)

**Pozsar Framework**:
- [Pozsar: Shadow Banking — The Money View (2014)](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2476415)

**BIS Global Liquidity**:
- [BIS Global Liquidity Indicators](https://www.bis.org/statistics/gli.htm)
- [BIS: Global Liquidity — Changing Instrument and Currency Patterns](https://www.bis.org/publ/qtrpdf/r_qt1809b.htm)
