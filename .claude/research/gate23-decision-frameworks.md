# Gate 2 & Gate 3 Design Research: Decision Frameworks & Risk Calibration

**Date**: 2026-05-18
**Purpose**: Inform the design of MarketMind Gate 2 (Signal Confirmation) and Gate 3 (Position Decision) with institutional investment frameworks.
**Focus**: PROCESS (how decisions flow through checkpoints) and RISK (how position size/risk is calibrated).

---

## 1. How Investment Committees Gate Decisions

### 1.1 The Three-Gate PE Model (Industry Standard)

The dominant institutional structure uses three formal gates, each producing a written go/no-go decision:

| Gate | Decision Question | Key Activities |
|------|-------------------|----------------|
| **Gate 1 – Screening** | Do we investigate this deal? | Initial market/competition/economics evaluation; allocate research resources; form team |
| **Gate 2 – Term Sheet / Deep Analysis** | Should we commit resources and sign? | Iterative deep analysis; engage legal/audit/advisors; negotiate structure and price |
| **Gate 3 – Final Execution** | Should we sign and execute? | Finalize agreements; confirm all diligence; final duty-of-care review |

**Key principle**: "Gates without decisions are status meetings — don't hold them." Every gate must end with one of three outcomes: continue as planned, change price/structure, or stop.

**MarketMind mapping**: Gate 1 (Direction) maps to Screening. Gate 2 (Signal Confirmation) maps to the deep analysis checkpoint — the point where conviction is tested from multiple angles before resources are committed. Gate 3 (Position Decision) maps to Final Execution — the point where analysis converts to action.

### 1.2 Decision Chain Mapping

Every institutional investment flows through a sequential chain:

```
Idea Generation → Initial Evaluation → IC Memo → IC Presentation → IC Vote → Legal/Compliance → Final Signature
```

Each link in the chain has a distinct audience and information requirement:
- **Analyst gate**: Wants data completeness, model validation, edge cases
- **IC gate**: Wants thesis clarity, risk/reward asymmetry, portfolio fit
- **Legal/compliance gate**: Wants restricted-list checks, insider-risk screening, regulatory conformance

**MarketMind application**: Gate 2 maps to the "IC Memo + IC Presentation" links. The AI presents multi-angle confirmation (L1-L3 analysis, Red Team, resonance, fragility, ELITE shadow consensus) structured so the user can interrogate each angle before advancing to Gate 3.

### 1.3 Governance Cadence (Ongoing Checkpoints)

Institutional processes layer checkpoints at multiple frequencies:

| Layer | Frequency | Purpose |
|-------|-----------|---------|
| Stand-up | Daily | Protect critical path, clear blocks, RAG status |
| Sponsor touchpoint | Twice weekly | Unlock decisions, address resource needs |
| Cross-stream sync | Weekly | Clear dependencies (legal, ops, tech) |
| Formal gates | Per-phase | Go/continue/stop with written outcomes |

**MarketMind application**: Gate 2 already has this cadence implicitly — L1 (daily stand-up depth), L2 (deeper review), L3 + Red Team (cross-stream sync). Gate 2 formalizes the "present to IC" moment.

### 1.4 Voting Mechanics & Decision Rules

Professional ICs define:
- **Voting membership** vs. advisory-only roles
- **Quorum rules**: minimum members for a valid decision
- **Thresholds**: simple majority, supermajority, or unanimity (common in PE)
- **Conditional vs. final approval**: "Approved subject to ODD/legal" vs. binding commitment
- **Veto gates**: Which functions (legal, compliance, ODD) can block post-vote execution
- **Dissent documentation**: Dissent is recorded, not hidden behind false consensus

**MarketMind application**: Gate 2's ELITE shadow agents function as voting members — each domain expert casts a perspective (confirm/challenge/neutral). The shadow consensus report is analogous to an IC vote tally with recorded rationale. Gate 3 adds the user's own "veto gates" — risk limits, position caps, stop-loss levels that block execution if violated.

---

## 2. Position Sizing & Risk Calibration Frameworks

### 2.1 Kelly Criterion: Mathematical Foundation

The Kelly Criterion provides the theoretical optimal bet size based on edge and odds:

```
K% = W - (1 - W) / R

Where: W = win probability, R = win/loss ratio (avg gain / avg loss)
```

**Critical implementation rules from practitioners**:

1. **Always use fractional Kelly**. Full Kelly is mathematically optimal but produces 50%+ drawdowns that are psychologically untenable. Half-Kelly sacrifices ~25% of returns for ~50% reduction in volatility. Quarter-Kelly is the conservative baseline.

2. **Account for correlations**. A portfolio of five positions all driven by the same factor is "one bet, not five." Position sizing must incorporate pairwise correlations — a strong edge on a highly correlated position gets a smaller allocation than the same edge on an uncorrelated asset.

3. **Higher volatility → smaller bets**. When implied volatility spikes, the "edge" shrinks because a wider range of outcomes is possible. Reducing positions during selloffs is often mathematically optimal, not cowardly.

4. **Enforce hard caps**. Per-position cap (e.g., never > 5% of portfolio), daily loss cap (halt trading after threshold), minimum edge threshold (no position unless conviction exceeds floor).

### 2.2 Volatility-Based Sizing (Basis Points at Risk)

Professional traders (Hedgeye, multi-strat funds) think in **basis points of capital at risk**, not dollars:

- Higher-volatility assets get smaller weightings; lower-volatility assets carry larger positions
- This enforces cross-asset comparability — a 50bp risk position in equities is directly comparable to a 50bp risk position in credit
- Drift bands (+/-10% around targets) trigger rebalancing, not calendar schedules

### 2.3 The "Pod Shop" Risk Budgeting Model

Multi-strategy funds (Citadel, Balyasny, Point72) use a layered risk allocation framework:

```
Total Portfolio Risk Budget
  → Equity Pods (allocated risk capital)
    → Individual PM teams (sub-allocated)
      → Position-level limits (hard caps)
  → Macro Pods
  → Credit Pods
  → Quant/Systematic Pods
```

Risk is monitored at four levels simultaneously: position, sector, factor, and total portfolio. Real-time risk aggregation ensures no single strategy or PM dominates portfolio risk.

**MarketMind application**: Gate 3 should present the position decision as a "risk budget allocation" problem — the user sees what percentage of total risk capital a proposed position consumes, how it correlates with existing holdings, and what factor exposures it adds. The AI proposes, the user allocates.

### 2.4 Fundamental Optimization (Alpha Theory Approach)

A structured position-sizing framework combining:

| Input Type | Examples |
|------------|----------|
| **Quantitative** | Price targets, bull/bear probabilities, volatility, liquidity, correlation |
| **Qualitative** | Conviction scores, management quality, catalyst calendar, ESG |
| **Constraints** | Per-position caps, sector limits, factor exposure limits, drawdown limits |
| **Refresh cycle** | Inputs re-evaluated weekly; positions rebalanced when drift exceeds bands |

---

## 3. Pre-Trade / Pre-Execution Controls

### 3.1 FINRA/SEC Market Access Rule (SEA Rule 15c3-5)

The standard institutional pre-trade control framework, required for broker-dealers and adopted as best practice by funds:

| Control | What It Checks |
|---------|---------------|
| **Order limits** | Dollar/quantity per order, per trader, per account |
| **Credit thresholds** | Pre-set capital limits; documented rationale for adjustments |
| **Erroneous order** | Price collars, duplicate detection, fat-finger protection |
| **Market impact** | ADV-based checks, liquidity screening, NBBO comparison |
| **Restricted securities** | Hard blocks on stocks with inside information; soft blocks on watchlist |
| **Concentration** | Single-security and sector exposure limits |

### 3.2 Structured Trade Execution Workflow (5 Steps)

From institutional trade automation practice:

| Step | Activity | Output |
|------|----------|--------|
| **1. Ticket creation** | Mandatory fields: instrument, side, notional, hedge reason, urgency | Structured ticket |
| **2. Pre-trade checks** | Reference data, policy compliance, risk sanity, canonical order payload | Validated order |
| **3. Approval routing** | Rules-based routing by notional/asset class/urgency; immutable evidence | Approval record |
| **4. Execution** | Push to OMS/EMS; capture fill, avg price, venue, slippage | Execution confirmation |
| **5. Exception handling** | Reason-coded exception queues with SLAs; weekly review | Continuous improvement |

**Key principle**: Ticket quality is the primary control point. Enforce required fields and controlled vocabularies upstream — don't catch errors at execution.

**MarketMind application**: Gate 3 should produce a "decision ticket" with mandatory fields (direction, position size, entry/exit levels, stop-loss, take-profit, risk budget consumed, conviction score, catalyst timeline). This ticket becomes the canonical record — it is what gets archived after execution.

---

## 4. AI-Assisted Decision Frameworks (Current State 2025–2026)

### 4.1 The Shift: From AI Answers to AI Decision Structures

The frontier is not "a smarter AI stock picker" but a **better decision structure**:

| Old Paradigm | New Paradigm |
|---|---|
| AI as single recommendation engine | AI as coordinated multi-agent team |
| One-shot answers | Repeatable, auditable process |
| Black-box automation | Structured human-AI collaboration with audit trail |

### 4.2 UBS Multi-Asset Process (6 Stages, 5 AI-Augmented)

UBS applies AI to five of six investment stages. The only non-automated stage — Capital Market Expectations — remains human-driven due to "data scarcity and the need for structural economic judgment."

| Stage | AI Application |
|-------|---------------|
| Strategy Design | Factor analytics, ML optimization under complex constraints |
| Tactical Allocation | NLP sentiment, non-linear recession modeling, ML ensembles |
| Portfolio Construction | Non-linear correlation, dendrogram clustering for hidden relationships |
| Security Selection | ML manager screening, factor analytics for skill vs. luck |
| Portfolio Implementation | Execution algorithms, automated trade scheduling |

### 4.3 Design Principles from State Street & Waton

- **Foundational clarity**: Models must have well-articulated economic logic
- **Transparency**: Interpretable outcomes, parsimonious design
- **Robustness**: Trivial input changes should not drastically change outputs
- **Multi-agent teams**: Different AI agents for research, analysis, risk — mimicking institutional team structure
- **Visible, controllable architecture**: Users see which agents contributed what to the decision

### 4.4 Human-in-the-Loop (HITL) as Governance Requirement

The literature converges: AI serves as a reasoning accelerator, not an autonomous decider. The human approves/rejects/overrides at defined gates. Explainability tools (SHAP, LIME, factor attribution) are requirements, not nice-to-haves.

---

## 5. Synthesis: Gate 2 & Gate 3 Design Implications

### Gate 2 — Signal Confirmation (Investment Committee Analog)

Gate 2 is the "IC Presentation + Vote" moment. The AI has completed full pipeline analysis (L1-L3, Red Team, resonance, fragility). Now:

1. **Multi-angle presentation**: ELITE shadow agents (each a domain expert) present their confirmation or challenge of the user's selected direction — analogous to IC members stating their position with rationale.
2. **Dissent is surfaced, not buried**: If the Red Team found a material risk or a shadow agent dissents, that must be presented explicitly. Hidden dissent produces "passed but not really" outcomes.
3. **Written gate outcome**: Gate 2 ends with a structured decision record — confirm direction as-is, modify direction (with specifics), or return to Gate 1 for a new direction.
4. **No position sizing yet**: Gate 2 is about conviction calibration, not capital allocation. The user is answering "am I confident enough in this direction to put capital at risk?" — not "how much?"

### Gate 3 — Position Decision (Execution Analog)

Gate 3 is the "Final Execution" gate. The user commits to specific parameters:

1. **Decision ticket (mandatory fields)**:
   - Direction (long/short, instrument)
   - Position size (as % of portfolio and absolute)
   - Entry level / exit target / stop-loss / take-profit
   - Risk budget consumed (% of total risk capital)
   - Conviction score (from Gate 2)
   - Catalyst timeline (expected holding period)
   - Correlation overlay (how this position interacts with existing holdings)

2. **Risk calibration methods to surface**:
   - Kelly-derived suggestion (present as a range: full/half/quarter, let user choose fraction)
   - Volatility-adjusted sizing (larger for low-vol, smaller for high-vol)
   - Hard risk limits enforced: per-position cap, daily loss cap, minimum conviction threshold

3. **Pre-execution checklist**:
   - Entry level reasonable given current market? (price collar check)
   - Position size within portfolio limits? (concentration check)
   - Stop-loss far enough to avoid noise, close enough to limit damage?
   - Any restricted-instrument or conflict-of-interest flags?
   - Approval chain: self-approved or needs review?

4. **Archive as canonical record**: The Gate 3 decision ticket becomes the permanent record. Post-trade, the system can compare actual outcome against planned parameters for learning/calibration.

---

## Sources

- Investment Committee Best Practices (Northern Trust, 2024) — 3-gate PE model, voting mechanics, governance cadence
- NZ Treasury Gateway Review Framework — 5-gate public sector investment review model
- Alpha Theory Blog — Fundamental optimization and position sizing best practices
- Hedgeye Risk Management — Volatility-based sizing, basis-points-at-risk methodology
- Bloomberg Odd Lots — Multi-strategy pod shop risk management practices
- FINRA Market Access Rule (SEA Rule 15c3-5) — Pre-trade control requirements
- SGX Practice Note 4.10.1(b) — Pre-execution check parameters
- Nasdaq Tech Tuesday — Pre-trade risk checks and last-stop controls
- FitGap Hedge Execution Workflows — 5-step structured trade execution
- UBS Asset Management — AI in multi-asset investing, 6-stage process
- State Street — AI transformation in investment management, design principles
- Caridi, Giovannini & Ricciardi Celsi (2026) — Three-layer AI-assisted value investing framework
- Waton MoTA Platform (2026) — Multi-agent human-AI collaborative investment system
- Yerra & Allam (2026) — Semantic State Abstraction Interfaces for LLM-augmented portfolio decisions
- Wellington Management (2025) — Multi-strategy hedge fund capital allocation framework
- Kelly Criterion practical implementations (Interactive Brokers, SparkCo, QuantConnect)
