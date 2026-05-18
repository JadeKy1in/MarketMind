# Phase I Architecture Concept: Iterative Learning Layer for MarketMind

**Date**: 2026-05-18
**Status**: Research synthesis — architecture recommendation
**Sources**: self-evolving-ai-investment.md, kg-temporal-learning-finance.md, multi-agent-learning-verification.md
**Phase H continuity**: Phase H built deep structural analysis (6 modules, 21 shadows, 4-layer verification). Phase I adds the learning loop that makes those analyses improve over time.

---

## 1. Core Concept: The Predict-Verify-Learn Loop

Phase H's pipeline produces structured hypotheses: each with a directional call, confidence score, causal chain, and time horizon. Twenty-one shadow agents analyze events from different angles, debate, and converge on a consensus. Then the session archives and the system moves on.

The gap: the next session starts from scratch. The 50th EUR/USD analysis is no better informed than the 1st. Shadows that consistently outperform get no more influence than shadows that don't. Causal claims that verified are treated identically to causal claims that failed.

Phase I closes this loop. The architecture is:

```
PREDICT ──→ WAIT (timeline expires) ──→ VERIFY (compare to outcome) ──→ LEARN ──→ UPDATE ──┐
                                                                                              │
   ←────────────────────────────────────── NEXT CYCLE (enriched) ─────────────────────────────┘
```

Each step is mechanical and verifiable:
- **Predict**: Every directional call is stored as a structured record with machine-resolvable criteria. "EUR/USD will rise" is ambiguous; "EUR/USD closing price on 2026-06-18 will exceed closing price on 2026-05-18" is not.
- **Verify**: A cron-resolution agent fetches ground truth from public APIs (market prices, FRED, ECB releases) and scores every prediction whose deadline has passed.
- **Learn**: Scores feed into four learning systems: calibration curves per agent, reputation weights per domain, entity memory enrichment, and knowledge graph edge resolution.
- **Update**: The next session loads entity memories, reputation-weighted agent contributions, and verified causal pathways as context — so the analysis starts from accumulated knowledge, not a blank slate.

The key design principle: **structure over free-text**. Every prediction, lesson, and entity state change is a structured record — not a paragraph of LLM reflection. Structured records are queryable, composable, and auditable. Free-text reflection is none of those things.

---

## 2. Learning Mechanisms

### 2.1 Prediction Verification Pipeline (Foundation)

This is the backbone. Without it, nothing else works. Every prediction the system makes is stored in a `PredictionStore` table:

```
{id, session_id, shadow_id, entity, claim_type, claim_value, confidence, horizon_days,
 resolution_date, resolution_criteria, sources_used, outcome: null, brier_score: null}
```

When `resolution_date` passes, a `ResolutionAgent` (cron job, runs daily) fetches the ground truth and scores the prediction. Resolution criteria are machine-verifiable: "Gold closing price on date X > closing price on date Y" fetches from a price API. "Fed will cut rates at June meeting" fetches from FRED or the Fed press release page.

This produces a growing dataset of scored predictions. At 1 session/week with ~10 directional calls per session, that's ~500 scored predictions per year — enough for statistically meaningful calibration after 6 months and enough for contrastive fine-tuning after ~12 months.

**Data needed**: Historical session outputs (already archived), market price APIs, economic release calendars.
**Produces**: Scored prediction dataset, per-agent per-domain accuracy metrics.
**Feasibility**: High. The session archive already exists. Market price APIs are freely available (Yahoo Finance, FRED, ECB). The resolution agent is a ~200-line Python module with a cron trigger.

### 2.2 Calibration Tracking with Brier Scores

Every probabilistic claim gets a Brier score: `BS = (p - outcome)^2`. The Brier score decomposes into calibration (do 80%-confidence predictions come true 80% of the time?) and resolution (how well do predictions discriminate between events?). This decomposition tells you *why* an agent scores poorly — overconfidence vs. inability to discriminate.

Per-agent calibration curves are maintained per domain. An agent that is consistently overconfident on tech stocks but well-calibrated on macro gets a per-domain confidence adjustment via Platt scaling. Before final output, the agent's historical calibration data scales its confidence: if 80% historically means 65% accuracy, output 65%.

**Data needed**: Scored prediction dataset from the verification pipeline.
**Produces**: Per-agent per-domain calibration curves, Platt scaling parameters applied at output time.
**Feasibility**: High. Brier scoring is a one-line formula. Platt scaling is a logistic regression over historical predictions. Both run in-process with no external dependencies.

### 2.3 Structured Post-Mortem (Reflection Engine)

After each prediction resolves, a `ReflectionAgent` compares the original analysis against what actually happened and produces a structured lesson:

```
{prediction_id, outcome, delta, root_cause_category, updated_belief, timestamp}
```

Root cause taxonomy drives targeted retrieval: was the error from a missing data source? A flawed causal chain? An over-weighted signal? A regime-change blind spot? At the next analysis time, the orchestrator queries the lesson store for past errors on the same entity, same sector, and same error category, and pre-loads relevant lessons into each agent's context.

Amazon Analyst Agents (ICML 2025) demonstrated this pattern: 44.5% to 81.3% first-response accuracy across four cycles purely through reflection + memory accumulation. No model retraining — just structured lessons retrieved at analysis time.

**Data needed**: Resolved predictions + original session transcripts.
**Produces**: Structured lesson records queryable by entity, error category, and recency.
**Feasibility**: Medium. The reflection agent is an LLM call that produces structured output. The retrieval step is a LanceDB query. The main cost is token usage per reflection (~2K tokens per resolved prediction).

### 2.4 Feature-Level Error Attribution (TextGrad Pattern)

Going beyond "you were wrong" to "here's which part of your reasoning was wrong." When a shadow's gold prediction resolves wrong, the system back-propagates:

- "Your thesis cited falling real rates, but real rates actually rose 15bp during the period."
- "You relied on a 3-week-old Fed speech. Source quality was low."
- "You missed China's gold import data which showed a 40% drop. Shadow S3 covered this but it wasn't surfaced to you."

This is TextGrad-style feedback — natural-language attribution of error to specific reasoning steps. The MENTOR framework (Zhejiang University, 2025) demonstrates that this produces measurably better subsequent analyses than numerical scores alone.

**Data needed**: Structured prediction records with `key_reasons` field, resolved outcomes, cross-shadow analysis transcripts.
**Produces**: Per-error attribution records that inform agent prompt enrichment and source credibility updates.
**Feasibility**: Medium. Requires the `key_reasons` field to be populated for each prediction (already planned in the hypothesis card structure). The attribution agent is an LLM call comparing predicted reasons to actual outcomes.

### 2.5 Source Credibility Tracking

Every analysis cites sources. Each source gets a credibility score, tracked per-domain (a source may be credible on US equities but not on crypto). When a claim citing source S proves wrong, S's score decreases. When a claim citing S proves right, S's score increases. Sources below a credibility threshold are pruned from the active RAG index; high-credibility sources are retrieved preferentially.

This is the RLFKV pattern (Ant Group, arXiv 2602.05723): decompose financial answers into atomic knowledge units, verify each against sources, use results as reward signals. No human annotation required.

**Data needed**: Source citations in prediction records, resolved outcomes.
**Produces**: Per-source per-domain credibility scores, pruned RAG index.
**Feasibility**: Medium. Requires source citation tracking in prediction records (a schema addition). The credibility update is a simple exponential moving average.

---

## 3. Entity Memory System

Each tracked entity (EUR/USD, AAPL, gold, Fed, ECB, etc.) accumulates a "memory file" — a structured JSON document that grows richer with each analysis session. The system gets better at analyzing EUR/USD the 50th time than the 1st time because it carries forward what it has learned.

### 3.1 Memory Schema

```json
{
  "entity_id": "eur_usd",
  "entity_type": "currency_pair",
  "created": "2026-05-18T00:00:00Z",
  "updated": "2026-05-18T00:00:00Z",
  "key_levels": {
    "support": [{"level": 1.0450, "source_session": "s_001", "confidence": 0.85}],
    "resistance": [{"level": 1.1250, "source_session": "s_001", "confidence": 0.72}]
  },
  "regime_assessment": [
    {"regime": "trending_down", "from": "2026-05-01", "to": null, "confidence": 0.78}
  ],
  "central_bank_stance": [
    {"bank": "ecb", "stance": "dovish", "from": "2026-04-15", "to": null, "confidence": 0.82}
  ],
  "dominant_narrative": [
    {"narrative": "eurozone recession fears", "from": "2026-05-01", "to": null, "strength": 0.75}
  ],
  "causal_pathways": [
    {
      "cause": "ecb_rate_cut", "effect": "eur_weakness",
      "mechanism": "interest_rate_differential",
      "verified_count": 3, "rejected_count": 1, "last_verified": "2026-05-15"
    }
  ],
  "seasonal_patterns": [
    {"pattern": "EUR tends to weaken in May", "occurrences": 4, "total_observations": 5}
  ],
  "past_analyses": [
    {"session_id": "s_001", "decision": "short", "confidence": 0.72, "outcome": null}
  ]
}
```

### 3.2 Update Mechanism

After each session, for every entity analyzed:
1. Load the entity's memory file from `data/entity_memory/{entity_id}.json`.
2. Append new observations: key levels, narratives, regime assessments.
3. If a prior claim is contradicted (e.g., ECB stance changed from hawkish to dovish), close the old interval (`to = now`) and open a new one. This preserves history.
4. Increment `verified_count` or `rejected_count` for causal pathways based on newly resolved predictions.
5. Write back the updated memory.

### 3.3 Retrieval at Analysis Time

Before analyzing an entity, the orchestrator loads its memory file and injects relevant context into agent prompts:
- Current regime assessment
- Active central bank stances
- Verified causal pathways with highest confidence
- Historical key levels that proved significant
- Past analysis outcomes (what did we get right/wrong last time?)

### 3.4 Storage Strategy

JSON files in `data/entity_memory/` for Phase I. This is sufficient for <1K entities, human-inspectable, git-trackable, and requires zero infrastructure. Migrate to a document store (LanceDB or MongoDB) if entity count exceeds ~1K or concurrent writes become necessary.

---

## 4. Shadow Learning Loop

Phase H's 21-shadow ecosystem already has specialization (different methodologies, different data sources). Phase I adds outcome-weighted reputation so shadows that consistently beat baseline get more influence, and the consensus becomes smarter over time.

### 4.1 Per-Agent Reputation Tracking

Each shadow maintains a running score per domain:

```
reputation = weighted_accuracy * calibration_score * recency_factor
```

- `weighted_accuracy`: recent Brier scores vs. all-shadow baseline
- `calibration_score`: 1.0 - Expected Calibration Error (ECE)
- `recency_factor`: exponential decay, half-life ~90 days

Shadows that consistently outperform on a domain (e.g., Shadow S7 is good at gold) get higher weight on that domain. Shadows that consistently underperform get down-weighted. The final consensus uses reputation-weighted averaging instead of equal weighting.

### 4.2 Domain Specialization Discovery

The reputation system naturally surfaces domain specialization. A shadow doesn't declare "I'm good at gold" — the data reveals it. After enough resolution cycles:

| Shadow | FX Brier | Equity Brier | Commodity Brier | Macro Brier |
|--------|:--------:|:------------:|:---------------:|:-----------:|
| S1_macro | 0.18 | 0.22 | 0.25 | **0.12** |
| S7_gold | 0.24 | 0.28 | **0.14** | 0.26 |
| S12_tech | 0.20 | **0.15** | 0.22 | 0.24 |

S1_macro gets higher weight on macro questions; S7_gold on commodity questions; S12_tech on equity questions. This specialization emerges from data, not from pre-assigned roles.

### 4.3 Cross-Shadow Methodology Transfer

Shadows share methodology insights without sharing raw analysis (which would create groupthink). If S7_gold consistently beats baseline on gold, the system extracts its reasoning framework — "When analyzing gold, prioritize: (1) real rates, (2) central bank reserves, (3) COMEX positioning" — and injects this heuristic into other shadows when they analyze gold. The shadows don't share *what* they think; they share *how* they think.

### 4.4 Dissent Amplification

When a minority of shadows is consistently correct against a majority consensus, the system amplifies minority voices. If 18/21 shadows are bullish on gold and the 3 bearish shadows are right, the next cycle gives those 3 dissenting shadows higher weight for that asset class. This prevents the system from converging on comfortable consensus and ignoring valid contrarian signals.

### 4.5 Agent Retirement

Shadows below a reputation threshold for N consecutive cycles (suggested: N=5) get flagged for methodology review. This is not automatic deletion — a shadow with consistently poor performance may have a systematic reasoning flaw that needs human review. The flag produces a report: "Shadow S14 has underperformed baseline for 5 consecutive cycles. Key error patterns: overconfidence on directional calls, over-reliance on dated macro reports."

---

## 5. RAG vs Knowledge Graph vs Hybrid

### 5.1 The Answer: Hybrid GraphRAG + VectorRAG

The 2024-2025 research consensus is unambiguous: **hybrid beats pure**. Multiple independent papers converge on the same finding:

| Approach | Strength | Weakness |
|----------|----------|----------|
| **VectorRAG** (pure) | Semantic similarity, fuzzy matching | Misses structured relationships, no traceability |
| **GraphRAG** (pure) | Precise relationship traversal, explainable | Misses semantically-similar but unlinked content |
| **HybridRAG** | Both + cross-validation | More complex to maintain |

In finance specifically, GraphRAG cuts hallucinations ~6% vs. conventional RAG (Barry et al., 2025) and reduces token usage 80%. HybridRAG outperforms both standalone approaches on earnings call Q&A (Sarmah et al., 2024). The reason: financial reasoning requires both semantic similarity ("find analyses similar to this one") AND structured relationship traversal ("what causal pathways connect ECB rate decisions to EUR/USD?"). Neither alone is sufficient.

### 5.2 Phase I Implementation: NetworkX + LanceDB

**Phase I (immediate)**:
- **Graph store**: NetworkX directed graph in memory, persisted to JSON. Each edge carries `{valid_from, valid_to, confidence, source_session_id}`. Entities are nodes; causal claims, correlations, and narrative links are edges.
- **Vector store**: LanceDB (embedded, zero-config, SQLite-compatible). Stores session texts, entity memory texts, and resolved lesson records as vector-queryable documents.
- **Hybrid retrieval**: For the next session's research phase, run both: vector search (LanceDB) for semantically similar past analyses + graph traversal (NetworkX) for related entities and causal pathways. Merge and deduplicate results.

**Phase II (scaling, when >1K entities or need Cypher)**:
- Migrate NetworkX to Neo4j Community Edition (free).
- Add the Neo4j LLM Knowledge Graph Builder for automated entity extraction.
- Use Text2Cypher for natural-language graph queries.

**Phase III (full GraphRAG, when >5K entities and need community detection)**:
- Implement Microsoft GraphRAG with Neo4j backend.
- Entity summaries and community summaries become the retrieval source.

### 5.3 Why Not Pure Knowledge Graph

A pure temporal knowledge graph with learned embeddings (TComplEx, BoxTE) requires significant data volume to train meaningful embeddings — typically >10K edges. MarketMind starts with zero edges and accumulates slowly (~10-20 per session). Learned TKG embeddings are the right destination but the wrong starting point. Exact timestamp filtering + graph traversal works immediately and provides value from the first session.

### 5.4 Why Not Pure Vector RAG

Vector RAG alone cannot answer structured questions like "what has historically driven EUR/USD the most?" or "which causal pathways involving the ECB have been verified?" These require graph traversal. Vector search returns similar-sounding analyses, but similarity is not causation. The system needs both.

---

## 6. Verification Pipeline

### 6.1 Ground Truth Sources

The verification pipeline needs machine-queryable ground truth. Priority sources:

| Data Type | Source | API | Update Frequency |
|-----------|--------|-----|:---:|
| FX prices | Yahoo Finance / OANDA | REST | Daily |
| Equity prices | Yahoo Finance | REST | Daily |
| Commodity prices | Yahoo Finance | REST | Daily |
| Bond yields | FRED (St. Louis Fed) | REST | Daily |
| Central bank rates | ECB, FRED | REST | Per-decision |
| Economic releases | FRED, ECB SDW | REST | Per-release |
| Crypto prices | CoinGecko / Binance | REST | Real-time |

All are free or have free tiers sufficient for MarketMind's resolution volume (~10 predictions per session, 1-2 sessions per week).

### 6.2 Resolution Criteria Must Be Machine-Verifiable

This is a hard rule. If a prediction cannot be automatically scored against a public data source, it does not enter the learning loop. Examples:

- **Valid**: "EUR/USD closing price on 2026-06-18 will exceed closing price on 2026-05-18"
- **Valid**: "Fed will cut the federal funds rate by 25bp at the June 2026 meeting"
- **Valid**: "Gold will trade above $2,500 at any point in the next 30 days" (requires intra-period high tracking)
- **Invalid**: "EUR/USD will be volatile" (ambiguous — what threshold defines "volatile"?)
- **Invalid**: "Market sentiment will improve" (not machine-measurable)

The prediction schema includes a `resolution_criteria` field that specifies exactly what API to query and what comparison to make.

### 6.3 Handling "Right for Wrong Reasons"

A prediction resolves correct but the causal chain was wrong. Example: predicted EUR/USD would rise because ECB would hold rates, but ECB actually cut rates and EUR/USD rose anyway (risk-on flow overwhelmed the rate differential).

This is handled by the `key_reasons` field in prediction records. At resolution time, the resolution agent separately scores:
1. **Directional accuracy**: Was the price direction correct? (binary score)
2. **Causal accuracy**: Did the cited reasons actually materialize? (multi-factored score, requires checking each cited reason against ground truth)

A prediction that is directionally right for wrong reasons gets a high directional score but a low causal score. This feeds into the causal knowledge graph: the edge "ECB rate hold → EUR strength" was NOT supported by this outcome, even though EUR strength occurred. The edge is weakened despite the correct directional call.

### 6.4 Time Horizon Alignment

MarketMind operates on multiple time scales. The verification pipeline must respect them:

| Analysis Type | Horizon | Resolution Check | Minimum Predictions Before Calibration |
|---------------|:-------:|:----------------:|:--------------------------------------:|
| Intraday (scout events) | 1-5 days | Daily | ~50 (2-3 months) |
| Weekly directional | 7-30 days | Weekly | ~30 (6 months) |
| Monthly macro themes | 30-90 days | Monthly | ~20 (1-2 years) |
| Quarterly regime calls | 90-180 days | Quarterly | ~10 (2-3 years) |

Phase I should focus on **medium-horizon predictions** (7-30 days) because they resolve quickly enough to produce a meaningful dataset within months while being structurally rich enough to support causal analysis. Short-horizon predictions produce more data points but carry less structural insight; long-horizon predictions carry rich insight but resolve too slowly for iterative learning.

---

## 7. Recommended Phase I Scope

### 7.1 What to Build First (Phase I Core — 4-6 weeks)

These four components form the minimum viable learning loop. They compose to deliver measurable improvement without requiring any of the deferred components.

**1. Prediction Store + Verification Pipeline (Priority 0)**
- SQLite table: `predictions` with the schema from section 6.2
- `ResolutionAgent`: daily cron that finds past-due predictions, fetches ground truth, computes Brier scores
- ~200-line Python module
- **Depends on**: Nothing (the session archive already exists)
- **Unlocks**: Everything else — calibration, reputation, entity memory enrichment, knowledge graph resolution

**2. Calibration Tracking (Priority 0)**
- Per-agent per-domain Brier score history
- Platt scaling parameters computed weekly
- Confidence adjustment applied at output time
- ~150-line Python module
- **Depends on**: Prediction store with scored predictions

**3. Entity Memory System (Priority 1)**
- JSON files in `data/entity_memory/` per the schema in section 3
- `EntityMemoryAgent`: loads entity memories at session start, updates them at session end
- Initial entities: EUR/USD, gold, S&P 500, Fed, ECB, US 10Y, BTC
- ~250-line Python module
- **Depends on**: Session archive (for populating initial memories), prediction store (for updating verified/rejected counts)

**4. Agent Reputation System (Priority 1)**
- Per-shadow per-domain reputation scores using EMA
- Reputation-weighted consensus replacing equal-weighted consensus
- Dissent amplification when minority view is consistently correct
- ~200-line Python module
- **Depends on**: Prediction store with per-agent scored predictions

### 7.2 What to Defer (Phase I Extension — months 2-4)

These require the core to be running first, both because they depend on scored predictions and because they need >=50-100 resolved predictions to be meaningful.

**5. Structured Post-Mortem (Reflection Engine)**
- ReflectionAgent that produces structured lessons from resolved predictions
- Lesson retrieval at analysis time
- ~200-line Python module + LLM calls
- **Depends on**: >=50 resolved predictions, entity memory system

**6. Hybrid Retrieval (NetworkX + LanceDB)**
- NetworkX causal graph populated from session analyses
- LanceDB vector store of session texts and entity memories
- Hybrid query at session research time
- ~300 lines across two modules
- **Depends on**: Entity memory system, >=10 sessions for meaningful graph

**7. Source Credibility Tracking**
- Per-source per-domain credibility scores
- RAG index biased toward high-credibility sources
- ~150-line Python module
- **Depends on**: >=30 resolved predictions with source citations

### 7.3 What to Defer to Phase J+ (months 4-12)

These require substantial data accumulation (>=100 verified predictions, >=1K graph edges) or are optimization layers that only make sense after the core loop is proven.

- **Feature-level error attribution (TextGrad)**: Requires structured `key_reasons` on every prediction and a reflection agent to compare reasons to outcomes
- **Cross-shadow methodology transfer**: Requires reputation system + sufficient cross-shadow performance data
- **Knowledge distillation (21 shadows to Core model)**: Requires substantial training data from shadow operations
- **Contrastive embedding fine-tuning**: Requires >=500 verified hypothesis-outcome pairs
- **Neo4j migration**: Required when entity count exceeds ~1K; premature before then
- **Full GraphRAG (Microsoft GraphRAG + Neo4j)**: Optimization layer; core learning loop works without it
- **Multi-agent self-play debate**: Requires reputation system + structured debate framework; research shows simpler approaches (reflection + memory) often outperform more complex designs (AEL, COLM 2026)

### 7.4 Design Principles

1. **Structure over free-text**: Every prediction, lesson, and entity state change is a structured record. LLM reflection text is supplementary, not primary.
2. **Start simple, measure, then add complexity**: AEL's finding that basic reflection + memory (Sharpe 2.13) outperformed more complex variants is consistent across surveyed systems. Build the simplest thing that closes the loop, measure it, and only add complexity when the data shows it helps.
3. **No foundation model retraining required**: Every Phase I mechanism operates at the application layer — prompt enrichment, statistical post-processing, structured memory, and retrieval augmentation. RL fine-tuning is an optimization, not a prerequisite.
4. **Time-aware everything**: All scores, weights, and edges decay over time. A perfect 2024 track record may mean nothing in a 2026 rate cycle. Exponential decay with domain-appropriate half-lives.
5. **Machine-verifiable resolution criteria only**: If a prediction cannot be automatically scored against a public data source, it stays out of the learning loop.

---

## References

- FinCrew: Self-Evolving Multi-Agent Financial Assistant (GitHub: tanmingtao1994-gif/fincrew)
- FinMem: Layered Memory Trading Agent (ICLR 2024)
- Amazon Analyst Agents: Self-Improving Multi-Agent Framework (ICML 2025) — 44.5% to 81.3% via reflection
- KalshiBench: LLM Epistemic Calibration (arXiv:2512.16030)
- AEL: Agent Evolving Learning for Portfolio Allocation (COLM 2026) — simple beats complex (Sharpe 2.13)
- TRACE: Temporal Rule-Anchored Chain-of-Evidence on KGs (arXiv:2603.12500)
- HybridRAG: Graph+Vector outperforms either alone (Sarmah et al., 2024)
- FinDKG: Dynamic KG with LLMs (ICAIF 2024) — (s, r, o, t, c) quintuple model
- RLFKV: Fine-Grained Knowledge Verification (Ant Group, arXiv:2602.05723)
- MENTOR: TextGrad Outcome Feedback for Financial Events (Zhejiang University, 2025)
- MADKE: Knowledge-Enhanced Multi-Agent Debate (Neurocomputing, 2025)
- SMAGDi: Multi-Agent Distillation 40B to 6B (NeurIPS 2025)
