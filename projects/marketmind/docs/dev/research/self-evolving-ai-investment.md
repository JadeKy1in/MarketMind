# Self-Evolving AI for Investment Analysis: Concrete Mechanisms

**Date**: 2026-05-18
**Status**: Research synthesis for MarketMind self-evolution design
**Sources**: 20+ papers, 8+ open-source projects, 5+ production systems

## Executive Summary

Six concrete mechanism families exist for building AI investment systems that learn from their own past analyses. Each family has published validation and at least one open-source implementation. The mechanisms compose: none requires retraining foundation models; all six can be implemented as layers in MarketMind's existing pipeline.

---

## 1. Structured Post-Mortem (复盘) with Reflection Engine

**What it is**: After a prediction's outcome window closes (e.g., "EUR/USD in 30 days"), an automated review agent compares the original analysis against what actually happened, produces a structured lesson, and stores it for future retrieval.

**Concrete implementations**:
- **FinCrew** (GitHub: tanmingtao1994-gif/fincrew) — a self-evolving multi-agent assistant with an explicit `Trade Review → Lesson Extraction → Long-term Memory` loop. Each trade produces a structured lesson injected into future analyses.
- **FinMem** (ICLR 2024) — layered memory architecture (working → short-term → long-term) with feedback loops that filter signal from noise across episodes.
- **Amazon Analyst Agents** (ICML 2025) — a multi-agent framework where an Analyst Agent learns from repeated month-end cycles. **Result**: 44.5% → 81.3% first-response accuracy across four cycles purely through reflection + memory accumulation.

**Key design decisions**:
1. **Structured lesson format**: Not free-text reflection. Each lesson should have: `{prediction, confidence, outcome, delta, root_cause_category, updated_belief}`.
2. **Root cause taxonomy**: Categorize errors — was it a missing data source? A flawed causal chain? An over-weighted signal? A regime-change blind spot? This taxonomy drives targeted retrieval.
3. **Retrieval at analysis time**: Before analyzing an asset/sector, query the lesson store for past errors on the same entity, same sector, and same error category.
4. **Forgetting curve**: Weight lessons by recency. A 6-month-old lesson on ECB policy may be stale after a regime change.

**MarketMind integration**: Add a `ReflectionAgent` that runs after each shadow consensus round. Input: the analysis + the final shadow verdict. Output: a structured lesson record. At next analysis time, the orchestrator pre-loads relevant lessons into each agent's context.

---

## 2. Calibration Tracking with Brier Scores

**What it is**: Track every probabilistic prediction the system makes, compute calibration metrics (Brier score, Expected Calibration Error) over time, and use miscalibration patterns to adjust future confidence levels.

**Evidence base**:
- **KalshiBench** (Nel, Lotus AI, Dec 2025): Evaluated 5 frontier LLMs on 300 prediction market questions. Key finding: **ALL models are systematically overconfident**. At 90%+ confidence, models are wrong 15-32% of the time. Reasoning-enhanced models (GPT-5.2-XHigh) showed *worse* calibration, not better — extended reasoning increases confidence without proportional accuracy gains.
- **ReMax/GRPO for Forecasting** (Turtel et al., May 2025): Used Brier score as RL reward signal. A 14B model fine-tuned with this approach matched frontier models on accuracy while halving calibration error (ECE 0.042 vs 0.08+). Simple trading rule turned calibration edge into **$127 vs $92 hypothetical profit**.
- **AIA Forecaster** (arXiv 2511.07678): Achieved superforecaster-level performance via Platt scaling and extremization — post-hoc statistical corrections to LLM probabilities.

**Concrete mechanism**:
1. **Log every probabilistic claim**: Structure each prediction as `{entity, horizon, probability, rationale, timestamp}`.
2. **Resolve at deadline**: When the outcome is known, score with Brier = `(p - outcome)^2`. Climatology baseline = always-predict-base-rate. Brier Skill Score = `1 - (Brier_model / Brier_climatology)`.
3. **Per-agent calibration curves**: Track each shadow agent's calibration separately. An agent that is consistently overconfident on tech stocks but well-calibrated on macro gets a per-domain adjustment.
4. **Confidence calibration layer**: Before final output, apply Platt scaling using the agent's historical calibration data. If an agent's 80% confidence historically means 65% accuracy, down-weight to 65%.

**MarketMind integration**: Add a `CalibrationStore` (SQLite table) tracking every probabilistic claim across all shadow agents. A `CalibrationAgent` runs weekly, computes per-agent per-domain calibration curves, and updates scaling parameters used at output time.

---

## 3. Knowledge Graph Accumulation with Temporal Causal Chains

**What it is**: Build a temporal knowledge graph where nodes are entities (assets, sectors, central banks, events) and edges are typed causal relationships. Each new analysis enriches the graph. Past predictions that verified become strengthened edges; failed predictions become weakened or removed edges.

**Evidence base**:
- **TRACE** (arXiv 2603.12500): Temporal Rule-Anchored Chain-of-Evidence on knowledge graphs for stock prediction. Rule-guided multi-hop exploration grounds reasoning chains in news text. Achieves 55.1% accuracy / 60.8% F1 with auditable UP/DOWN verdicts and human-readable causal paths.
- **FEEKG** (Expert Systems w/Apps, 2024): Financial Event Evolution Knowledge Graph with 112,000 entities and 78,500 relationships. Multi-layer "entity-event-risk" structure that mines potential risk entities and summarizes risk evolution rules.
- **DynTKG** (2025): Hawkes process-driven time-decay subgraph pruning. Explicit causal consistency constraint: `t_cause < t_effect`. 5.8x model compression with only 1.3% performance loss.
- **FinCaKG-Onto**: 95.6% ontology consistency for causality extraction from financial reports.

**Concrete mechanism**:
1. **Schema**: `(Entity) -[CAUSES {strength, evidence, timestamp, verified}]-> (Entity)`. Entities: assets, sectors, central banks, economic indicators, geopolitical events.
2. **Edge creation**: Every analysis that asserts "X will cause Y" creates a provisional edge with `verified=false`.
3. **Edge resolution**: When Y's outcome is observed, if X's causal chain was correct, strengthen the edge. If wrong, weaken or remove it.
4. **Query at analysis time**: For asset X, traverse the graph to find: (a) what has historically driven X, (b) what recently changed, (c) what the current consensus causal chain predicts.
5. **Temporal decay**: Edges weaken over time via exponential decay unless reinforced by new evidence.

**MarketMind integration**: A `CausalGraphStore` (NetworkX + SQLite persistence). The analysis pipeline writes provisional edges; a `GraphResolutionAgent` verifies edges against outcomes. At analysis time, the orchestrator queries the graph for relevant causal context and injects it into agent prompts.

---

## 4. Multi-Agent Debate with Outcome-Weighted Agent Reputation

**What it is**: Multiple specialized agents analyze the same event from different angles. Their disagreement is tracked over time. Agents whose analyses consistently align with outcomes gain reputation weight; agents with poor track records are down-weighted or retrained.

**Evidence base**:
- **Dual-Agent LLM Debate for Financial Forecasting** (MDPI Mathematics, 2026): Proponent (Gemini Pro 3) vs Opponent (ChatGPT 5.2) debating 75 financial indicators across 5 asset classes. **Consensus forecasts after debate significantly outperformed single-agent baselines**, especially for volatile assets (crypto, 10y bonds). Validated with paired t-tests.
- **TradingAgents** (70k+ GitHub stars): Multi-agent framework with Analyst Team (fundamental, sentiment, news, technical), Researcher Team (bull/bear debate), and Trader + Risk Manager. Debate-driven decision-making with dynamic multi-round discussion.
- **MAIS for Bias Reduction** (2025): Specialized agents + debate protocols reduced overconfidence, confirmation bias, and anchoring. **Significant Sharpe improvements** and reduced drawdowns vs single-agent.
- **AEL** (COLM 2026): Two-timescale self-improvement via bandit-based agent selection. Key finding: simpler is often better — the basic variant (reflection + memory) achieved Sharpe 2.13, outperforming more complex variants.

**Concrete mechanism**:
1. **Agent specialization**: Each shadow agent has a declared methodology (technical, macro, sentiment, fundamental, contrarian). At debate time, agents present their analyses and confidence.
2. **Structured disagreement capture**: Record not just "Bull vs Bear" but *why* they disagree — which specific assumption, data point, or causal chain differs.
3. **Outcome-weighted reputation**: Each agent gets a running score: `reputation = weighted_accuracy * calibration_score * recency_factor`. Weights decay over time.
4. **Consensus weighting**: Final output weights each agent's view by reputation. A consistently accurate macro analyst gets more weight on macro questions.
5. **Agent retirement/retraining**: Agents below a reputation threshold for N consecutive cycles get flagged for methodology review or retirement.

**MarketMind integration**: The existing 21-shadow-agent ecosystem already has specialization. Add: (1) per-agent reputation tracking, (2) structured debate summaries capturing *why* agents disagree, (3) reputation-weighted consensus instead of equal-weighted.

---

## 5. Closed-Loop RAG with Outcome Verification

**What it is**: The knowledge base (RAG store) updates based on outcome verification. When an analysis references a source or fact pattern that later proves wrong, that source's credibility is downgraded. When an analysis misses a key driver that later proves decisive, that gap is identified and relevant sources are added.

**Evidence base**:
- **QuantAgent** (双层自改进): Writer-Critic inner loop + real-world outer loop. Knowledge base automatically accumulates signals, implementation details, and performance metrics. The agent's Bayesian regret converges sublinearly in O(sqrt(KT)).
- **FactorMiner** (arXiv 2602.14670): Ralph Loop paradigm (Retrieve → Generate → Evaluate → Distill). Experience memory stores successful factor patterns and forbidden high-correlation regions. Each mining session feeds outcomes back into memory.
- **FinAgent-RAG** (arXiv 2605.05409): Contrastive Financial Retriever + Program-of-Thought + Adaptive Strategy Router. 76.81-78.46% execution accuracy on FinQA benchmarks.
- **RLFKV from Ant Group** (arXiv 2602.05723): Decomposes financial answers into atomic knowledge units (entity, metric, value, timestamp), verifies each against sources, uses results as RL reward signals. Eliminates need for human annotation.

**Concrete mechanism**:
1. **Atomic knowledge decomposition**: Break every analysis into claims like `(entity=EUR/USD, metric=direction, value=UP, confidence=0.75, horizon=30d, sources=[s1, s2])`.
2. **Source credibility tracking**: Each source has a credibility score. When a claim citing source S proves wrong, S's score decreases. When a claim citing S proves right, S's score increases. Track per-domain (a source may be credible on US equities but not on crypto).
3. **Gap detection**: When an analysis misses a decisive factor, log the gap. Next time that entity/sector is analyzed, the orchestrator checks the gap log and ensures the missing factor is included.
4. **Knowledge base pruning**: Sources below a credibility threshold are removed from the active RAG index. High-credibility sources are retrieved preferentially.

**MarketMind integration**: A `SourceCredibilityStore` tracks every source used in analyses. A `KnowledgeGapStore` tracks decisive factors that were missed. The RAG retrieval step queries both stores to bias toward credible sources and ensure historical gaps are addressed.

---

## 6. Prediction-Market-Style Verification Pipeline

**What it is**: Define clear, externally-verifiable resolution criteria for every prediction. When the resolution date arrives, automatically fetch the ground truth (market price, economic release, central bank decision) and score the prediction. This creates a growing dataset of scored predictions for calibration, reputation, and learning.

**Evidence base**:
- **PolyBench** (GitHub): Evaluates 7 SOTA LLMs across 38,666 binary prediction markets on Polymarket. Automated pipeline: Event Resolution Criteria → CLOB States → News Streams → LLM Predictions → Outcome Verification. Metrics: Confidence-Weighted Return, APY, Sharpe Ratio.
- **IBM Replayable Financial Agents** (ICLR 2026): Measures determinism and accuracy of LLM agents across 3 financial benchmarks. Key finding: determinism does NOT equal accuracy (r = -0.11) — consistent wrong answers are not better than inconsistent ones.
- **Torghut LLM Review Gate**: Production pipeline with full audit trail (prompt version, model, request/response, rationale, confidence). Fail-closed for live trading. Persisted review table linked to trade outcomes.
- **AWS Automated Reasoning**: Formal mathematical logic verification of LLM outputs against defined policies. Produces auditable proof chains.

**Concrete mechanism**:
1. **Prediction schema**: Every prediction must have: `{id, entity, claim_type, claim_value, confidence, horizon_days, resolution_date, resolution_criteria, sources_used}`.
2. **Automated resolution**: A cron job runs daily, finds predictions past their resolution date, fetches ground truth from a defined API (market prices, FRED, ECB, etc.), and computes the score.
3. **Resolution criteria must be machine-verifiable**: "EUR/USD will rise" is ambiguous. "EUR/USD close price on 2026-06-18 will be > close price on 2026-05-18" is machine-verifiable.
4. **Scoring**: Brier score for probabilistic claims. Directional accuracy for directional claims. Mean Absolute Error for numeric claims. All stored per-prediction, per-agent, per-domain.
5. **Feedback loop**: Resolved predictions feed into: (a) calibration curves, (b) agent reputation weights, (c) knowledge graph edge resolution, (d) source credibility updates.

**MarketMind integration**: A `PredictionStore` table with resolution criteria. A `ResolutionAgent` cron job that fetches ground truth and scores all past-due predictions. This is the backbone that feeds mechanisms 1-5 with verified outcome data.

---

## Implementation Priority for MarketMind

The six mechanisms have dependencies. Recommended build order:

| Priority | Mechanism | Depends On | Effort | Impact |
|:---:|---|---|:---:|:---:|
| **1** | Prediction Verification Pipeline (#6) | Nothing | Medium | Foundation for all others |
| **2** | Calibration Tracking (#2) | #6 (needs scored predictions) | Low | Immediate accuracy gains |
| **3** | Agent Reputation (#4) | #6 (needs per-agent scores) | Low | Improves consensus quality |
| **4** | Structured Post-Mortem (#1) | #6 (needs resolved outcomes) | Medium | Long-term learning |
| **5** | Source Credibility RAG (#5) | #6 (needs verified claims) | Medium | Improves input quality |
| **6** | Causal Knowledge Graph (#3) | #6 (needs edge resolution) | High | Deepens understanding |

**Minimum viable self-evolution**: Build #6 + #2 + #3. This gives you: (a) a growing dataset of scored predictions, (b) calibrated confidence outputs, and (c) reputation-weighted consensus. These three compose without #1, #5, or #3 and provide measurable improvement within 2-4 weeks of deployment.

## Key Design Principles (from all surveyed systems)

1. **Structure over free-text**: Every system that works uses structured prediction/lesson/claim records. Raw LLM reflection text is not searchable, not composable, and not auditable. Schema first.

2. **Atomic decomposition**: Break analyses into independently-verifiable claims. A paragraph like "ECB will likely cut rates due to slowing growth and easing inflation" becomes three claims: (1) ECB cuts rates, (2) growth is slowing, (3) inflation is easing. Each is separately verifiable.

3. **Time-aware everything**: All claims, edges, and reputation scores must decay over time. A perfect 2024 track record on tech stocks may mean nothing in a 2026 rate cycle.

4. **Less is more**: AEL's finding that the simplest variant (reflection + memory) outperformed more complex designs (credit assignment, tool selection, skill learning) is consistent across multiple systems. Start simple, add complexity only when measurement shows it helps.

5. **Machine-verifiable resolution criteria**: If a prediction can't be automatically scored against a public data source, it shouldn't enter the learning loop. Human-scored predictions don't scale and introduce subjective bias.

6. **No foundation model retraining required**: Every mechanism described works at the application layer — prompt engineering, retrieval augmentation, statistical post-processing, and structured memory. RL fine-tuning (ReMax/GRPO) is an optimization, not a prerequisite.

---

## References

- Multi-Dimensional Behavioral Evaluation of Agentic Stock Prediction Systems (arXiv:2605.05739)
- FactorMiner: Self-Evolving Agent with Skills and Experience Memory (arXiv:2602.14670)
- FactorEngine: Program-level Knowledge-Infused Factor Mining (arXiv:2603.16365)
- QuantEvolver: RL Fine-Tuning for Alpha Factor Discovery (arXiv:2605.15412)
- AIA Forecaster: Calibrated LLM Forecasting (arXiv:2511.07678)
- RETuning: Inference-Time Scaling for Stock Prediction (arXiv:2510.21604)
- KalshiBench: LLM Epistemic Calibration via Prediction Markets (arXiv:2512.16030)
- Outcome-Based RL for Calibrated Forecasting (arXiv:2505.17989)
- TRACE: Temporal Rule-Anchored Chain-of-Evidence (arXiv:2603.12500)
- DynTKG: Dynamic Subgraph Pruning with Causal Distillation (2025)
- FEEKG: Financial Event Evolution Knowledge Graph (Expert Systems w/Apps, 2024)
- Dual-Agent LLM Debate for Financial Forecasting (MDPI Mathematics, 2026)
- FinMem: Layered Memory Trading Agent (ICLR 2024)
- Building Analyst-Like Agents: Self-Improving Multi-Agent Framework (ICML 2025)
- AEL: Agent Evolving Learning for Portfolio Allocation (GitHub: WujiangXu/AEL, COLM 2026)
- QuantAgent: Self-Improving LLM for Trading (双层自改进框架)
- FinAgent-RAG (arXiv:2605.05409)
- RLFKV: Fine-Grained Knowledge Verification (Ant Group, arXiv:2602.05723)
- PolyBench: LLM Benchmark on Live Prediction Markets (GitHub: PolyBench/PolyBench)
- TradingAgents: Multi-Agent LLM Financial Trading Framework (GitHub: TauricResearch/TradingAgents)
- Dexter: Autonomous Financial Research Agent (GitHub: virattt/dexter)
- FinCrew: Self-Evolving Multi-Agent Financial Assistant (GitHub: tanmingtao1994-gif/fincrew)
- AlphaAnalyst: Autonomous Equity Research Agent (GitHub: kbhujbal/AlphaAnalyst)
- AutoHypothesis: Agentic Quant Research Framework (GitHub: arteemg/AutoHypothesis)
- IBM Replayable Financial Agents (ICLR 2026)
- Fintool: Continuous LLM Evaluation (ZenML LLMOps Database)
