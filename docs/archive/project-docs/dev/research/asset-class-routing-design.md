# Asset-Class Routing Framework for Causal Decomposition & Flow Tracking

**Author**: Quant Analyst (Sonnet 1M)
**Date**: 2026-05-18
**Purpose**: Address Red Team Logic C1 + C2 findings from Phase H architecture audit. Design asset-class-aware routing so that `causal_decomposition.py` and `flow_decomposition.py` apply the correct analytical lens per asset class, rather than assuming all hypotheses fit a US fixed-income balance-sheet model.

**Immediate consumers**: Architect (converts to prompt templates), Builder (implements routing in investigation_loop.py)

---

## Problem Restatement

**C1 (Balance Sheet)**: The causal decomposition module applies asset/liability decomposition to ALL hypotheses. This works only for US fixed income (~15% of hypotheses). For commodities (soybeans, oil), there is no balance sheet. For FX, TWO central bank balance sheets interact. For crypto, no balance sheet at all.

**C2 (Flow Tracking)**: The flow decomposition module proposes 5 US-centric entity types (US_HOUSEHOLD, US_INSTITUTIONAL, FOREIGN_OFFICIAL, FOREIGN_PRIVATE, FED). This does not work for Japanese yen (dominant entities: BoJ, GPIF, Japanese retail), European equities (ECB, European insurers, global asset managers), or Chinese bonds (PBoC, SAFE, Chinese banks, Stock Connect flows).

**Core insight**: "Who buys what" and "what balances what" are asset-class-relative questions. The decomposition lens must match the asset being analyzed.

---

## 1. Asset Class Taxonomy

MarketMind analyzes 9 distinct macro asset classes. Each requires a different decomposition framework:

| # | Asset Class | Tickers (from asset_universe) | MarketMind Hypothesis Coverage (est.) |
|:---:|------|------|:---:|
| AC1 | **US Fixed Income / Rates** | TLT, yield-curve topics | ~15% |
| AC2 | **US Broad Equities** | SPY, QQQ, IWM, DIA | ~30% |
| AC3 | **Gold / Precious Metals** | GLD, SLV | ~8% |
| AC4 | **Crude Oil / Petroleum** | USO, XLE | ~12% |
| AC5 | **Natural Gas** | UNG | ~5% |
| AC6 | **Agriculture** | DBA, softs, grains | ~5% |
| AC7 | **FX / Major Currency Pairs** | DXY-implied, EUR/USD, USD/JPY | ~10% |
| AC8 | **Crypto** | BTC-USD | ~8% |
| AC9 | **EM Macro / EM Equities** | EEM | ~7% |

Individual equities (AAPL, MSFT, etc.) inherit routing from their macro asset class. Sector ETFs (XLF, XLK, XLE, XLV) route to AC2 (US Broad Equities) with a sector overlay.

---

## 2. Per-Asset-Class Decomposition Framework

For each asset class, define four things:
1. **Decomposition Lens** — what analytical framework applies? Balance sheet? Physical S&D? Carry/CIP? On-chain?
2. **Dominant Entity Types** — who are the buyers and sellers?
3. **Key Data Sources** — what verifiable data supports the analysis?
4. **Net Directional Force** — what does "bullish" vs. "bearish" mean in this context?

---

### AC1: US Fixed Income / Rates

| Dimension | Specification |
|---|---|
| **Decomposition Lens** | **Balance sheet (asset/liability dual-direction)**. Asset side: SOMA holdings (Treasuries by maturity, MBS, agency debt). Liability side: currency, bank reserves, ON RRP, TGA, other deposits. Net Liquidity = WALCL - RRPONTSYD - WTREGEN. Reserves/GDP ratio as regime classifier (ample >= 10%, ample 8-10%, stressed < 8%). |
| **Dominant Entity Types** | (1) Federal Reserve — SOMA manager, rate setter, QT/QE executor. (2) US Treasury — TGA manager, debt issuer, bill/bond maturity decision-maker. (3) US Households — direct + via mutual funds/ETFs. (4) US Institutional — pension funds, insurers, bank treasuries. (5) Foreign Official — central bank reserve managers (FOI in TIC). (6) Foreign Private — hedge funds (Cayman Islands), global asset managers. (7) Money Market Funds — ON RRP users, T-bill buyers, marginal liquidity providers. (8) Dealer Banks — Treasury market-makers, repo intermediaries, SLR-constrained balance sheets. |
| **Key Data Sources** | Fed H.4.1 (weekly): WALCL, RRPONTSYD, WTREGEN, WRBWFRBL, WSHOSHO. FRED daily: DFF, IORB, SOFR. TIC SLT (monthly): official vs. private Treasury flows by country. Z.1 Flow of Funds (quarterly): sectoral holdings by instrument. Treasury auction calendar: bill/bond/note sizes and settlement dates. |
| **Net Directional Force** | **Net Liquidity Injection (+)**: WALCL flat/rising + ON RRP falling + TGA falling. Reserves increasing. **Net Liquidity Drainage (-)**: WALCL falling (QT) + ON RRP near zero + TGA rising. Reserves falling. **Threshold alerts**: ON RRP < $100B = buffer exhausted, reserves directly exposed. Reserves/GDP < 8% = funding stress possible. SOFR - ON RRP rate >= 0.05% = interbank funding stress. 10Y yield approaching 4.5% = political pain threshold. |
| **Causal Decomposition Pattern** | Asset-side change (Fed selling/draining) + Liability-side change (TGA drain, RRP shift) → Net impulse on duration/curve. Example: "Fed QT reduces 10Y duration supply BUT Treasury shifts issuance to bills (short end), steepening the curve. Net effect: long-end yields rise, short-end anchored." |

---

### AC2: US Broad Equities

| Dimension | Specification |
|---|---|
| **Decomposition Lens** | **Liquidity regime + flow of funds**. No direct balance sheet — equities respond to the net liquidity impulse from the rates/FX complex. Primary channel: Net Liquidity (WALCL - RRP - TGA) → risk asset prices. Secondary channels: corporate buybacks (authorized vs. executed), ETF flows (creation/redemption), institutional positioning (COT, 13F). Decomposition is about *flow attribution*, not balance-sheet identity. |
| **Dominant Entity Types** | (1) US Households — direct equity + mutual fund/ETF holdings (~38% of market). (2) US Institutional — pension funds, endowments, insurers (~25%). (3) Foreign Official — sovereign wealth funds, reserve managers (~5%). (4) Foreign Private — global asset managers, hedge funds (~15%). (5) Corporations — buyback desks (~2-3% annual net demand). (6) Market Makers / HFTs — intraday liquidity, gamma hedging flows. (7) ETFs — passive rebalancing flows (quarterly, mechanically predictable). |
| **Key Data Sources** | Fed Z.1 (quarterly): corporate equity net issuance/repurchase, household equity holdings, foreign holdings. TIC SLT (monthly): cross-border equity flows by country. COT (weekly): ES, NQ, RTY futures positioning. ETF flow data (daily): SPY, QQQ, IWM AUM changes. 13F filings (quarterly): institutional holdings. Corporate buyback announcements + actual execution (quarterly). CBOE put/call ratios, VIX futures term structure. |
| **Net Directional Force** | **Bullish Flow (+)**: Net Liquidity rising + foreign inflows positive + buybacks > issuance + institutional positioning net long. **Bearish Flow (-)**: Net Liquidity falling + foreign outflows + buybacks declining + institutional de-grossing. **Counter-intuitive case**: Net Liquidity falling BUT equities rising → check corporate buybacks, passive flows, gamma positioning for explanation. |
| **Causal Decomposition Pattern** | Who is buying, who is selling, at what volume? Decompose into: (a) passive/mechanical flows (401k, ETF rebal, index inclusion), (b) active discretionary flows (hedge fund, active mutual fund), (c) corporate flows (buybacks, issuance, insider trading), (d) foreign flows (official vs. private). Net directional force = sum of (a) through (d) weighted by historical impact coefficient. |

---

### AC3: Gold / Precious Metals

| Dimension | Specification |
|---|---|
| **Decomposition Lens** | **Real rate framework + reserve diversification + physical flow**. Gold has no balance sheet and no earnings stream. Decomposition is three-dimensional: (a) real rates (TIPS yields): opportunity cost of holding gold → dominant explanatory variable. (b) central bank reserve behavior: PBoC, RBI, Turkish CB, Polish NBP are active buyers diversifying from USD reserves. (c) physical flow: ETF holdings (GLD, IAU), COMEX inventory, LBMA clearing data, Swiss refinery exports, Shanghai Gold Exchange withdrawals. |
| **Dominant Entity Types** | (1) Central Banks (official sector) — reserve diversification, sanctions-proofing. PBoC, RBI, NBP are primary buyers. (2) ETF Investors — GLD/IAU holders, rate-sensitive, tactical. (3) Futures Speculators — COMEX managed money, momentum-driven. (4) Physical Consumers — India (jewelry demand, wedding season), China (retail bars/coins), Turkey. (5) Producers (miners) — hedging flows, AISC cost floor. (6) Swiss Refineries — physical flow hub, export data as real-time demand proxy. |
| **Key Data Sources** | WGC Gold Demand Trends (quarterly): jewelry, technology, investment, central bank. COMEX COT (weekly): managed money net positioning. ETF holdings (daily): GLD, IAU, GBSS tonnage. TIPS real yields (daily): 5Y, 10Y, 30Y. DXY (daily): inverse correlation with gold. LBMA clearing data (monthly): volume, value. Swiss customs gold exports (monthly): flows to China, India, Turkey. Shanghai Gold Exchange withdrawals (weekly). Central bank gold reserve data (IMF IFS, quarterly but lagged). |
| **Net Directional Force** | **Bullish (+)**: Real rates falling + central bank buying > 300 tonnes/quarter + ETF inflows + COMEX managed money net long expanding + DXY weakening. **Bearish (-)**: Real rates rising + CB buying slowing to < 150 tonnes/quarter + ETF outflows + managed money net short + DXY strengthening. **Divergence signal**: Real rates rising BUT gold holding/rising → central bank buying or geopolitical fear premium dominating (this is the most actionable counter-consensus pattern). |
| **Causal Decomposition Pattern** | Decompose into: (a) macro/rate component (explainable by real rates + DXY), (b) reserve diversification component (explainable by CB buying trend), (c) residual (geopolitical, technical, flow-driven). When (b) or (c) dominate, the narrative is "gold decoupling from rates" — historically precedes major moves. |

---

### AC4: Crude Oil / Petroleum

| Dimension | Specification |
|---|---|
| **Decomposition Lens** | **Physical supply-demand balance + speculative positioning overlay**. Oil is a physical commodity with inelastic short-term S&D. Decomposition is fundamentally about: (a) supply side: OPEC+ quotas and compliance, US shale production (EIA DPR), non-OPEC supply, disruptions (geopolitical, weather). (b) demand side: global GDP growth, China crude imports, US refinery utilization, transportation demand. (c) inventory buffer: US commercial crude stocks (EIA weekly), Cushing hub, global floating storage, SPR. (d) speculative overlay: managed money positioning in WTI and Brent futures/options. |
| **Dominant Entity Types** | (1) OPEC+ Producers — Saudi Arabia, Russia, Iraq, UAE, Kuwait. Marginal supply decision-makers. (2) US Shale Producers — Permian Basin operators, E&P companies, hedging behavior. (3) National Oil Companies (NOCs) — Saudi Aramco, NIOC, PDVSA, Pemex. (4) International Oil Companies (IOCs) — Exxon, Chevron, Shell, BP, Total. (5) Physical Traders — Vitol, Trafigura, Glencore, Mercuria. Control floating storage and arbitrage flows. (6) Speculators — managed money in WTI/Brent futures (COT report). (7) Strategic Buyers — US SPR (DOE), China SPR, India SPR. (8) Refiners — US Gulf Coast, Chinese teapots, European refiners. |
| **Key Data Sources** | EIA Weekly Petroleum Status Report: crude stocks, production, imports, refinery utilization, product inventories. EIA Drilling Productivity Report (monthly): Permian, Bakken, Eagle Ford production per rig. OPEC Monthly Oil Market Report: production by member, global demand forecast. Kpler/Vortexa (commercial): satellite-tracked floating storage, cargo flows. Baker Hughes Rig Count (weekly). COT (weekly): WTI managed money net positioning. IEA Oil Market Report (monthly). China customs crude imports (monthly). |
| **Net Directional Force** | **Tightening / Bullish (+)**: Global supply < demand (implied stock draw), OPEC+ compliance > 90%, US commercial crude stocks drawing > seasonal norm, managed money net long expanding, backwardation in futures curve. **Loosening / Bearish (-)**: Supply > demand (stock build), OPEC+ cheating/deal breakdown, US production surging, managed money net short, contango in curve. **Key threshold**: US commercial crude stocks vs. 5-year seasonal average. >1 std dev above = oversupplied; >1 std dev below = undersupplied. Cushing stocks < 20M bbls = physical squeeze risk. |
| **Causal Decomposition Pattern** | Decompose price move into: (a) supply shock component (OPEC+ decision, disruption), (b) demand shock component (GDP surprise, China imports), (c) inventory cycle component (draw/build vs. seasonal norm), (d) speculative component (residual = actual move minus S&D-justified move). |

---

### AC5: Natural Gas (US Henry Hub / UNG)

| Dimension | Specification |
|---|---|
| **Decomposition Lens** | **Storage trajectory vs. 5-year norm + weather-driven demand + production growth**. Natural gas has no global benchmark — US Henry Hub is a domestic market driven by: (a) storage: weekly EIA storage report, deviation from 5-year average. (b) weather: HDD/CDD forecasts, winter/summer demand. (c) production: associated gas from oil wells (Permian, Bakken), dry gas production (Appalachia, Haynesville). (d) LNG exports: feedgas to liquefaction terminals, global arbitrage (JKM, TTF vs. Henry Hub). |
| **Dominant Entity Types** | (1) E&P Producers — Appalachian (EQT, Range Resources), Haynesville, Permian associated gas. (2) LNG Exporters — Cheniere (Sabine Pass, Corpus Christi), Freeport, Venture Global. (3) Utilities / LDCs — storage operators, winter hedgers. (4) Speculators — managed money in NG futures (COT). (5) Physical Traders — pipeline capacity holders, storage arbitrageurs. (6) Power Generators — gas-to-coal switching at specific price thresholds. |
| **Key Data Sources** | EIA Weekly Natural Gas Storage Report: working gas in storage vs. 5-year range. NOAA weather forecasts: 6-10 day, 8-14 day HDD/CDD outlooks. EIA Natural Gas Monthly: production by region, consumption by sector. Baker Hughes gas rig count (weekly). LNG feedgas flows (daily, from pipeline flow data). COT (weekly): NG managed money positioning. |
| **Net Directional Force** | **Bullish (+)**: Storage deficit vs. 5-year avg growing + weather forecast colder/hotter than normal + production flat/declining + LNG exports increasing. **Bearish (-)**: Storage surplus growing + mild weather + production surging + LNG outages. **Key indicator**: End-of-March storage level determines post-winter buffer; end-of-October storage determines pre-winter cushion. |
| **Causal Decomposition Pattern** | Decompose into: (a) weather deviation (HDD/CDD delta from normal × demand coefficient), (b) structural production trend (year-over-year rig/production), (c) LNG export demand (feedgas flows × utilization), (d) storage trajectory residual. Weather dominates short-term; production trend dominates medium-term. |

---

### AC6: Agriculture (Grains, Softs — DBA, Corn, Soybeans, Wheat)

| Dimension | Specification |
|---|---|
| **Decomposition Lens** | **Supply: acreage, yield, weather. Demand: feed, food, fuel, exports. Trade: tariffs, shipping.** Agricultural commodities are annual-cycle physical goods. Decomposition: (a) US supply: planting intentions (March), acreage (June), yield (growing season), production (harvest). USDA WASDE monthly updates are the single most important input. (b) South American supply: Brazil safrinha corn (Feb-Jun), Argentina soybeans (Mar-May). (c) Global demand: China imports (soybeans, corn), India imports (vegetable oils, pulses), feed demand (livestock herd size), biofuel mandates (US ethanol, EU biodiesel). (d) Trade flows: export inspections, shipping costs, Black Sea corridor, Panama Canal. (e) Weather: US Midwest growing conditions (May-Aug), Brazil rainfall (Oct-Feb), ENSO cycle. |
| **Dominant Entity Types** | (1) US Farmers — acreage decisions, crop insurance thresholds, selling behavior. (2) Brazilian/Argentine Farmers — planting decisions, currency effects (weaker BRL = more selling). (3) Grain Traders — ADM, Bunge, Cargill, Louis Dreyfus (ABCD). Control storage, logistics, export elevators. (4) China (COFCO, Sinograin) — largest importer, state reserves, food security policy. (5) Importers — Egypt (wheat), Japan, South Korea, SE Asia. (6) Biofuel Producers — US ethanol plants, EU biodiesel, India ethanol blending. (7) Speculators — managed money in grains futures (COT), index fund rolling. |
| **Key Data Sources** | USDA WASDE (monthly, ~10th of each month): US and world supply/demand for all major crops. USDA Crop Progress (weekly, seasonal): planting/harvesting progress, crop conditions (% good/excellent). USDA Export Inspections/Sales (weekly). COT (weekly): grains managed money. Brazil CONAB crop estimates (monthly). Weather models: GFS, ECMWF (continuous). Ocean freight: Baltic Dry Index, grain routes. |
| **Net Directional Force** | **Bullish (+)**: Ending stocks-to-use ratio declining, weather threat to US crop, strong China import demand, weak USD (makes US exports cheaper), managed money net long. **Bearish (-)**: Stocks-to-use rising, bumper crop, weak export demand, strong USD, managed money net short. **Key threshold**: US corn stocks-to-use < 10% = price rationing needed; soybeans stocks-to-use < 5% = extremely tight. USDA WASDE surprises > 2% of production = major price moves. |
| **Causal Decomposition Pattern** | Decompose into: (a) supply deviation from trend (weather-adjusted yield model), (b) demand deviation from trend (China imports, biofuel mandates), (c) trade/currency overlay (BRL, USD, freight costs), (d) speculative positioning residual. |

---

### AC7: FX / Major Currency Pairs (DXY, EUR/USD, USD/JPY, USD/CNY)

| Dimension | Specification |
|---|---|
| **Decomposition Lens** | **DUAL balance sheet framework + carry/CIP + capital flow trilemma**. FX is inherently multi-jurisdictional. Decomposition: (a) Policy rate differential: Fed vs. counterparty CB policy path (dot plot vs. ECB staff projections vs. BoJ outlook). (b) Balance sheet relative pace: QT/QE differential — who is tightening liquidity faster? (c) Covered Interest Parity (CIP) deviations: cross-currency basis (CCB) as barometer of dollar funding stress. Negative CCB = synthetic dollar funding more expensive = dollar scarcity. (d) Capital flows: TIC data for cross-border securities, BIS banking flows, SWIFT payment flows. (e) Terms of trade / current account: oil price impact on commodity currencies (CAD, NOK, RUB), manufacturing exports for EUR, JPY, CNY. |
| **Dominant Entity Types** | (1) Central Banks — Fed, ECB, BoJ, BoE, PBoC, SNB, RBA, RBNZ, BoC. (2) FX Reserve Managers — SAFE (China), MoF (Japan), MAS (Singapore), HKMA, Saudi SAMA. (3) Global Asset Managers — BlackRock, Vanguard, PIMCO, Allianz. FX hedging decisions for international portfolios. (4) Japanese Retail (Mrs. Watanabe) — large retail FX carry traders, margin-based, stop-loss clusters. (5) Corporate Treasuries — hedging of trade receivables/payables, FX swap users. (6) Hedge Funds — global macro funds, systematic CTAs, carry trade operators. (7) Sovereign Wealth Funds — GPIF (Japan, $1.5T+), NBIM (Norway), ADIA (UAE), KIA (Kuwait). (8) BIS / CLS — settlement infrastructure, FX swap data. |
| **Key Data Sources** | Central bank policy statements + minutes (continuous). Cross-currency basis (daily): EUR/USD, USD/JPY, GBP/USD from Bloomberg/Reuters/Macrosynergy. TIC SLT (monthly): country-level flows into US securities. BIS Locational Banking Statistics (quarterly): cross-border bank claims. BIS OTCD (semi-annual): FX swap/forward notional outstanding. CFTC COT (weekly): DXY, EUR, JPY, GBP, CAD, AUD, CHF futures positioning. CLS settlement data (aggregate, monthly): interbank FX volumes. Carry-to-risk ratios: vol-adjusted yield differential. |
| **Net Directional Force** | **Dollar Strength (+)**: Fed rate advantage widening + Fed QT faster than peers + negative CCB widening (dollar scarcity) + US attracting capital inflows + COT net long USD. **Dollar Weakness (-)**: Rate advantage narrowing + Fed QT slowing/ending while ECB/BoJ normalize + CCB narrowing + capital outflows from US + COT net short USD. **Fragility signal**: When USDJPY carry is large AND CCB is wide AND Japanese retail is heavily short JPY → reverse-Kuroda risk. When BOJ hints at normalization → violent short-squeeze in JPY. |
| **Causal Decomposition Pattern** | Decompose into: (a) rate differential component (2Y yield spread × historical beta), (b) balance sheet relative pace (Fed vs. counterparty CB), (c) CIP/CCB deviation (funding stress), (d) flow component (TIC + BIS + COT direction), (e) residual (intervention, geopolitical, safe-haven bid). For USD/JPY specifically: track MoF intervention risk above 150, near-certain above 160. |

---

### AC8: Crypto (Bitcoin / BTC-USD)

| Dimension | Specification |
|---|---|
| **Decomposition Lens** | **On-chain flow + ETF flow + macro correlation + supply schedule**. Crypto has no balance sheet, no earnings, no central bank. Decomposition: (a) On-chain flows: exchange net flows (inflow = selling pressure, outflow = accumulation), whale wallet activity, miner selling, long-term holder (LTH) vs. short-term holder (STH) behavior. (b) ETF flows: spot BTC ETF daily inflows/outflows (aggregate across IBIT, FBTC, GBTC, ARKB, BITB, etc.) — this is now the dominant marginal price-setter. (c) Macro correlation: correlation with NDX/QQQ, real rates, dollar — BTC behaves as a high-beta risk asset during risk-on, but occasionally decouples as "digital gold." (d) Supply mechanics: halving cycle, miner capitulation, illiquid supply ratio. (e) Stablecoin flows: USDT/USDC market cap growth → dry powder. Exchange stablecoin reserves rising = buying power building. |
| **Dominant Entity Types** | (1) Spot BTC ETF Issuers — BlackRock (IBIT), Fidelity (FBTC), Grayscale (GBTC), ARK (ARKB), Bitwise (BITB). Aggregate ETF flow is the primary daily signal. (2) Long-Term Holders (LTH) — addresses holding >155 days. Accumulation during bear markets, distribution during bull peaks. (3) Short-Term Holders (STH) — addresses holding <155 days. Panic sellers, momentum chasers. (4) Miners — hash rate, miner wallet outflows, capitulation during low-price / high-hashrate environments. (5) Exchanges — Binance, Coinbase, Kraken. Net flow in/out of exchange wallets = near-term selling/buying pressure. (6) Stablecoin Issuers — Tether (USDT), Circle (USDC). Market cap and exchange balances. (7) MicroStrategy / Corporate Treasuries — Michael Saylor, publicly known accumulation. (8) Whales — wallets with >1,000 BTC, tracked via Glassnode/Coin Metrics. |
| **Key Data Sources** | Glassnode / Coin Metrics (on-chain analytics, commercial). Spot BTC ETF daily flow data (free, aggregated by Farside Investors, CoinGlass). Exchange reserve data (on-chain, public). Stablecoin market cap data (daily). CME BTC futures COT (weekly): managed money, leveraged funds positioning. Hash rate / difficulty (on-chain, public). BTC options open interest + max pain (Deribit, daily). |
| **Net Directional Force** | **Bullish (+)**: ETF net inflows > $200M/day sustained + exchange reserves declining (outflow to cold storage) + stablecoin market cap growing + LTH accumulation + hash rate rising. **Bearish (-)**: ETF net outflows sustained + exchange reserves rising (inflow = selling) + stablecoin market cap shrinking + LTH distribution + miner capitulation. **Divergence pattern**: Price falling BUT ETFs still buying AND LTH still accumulating → whale distribution or macro headwind dominating. This resolves when the opposing force exhausts. |
| **Causal Decomposition Pattern** | Decompose into: (a) ETF flow component (daily IBIT+FBTC+GBTC+ARKB+BITB net flow, converted to BTC), (b) on-chain flow component (exchange net flow + LTH/STH supply change), (c) macro beta component (NDX × correlation coefficient), (d) supply cycle component (post-halving supply reduction, miner behavior), (e) stablecoin-dry-powder component. |

---

### AC9: EM Macro / EM Equities (EEM)

| Dimension | Specification |
|---|---|
| **Decomposition Lens** | **Dollar cycle + capital flow push/pull + carry trade + China credit impulse**. EM is a derivative of global liquidity conditions. Decomposition: (a) Dollar cycle: strong USD = EM tightening (imported inflation, dollar debt service burden). Weak USD = EM easing. DXY is the single most important EM variable. (b) Capital flow push: G4 central bank liquidity → flows into EM search for yield. When G4 tightens, EM outflows. (c) Capital flow pull: EM domestic fundamentals (current account, reserves, reform narrative). (d) China credit impulse: the largest single-country driver of EM demand. Chinese fiscal/monetary stimulus → commodity demand → EM exporter revenues. (e) Carry trade: interest rate differential + vol-adjusted attractiveness. |
| **Dominant Entity Types** | (1) G4 Central Banks (Fed, ECB, BoJ, BoE) — the "push" side. Global liquidity conditions. (2) EM Central Banks — BCB (Brazil), Banxico, RBI (India), BI (Indonesia), SARB. Rate decisions + reserve accumulation. (3) Global EM Funds — dedicated EM equity and bond funds (EPFR-tracked). (4) Cross-Border Bank Lending (BIS-tracked) — USD/EUR/JPY credit to EM non-banks. (5) China — PBoC stimulus, property sector, credit impulse. The demand engine for commodity-exporting EMs. (6) FX Reserve Managers (EM side) — accumulation vs. intervention. (7) Sovereign Wealth Funds (EM) — CIC (China), NBIM (Norway, petro-funded). |
| **Key Data Sources** | EPFR fund flow data (weekly): EM equity, EM bond fund flows. BIS Global Liquidity Indicators (quarterly): USD/EUR/JPY credit to EM. IIF Capital Flows Tracker (monthly): portfolio flows to EM. TIC data: from US perspective, but shows EM official holdings. China credit impulse (monthly): total social financing (TSF) YoY. EM FX carry indices: Bloomberg/JPM/DB EM carry indices. CDS spreads (daily): EM sovereign CDS as risk barometer. |
| **Net Directional Force** | **Bullish for EM (+)**: DXY weakening + Fed pausing/dovish + G4 liquidity expanding + EM fund inflows + China credit impulse positive + EM FX carry attractive. **Bearish for EM (-)**: DXY strengthening + Fed hawkish/tightening + G4 liquidity contracting + EM fund outflows + China slowdown + carry unwinding. **Fragility threshold**: When EM sovereign CDS > 300bps for major EMs (Brazil, Mexico, Indonesia) AND DXY > 105 → EM stress regime. Crosses 400bps → systemic risk. |
| **Causal Decomposition Pattern** | Decompose into: (a) dollar/rate component (DXY × correlation), (b) push factor (G4 liquidity proxy → EM flow prediction), (c) pull factor (EM current account, reserves, reform narrative), (d) China component (credit impulse × commodity exporter beta), (e) carry/tactical component (yield differential adjusted for volatility). |

---

## 3. Routing Logic

### 3.1 Routing Decision Tree

Given a hypothesis text `H`, route to the correct asset class framework as follows:

```
Step 1: EXTRACT explicit asset references
  - Ticker mentions (TLT, SPY, GLD, USO, BTC-USD, EEM, DXY, etc.)
  - Asset class keywords ("Treasury", "bond", "equity", "gold", "oil", "FX", "Bitcoin", "EM")
  → Map to candidate asset class set

Step 2: EXTRACT mechanism keywords
  - Balance sheet terms: "ON RRP", "TGA", "QT", "QE", "reserves", "SOMA", "H.4.1", "IORB"
    → US Fixed Income (AC1)
  - Flow terms: "TIC data", "buybacks", "ETF flows", "passive flows", "13F"
    → US Equities (AC2) [unless AC1 already identified from tickers]
  - Gold terms: "real yields", "TIPS", "central bank buying", "Shanghai Gold Exchange", "jewelry demand"
    → AC3
  - Oil terms: "OPEC", "EIA", "crude stocks", "rig count", "WTI", "Brent", "SPR"
    → AC4
  - Gas terms: "Henry Hub", "storage", "LNG feedgas", "HDD", "CDD", "nat gas"
    → AC5
  - Ag terms: "WASDE", "acreage", "stocks-to-use", "crop conditions", "soybean", "corn", "wheat"
    → AC6
  - FX terms: "cross-currency basis", "CIP", "carry trade", "DXY", "EURUSD", "USDJPY", "swap line", "CLS"
    → AC7
  - Crypto terms: "on-chain", "hash rate", "ETF flow" [with BTC ticker], "halving", "whale", "stablecoin", "UTXO"
    → AC8
  - EM terms: "capital flows", "DXY", "EMBI", "EPFR", "carry trade", "China credit impulse"
    → AC9

Step 3: IF Step 1 + Step 2 point to SAME asset class
  → Use that class's framework (single-asset analysis)
  
Step 4: IF Step 1 + Step 2 point to DIFFERENT asset classes OR multiple from Step 1
  → MULTI-ASSET analysis (see Section 4). Apply PRIMARY lens from the asset class of the
    price-relevant ticker, supplemented by CROSS-ASSET transmission channels from the
    mechanism-identified asset class.
  
Step 5: IF no match from Steps 1 OR 2
  → Apply GENERIC FLOW framework:
    - Attempt to identify central entity types from entity-level prompt
    - Apply AC2 (US Broad Equities) as fallback lens (most hypotheses are equity-adjacent)
    - Flag as "unclassified — generic flow" in HypothesisResult for downstream quality tracking

Step 6: SELF-CHECK — ask whether this routing makes sense
  - Would a professional macro analyst use this lens for this hypothesis?
  - If no → re-route to the closest matching class
  - Record the routing decision + confidence in the hypothesis metadata
```

### 3.2 Routing Confidence

Each routing decision carries a confidence score:

| Confidence | Condition | Action |
|:---:|---|---|
| **HIGH (>0.9)** | Steps 1+2 agree on same asset class, ticker explicitly present | Apply single-class framework directly |
| **MEDIUM (0.5-0.9)** | Step 1 has ticker, Step 2 has no mechanism match; OR Step 2 has strong mechanism match, Step 1 has no ticker | Apply identified class but flag for review |
| **LOW (0.3-0.5)** | Steps 1+2 disagree; OR only keyword overlap, no explicit ticker or mechanism | Multi-asset analysis; expand entity types to cover both candidate classes |
| **NONE (<0.3)** | No asset or mechanism match | Generic flow fallback; flag for human review in Gate 1 |

### 3.3 Routing Examples

| Hypothesis | Step 1 Match | Step 2 Match | Route To | Confidence |
|---|---|---|---|---|
| "Fed QT is draining reserves, 10Y yield will break 4.5% by Q3" | TLT-implied (rates) | QT, reserves, 10Y | AC1 (US Fixed Income) | HIGH |
| "AI capex cycle will push SPY to new highs despite QT" | SPY | None strong | AC2 (US Broad Equities) | MEDIUM |
| "PBoC gold buying signals USD reserve diversification, gold to $3200" | GLD | CB buying, gold | AC3 (Gold) | HIGH |
| "OPEC+ production increase + China demand slowdown = oil to $55" | USO, XLE | OPEC, oil | AC4 (Crude Oil) | HIGH |
| "BoJ rate hike will trigger JPY carry unwind, risk assets sell off" | DXY-implied, EEM | cross-currency basis, carry | AC7 (FX) + AC9 (EM) | MEDIUM — multi-asset |
| "BTC ETF inflows accelerating, on-chain supply drying up" | BTC-USD | ETF flows, on-chain | AC8 (Crypto) | HIGH |
| "Strong dollar + hawkish Fed → EM outflows intensify" | EEM | DXY, EM flows | AC9 (EM Macro) | HIGH |
| "Geopolitical tension drives commodity supercycle" | DBA, USO, GLD | None specific | MULTI (AC3+AC4+AC6) | LOW — expand all |

---

## 4. Multi-Asset Hypothesis Handling

When a hypothesis spans multiple asset classes (e.g., "strong dollar crushes EM and commodities"), apply a **primary-secondary decomposition**:

### 4.1 Rules

1. **Identify the PRIMARY asset class**: the asset whose price change is being predicted. This is the analysis target.
2. **Identify the SECONDARY asset class(es)**: the assets acting as causal drivers.
3. **Apply the primary class's decomposition lens** to the target.
4. **Model the secondary class's output** as an input to the primary decomposition.
5. **Do NOT run full decomposition on secondaries** — that causes token explosion. Instead, extract the single most relevant metric from the secondary class and feed it into the primary.

### 4.2 Example: "Strong dollar crushes EM equities"

- **Primary**: AC9 (EM Macro), target = EEM
- **Secondary**: AC7 (FX), driver = DXY
- **How to handle**: Apply AC9 decomposition lens to EEM. Use DXY trajectory as the primary "push" input. Extract only the dollar directional force (from AC7 framework) — do NOT run full dual-balance-sheet + CIP analysis on DXY. Feed the DXY net directional force as the dollar/rate component in the AC9 decomposition.

### 4.3 Example: "Fed QT drains liquidity → SPY corrects 10%"

- **Primary**: AC2 (US Broad Equities), target = SPY
- **Secondary**: AC1 (US Fixed Income), driver = Fed QT
- **How to handle**: Apply AC2 decomposition lens to SPY. Extract the Net Liquidity signal from AC1 (WALCL - RRP - TGA trend) as the liquidity-regime input to AC2. Do NOT run full 5-entity balance-sheet decomposition — that's overkill for equities.

### 4.4 Token Budget Guard

Multi-asset analysis is expensive (2x-3x the prompts). Apply these limits:
- Maximum 2 secondary asset classes per hypothesis
- Secondary decomposition depth: 1 level only (extract directional force, do not cascade)
- If >2 asset classes are implicated, pick the 2 with the highest routing confidence and note the others as "not modeled"

---

## 5. Entity Type Mapping by Asset Class

This table maps each asset class to its entity types, so that `flow_decomposition.py` can instantiate the correct entity set per hypothesis routing:

| Asset Class | Entity Count | Entity Enum (for flow_decomposition.py) |
|---|---|---|
| AC1: US Fixed Income | 8 | FED, US_TREASURY, US_HOUSEHOLD, US_INSTITUTIONAL, FOREIGN_OFFICIAL, FOREIGN_PRIVATE, MONEY_MARKET_FUNDS, DEALER_BANKS |
| AC2: US Broad Equities | 7 | US_HOUSEHOLD, US_INSTITUTIONAL, FOREIGN_OFFICIAL, FOREIGN_PRIVATE, CORPORATE_BUYBACKS, MARKET_MAKERS, ETF_CREATORS |
| AC3: Gold | 6 | CENTRAL_BANKS_OFFICIAL, ETF_INVESTORS, FUTURES_SPECULATORS, PHYSICAL_CONSUMERS, PRODUCERS, REFINERIES |
| AC4: Crude Oil | 8 | OPEC_PLUS_PRODUCERS, US_SHALE_PRODUCERS, NATIONAL_OIL_COS, INT_OIL_COS, PHYSICAL_TRADERS, SPECULATORS, STRATEGIC_BUYERS, REFINERS |
| AC5: Natural Gas | 6 | EP_PRODUCERS, LNG_EXPORTERS, UTILITIES_LDC, SPECULATORS, PHYSICAL_TRADERS, POWER_GENERATORS |
| AC6: Agriculture | 7 | US_FARMERS, SA_FARMERS, GRAIN_TRADERS_ABCD, CHINA_IMPORTERS, OTHER_IMPORTERS, BIOFUEL_PRODUCERS, SPECULATORS |
| AC7: FX | 8 | CENTRAL_BANKS, FX_RESERVE_MGRS, GLOBAL_ASSET_MGRS, JP_RETAIL_FX, CORPORATE_TREASURIES, HEDGE_FUNDS, SOVEREIGN_WEALTH_FUNDS, BIS_CLS |
| AC8: Crypto | 8 | ETF_ISSUERS, LONG_TERM_HOLDERS, SHORT_TERM_HOLDERS, MINERS, EXCHANGES, STABLECOIN_ISSUERS, CORPORATE_HOLDERS, WHALES |
| AC9: EM Macro | 7 | G4_CENTRAL_BANKS, EM_CENTRAL_BANKS, GLOBAL_EM_FUNDS, CROSS_BORDER_BANKS, CHINA_PBOC, FX_RESERVE_MGRS_EM, EM_SWF |

---

## 6. "Net Directional Force" — Unified Definition

Every asset class decomposition must produce a `NetDirectionalForce` object with these standardized fields:

```
NetDirectionalForce:
  direction: "POSITIVE" | "NEGATIVE" | "NEUTRAL" | "CONFLICTING"
  strength: 0.0-1.0  # conviction in the direction
  primary_component: str  # which sub-component dominates (e.g., "liability_side", "physical_supply", "rate_differential")
  secondary_component: str  # second-largest contributor
  conflict_flag: bool  # True if sub-components point in opposite directions
  conflict_detail: str | None  # e.g., "asset_side is negative but liability_side is positive, net neutral"
  key_thresholds: list[ThresholdProximity]  # which fragility thresholds are nearby
```

This unified format allows `decision.py` to ingest net directional force from ANY asset class without knowing the decomposition internals.

---

## 7. Decomposition Depth by Asset Class

Not all asset classes require the same depth of analysis. Scale decomposition by the asset class:

| Depth Tier | Asset Classes | What to Run |
|:---:|---|---|
| **Full (4-layer)** | AC1 (US Fixed Income) | Balance sheet asset/liability + entity flow + data verification + fragility check. This is the only class where the full 4-layer framework is justified, because the data is structured and the causal channels are well-defined. |
| **Standard (3-layer)** | AC4 (Oil), AC7 (FX), AC8 (Crypto) | Core decomposition + entity flow + data verification. Skip balance sheet (not applicable or dual-CB complexity). |
| **Light (2-layer)** | AC2 (US Equities), AC3 (Gold), AC9 (EM) | Flow attribution + data verification. Decomposition is flow-driven, not identity-based. |
| **Physical-only (2-layer)** | AC5 (Nat Gas), AC6 (Agriculture) | Physical S&D balance + speculative overlay. No institutional entity tracking needed. |

---

## 8. Integration Points

This routing framework touches four modules:

| Module | What Changes |
|---|---|
| `investigation_loop.py` | Add `_route_asset_class(hypothesis: str) -> AssetClassRouting` as a Pre-Act sub-step. Store routing result in `HypothesisResult.asset_class_routing`. |
| `pipeline/causal_decomposition.py` | Accept `AssetClassRouting` at initialization. Select decomposition lens from routing, not from hardcoded balance-sheet assumption. For AC4-AC9, skip balance sheet entirely. |
| `pipeline/flow_decomposition.py` | Accept `AssetClassRouting` at initialization. Instantiate entity enum from Section 5 table. Prompt Pro with asset-class-specific entity descriptions. |
| `config/` | New data module: `config/asset_class_taxonomy.py` (~120 lines) containing all tables from Sections 2 and 5. This is a data module, exempt from single-entry-point rule. |

---

## 9. Design Validation (Self-Check Against C1, C2)

**C1 (Balance sheet over-application)**:
- AC1 (US Fixed Income) is the ONLY class where balance sheet decomposition is the primary lens.
- AC2 and AC9 use liquidity-regime input from AC1 but do NOT run their own balance sheet decomposition.
- AC4-AC6 use physical S&D, not balance sheet.
- AC7 uses DUAL balance sheet (comparative, not single-entity).
- AC8 has no balance sheet at all.
- **Verdict**: C1 resolved -- balance sheet only applied to AC1; all other classes use appropriate lens.

**C2 (US-centric entity types)**:
- Each asset class defines its OWN entity set (Section 5).
- AC7 (FX) entity set includes BoJ, GPIF, Japanese retail, SAFE, SNB -- jurisdiction-appropriate.
- AC9 (EM) entity set includes G4 central banks, EM central banks, China PBoC, EPFR-tracked funds.
- AC8 (Crypto) entity set has no US-centric types at all.
- **Verdict**: C2 resolved -- entity types are asset-class-relative, not universally US-centric.
