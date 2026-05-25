# Shadow Agent Verifiable Self-Improvement: Mechanisms Research

**Date:** 2026-05-18
**Purpose:** Identify active mechanisms (not passive measurement) by which AI investment agents can demonstrably improve over time. Brier scores and direction accuracy already track "are we better?" — this research addresses "HOW do we get better, and how do we prove it?"

---

## 1. Self-Improving Agent Architectures

### 1.1 Memory-Based Self-Evolution (No Weight Updates)

The dominant paradigm in 2025–2026 is **externalized memory** — agents improve by accumulating structured knowledge artifacts rather than updating model weights. This is critical for auditability: every improvement is a human-readable artifact.

**Memento-Skills** (arXiv, March 2026) uses a Read-Write Reflective Learning loop:
- A skill router selects relevant past skills (~experiences) for the current task.
- After task execution, the agent writes new skills or updates existing ones as structured markdown.
- Achieved 26.2% improvement on General AI Assistants and 116.2% on Humanity's Last Exam — with **zero parameter updates**.
- For MarketMind: each shadow could maintain a `skills/` directory of markdown files capturing successful analysis patterns. After a gold analysis proves accurate, the shadow writes a skill entry describing its reasoning path.

**FORGE** (arXiv, May 2026) introduces population-based memory evolution:
- A Reflection Agent converts failed trajectories into reusable knowledge in three formats: Rules (heuristics), Examples (few-shot demonstrations), or Mixed.
- Population broadcast propagates the best memories across the entire agent population.
- Key finding: Examples format yielded highest returns; Rules format was most token-efficient (~40% reduction).
- Improvement over zero-shot: 1.7–7.7x. Improvement over Reflexion baseline: 29–72%.
- For MarketMind: shadows analyzing the same asset (e.g., gold) could share their best few-shot examples via broadcast, while shadows on different assets would only receive cross-asset Rules.

**GenericAgent** (arXiv, April 2026) adds a self-evolution mechanism that converts verified past trajectories into reusable SOPs (standard operating procedures) and executable code. Its Contextual Information Density Maximization layer ensures memories don't bloat context windows.

### 1.2 Few-Shot Example Accumulation

**Self-Generated In-Context Examples** (NeurIPS 2025, Sarukkai et al.) provides the strongest direct evidence:
- Agents accumulate their own successful trajectories as few-shot examples for future prompts.
- Naive accumulation alone: ALFWorld 73→89%, Wordcraft 55→64%, InterCode-SQL 75→79%.
- With population-based curation + exemplar-level filtering: ALFWorld reached 93%, surpassing hand-crafted approaches.
- The improvement from self-generated examples **exceeded the improvement from upgrading GPT-4o-mini to GPT-4o**.

**Mechanism for MarketMind**: After each analysis cycle, the shadow saves its complete reasoning trajectory (data → analysis → prediction → confidence). When a prediction resolves, trajectories with direction accuracy >0.7 are promoted to the few-shot library. The next analysis prepends the 3 most relevant past successes as in-context examples, selected by embedding similarity to the current query.

### 1.3 Release Engineering for Agents

**AgentDevel** (arXiv, January 2026) reframes agent improvement as software release engineering:
- An implementation-blind LLM critic evaluates failures without accessing agent internals (prevents overfitting to the evaluator).
- Script-based executable diagnosis produces auditable specs of what went wrong.
- Flip-centered gating prioritizes two signals: pass→fail regressions (must fix) and fail→pass fixes (validates the fix is real).
- Maintains a single canonical version line — no branching, only linear improvement.

**For MarketMind**: Each shadow methodology change is a "release." Before promoting, run the new methodology against the old on a held-out test set of past predictions. A flip-centered gate checks: did any previously-correct prediction become wrong? Did any previously-wrong prediction become correct? Only promote if net improvement is positive AND no catastrophic regressions.

---

## 2. RAG-Based Agent Improvement

### 2.1 Self-Built Knowledge Bases

The core question: can an agent build and query its own knowledge base from past successes, and does this outperform static RAG?

**ICAL — In-Context Abstraction Learning** (NeurIPS 2024) shows VLMs generating their own examples from sub-optimal demonstrations. The agent's library grows more efficient over time — requiring less human feedback and fewer environment interactions. On VisualWebArena: 14.3% → 22.7%. The library becomes a *distilled* knowledge base: noisy raw trajectories are converted into clean, annotated examples.

**Knowledge Agent** (GitHub) implements a production-grade multi-agent curation system:
- Sub-agents: Analyst, Researcher, Curator, Auditor, Fixer, Advisor
- The Auditor detects duplicate entities and inconsistent naming
- The Curator applies quality scoring: semantic match (0.4), timeliness (0.3), authority (0.2), structure (0.1)
- Destructive operations (deletion, merging) require human approval

### 2.2 GraphRAG for Investment Knowledge

**Agentic GraphRAG for Capital Markets** (AWS, 2026) demonstrates graph-based knowledge accumulation for investment analysis:
- TigerGraph stores ~600K triples (entity-relation-entity)
- Agent dynamically routes between graph queries (Cypher) and document retrieval
- Multi-hop reasoning: "Who invested in company X, and what else did they invest in?"

**FinKario** (2025) combines event graphs with RAG:
- Beat best financial LLM by 18.81% on A-share backtests
- Removing the event graph reduced Sharpe ratio by 81%
- The graph captures causal relationships between events, not just similarity

**Corpus2Skill** (arXiv, April 2026) replaces embedding-based search with navigable skill hierarchies:
- LLM-generated summaries at each hierarchy level for routing
- Cross-branch navigation via entity indices
- Outperforms BM25, Dense, Hybrid, RAPTOR, and Agentic RAG on enterprise QA

### 2.3 Quality Filtering — Preventing Garbage Accumulation

The key risk in self-built knowledge bases: retrieving bad past analyses poisons future ones. Three mechanisms:

1. **Resolution-gated ingestion**: Only ingest analyses whose predictions have resolved with verified accuracy above threshold. Before resolution, store in a "pending" partition.
2. **Counterfactual filtering**: For each ingested analysis, ask "if the agent had used this as an example, would the outcome have been better?" Only ingest examples that pass this test.
3. **Diversity sampling**: Cluster ingested examples by embedding and keep only the best per cluster to prevent the few-shot library from becoming dominated by one regime.

**QR3AG** (ScienceDirect) adds dynamic retrieval thresholds — the system decides whether retrieval is needed at all based on query-response relevance, reducing retrieval redundancy by 50.5%.

---

## 3. Structured Improvement Loops

### 3.1 The Predict-Verify-Analyze-Update Loop

This is the core mechanism MarketMind needs. The literature converges on a four-stage closed loop:

```
Prediction → Outcome resolution → Error attribution → Knowledge update → Next prediction is better
```

**STAR** (arXiv, May 2026) provides the most actionable framework for error attribution:
- Decomposes agent failure into four stages: Evidence Package → Hypothesis Set → Analysis Structure → Decision Report
- Stage-wise audit localizes the error to a specific reasoning stage, not just "the final answer was wrong"
- Counterfactual candidate evaluation identifies the *decisive faulty stage* — the one whose correction restores consistency
- Fast/Slow routing: lightweight local repair for near-miss traces; replay-based full localization for severely contaminated traces

Applied to MarketMind: when a shadow's gold prediction is wrong, STAR-style decomposition would ask:
1. **Evidence stage**: Did the shadow look at the right data? (Missing indicators, stale data?)
2. **Hypothesis stage**: Did it form the right hypotheses? (Wrong causal model of what drives gold?)
3. **Analysis stage**: Did it weight evidence correctly? (Overweighting recent data, ignoring structural factors?)
4. **Decision stage**: Did the final synthesis make sense given the analysis? (Contradiction between analysis and prediction?)

### 3.2 ErrorProbe: Self-Improving Error Diagnosis

**ErrorProbe** (arXiv, April 2026) adds a three-stage pipeline:
1. Operationalize failure taxonomy to detect local anomalies
2. Symptom-driven backward tracing to prune irrelevant context
3. Multi-agent team (Strategist, Investigator, Arbiter) validates error hypotheses

The key insight: **verified episodic memory** — memories are only updated when error patterns are confirmed by the Arbiter, preventing the agent from "learning" from one-off noise.

### 3.3 IBM/UC Berkeley Failure Taxonomy (MAST)

14 distinct failure patterns across 3 categories, with **FM-3.3 (Incorrect Verification)** as the strongest predictor of failure:
- The agent declares success without checking ground truth
- For MarketMind: a shadow might report high confidence without verifying that all required data sources were actually fetched

### 3.4 Contrastive Learning from Outcomes

**ICTO — Iterative Contrastive Trajectory Optimization** (Dec 2024):
- Pairs successful and failed trajectories contrastively
- Step-level rewards computed as cumulative reward difference between success/failure pairs
- Uses DPO to favor actions leading to success and penalize those leading to failure
- Achieved 70.2 avg reward on WebShop, 75.6% success on ScienceWorld

**CUT — Contrastive Unlikelihood Training** (Feb 2024):
- Learns from language feedback (criticisms), not just scalar rewards
- With only 1,317 judgment examples, boosted LLaMA2-13B win rate from 1.87% → 62.56%
- Through 4 iterative rounds of self-improvement: reached 91.36%

For MarketMind: after each prediction resolves, pair the shadow's reasoning with what the reasoning *should have been* given the outcome. Feed both as a contrastive pair to the next cycle.

### 3.5 Anthropic's "Dreaming" — Production Implementation

Launched May 2026 for Claude Managed Agents:
- Scheduled process reviews past agent sessions, extracts cross-session patterns
- Writes learnings as plain-text notes and structured "playbooks"
- Does not modify model weights — all improvement is auditable
- Harvey (legal AI): ~6x task completion rate increase
- Part of a broader platform: Outcomes (rubric-based autonomous iteration) + Multi-Agent Orchestration

---

## 4. Explainable Improvement

### 4.1 How to Prove the Agent Got Better

The quant finance literature provides the gold standard for verifiable improvement:

**AlgoXpert Alpha Research Framework** (arXiv, March 2026):
- Three-stage protocol: In-Sample → Walk-Forward Analysis → Out-of-Sample
- Walk-forward uses rolling windows with purge gaps to prevent information leakage
- Majority-pass rule + catastrophic-veto rule for strategy approval
- Parameter stability over point optima: flat parameter regions generalize; sharp peaks are overfitted

**GT-Score** (Journal of Risk and Financial Management, 2026):
- Composite objective: performance + statistical significance + consistency + downside risk
- 98% improvement in generalization ratio (OOS/IS) vs. baseline objectives
- Walk-forward validation with 9 sequential splits + Monte Carlo with 15 seeds

**Interpretable Hypothesis-Driven Trading** (Deep, Deep & Lamptey, 2025–2026):
- Every trade originates from a human-readable hypothesis
- Rolling window validation across 34 independent test periods
- Honest reporting: aggregate returns were statistically insignificant (p=0.34), and the authors report this to combat publication bias

### 4.2 Audit Trails for Agent Reasoning

**What gets logged determines what can be explained:**

| Layer | What to Log | Why |
|-------|-------------|-----|
| **Intent** | Why the agent chose action X over Y | The cognitive path, not just the state |
| **Data provenance** | Exactly which data sources were fetched, when, and whether they succeeded | Prevents "analysis based on missing data" |
| **Reasoning chain** | Full chain-of-thought at each stage (Evidence → Hypothesis → Analysis → Decision) | Enables stage-level error attribution |
| **Tool calls** | Every tool invocation with parameters, results, and timing | Detects tool misuse patterns |
| **Decision** | Final prediction with confidence decomposition (why this confidence level?) | Enables calibration tracking |

**AEMA** (arXiv, January 2026) provides a process-aware multi-agent evaluation framework:
- Four roles: Planning Agent, Prompt-Refinement Agent, Evaluation Agents, Final Report Agent
- Produces traceable evaluation logs with lower score dispersion than single LLM-as-Judge

### 4.3 Before/After Comparison Methodology

To prove an improvement is real (not overfitted):

1. **Fixed test set**: Curate a static set of 50–100 historical prediction scenarios that never change. Every methodology change is evaluated against this same set.
2. **Out-of-time validation**: The test set must be chronologically after any training examples used in the methodology. No future information leakage.
3. **Statistical significance**: Run each methodology multiple times (LLMs are non-deterministic) and report mean + confidence interval, not a single run.
4. **Decomposition of improvement**: When accuracy improves, attribute it to specific categories:
   - Better data coverage (new sources, fewer fetch failures)
   - Better reasoning (improved analysis logic, fewer contradictions)
   - Better calibration (confidence better matched to outcomes)
   - Regime adaptation (methodology adapted to changed market conditions)
5. **Regression audit**: For every prediction that changed from correct to incorrect, document WHY. A methodology that fixes 10 errors but introduces 3 new ones needs the 3 regressions explained.

### 4.4 A/B Testing for Agent Methodology

**Amazon Bedrock AgentCore** (May 2026) provides the emerging production pattern:
- Recommendations generated from production traces
- Batch evaluation against curated datasets
- A/B test on live traffic with confidence intervals and statistical significance
- Configuration bundles as immutable, versioned snapshots

**Distributional** demonstrates the full loop: discover issues → root cause → A/B test fix → track improvement. Metrics: absolute error, user feedback scores, and production trace comparisons.

---

## 5. Synthesis: A Concrete Improvement Architecture for MarketMind Shadows

Combining the research into a practical mechanism:

### 5.1 The Improvement Loop (Per Shadow, Per Asset)

```
CYCLE N:
  1. Shadow loads its skill library (past successful analyses for this asset)
  2. Shadow loads relevant few-shot examples (top 3 by embedding similarity)
  3. Shadow produces analysis + prediction + confidence
  4. Analysis stored in "pending" partition (unresolved)

CYCLE N+1 (after outcome resolves):
  5. Verify outcome against prediction → compute Brier score, direction accuracy
  6. If direction accuracy > 0.7: promote analysis to skill library + few-shot store
  7. If direction accuracy < 0.5: run STAR-style error attribution
     - Which stage failed? Evidence? Hypothesis? Analysis? Decision?
     - Write a "lesson learned" rule: "When X condition holds, don't do Y"
  8. If direction accuracy < 0.3: flag for human review (possible regime change)
  9. Population broadcast: best rules/examples propagate to sibling shadows
 10. A/B test: every 5 cycles, compare current methodology against methodology from 5 cycles ago on fixed test set
```

### 5.2 Verifiable Improvement Metrics

| Metric | What It Proves | Mechanism |
|--------|---------------|-----------|
| **Direction accuracy (rolling 20)** | Are predictions getting more accurate? | Compare current 20-cycle window vs. 20-cycle window from 40 cycles ago |
| **Brier score trend** | Is calibration improving? | Lower = better probability estimates |
| **Error attribution distribution** | Are specific error categories shrinking? | Track STAR stage-level errors over time |
| **Few-shot hit rate** | Are retrieved examples actually relevant? | % of retrieved examples that share the correct prediction direction |
| **Generalization ratio** | Is improvement real or overfitted? | OOS accuracy / in-sample accuracy on each new cycle |
| **Regression count** | Are we breaking old correct predictions? | Count of previously-correct predictions that became wrong after methodology change |

### 5.3 Audit Trail (Minimum Viable)

Each shadow cycle writes one structured artifact:
```json
{
  "cycle_id": "gold-2026-05-18",
  "methodology_version": "v3.2",
  "stages": {
    "evidence": {"sources_fetched": 12, "sources_failed": 0, "data_window": "2024-01-01:2026-05-18"},
    "hypothesis": ["rate_cut_bullish", "inflation_hedge", "geopolitical_premium"],
    "analysis": "L3_interactive_v2 reasoning chain hash: a1b2c3",
    "decision": {"direction": "bullish", "confidence": 0.72, "confidence_decomposition": {...}}
  },
  "few_shot_examples_used": ["gold-2025-11-15", "gold-2026-01-20", "gold-2026-03-05"],
  "skills_loaded": ["gold-rate-sensitivity", "gold-crisis-response"],
  "prediction": {"direction": "up", "horizon": "7d", "confidence": 0.72}
}
```

When the outcome resolves, append:
```json
{
  "resolution": {"actual_direction": "up", "brier_score": 0.08, "direction_correct": true},
  "promoted": true,
  "lessons_learned": []
}
```

This artifact is the unit of improvement. Every methodology change can be evaluated by re-running it against the archive of resolved cycles.

---

## 6. Key References

| Paper/System | Date | Core Contribution |
|-------------|------|-------------------|
| Memento-Skills | Mar 2026 | Read-Write Reflective Learning, no weight updates |
| FORGE | May 2026 | Population broadcast of failure-refined memories |
| Self-Generated In-Context Examples | NeurIPS 2025 | Few-shot accumulation beats model upgrade |
| AgentDevel | Jan 2026 | Release engineering with flip-centered gating |
| STAR | May 2026 | Stage-level error attribution + counterfactual repair |
| ErrorProbe | Apr 2026 | Verified episodic memory with multi-agent validation |
| ICTO | Dec 2024 | Contrastive trajectory optimization from success/failure pairs |
| Anthropic Dreaming | May 2026 | Production self-improvement via playbook extraction |
| AlgoXpert | Mar 2026 | IS→WFA→OOS protocol with defense-in-depth |
| GT-Score | 2026 | Anti-overfitting objective function, 98% generalization improvement |
| Agentic GraphRAG (AWS) | 2026 | Graph-based knowledge accumulation for capital markets |
| Corpus2Skill | Apr 2026 | Navigable skill hierarchies over embedding search |
| AEMA | Jan 2026 | Process-aware multi-agent evaluation framework |
| MAST (IBM/UC Berkeley) | 2026 | 14 failure patterns, incorrect verification as top predictor |
| Amazon AgentCore | May 2026 | Production A/B testing loop with immutable config snapshots |
