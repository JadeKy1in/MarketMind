# Phase H External Approaches: Adoptable Patterns from Industry & Open Source

**Compiled**: 2026-05-18
**Purpose**: Survey external approaches to multi-asset investment analysis pipelines that could inform MarketMind Phase H redesign. Focus on concrete architectures, module designs, and data flow patterns we can adopt.
**Related research**: [[balance-sheet-flow-frameworks]], [[asset-class-routing-design]], [[gate1-9-critical-synthesis]]

---

## Executive Summary

Seven adoptable design patterns emerged from the survey, each with a clear mapping to Phase H needs:

| # | Pattern | Source | Adopt for Phase H |
|:--:|---------|--------|-------------------|
| 1 | Modular agent-per-modality architecture | MarketSenseAI 2.0, TradingAgents | Replace monolithic analysis with specialized analysis agents |
| 2 | Adversarial dual-agent verification | MSCI (2025) | Replace self-reviewed analysis with skeptic-agent challenge |
| 3 | Four-pillar macro decomposition | Bridgewater/Dalio | Universal macro lens: Growth, Inflation, Risk Premium, Flows |
| 4 | Four-season regime quadrant | Bridgewater All Weather | Asset-class-agnostic regime mapping |
| 5 | Separation of concerns (Alpha/Risk/Optimizer) | QuantPedia, Macrosynergy | Clear contract between analysis modules and decision stage |
| 6 | Multi-scale frequency decomposition | VMD/EMD academic literature | Handle non-stationarity across crypto, commodities, FX |
| 7 | Tiered-model cost routing | TradingAgents, J.P. Morgan | Expensive models for reasoning, cheap models for summarization |

---

## 1. Multi-Agent Modular Architecture (MarketSenseAI 2.0)

**Source**: Fatouros et al., 2025. arXiv:2502.00415. 125.9% cumulative returns vs 73.5% benchmark on S&P 100 (2023-2024).

### Architecture

```
News Agent → Fundamentals Agent → Dynamics Agent → Macro Agent → Signal Agent
     │              │                  │               │              │
     └──────────────┴──────────────────┴───────────────┘              │
                              │                                       │
                         Synthesis Layer ← Chain-of-Thought ←─────────┘
                              │
                         Buy/Hold/Sell Signal
```

Each agent is responsible for exactly ONE data modality:
- **News Agent**: Aggregates and narrativizes daily news
- **Fundamentals Agent**: SEC filings (10-K/10-Q) via Chain-of-Agents (CoA) approach for large documents
- **Dynamics Agent**: Price movements, volatility, Sharpe ratios vs peers
- **Macro Agent**: RAG + HyDE (Hypothetical Dense Embeddings) on institutional reports (FED, ECB, IMF, JPMorgan, BlackRock)
- **Signal Agent**: Chain-of-Thought integration producing final signal

### Adoptable for MarketMind

- **Agent-per-modality pattern**: Each of Phase H's 6 analysis modules should be a self-contained agent with its own data sources and reasoning chain. No shared state between agents except through a synthesis layer.
- **Chain-of-Agents (CoA) for large documents**: When analyzing SEC filings or central bank reports, split into sequential chunks where each chunk inherits context from the previous. This avoids token overflow.
- **HyDE-based retrieval**: Generate hypothetical embeddings before retrieval for richer semantic matching against macro reports.
- **Signal integration via CoT**: The final decision stage receives structured outputs from all analysis modules and reasons step-by-step to a conclusion.

---

## 2. Adversarial Dual-Agent Verification (MSCI, 2025)

**Source**: MSCI blog post "Leveraging Language Models to Capture Investment Strategies." Achieved >95% agreement with human expert assessments.

### Architecture

```
Input → Positive Agent ("Is this division working on in-scope activities?")
     → Skeptic Agent ("Is this division more aligned with in-scope or out-of-scope?")
     → Consensus/Synthesis
```

### Adoptable for MarketMind

This directly addresses Red Team finding C4 (hypothesis analysis output doesn't flow to decision stage). Instead of a single analysis pass:

1. **Analyst Agent** generates the bull case with supporting evidence
2. **Skeptic Agent** generates the bear case and challenges assumptions
3. **Synthesis** merges both perspectives into a decision recommendation with explicit uncertainty quantification

This pattern also maps to the existing `shadow_agent.py` infrastructure — the skeptic can operate as a shadow that challenges the primary analysis.

**Key MSCI lesson**: "Separate classification from scoring. Let LLMs handle sentiment/linkage classification; use deterministic methods for numerical scoring." This prevents LLM hallucination on quantitative outputs.

---

## 3. Bridgewater Four-Pillar Macro Decomposition

**Source**: Dalio/Bridgewater methodology, Andy Constan (ex-Bridgewater) analysis.

### Framework

Every macro question decomposes into four universal pillars:

| Pillar | Core Question | MarketMind Module |
|--------|--------------|-------------------|
| **Growth** | Where is real economic expansion heading? | Causal decomposition (supply/demand) |
| **Inflation** | What is the price level trajectory? | Causal decomposition (cost-push vs demand-pull) |
| **Risk Premium** | What compensation do assets offer for risk? | Fragility scanning (risk/reward asymmetry) |
| **Flows** | Where is capital moving across borders/asset classes? | Flow tracking + cross-border capital flow |

### Four-Season Quadrant (Asset-Class-Agnostic)

```
          Growth ↑
             |
    Spring   |   Summer
    (Stocks) |   (Commodities, TIPS)
  -----------+-----------→ Inflation
    Winter   |   Autumn
    (Bonds)  |   (Gold, Real Assets)
             |
          Growth ↓
```

### Adoptable for MarketMind

This directly solves Red Team finding C1 (balance sheet decomposition only works for US fixed income). The four-pillar framework is **asset-class-universal**:

- **US equities**: Growth pillar (earnings growth) + Risk Premium pillar (equity risk premium)
- **Commodities**: Growth (demand) + Inflation (supply constraints) + Flows (speculative positioning)
- **FX**: Growth differential + Inflation differential + Flows (carry trade, reserve diversification)
- **Crypto**: Risk Premium (risk-on/off) + Flows (ETF inflows, exchange reserves)
- **Fixed income**: All four pillars (the original balance sheet approach fits here)

**Implementation**: Replace the monolithic `causal_decomposition.py` with 4 sub-modules, one per pillar. Each hypothesis routes to the relevant pillar(s) based on asset class.

---

## 4. Separation of Concerns: Alpha / Risk / Optimizer

**Source**: QuantPedia research workflow, Macrosynergy, BlackArbs Alpha Lab.

### Architecture

```
Data Ingestion → Alpha Research → Factor Testing → Portfolio Construction → Execution
                     │                  │                    │
               Signal Discovery    Validation         Risk-Constrained Opt
               (ML, economic)     (walk-forward,      (Mean-Variance,
                                  multiple-testing     Risk Parity)
                                  correction)
```

Three independent models with clean contracts:

| Model | Responsibility | Output |
|-------|---------------|--------|
| **Alpha Model** | Return forecasts per asset | Expected return vector |
| **Risk Model** | Covariance estimation | Covariance matrix |
| **Optimizer** | Convex QP given constraints | Portfolio weights |

### Adoptable for MarketMind

MarketMind's Phase H modules map cleanly to this separation:

- **Alpha Model**: Causal decomposition + conditional forecasting + flow tracking (what's changing and why)
- **Risk Model**: Fragility scanning + historical regime mapping (what could go wrong)
- **Optimizer**: Decision stage (given alpha + risk, what action is appropriate)

The key insight: analysis modules should output **structured, machine-readable signals** (not just narrative text) that the decision stage can consume. This directly addresses Red Team finding C4.

**QuantPedia's iterative loop** is also adoptable:
```
Screen → Validate → Combine → Compare → Diagnose → Refine → (repeat)
```
This maps to MarketMind's investigation loop, where each iteration refines the hypothesis.

---

## 5. Multi-Scale Frequency Decomposition

**Source**: Sentiment-VMD-MTL (Expert Systems with Applications, 2026), SSA-MAEMD-TCN (arXiv, 2025), CMGM cross-market graph (Alexandria Engineering Journal, 2025).

### Core Technique

Financial time series are non-stationary. Decompose into frequency bands:

| Technique | What it separates | When to use |
|-----------|------------------|-------------|
| **VMD** (Variational Mode Decomposition) | Long-term trend vs short-term fluctuation | Any non-stationary series |
| **EMD** (Empirical Mode Decomposition) | Intrinsic mode functions at different scales | Multi-timescale analysis |
| **SSA** (Singular Spectrum Analysis) | Signal vs noise separation | Denoising before analysis |
| **Wavelet** | Time-frequency localization | Regime transition detection |

### Adoptable for MarketMind

For Phase H's fragility scanning and conditional forecasting:
- Decompose price signals into trend (long-term, regime-driven) and fluctuation (short-term, noise) components
- Analyze each component separately — the causal drivers of trend are different from the drivers of noise
- Map each frequency band to the appropriate Bridgewater pillar (e.g., trend → Growth/Inflation, fluctuation → Risk Premium/Flows)

The **CMGM cross-market graph** approach is also relevant: model assets as nodes with multi-dimensional edges (volatility correlation, skewness correlation, time-evolving correlation). This could inform the cross-border capital flow module's inter-asset dependency tracking.

---

## 6. Tiered-Model Cost Routing

**Source**: TradingAgents (Xiao et al., 2024), J.P. Morgan "Ask David" (2025), Captide (2025).

### Pattern

Use different LLM tiers based on task complexity:

| Task | Model Tier | Example |
|------|-----------|---------|
| Summarization, data extraction | Cheap (GPT-4o-mini, DeepSeek) | News aggregation, filing parsing |
| Entity recognition, classification | Cheap | Asset class routing, entity tagging |
| Causal reasoning, debate | Expensive (Opus, o1-preview) | Hypothesis analysis, decision synthesis |
| Final integration | Expensive | Signal generation, report writing |

TradingAgents uses GPT-4o-mini for analyst agent tasks (low depth) and o1-preview for fund manager decisions (high depth).

### Adoptable for MarketMind

Phase H's 6 analysis modules have varying complexity:
- **Entity tagging and flow classification**: Cheap model
- **Regime mapping (historical pattern matching)**: Medium (RAG + classification)
- **Causal decomposition and fragility scanning**: Expensive (multi-step reasoning)
- **Decision synthesis**: Most expensive (adversarial debate + integration)

Implement a `ModelRouter` that selects the model based on the analysis module and hypothesis complexity. This is a direct cost optimization (trading ~30% of inference cost on cheap models for a 10x cheaper bill).

---

## 7. Open-Source Framework Design Patterns

### Macrosynergy (pip install macrosynergy, v1.0 Nov 2024)

Seven sub-packages covering the full pipeline. The architecture pattern is worth adopting:

```
macrosynergy/
├── download/     # Data ingestion interface (JPMaQS API)
├── panel/        # Panel time-series analysis (cross-country, multi-asset)
├── learning/     # ML integration (scikit-learn)
├── signal/       # Transform indicators → trading signals
├── pnl/          # Portfolio construction, risk, backtests
├── management/   # Utilities, simulation, validation
└── visuals/      # Scorecards, visualizations
```

**Adoptable**: The sub-package pattern — each Phase H module should be its own package with a single public entry point. The `signal/` sub-package (transform indicators → signals) maps directly to what MarketMind's analysis modules must output for the decision stage.

### QRAFTI (arXiv:2604.18500, April 2026)

Multi-agent framework for equity factor research:
- **Factor Research Agent**: Interprets requests, decomposes tasks, selects tools
- **Risk Manager Agent**: Generates diagnostics and narrative reports
- **Quant Developer Agent**: Writes custom code when built-in tools are insufficient

Key finding: "Chained tool calls and reflection-based planning offer better performance and explainability than dynamic code generation alone."

**Adoptable**: The reflection-based planning approach — agents should plan their analysis steps, execute, then reflect on results before producing output. This is more reliable than single-pass generation.

### Microsoft Qlib RD-Agent (2024-2025)

Multi-agent framework for automated factor mining and model optimization. The agent architecture (factor research → factor validation → model integration) mirrors what Phase H needs for hypothesis analysis.

### LangGraph Patterns (Captide, Finbot, langchain-trading-agents)

Common LangGraph architecture for financial agents:
```
Supervisor Agent → [DataAgent, AnalystAgent, ComplianceAgent] → Supervisor → Output
```

State management via LangGraph's `StateGraph`, structured output via `trustcall`, observability via LangSmith.

**Adoptable for MarketMind**: The supervisor pattern — a thin orchestration layer that routes to specialized sub-agents. This aligns with MarketMind's existing glue-layer architecture principle (§3.1 of workspace CLAUDE.md).

---

## 8. Multi-Entity Sentiment: One Event → Multiple Asset Signals

**Source**: Permutable.ai multi-entity sentiment code, TextReveal by SESAMm (50M+ entity knowledge graph).

### Pattern

A single macro event triggers different directional signals per asset class:
- BoE rate hike → Bullish GBP, Bearish FTSE equities, Neutral commodities
- Iran-Israel escalation → Bullish oil, Bearish risk assets, Bullish gold

### Adoptable for MarketMind

Phase H's entity-level flow tracking should implement **entity-aware sentiment mapping**: when a hypothesis references multiple entities/assets, generate separate directional signals for each. The current single-hypothesis → single-score pipeline loses cross-asset nuance.

---

## 9. Data Flow Pattern: Structured Output Contract

### The Problem (Red Team C4)

Analysis modules produce narrative text. The decision stage needs structured inputs. There's no contract between them.

### The Solution (Multiple Sources)

From Macrosynergy, QuantPedia, and J.P. Morgan's "Ask David":

Every analysis module must output a **structured signal object**:

```python
@dataclass
class ModuleSignal:
    module: str                    # e.g., "causal_decomposition"
    hypothesis_id: str
    asset_class: str
    direction: Literal[-1, 0, 1]  # Bearish, Neutral, Bullish
    confidence: float              # 0.0 - 1.0
    reasoning_chain: list[str]     # Step-by-step reasoning (for audit)
    evidence_sources: list[str]    # Source citations
    counter_arguments: list[str]   # Self-identified weaknesses (skeptic output)
    regime_context: str            # Current macro regime (from regime mapping)
```

The decision stage consumes a list of `ModuleSignal` objects (one per analysis module) and synthesizes them. This contract:
1. Makes the analysis → decision data flow explicit and testable
2. Enables independent testing of each module (mock inputs → verify structured output)
3. Supports audit trail (every decision traces back to specific module signals)
4. Allows the skeptic agent to target specific signals for challenge

---

## 10. What NOT to Adopt (Anti-Patterns Identified)

| Anti-Pattern | Why to Avoid |
|-------------|-------------|
| **End-to-end black-box models** (StockTime, LLMoE) | Opaque reasoning. MarketMind requires explainable analysis, not black-box predictions. |
| **Pure RL-based decision making** (SAPPO, FinRL) | Requires reward engineering that overfits to backtests. Mismatch with MarketMind's anti-overfitting constraint. |
| **Generative market simulation** (GenMarket) | Over-engineered for Phase H. Synthetic scenario generation is a Phase I/J concern. |
| **Single-model monolithic pipelines** | Every production system (J.P. Morgan, MSCI, Bridgewater) uses modular separation. Monoliths fail at scale. |
| **Sentiment-only approaches** | MarketMind already does this in early phases. Phase H is about moving BEYOND surface sentiment to structural analysis. |
| **Transformer predictions without baselines** | Kinlay (2026) showed that transformer forecasts were beaten by simple 20-day momentum on Sharpe ratio. Always benchmark against naive baselines. |

---

## Mapping to Phase H Red Team Findings

| Red Team Finding | External Solution | Implementation |
|-----------------|-------------------|----------------|
| **C1**: Balance sheet only works for US FI | Bridgewater 4-pillar framework | Replace single decomposition with Growth/Inflation/Risk Premium/Flows routing per [[asset-class-routing-design]] |
| **C2**: Flow entity model is US-centric | Permutable multi-entity approach | Entity model defined per asset class, not globally. See [[asset-class-routing-design]] for per-AC entity tables. |
| **C3**: Investigation module needs structural extraction | Module extraction rules (§3.1 of workspace CLAUDE.md) | Extract before adding. Split by concern, not by function. |
| **C4**: Analysis output doesn't flow to decision | Structured signal contract (§9 above) | `ModuleSignal` dataclass as the contract between analysis and decision stages. |

---

## Priority Adoption Sequence

1. **Structured signal contract** (Section 9) — prerequisite for C4 fix. Implement first.
2. **Four-pillar decomposition** (Section 3) — replaces US-centric balance sheet (C1 fix). Implement per [[asset-class-routing-design]].
3. **Per-asset-class entity models** (Section 8 + [[asset-class-routing-design]]) — C2 fix.
4. **Adversarial dual-agent verification** (Section 2) — quality improvement, leverages existing `shadow_agent.py`.
5. **Tiered-model cost routing** (Section 6) — cost optimization, not blocking.
6. **Multi-scale decomposition** (Section 5) — enhancement for fragility scanning, can be Phase H.1.

---

**Next**: Architect review of these adoptable patterns against the Phase H redesign plan. Key question: which patterns are Phase H mandatory (must ship before phase complete) vs Phase H enhancement (nice to have, can defer)?
