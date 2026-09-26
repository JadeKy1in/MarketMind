# Shadow Agent Growth Models: Research Synthesis

**Date**: 2026-05-18
**Purpose**: Concrete, implementable approaches for MarketMind's 23 shadow analysts to specialize, forage, improve, and accumulate domain expertise over time.

---

## 1. Domain Specialization Architecture

### 1.1 The Standing Committee Problem

Current MoE and multi-agent research converges on a critical finding: in practice, a small core of "generalist" experts handles the majority of routing across all domains. The "Standing Committee" pattern (Wang et al., 2026 -- COMMITTEEAUDIT) shows that a compact coalition of routed experts captures the majority of routing mass across all domains, layers, and budgets. This means **naive agent specialization fails** -- agents drift toward generalism unless specialization is architected in from the start.

**Implication for MarketMind**: The 23 shadows should NOT be allowed to converge into generalists. Each needs a hard-coded domain boundary with separate knowledge stores.

### 1.2 Recommended Pattern: Router + Domain Silo

The **MoDEM** architecture (Simonds et al.) demonstrated +36.4% on MATH and +26.2% on Olympiad Bench by routing to domain-specialized models rather than using a single generalist. For MarketMind:

```
News Article → Flash Classifier (cheap model: Haiku/Gemini Flash)
  ├── Gold → Gold Shadow (domain: precious metals)
  ├── Crypto → Crypto Shadow (domain: digital assets)
  ├── Energy → Energy Shadow (domain: oil, gas, renewables)
  ├── Macro → Macro Shadow (domain: central banks, GDP, inflation)
  └── Cross-Domain → Router spawns 2-3 relevant shadows, ELITE synthesizes
```

**Flash classification cost**: ~20 tokens per article ($0.000001 at Flash tier). For 345 daily articles: ~$0.0003/day. This is the Smart Model Router pattern -- a cheap tier-0 model classifies, domain agents consume only relevant articles.

### 1.3 Separation of Persona vs. Knowledge

The critical architectural insight from production systems (Explai, Covasant): **prompt personas govern behavior (tone, decision rules, reasoning style); RAG governs knowledge (facts, relationships, domain data).** These must be in separate layers:

```
┌─────────────────────────────────────┐
│ BEHAVIOR: Prompt Persona             │  ← How the shadow thinks and decides
│ (Gold analyst tone, risk rules, etc) │
├─────────────────────────────────────┤
│ KNOWLEDGE: Domain RAG + KG           │  ← What the shadow knows (accumulates)
│ (Gold-specific articles, price data) │
├─────────────────────────────────────┤
│ MEMORY: Episodic Store               │  ← What the shadow learned (experiences)
│ (Past predictions, outcomes, lessons)│
└─────────────────────────────────────┘
```

The persona stays lean and stable. The knowledge and memory layers grow unbounded.

---

## 2. Information Foraging: Budget-Aware Retrieval

### 2.1 Budget Tracker Pattern (Google, 2026)

The Budget Tracker plug-in makes the agent explicitly aware of remaining tool-call and token budgets at each step. Results: **40.4% fewer search calls, 31.3% cost reduction.** The key insight: agents that see their remaining budget naturally shift from exploration to exploitation as budget depletes.

**MarketMind implementation**: Each shadow gets a daily Flash query quota (e.g., 50 Flash-tier queries/day). The Budget Tracker is appended to the system prompt:

```
Flash query quota remaining: {remaining}/{total}
Priority queue: {top_3_unresolved_questions}
```

The shadow sees its remaining quota and prioritizes accordingly.

### 2.2 Information Foraging Theory (IFT) for Agents

InForage (Qian et al., NeurIPS 2025 Spotlight) applies biological foraging theory to LLM agents:
- **Information Scent**: Intermediate retrieval quality signals guide search direction
- **Patch Model**: Information exists in clusters; agents decide when to leave a patch
- **Diet Model**: Agents select information sources based on profitability (value/cost)

**MarketMind implementation**: Shadows use an "information scent" scoring system for each potential query:
1. **Novelty score**: Is this likely new information vs. what I already know? (check against episodic memory)
2. **Relevance score**: How directly does this apply to my current analysis task?
3. **Actionability score**: Will this change my investment thesis?

Scent = novelty * relevance * actionability. Only queries above threshold proceed.

### 2.3 Exploration → Exploitation Transition

BAVT (Budget-Aware Value Tree Search, 2026) introduces budget-conditioned node selection: as budget depletes, the agent shifts from broad foraging to focused exploitation. This is parameter-free -- the remaining budget itself is the scaling exponent.

**MarketMind implementation**: In the first 25% of quota, shadows explore broadly (high novelty tolerance). In the last 25%, they exploit deeply (only query if actionability is high). No hard rules -- the remaining budget percentage drives the transition.

---

## 3. Verifiable Agent Improvement (Beyond Prompts)

### 3.1 The Winning Pattern: Heuristics Over Raw Trajectories

**ERL (Experiential Reflective Learning, 2026)**: Distills agent task trajectories into reusable heuristics capturing effective strategies and failure modes. Key finding: **heuristics generalize better than raw trajectory few-shot examples.** +7.8% success rate on Gaia2 from single-attempt trajectories.

**FORGE (2026)**: Failure trajectories → structured Rules/Examples. Examples achieved strongest returns; Rules offered ~40% fewer tokens. Champion broadcast (best agent's memory shared to all) improved performance 29-72%.

**MarketMind implementation**: Each shadow accumulates a `domain_heuristics.yaml`:
```yaml
gold_domain_heuristics:
  - id: h_001
    text: "Central bank gold purchases >100 tonnes/quarter = structural support, not speculative. Do not overweight ETF flow data in these regimes."
    source: trajectory_2026_0412_gold_rally
    successes: 14
    failures: 2
    confidence: 0.875
    created: 2026-04-12
    last_activated: 2026-05-15
  - id: h_002
    text: "When real yields fall but gold doesn't rally within 5 days, check USD strength. Dollar correlations dominate in these regimes."
    source: failure_2026_0318_gold_analysis
    successes: 8
    failures: 1
    confidence: 0.889
    created: 2026-03-18
    last_activated: 2026-05-10
```

Heuristics are retrieved by LLM-based relevance scoring (outperforms embedding-based per ERL findings), and top-K are injected into the shadow's context before analysis.

### 3.2 Dual Memory: Success + Failure

ERL found that **failure-derived heuristics excel on Search tasks; success-derived heuristics excel on Execution tasks.** Both are needed.

**MarketMind implementation**: Each shadow maintains:
- **Success memory**: "When I predicted X correctly, what was my reasoning chain?"
- **Failure memory**: "When I was wrong, what did I miss?" (FORGE pattern -- convert failure trajectories into Rules)

### 3.3 Confidence Decomposition (4 Independent Factors)

The production Fact-KG/Interpretation-KG split system (cycle 2837+ agent society) demonstrated that decomposing confidence into 4 independent, verifiable factors eliminates correlated signal problems:

1. **Usage** -- time-weighted retrieval frequency of supporting facts
2. **Consistency** -- stability of referenced facts across time
3. **Structural centrality** -- graph topology position of supporting nodes
4. **Pattern alignment** -- motif membership, trend alignment

All factor pairs maintained |r| < 0.15 after redesign.

**MarketMind implementation**: Each shadow's investment thesis is scored across these 4 dimensions. The combined score is a verifiable, auditable confidence metric -- not just "the LLM said it was confident."

### 3.4 What NOT to Do

- **Fine-tuning**: Expensive, catastrophic forgetting, stale as soon as data changes. Only justified for models serving 100K+ queries/day on a single domain.
- **Brute-force RAG**: Passive similarity retrieval adds latency without guaranteeing utility. MemRL (2026) demonstrated that RL-trained memory policies outperform RAG on complex benchmarks without fine-tuning.
- **Prompt-only evolution**: Brittle across runs, conflicts with prior knowledge, doesn't generalize. The prompt should govern behavior, not accumulate knowledge.

---

## 4. Agent Memory That Improves with Experience

### 4.1 Letta/MemGPT: OS-Level Memory Management

Letta (Apache 2.0, from the MemGPT paper) implements virtual context management -- treating the LLM context window like OS virtual memory:

| Tier | Analogy | Purpose |
|------|---------|---------|
| Core Memory | RAM | Editable blocks in context (persona, current task state) |
| Recall Memory | Disk Cache | Searchable conversation history outside context |
| Archival Memory | Cold Storage | Long-term persistent via vector search (pgvector) |

The agent **self-edits** its own memory using tool calls (`core_memory_append`, `archival_memory_insert`).

**Skill Learning** (Dec 2025): Two-stage process -- Reflection (evaluating past trajectories) + Creation (generating reusable skill files). Achieved **+36.8% relative improvement (15.7% absolute)** on Terminal Bench 2.0, with ~15.7% cost reduction.

**MarketMind implementation viability**: Letta is a full agent runtime platform, not a library. Adopting it means running shadows inside the Letta runtime. For a self-hosted system like MarketMind with custom pipeline logic, this is a heavy commitment. Partial adoption: use the tiered memory concept (core/recall/archival) with a lightweight implementation using local SQLite + ChromaDB for embeddings.

### 4.2 Episodic Memory with Outcome Labels

The BharatMLStack 4-layer episodic memory architecture (2026):
1. **Immutable Timeline** -- append-only experience records
2. **Episode Segmentation** -- with outcome labels (SUCCESS, FAILURE, PARTIAL, UNKNOWN)
3. **Episodic Graph** -- typed causal links (CAUSED_BY, LEARNED_FROM, RETRY_OF, CONTRADICTED)
4. **Generalized Facts** -- versioned heuristics with confidence scores

**Result**: 78% accuracy vs. 56% baseline using the same frozen LLM. Only memory differed -- 40% relative improvement.

**MarketMind implementation**: Each shadow writes an immutable daily log:
```json
{
  "date": "2026-05-18",
  "shadow": "gold_analyst",
  "articles_consumed": 12,
  "flash_queries_used": 8,
  "thesis": "Gold bullish short-term due to central bank buying + real yield divergence",
  "confidence": {"usage": 0.82, "consistency": 0.91, "centrality": 0.75, "pattern": 0.88},
  "outcome": "PENDING",
  "heuristics_activated": ["h_001", "h_007"],
  "heuristic_created": null
}
```

When outcome is later known (market moved), the log is updated with SUCCESS/FAILURE/PARTIAL and the relevant heuristics are reinforced or deprecated.

### 4.3 AgentFly: Q-Value Memory Selection

AgentFly (2025, #1 on GAIA at 87.88%) uses a Q-network to score memory cases by value -- higher Q = more successful past case, selected with higher probability.

**MarketMind simplification**: Instead of training a Q-network, use a simpler scoring function:
- Each heuristic has `successes` and `failures` counts
- Wilson score interval (lower bound) for statistical confidence
- Time-decay factor (older successes count less)
- Top-K by Wilson lower bound are injected into shadow context

This gives mathematically justified confidence bounds without ML overhead.

---

## 5. Concrete Implementation Path

### Phase 1: Foundation (Week 1-2)
1. **Flash classifier router**: 20-token classification of all 345 articles into domains. Uses Haiku (cheapest tier).
2. **Domain silo**: Each shadow gets its own knowledge base directory + ChromaDB collection. No cross-contamination.
3. **Daily immutable log**: JSON log per shadow per day. Manual outcome annotation for now.

### Phase 2: Foraging (Week 3-4)
4. **Budget tracker prompt injection**: Each shadow sees remaining Flash query quota.
5. **Information scent scoring**: Novelty * Relevance * Actionability for each potential query.
6. **Exploration/exploitation transition**: Budget percentage drives the shift, parameter-free.

### Phase 3: Heuristics (Week 5-6)
7. **Heuristic extraction from trajectories**: After each analysis cycle, shadow reflects: "What rule did I apply? Was I right?" Distills to heuristics.
8. **Wilson-score retrieval**: Top-K heuristics injected into context, selected by statistical confidence.
9. **Heuristic lifecycle**: Created → Active (successes > failures) → Deprecated (failures > successes * 2).

### Phase 4: Verifiable Metrics (Week 7-8)
10. **4-factor confidence decomposition**: Usage, Consistency, Structural centrality, Pattern alignment -- with correlation monitoring (target |r| < 0.15).
11. **Outcome backfill**: When market data resolves, update past logs with SUCCESS/FAILURE.
12. **Growth dashboard**: Per-shadow: heuristic count, avg confidence, success rate trend, knowledge base size.

### Key Design Principles
- **No fine-tuning**. All improvement is at the application layer (memory, heuristics, retrieval).
- **No weight updates**. The LLM stays frozen. Memory and heuristics improve.
- **Auditable by design**. Every heuristic, every log entry, every confidence score is a file on disk.
- **Quality over speed**. Budget-awareness means fewer queries, not faster queries.
- **Domain purity**. Shadows never cross-contaminate knowledge bases.

---

## References

- COMMITTEEAUDIT / "The Illusion of Specialization" -- Wang et al., 2026 (arXiv:2601.03425)
- MoDEM -- Simonds et al. (arXiv:2410.07490)
- ERL (Experiential Reflective Learning) -- 2026 (arXiv:2603.24639)
- FORGE -- 2026 (arXiv:2605.16233v1)
- MemRL -- January 2026 (novalogiq.com)
- InForage / IFT for LLMs -- Qian et al., NeurIPS 2025 Spotlight (arXiv:2505.09316)
- BAVT (Budget-Aware Value Tree Search) -- March 2026 (arXiv:2603.12634)
- Budget Tracker + BATS -- Google, 2026 (venturebeat.com)
- Letta/MemGPT -- Packer & Wooders, Apache 2.0 (letta.com)
- AgentFly (CBR + Q-value memory) -- 2025, #1 GAIA 87.88%
- Episodic Memory Architecture -- BharatMLStack, 2026 (meesho.github.io)
- Fact-KG / Interpretation-KG split -- Production agent society, 2026 (dev.to)
- Smart Model Router -- LobeHub/OpenClaw (lobehub.com)
