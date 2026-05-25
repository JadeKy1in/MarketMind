# Heuristic Workflow Research 1: How Professional Analysts Process News & Form Investment Theses

**Research Date:** 2026-05-17
**Purpose:** Understand the cognitive process and decision tree that professional buy-side analysts use to go from "I see X happened" to "I should buy/sell Y" — to inform MarketMind's heuristic browsing engine.

---

## 1. The Full Analyst Workflow: Headline to Trade

### Phase 0: The Trigger — Where Ideas Come From

Buy-side analysts (at hedge funds, asset managers, institutional investors) draw ideas from two broad buckets:

| Source | Examples |
|---|---|
| **Qualitative (~75%)** | Company presentations, news headlines, due diligence on existing holdings, "rich text screening" for keywords like "acquisition" or "restructuring," sell-side relationship calls, industry conferences |
| **Quantitative (~25%)** | Screens for stocks underperforming market/peers, screens for depressed operating margins vs. history, sentiment rankings, systematic factor scans |

**Key filter at this stage:** *Stay within your circle of competence.* Analysts do not start from a blank universe; they start from familiarity — an industry they already understand, a business model they've seen work, or a change that raises a question.

### Step-by-Step Workflow

```
HEADLINE / NEWS TRIGGER
        |
        v
  MORNING TRIAGE -- Filter: circle of competence? catalyst? variant view?
        |
        v
  QUALITATIVE DEEP DIVE -- 10-Ks, transcripts, sell-side notes, value chain map
        |
        v
  STRATEGIC PRESSURE TEST -- Moat, industry structure, pricing power, bear case
        |
        v
  QUANTITATIVE MODELING -- Forecasts, forensic accounting, valuation (DCF + comps)
        |
        v
  FULL PICTURE CHECK -- Catalysts, flow, insider activity, consensus vs. variant
        |
        v
  INVESTMENT MEMO -- Thesis + drivers + risks + price targets + variant view
        |
        v
  PM / IC PRESENTATION -- Debate, size, decide (buy / watch / pass)
        |
        v
  ONGOING MONITORING -- Daily news, thesis integrity checks, sell discipline
```

### Detailed Steps

**Step 1: Morning Brief & News Triage (6:00-7:00 AM)**
- Check foreign/overnight markets (futures, Asian/European close) as a proxy for U.S. open
- Scan 50-60+ emails from sell-side research desks, sales teams, news aggregators
- Morning meeting (7:00 AM) with portfolio team — discuss key positions, concentration issues, underperformers, flag news-driven opportunities
- **Core question:** *What matters today, and for the next few days?*

**Step 2: First-Pass Filter — "Is This Worth My Time?"**

| Filter Question | What You're Testing |
|---|---|
| Can I explain this business in plain language? | Circle of competence |
| Does it have a clear, repeatable way of creating value? | Business model durability |
| Is there a genuine **catalyst** or change driving this? | Why now? (Not just "good company") |
| Is the market missing something? | Variant perception vs. consensus |

**Good investors try to kill ideas early rather than fall in love with them.**

**Step 3: Initial Qualitative Research ("Understand the Business First")**
- **Notice: buy-side analysts do NOT start with models or valuation.** This phase is purely strategic.
- Read sell-side initiation reports and recent broker notes (consensus framing, but maintain skepticism)
- Read company materials: 10-K, 10-Q, earnings transcripts, investor day presentations
- **Map the value chain**: Who are the suppliers? The customers? Where does pricing power sit?
- **Identify critical factors** — the 3-5 variables that will drive stock performance
- **Interview industry contacts**: Distributors, former executives, channel partners, procurement leads (proprietary primary research that distinguishes buy-side from sell-side)

**Step 4: Pressure-Test the Strategic Thesis ("Try to Kill It")**
- Competitive moat assessment: switching costs, network effects, brand, cost advantage, regulation, intangibles
- Industry structure analysis: Does the industry naturally concentrate value, or does competition erode returns?
- Customer/pricing power analysis: How much pricing power exists? How easy to switch?
- Management & governance: Track record, capital allocation history, insider ownership, incentives
- **The bear case is built first.** Key questions:

> *"What could realistically go wrong? Could technology change the economics? Could regulation shift? Could a new competitor attack the core? What is the most likely way this goes to zero?"*

**Step 5: Deep Quantitative Work ("Build the Model")**
- Financial model construction: 3-statement model with scenario-driven forecasts
- Forensic accounting review: Yellow/red flags in revenue recognition, working capital, non-GAAP adjustments
- Peer benchmarking: Side-by-side on margins, growth, ROIC, multiples
- **Valuation (multi-method)**: DCF (preferred), P/E, EV/EBITDA, P/S vs. peers and history, bear/base/bull price targets

**Step 6: Full Picture Check — Catalysts, Flow, and Sentiment**

| Layer | What's Checked |
|---|---|
| **Catalyst calendar** | Earnings dates, FDA/regulatory decisions, conferences, product launches, contract expirations |
| **Institutional flow / positioning** | Unusual options activity, block trades, 13F filings, short interest/float |
| **Insider activity** | SEC-reported insider buying/selling — are executives aligned? |
| **Sell-side consensus** | Where does Wall Street stand? Recent upgrades/downgrades? |
| **Sentiment signals** | News sentiment, social media, developer activity (tech), customer reviews |

**Step 7: Synthesize the Investment Case ("Write the Memo")**
- Deliverable: **Confidential investment memo** (proprietary IP, not a public report)
- Must answer the 7 critical elements (James Valentine's framework):
  1. What is the recommendation? (Buy/Sell/Hold)
  2. What is the price target?
  3. What is the catalyst?
  4. What is the variant perception?
  5. What are the risks?
  6. What is the time horizon?
  7. What would invalidate the thesis?

**Step 8: Internal Presentation & Debate**
- Present to portfolio manager (PM) or investment committee
- PM pressure-tests: inventory levels, customer concentration, macro sensitivity
- Decision: initiate position, add to watchlist with trigger levels, or pass

**Step 9: Ongoing Monitoring & Maintenance**
- Daily monitoring of news, price action, any signal touching the thesis's critical factors
- Flash reports on material events (earnings, guidance, M&A, regulatory)
- Regular thesis review: "Is the thesis intact?"
- **Sell discipline**: Exit when (a) price target reached, (b) thesis factor breaks, or (c) better risk/reward emerges

---

## 2. The Hierarchy of Evidence: Signal -> Verify -> Cross-Check -> Decide

### The Core Pipeline Pattern

Across systematic investing, quant research, and institutional decision-making, a recurring pattern emerges:

| Stage | What Happens |
|---|---|
| **Signal** | Detect raw indicators from data |
| **Verify** | Validate against independent sources |
| **Cross-Check** | Triangulate across multiple data streams (fundamentals, technicals, estimates, alternatives) |
| **Decide** | Convert validated evidence into an actionable verdict |

### Framework 1: Signal Architecture Canvas (FMP)

A four-stage framework:
- **Input** -> Normalized data (price, valuation, technicals)
- **Logic** -> Rules defining how inputs interact
- **Insight** -> A defensible conclusion
- **Action** -> A portfolio/risk decision based on the insight

### Framework 2: Cross-Dataset Triangulation

Detecting mispricings by aligning three data streams:
- **Fundamental Reality** (ROIC, capital efficiency)
- **Market Expectation** (analyst consensus estimates)
- **Price Truth** (volatility, support levels)

### Framework 3: BlackRock's Alternative Data Evaluation Process
- **Originality** testing
- **Completeness & coverage**
- **Statistical power** (Information Coefficient, Predictive R-squared)
- **Additivity & redundancy checks** (cross-signal validation)
- **Economic intuition testing**

### Framework 4: Top-Down vs. Bottom-Up Analysis Chains

**Top-Down (Macro -> Micro):**
```
STEP 1: MACROECONOMIC ANALYSIS
  GDP growth, inflation, interest rates, monetary/fiscal policy
  Identify phase of the business cycle (Expansion/Peak/Contraction/Recovery)
      |
      v
STEP 2: SECTOR & REGION SELECTION
  Which sectors benefit from the current/next cycle phase?
  Cyclical vs. Defensive rotation, geographic allocation
      |
      v
STEP 3: INDUSTRY-SPECIFIC ANALYSIS
  Competitive landscape, regulatory & technological trends, supply/demand
      |
      v
STEP 4: COMPANY SELECTION
  Financial statement analysis, valuation (P/E, P/B, DCF), management quality
```

**Bottom-Up (Micro -> Macro):**
```
STEP 1: COMPANY FUNDAMENTALS
  Revenue growth, profit margins, ROE, balance sheet strength, cash flow quality
      |
      v
STEP 2: COMPETITIVE POSITIONING
  Moat analysis, market share, industry structure, peer comparison
      |
      v
STEP 3: VALUATION ASSESSMENT
  DCF, P/E, P/B, EV/EBITDA, margin of safety vs. intrinsic value
      |
      v
STEP 4: MACRO OVERLAY (Final Check)
  Does the macro environment pose a material threat?
  How has the stock behaved in prior economic cycles?
```

### Goldman Sachs Hybrid: Macro-to-Micro Bridge

**Phase A: Business Cycle Identification**
- Use a Global Leading Indicator (GLI) to define four phases: Expansion, Slowdown, Contraction, Recovery

**Phase B: Six-Factor Macro Regression**
- For each phase, map stocks against: market risk (beta), domestic growth, domestic policy/liquidity, domestic inflation, oil prices, global growth
- Each stock receives a **macro score** based on regression sensitivities

**Phase C: Micro Factor Overlay (Micro Z-score)**
- **Valuation**: Forward P/E, dividend yield, P/B
- **Fundamentals**: Earnings revisions (magnitude & breadth), target price changes
- **Technical indicators**: RSI (momentum), Bollinger Bands (volatility), MACD (trend)

**Result**: Stocks ranked by summing macro and micro scores. Backtest: ~11.4% annualized outperformance.

### MFS Macro/Micro Forum: Divergence as Signal

MFS runs a quarterly Macro/Micro Forum:
- **Scoring Dimensions**: Labor, Capex, Revenue Growth, Profit Margins
- **Scale**: 1=above-trend, 2=normalized, 3=below-trend
- **Decision Rule**: When macro and micro scores **diverge**, it signals potential inflection points and contrarian opportunities

**2022-2023 Case Study**: Macro was "flashing red" (recessionary, aggressive Fed, banking crisis). Micro told a different story (labor hoarding, locked-in low mortgages, resilient consumer, strong pricing power). MFS added credit risk when spreads priced near-certain recession, capturing significant alpha as spreads compressed.

---

## 3. Heuristic Browsing: How Analysts Decide What to Read Deeply vs. Skim

### The Expectation Gap: The Core Heuristic

From Quant StackExchange research:

> *"The price move caused by news is the difference between the actual information and what the market had already expected."*

Three scenarios for the **same fundamental outcome** (company worth 10% less):

| Scenario | What Happens | Price Reaction |
|----------|-------------|----------------|
| **A** - Pure surprise | No one saw it coming | Stock down 10% |
| **B** - Fully priced in | Market quietly marked it down over weeks | Stock **unchanged** |
| **C** - Over-priced-in | Market marked it down 15% on fear; actual problem smaller | **Relief rally +5%** |

**Implication for news triage: The market doesn't react to *what happened* — it reacts to the *delta* between what happened and what was already discounted.** An analyst should filter headlines through this lens immediately.

### Three-Step Triage Framework (Longbridge Research)

**Step 1: What is the Consensus?**
Identify the sell-side/economist consensus as the anchor. This is the most direct gauge of "what the market expects."

**Step 2: Where Does the Market Stand Relative to Consensus?**
Use **three independent dimensions** to triangulate positioning:
- **Equities (sector ETFs)**: How have the most correlated stocks been trading into the event? Are they already pricing in the tail outcome?
- **Rates (e.g., 2Y Treasury)**: What is the rates market saying about policy path expectations? A flat 2Y yield suggests no hawkish repositioning.
- **Derivatives / TIPS / Breakevens**: What is the most "honest" market-implied forecast? These are arbitrage-enforced and hard to fake.

**Step 3: Map the Gap -> Asymmetric Risk**
Once you know consensus and market stance, identify the **asymmetric fulcrum point** — the threshold where a data print shifts from "priced in / boring" to "genuine rerating event."

### Common Triage Errors

1. **"Known = Priced In" fallacy**: Just because something is widely known doesn't mean it's fully discounted. If there's high *dispersion* around consensus, pricing is incomplete.
2. **Over-reliance on a single indicator**: VIX alone, or any single metric, is insufficient. Cross-asset triangulation matters.
3. **Conflating event-level vs. trend-level**: News triage is for tactical positioning; don't let an event framework shake a structural thesis.
4. **Using analysis as a substitute for position sizing**: Even the best "priced in" analysis doesn't justify full conviction bets.

### The "Roulette Wheel" Trap

One trading desk kept an Excel macro that would **randomly generate a plausible-sounding explanation** for any unexplained price move ("merger talk," "JP Morgan bought 500," "North Korean missile test"). The point: much of the real-time "news explanation" on Bloomberg/CNBC is **post-hoc narrative construction**, not genuine causal attribution. Analysts learn to distinguish between genuine catalysts and post-hoc rationalization.

### Psychological Anchors in Triage (Birru 2015)

- **52-week high** acts as a psychological anchor that systematically biases expectations
- Near 52-week highs -> analysts become **downward-biased** in forecasts -> positive surprises more likely
- Far from 52-week highs -> **upward-biased** expectations -> negative surprises more likely
- This connects to **PEAD (Post-Earnings Announcement Drift)** — stocks drift in the direction of surprise for weeks afterward

---

## 4. Data Cross-Referencing: From Hunch to Verification Chain

### Typical Cross-Referencing Chains

**Chain 1: Policy News**
```
Policy announcement (Fed, fiscal, regulatory)
    -> Check interest rate futures (Fed Funds futures, Eurodollar)
    -> Check sector ETF flows (XLF, XLI vs. XLU, XLP rotation)
    -> Check individual stock sensitivity (rate-sensitive names, banks, REITs)
```

**Chain 2: Geopolitical News**
```
Geopolitical event (conflict, sanctions, trade war)
    -> Check commodity prices (oil, gold, wheat, rare earths)
    -> Check supply chain stocks (semis, logistics, shipping)
    -> Check currency pairs (ruble, yuan, euro vs. dollar)
    -> Check defense/aerospace stocks
```

**Chain 3: Company-Specific News**
```
Earnings surprise / guidance change
    -> Check peer stock reactions (sector-wide or company-specific?)
    -> Check options market (implied volatility, put/call skew)
    -> Check insider filings (any recent buying/selling?)
    -> Check short interest (was this a squeeze candidate?)
    -> Check sell-side revisions (were analysts behind?)
```

**Chain 4: Macro Data Print**
```
Economic data release (CPI, NFP, GDP)
    -> Check bond yields (2Y, 10Y, breakevens)
    -> Check Fed Funds futures (implied rate path shift)
    -> Check USD index (dollar reaction)
    -> Check sector rotation (cyclical vs. defensive)
    -> Check gold (inflation hedge signal)
```

### The Information Edge Hierarchy

The SIS International Research framework maps source value and edge decay:

| Source Tier | Use Case | Edge Decays In |
|---|---|---|
| Sell-side research | Consensus benchmarking | Immediate |
| Data subscriptions (Bloomberg, FactSet) | Screening, monitoring | Immediate |
| Expert networks (transactional) | Hypothesis testing | **Weeks** |
| Commissioned primary research | Thesis construction, sizing | **Quarters** |
| Proprietary panels, longitudinal VOC | Multi-cycle conviction | **Years** |

**Key insight: The further down the stack an analyst goes, the longer the information edge persists.** The best funds treat research as proprietary input, not a shared utility.

### The Investigative Sequence (SIS Framework)

For allocators following a lead:

1. **Category Structure** — Map the value chain, concentration, and pricing power. *Output: which seat in the chain captures economics.*
2. **Demand Verification** — Test end-customer behavior through voice-of-customer (VOC). *Output: does the demand narrative survive contact with buyers?*
3. **Competitive Position** — Run win/loss analysis and procurement interviews. *Output: are share gains durable or promotional?*
4. **Catalyst Sizing** — Quantify the event driving the trade. *Output: probability-weighted position size.*

**Critical warning: Allocators who skip to Stage 4 underwrite catalysts without verified demand.** The result is correctly identified events with mispriced magnitudes.

### Source Triangulation (Altss)

Formal discipline of cross-referencing claims across independent source types:
- **Tier 1**: Regulatory filings (SEC, CFTC)
- **Tier 2**: Verified press (not syndicated copies)
- **Tier 3**: Direct observation (store visits, channel checks)

Source independence is critical — treating high-volume derivative mentions as independent verification is a fallacy.

---

## 5. Key Frameworks: Druckenmiller, Soros, Dalio

### Stanley Druckenmiller — "Listen to the Market, Then Verify"

**Core Philosophy**: Price action is the primary disciplinary tool. For 35+ years, the interplay between price movement and news flow validated or invalidated his theses.

**Decision Process**:
1. **Form a contrarian thesis** — unique, forward-looking (18-24 months ahead), not yet priced in
2. **Build a starter position** and wait for price confirmation
3. **When momentum shifts in his favor -> "pile in"** — the "Big Bet" philosophy, learned from Soros
4. **If price action contradicts the thesis -> cut immediately.** Soros described as "the best loss taker I've ever seen"
5. **Use technicals for timing, fundamentals/valuation only for sizing** (how far a move can go)

> *"Earnings don't move the overall market; it's the Federal Reserve Board... it's liquidity that moves markets."*

**The Machine Problem**: Druckenmiller admits passive/algorithmic investing has disrupted his price-action discipline. When algos dominate, price signals no longer reliably correlate with news. He now runs small amounts with machine-driven strategies purely to receive their signals as "one more input."

### George Soros — Reflexivity: The Market Is Always Wrong

**Core Philosophy**: Markets are **always wrong** — they present a biased view of the future. The theory of reflexivity explains why.

**Reflexivity Explained**: A two-way feedback loop:
- **Cognitive function**: how participants perceive the environment (biased, incomplete)
- **Manipulative function**: how their actions change the environment

Cycle: biased perceptions -> actions -> impact on reality -> change in perceptions -> new actions...

This produces **boom/bust cycles** built on a real trend distorted by a collective misconception. Prices don't just reflect fundamentals — they actively change them.

> *"Every bubble consists of a trend that can be observed in the real world and a misconception relating to that trend."*

**Decision Process**:
- **Work with a hypothesis**: investing is submitting a hypothesis to practical test. The market is the laboratory.
- **Identify false trends**: beliefs founded on false assumptions that become self-reinforcing through reflexivity. Participate, but maintain objectivity to exit before they collapse.
- **Bet big when conviction is high**: *"It's not whether you're right or wrong, but how much money you make when you're right and how much you lose when you're wrong."*
- **"Insecurity analysis"**: Soros calls himself an *insecurity analyst* — he knows he may be wrong, so he constantly watches for discrepancies between expectations and reality. *"I'm only rich because I know when I'm wrong."*

**Soros-Druckenmiller Connection**: Druckenmiller was Soros's protege at Quantum Fund for 12 years. The Black Wednesday (1992) trade: Druckenmiller wanted to short $5.5 billion. Soros: "That is the most ridiculous use of money management I ever heard. We should have 200% of our net worth in this trade." They made $1 billion.

### Ray Dalio — The Machine: Principles Encoded into Algorithms

**Core Philosophy**: Human emotions are the biggest obstacle to good investing. Answer: **convert decision-making principles into algorithms**, creating an "idea meritocracy where the best ideas win out over human bias, emotion, and blind spots."

> *"Markets are cold machines. Investors are emotional."*

**Decision Process**:
1. **Write down principles**: every painful mistake -> "What decision rule would have avoided this?" -> write it down
2. **Encode into algorithms**: since the 1980s, principles fed into "expert systems" that process data and output recommended decisions
3. **Human + machine partnership**: like driving with a GPS. Computer suggests, human evaluates and overrides if needed. *"You make the move, it makes the move. You compare and refine."*
4. **Believability-weighted decisions**: the "Dot Collector" tool lets colleagues rate each other. When deciding, votes are weighted by each person's "believability" on that topic — not democratic, not autocratic.
5. **Continuous stress-testing**: radical transparency — every conversation recorded and visible to all.

**Results**: Bridgewater runs ~$160 billion. 23 profitable years out of 26.

**Critical Distinction**: Dalio insists on **understanding the algorithm** (expert systems he designed) vs. blindly trusting black-box ML. *"If you don't understand the algorithm and the future differs from the past, you're in big trouble."*

### Three Philosophies Compared

| Dimension | **Druckenmiller** | **Soros** | **Dalio** |
|---|---|---|---|
| **Primary signal** | Price action vs. news | Reflexive feedback loops | Encoded principles + data |
| **Verification method** | Does the market move with the thesis? If no, cut. | Watch for discrepancy between expectation and reality. | Algorithmic output vs. human judgment, debated openly. |
| **Role of conviction** | Bet the ranch when signals align. | Bet big when hypothesis strong, odds favorable. | Believability-weighted group decision; conviction distributed. |
| **Error handling** | Cut immediately, no ego. "Wipe the slate clean any day." | "Insecurity analyst" — always questioning own thesis. | Principles refined after every mistake; system evolves. |
| **View on machines** | Disruptive to price signals; reluctantly incorporating as input. | N/A — largely pre-algorithmic era. | Core to entire process for 35+ years. |

---

## 6. The "Sleuth" Method: Hunch-Driven Investigative Research

Avner Mandelman (Giraffe Capital) formalized the hunch-driven, lead-following approach in *The Sleuth Investor* (2007) and *The Advanced Sleuth Investor* (2023).

### Core Premise
SEC filings, annual reports, and press releases are insufficient. To uncover lucrative investments, an analyst must **"dig beneath the printed surface of public information and sleuth for physical evidence."**

### The "Four P's" Framework

| Element | What to Investigate |
|---|---|
| **People** | Employees, customers, suppliers — get information from low-level employees, people in bars, Uber drivers, anyone in the ecosystem |
| **Product** | Physical movement of inventory, the product's journey, competing products |
| **Periphery** | Physical surroundings, community, the "economic eco-chain" |
| **Plant** | Production facilities, offices, factory utilization |

**His favorite research tools**: "A phone — and beer."

### The Three Criteria for Useful Information

> *"For a piece of information to be useful for an investor, it has to have three criteria. It has to be **true**, it has to be **significant**, and it has to be **exclusive to you**. The only way to generate it is to do the work yourself."*

### The Hunch-to-Trade Arc

1. **A hunch forms** — anomaly in the numbers, something heard from a supplier, a product that seems to be everywhere (or nowhere), an industry contact's offhand comment
2. **The hunch is stress-tested cheaply** — before building any model, try to *kill the idea* by talking to practitioners. Funds like Citadel, Point72, Millennium have built internal expert networks for this.
3. **Physical evidence is gathered** — store visits, factory gate checks, dealer foot traffic, freight lane density
4. **If the lead survives, it's escalated** — from hypothesis testing to thesis construction, competitive intelligence audits, voice-of-customer programs, and finally to position sizing
5. **Conviction builds when multiple pieces align** — business model makes sense, competitive position is defensible, management incentives are rational, industry dynamics support the story. Only then does deep financial modeling begin.

### The Hunterbrook Model: Journalism-as-Investment-Research

A recent evolution — a hybrid hedge fund/investigative journalism outfit ($100M raised):
- **Hunterbrook Media** investigates companies using only public information
- **Hunterbrook Capital** trades on findings before publication
- Investigations have <50% hit rate on turning into trades — many leads go nowhere, which is accepted as part of the process
- The model formalizes the hunch-following process: investigate -> gather evidence -> if the case is strong, trade -> then publish

---

## 7. Decision Chain Mapping: The Institutional Gate System (Altss)

### The 7-Stage Decision Chain

| # | Stage | Who's Involved | Role |
|---|-------|----------------|------|
| 1 | **Screening** | Analyst, Associate | Initial filter — does the opportunity fit the mandate? |
| 2 | **Investment Team Evaluation** | Senior professionals | Deeper diligence on strategy, team, track record |
| 3 | **IC Memo Authoring** | Designated team member | Building the written case for the investment committee |
| 4 | **IC Presentation** | Presenter + IC members | Live recommendation and Q&A |
| 5 | **IC Vote** | Investment Committee | Formal approval (or rejection) decision |
| 6 | **Legal/Compliance Review** | Legal & Compliance teams | Terms validation, risk mitigation |
| 7 | **Final Signature** | CFO or Principal | Execution — subscription documents, funding |

### Chain Complexity

| Complexity | Type | Steps |
|------------|------|-------|
| **Simple** | Principal-led | 1-2 steps |
| **Moderate** | CIO-led | 3-4 steps (including IC) |
| **Complex** | Institutional | 5-7 steps (multiple committees) |

### Key Insights for Decision Design

1. **"CIO is not the decision-maker"** — many recommend but don't approve; IC or principal holds final authority
2. **"One pitch fits all" is a mistake** — analysts want detail, IC members want thesis summary, legal wants risk mitigation
3. **Chains aren't linear** — they're often iterative, looping back for questions and clarifications
4. **Gate clarity reduces drift** — undefined gate criteria cause "one more question" loops and late-stage reversals
5. **Execution is a separate risk** — approval doesn't equal funding; the handoff from IC to legal/subscription is a common failure point

---

## 8. Synthesis: The Cognitive Decision Tree

Drawing from all sources, here is the unified cognitive model of how a human analyst's mind navigates from headline to trade:

```
HEADLINE APPEARS
    |
    |--- Q1: IS THIS IN MY CIRCLE OF COMPETENCE?
    |       NO  -> Skip (or note for later)
    |       YES -> Continue
    |
    |--- Q2: WHAT IS THE CONSENSUS EXPECTATION?
    |       (i.e., what was "priced in" before this headline?)
    |       -> Check: sell-side estimates, economist forecasts, recent price action
    |
    |--- Q3: WHAT IS THE SURPRISE / EXPECTATION GAP?
    |       (How far does this news deviate from consensus?)
    |       GAP IS SMALL OR ZERO -> Skip (already priced)
    |       GAP IS LARGE -> Continue
    |
    |--- Q4: IS THE SURPRISE DIRECTIONALLY CLEAR?
    |       (Positive or negative for what assets, specifically?)
    |       UNCLEAR -> Defer to macro/futures/rates for direction signal
    |       CLEAR -> Continue
    |
    |--- Q5: IDENTIFY THE AFFECTED CHAIN
    |       (What is the first-order, second-order, third-order impact?)
    |       -> Map: policy -> rates -> sectors -> stocks
    |       -> Map: geopolitics -> commodities -> supply chain -> FX
    |       -> Map: company news -> peers -> suppliers -> customers
    |
    |--- Q6: CROSS-REFERENCE WITH INDEPENDENT DATA STREAMS
    |       -> Rates/bonds confirming or contradicting?
    |       -> Sector ETFs already moved or not?
    |       -> Options market pricing the gap?
    |       -> Insider activity aligned or contradictory?
    |       ALL ALIGNED -> High conviction
    |       SOME CONTRADICT -> Investigate why; skepticism warranted
    |       MOST CONTRADICT -> Defer or fade the consensus
    |
    |--- Q7: TRY TO KILL THE THESIS
    |       -> What is the bear case?
    |       -> What is the most likely way this thesis goes to zero?
    |       -> Is the information true, significant, and exclusive?
    |       THESIS SURVIVES -> Build model
    |       THESIS BREAKS -> Abandon
    |
    |--- Q8: SIZE THE TRADE
    |       -> Conviction level? (believability-weighted)
    |       -> Asymmetric payoff? (reward >> risk)
    |       -> Portfolio impact? (correlation, concentration)
    |       -> Time horizon? (catalyst date)
    |
    |--- Q9: DECIDE AND MONITOR
    |       -> Enter position (starter or full size)
    |       -> Set invalidation criteria upfront
    |       -> Monitor: thesis factors intact? price confirming?
    |       -> Exit discipline: thesis breaks OR target reached OR better opportunity
```

---

## 9. Implications for MarketMind's Heuristic Browsing Engine

### What to Model

1. **The expectation gap heuristic**: Every news item should be evaluated against "what was priced in." This requires measuring the delta between the signal and consensus expectations.

2. **Cross-asset triangulation**: A single signal is noise. Multi-stream confirmation (rates + equities + derivatives + flows) is where conviction lives. MarketMind should never fire on one data point.

3. **Affected-chain mapping**: News doesn't impact assets in isolation. The engine should trace N-order effects: policy -> rates -> sectors -> stocks; geopolitics -> commodities -> supply chains -> FX.

4. **The "try to kill it" step**: Every generated thesis should include an auto-generated bear case. This mirrors what the best analysts do manually.

5. **The information hierarchy**: Price data is a timing filter, not a signal source (already encoded in MarketMind's anti-overfitting rule). True edge comes from proprietary synthesis of public information — the engine's role is to do the cross-referencing that would take a human hours.

6. **Druckenmiller's price-action verification**: Price movement should confirm or contradict the thesis signal. If the market isn't moving with the signal, the signal is noise.

7. **Soros's reflexivity lens**: Check whether market perception (price action) is creating a feedback loop that changes fundamentals. This is the "bubble detection" angle.

8. **Dalio's principle-encoding**: the engine's decision rules should be explicit, auditable, and refinable. No black-box ML where the logic can't be inspected.

### What NOT to Model

- **Real-time trading signals**: MarketMind is analysis-only (physical isolation from brokerage APIs)
- **Black-box ML predictions**: The Dalio principle applies — the algorithm must be inspectable
- **Post-hoc narrative**: Avoid the "Roulette Wheel" trap of generating plausible-sounding explanations for random price moves

---

## Sources

- [What Makes a Good Equity Research Report? (Hebbia)](https://www.hebbia.com/resources/equity-research-report)
- [How to Research a Stock: A Complete Guide for Active Traders (Benzinga)](https://www.benzinga.com/pro/blog/how-to-research-a-stock-a-complete-due-diligence-guide-for-active-traders)
- [The Genius of Stan Druckenmiller: Lessons for Investors (Latticework)](https://www.latticework.com/p/the-genius-of-stan-druckenmiller)
- [Discount the obvious, bet on the unexpected (Morningstar)](https://www.morningstar.in/posts/48402/discount-obvious-bet-unexpected.aspx)
- [How George Soros Finds His Trades (GuruFocus)](https://www.gurufocus.com/news/540468/how-george-soros-finds-his-trades)
- [George Soros, Reflexivity, And His Success (Seeking Alpha)](https://seekingalpha.com/article/4150644-george-soros-reflexivity-and-his-success)
- [Ray Dalio Launches 'Digital Ray' AI Twin (Yahoo Finance)](https://finance.yahoo.com/sectors/technology/articles/ray-dalio-launches-digital-ray-220104608.html)
- [Ray Dalio Reveals He Has Been Using AI For Decision Making Over 35-40 Years (Asianet News)](https://newsable.asianetnews.com/markets/ray-dalio-reveals-he-has-been-using-ai-for-decision-making-over-35-40-years-says-it-s-big-part-of-what-made-bridgewater-successful-articleshow-z5wp5af)
- [Markets are cold machines. Investors are emotional: Ray Dalio (Fortune India)](https://www.fortuneindia.com/business-news/markets-are-cold-machines-investors-are-emotional-ray-dalio/128970)
- [Trading Lessons From the Great Stanley Druckenmiller (GuruFocus)](https://www.gurufocus.com/news/462609/trading-lessons-from-the-great-stanley-druckenmiller)
- [Top Down vs. Bottom Up Analysis (Britannica Money)](https://www.britannica.com/money/top-down-vs-bottom-up-analysis)
- [Combining macro and micro the Mill Street way (Mill Street Research)](https://www.millstreetresearch.com/combining-macro-and-micro-the-mill-street-way/)
- [Goldman Sachs and the art of macro stock screening (Business Insider)](https://www.businessinsider.com/goldman-sachs-and-the-art-of-macro-stock-screening-2013-2)
- [Using Top-Down and Bottom-Up Insights to Manage Risk (MFS)](https://www.mfs.com/en-jp/institutions-and-consultants/insights/portfolio-insights/macro-micro-construct-robust-risk-budgeting.html)
- [Private Equity-backed Hedge Fund Macro Investment Analysis Process (Process Street)](https://www.process.st/templates/private-equity-backed-hedge-fund-macro-investment-analysis-process/)
- [How Do You Actually Find Investing Ideas? (PrepLounge)](https://www.preplounge.com/finance-forum/how-do-you-actually-find-investing-ideas-24083)
- [Expectation gap: price move = actual - expected (Quant StackExchange)](https://quant.stackexchange.com/)
- [Psychological Barriers, Expectational Errors, and Underreaction to News (Birru, 2015)](https://www.semanticscholar.org/paper/Charles-A.-Dice-Center-for-Research-in-Financial-to-Birru/93b06d75fe8ef42869824352e10278efe9470410)
- [The Sleuth Investor (Mandelman, 2007)](https://books.google.com.sg/books?id=sWuoBpv1wsYC)
- [Issue #78 - Nightview Capital: Fundamental equity investors](https://www.nightviewcapital.com/issue-78-8ncyj-r7fhx-z59l5/)
- [Fund managers use tactics to uncover problems (News24)](https://www.news24.com/business/Companies/Financial-Services/Fund-managers-use-tactics-to-uncover-problems-20140812)
- [Hunterbrook Launches the "Hedge Fund That's Also a Newspaper" (Politico)](https://www.politico.com/news/magazine/2024/05/25/hunterbrook-media-sam-koppelman-journalism-00158129)
- [This news-driven hedge fund has made headlines — here's how it works (Business Insider)](https://www.businessinsider.com/hunterbrook-capital-news-hybrid-hedge-fund-2024-4)
- [Source triangulation (Altss Taxonomy)](https://altss.com/taxonomy/source-triangulation)
- [Decision Chain Mapping (Altss Glossary)](https://altss.com/glossary/decision-chain-mapping)
- [Investment Decision Chain (Altss Taxonomy)](https://altss.com/taxonomy/investment-decision-chain)
- [Building a Market Insight Framework with FMP (Financial Modeling Prep)](https://intelligence.financialmodelingprep.com/education/financial-analysis/building-a-market-insight-framework-with-fmp--turning-price-fundamentals-and-technicals-into-actionable-research-signals)
- [Cross-Dataset Anomaly Detection (Financial Modeling Prep)](https://intelligence.financialmodelingprep.com/education/financial-analysis/crossdataset-anomaly-detection-spotting-conflicts-between-price-fundamentals-and-estimates)
- [How LinqAlpha assesses investment theses using Devil's Advocate on Amazon Bedrock (AWS)](https://aws.amazon.com/cn/blogs/machine-learning/how-linqalpha-assesses-investment-theses-using-devils-advocate-on-amazon-bedrock/)
