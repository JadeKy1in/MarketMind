# Knowledge Graph & Temporal Learning for Financial AI

**Date**: 2026-05-18
**Purpose**: Research for MarketMind knowledge accumulation architecture — understanding investable approaches to entity-centric memory, temporal reasoning, and causal graph learning.

---

## 1. Financial Knowledge Graphs (Open Source Landscape)

### 1.1 FinKG — Core Financial Ontology (IEEE 2023)

Kertkeidkachorn et al. built a manually-crafted financial KG from SEC EDGAR filings + open exchange data, verified by domain experts. Ontology-driven with well-defined entity types (companies, sectors, financial instruments, regulatory bodies) and relationship types (ownership, supply chain, policy impact).

**Relevance to MarketMind**: The ontology design is the reusable part. Their entity/relation taxonomy maps directly to what MarketMind needs: Company nodes, Sector nodes, CentralBank nodes, MacroIndicator nodes, with relationship edges like `impacts→`, `supplies→`, `regulates→`, `competes_with→`.

**Implementable takeaway**: Adopt their ontology schema as a starting taxonomy for MarketMind entities. Build incrementally rather than trying to pre-populate a full graph.

### 1.2 FinDKG — Dynamic KG with LLMs (2024, 71+ GitHub stars)

[github.com/BenikaHall/FinDKG](https://github.com/BenikaHall/FinDKG)

The most complete open-source implementation. Three components:

| Component | What it does | Tooling |
|-----------|-------------|---------|
| **FinDKG Dataset** | ~400K WSJ articles (1999–2023) extracted into temporal quintuples `(s, r, o, t, c)` | Custom extraction pipeline |
| **ICKG Generator** | Fine-tuned Mistral-7B for KG extraction from financial news | HuggingFace model |
| **KGTransformer** | Attention-based GNN for temporal link prediction and anomaly detection | PyTorch + DGL |

**Performance**: KGTransformer outperforms thematic ETFs on portfolio construction. ~10% improvement on link prediction.

**Implementable takeaway**: The `(subject, relation, object, timestamp, confidence)` quintuple is the right data model for MarketMind. Each analysis produces these quintuples — confidence comes from the 4-layer verification, timestamp from session time.

### 1.3 FinTechKG — Temporal RGCN for Prediction (2024)

Jeyaraman et al. (SMU). Three-dimensional extraction: Commercial Entities + Concept Entities + Temporal Dimensions. Combines temporal RGCN with FinBERT embeddings through a projection layer, then LSTM for temporal dependencies. 95% accuracy on revenue prediction.

**Implementable takeaway**: The FinBERT + GNN fusion pattern is a proven architecture. For MarketMind, after accumulating ~100+ entity memories, a lightweight GNN over the entity graph could surface cross-entity patterns invisible to per-asset analysis.

### 1.4 FinReflectKG — Agentic KG Construction (ACM ICAIF 2025)

Three extraction modes: single-pass, multi-pass, and reflection-agent-based. Constructed from S&P 100 10-K filings. 64.8% compliance on rule-based checks. Demonstrates that agentic (multi-agent, iterative refinement) extraction yields better quality than single-pass LLM extraction.

**Implementable takeaway**: MarketMind already has a multi-agent architecture (L1→L2→L3→Decision). KG extraction can be another agent in the pipeline — consuming the same hypothesis/verification outputs.

---

## 2. Temporal Knowledge Graphs (TKG)

### 2.1 Core Concept

Traditional KGs model static facts: `(ECB, policy_stance, hawkish)`. TKGs add time validity: `(ECB, policy_stance, hawkish, [2026-03, 2026-07])`. In finance, almost every fact is time-bound. TKGs are not optional — they are the correct data model.

### 2.2 TKG Embedding Methods

| Method | Approach | Best For |
|--------|----------|----------|
| **TComplEx** | Complex-valued tensor factorization with time | Link prediction |
| **BoxTE** | Box embeddings (regions in space) for time intervals | Representing temporal uncertainty |
| **TiPNN** | Temporal inductive path neural network | Reasoning over new entities |
| **GenTKG** | LLM + retrieval for generative TKG forecasting | "What will happen next?" queries |

### 2.3 TiAR — Time-Aware Relation Representation (OpenReview 2024)

Encodes relation features with temporal displacement values between events. Uses attention-based neighborhood aggregation with path constraints. Outperforms SOTA on ICEWS benchmarks (political event prediction — directly transferable to macro analysis).

### 2.4 Implementable Approach for MarketMind

**Data structure**: NetworkX or Neo4j graph where each edge carries `{valid_from, valid_to, confidence, source_session_id}`.

**Update mechanism**: When a new analysis contradicts a prior edge (e.g., "ECB hawkish" → "ECB dovish"), the old edge gets `valid_to = new_session_time` and the new edge gets `valid_from = new_session_time`. This preserves history while keeping the graph current.

**Query pattern**: "At time T, what was the state of entity E?" = traverse edges where `valid_from <= T AND (valid_to IS NULL OR valid_to > T)`.

**Simple implementation without ML**: Start with exact timestamp filtering. Add TKG embeddings (BoxTE or TComplEx) later when the graph exceeds ~10K edges and you need learned inference.

---

## 3. Causal Graph Learning from Text

### 3.1 CausalStock — End-to-End Causal Discovery (NeurIPS 2024)

Liang et al. design a lag-dependent temporal causal discovery mechanism. Uses a Functional Causal Model to encapsulate discovered relations for stock prediction. Tested on 6 real-world datasets (US, China, Japan, UK). Key insight: causal relations learned from news improve both prediction accuracy AND explainability.

### 3.2 FinCaKG — Financial Causality KG from Text (2024)

Ziwei Xu et al. End-to-end framework to construct a Financial Causality Knowledge Graph from unstructured text. Extensions: FinCaKG-Onto (2025) adds domain ontology layer.

### 3.3 RC2R — LLM + KG Causal Reasoning (arXiv 2024)

Yu et al. Fuse LLM reasoning with financial KGs for formal causal reasoning on risk contagion. Uses multi-scale contrastive learning to align text tokens and graph nodes. Visualizes causal pathways via Sankey diagrams. Strong OOD generalization.

**Implementable takeaway**: MarketMind already generates causal hypotheses ("Fed raise → USD strengthen → commodities fall"). After 20+ sessions, these form a causal chain dataset. The implementable step is:

1. **Extract**: Parse each session's `hypothesis_causal_chain` into structured `(cause, effect, mechanism, confidence, session_id, timestamp)` tuples.
2. **Validate**: When a hypothesis chain is later verified or rejected by market outcomes, update `confidence` and add `verification_result`.
3. **Query**: "What are the highest-confidence causal pathways for EUR/USD?" → traverse the causal subgraph, rank by verified confidence.
4. **Tool**: NetworkX is sufficient for <100K causal edges. Move to Neo4j if you need Cypher querying or want to combine with GraphRAG.

---

## 4. Graph RAG (Graph-based Retrieval Augmented Generation)

### 4.1 Key Finding: Hybrid Beats Pure

Multiple 2024–2025 papers converge on the same result: **Hybrid GraphRAG + VectorRAG outperforms either alone**.

| Approach | Strength | Weakness |
|----------|----------|----------|
| VectorRAG | Semantic similarity, fuzzy matching | Misses structured relationships, no traceability |
| GraphRAG | Precise relationship traversal, explainable | Misses semantically-similar but unlinked content |
| **HybridRAG** | Both + cross-validation | More complex to maintain |

### 4.2 MS GraphRAG + Neo4j

Microsoft GraphRAG uses LLM-derived entity/community summaries for hierarchical retrieval. Neo4j integration (`neo4j-contrib/ms-graphrag-neo4j`, March 2025) replaces the default LanceDB backend with Neo4j. This gives Cypher-based graph querying alongside community-summary-based retrieval.

### 4.3 Vector Institute KG-RAG

[github.com/VectorInstitute/kg-rag](https://github.com/VectorInstitute/kg-rag) — Open-source framework for SEC 10-Q filing analysis. Implements: standard RAG, CoT RAG, entity-based KG retrieval with beam search, Cypher-based Neo4j queries, GraphRAG with community detection.

### 4.4 Implementable Approach for MarketMind

**Phase 1 (immediate — NetworkX in-memory)**:
- After each analysis session, extract entities, relationships, and hypotheses into a NetworkX directed graph.
- Store session texts in a LanceDB vector table (SQLite-compatible, zero-config).
- For the next session's research phase: hybrid retrieval = vector search (LanceDB) for similar past analyses + graph traversal (NetworkX) for related entities/hypotheses.

**Phase 2 (scaling — Neo4j)**:
- When entity count exceeds ~1K or you need Cypher querying, migrate to Neo4j Community Edition (free).
- Use the Neo4j LLM Knowledge Graph Builder for automated entity extraction from session transcripts.
- Add Text2Cypher via a fine-tuned model (neo4j/text-to-cypher-Gemma-3-4B on HuggingFace).

**Phase 3 (full GraphRAG)**:
- Implement Microsoft GraphRAG with Neo4j backend.
- Entity summaries + community summaries become the retrieval source for session context.

### 4.5 Performance Data

- **Hallucination reduction**: GraphRAG cuts hallucinations ~6% vs conventional RAG on Finance Bench (Barry et al., 2025).
- **Token efficiency**: 80% reduction in token usage, 734x reduction for contradiction detection (O(n^2) → O(k*n)).
- **Accuracy**: HybridRAG outperforms both standalone VectorRAG and GraphRAG on earnings call Q&A (Sarmah et al., 2024).

---

## 5. Entity-Centric Memory

### 5.1 The Concept

Rather than storing all analysis outputs in a flat database, each entity (asset, sector, central bank) gets its own "memory file" that accumulates knowledge over time. Each new analysis enriches the entity's memory.

### 5.2 GenieAI — Context Graph Architecture

GenieAI's investment operations platform proposes: System of Record → System of Knowledge. Key pattern: **Context Graph** — linking events, decisions, and outcomes by entity, forming an audit trail that answers not just "what happened" but "why."

### 5.3 Design for MarketMind

**Entity memory schema** (JSON file per entity, stored in `data/entity_memory/`):

```json
{
  "entity_id": "eur_usd",
  "entity_type": "currency_pair",
  "created": "2026-05-18T00:00:00Z",
  "updated": "2026-05-18T00:00:00Z",
  "key_levels": {
    "support": [{"level": 1.0450, "source_session": "s_20260518_001", "confidence": 0.85}],
    "resistance": [{"level": 1.1250, "source_session": "s_20260518_001", "confidence": 0.72}]
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
      "cause": "ecb_rate_cut",
      "effect": "eur_weakness",
      "mechanism": "interest_rate_differential",
      "verified_count": 3,
      "rejected_count": 1,
      "last_verified": "2026-05-15"
    }
  ],
  "seasonal_patterns": [
    {"pattern": "EUR tends to weaken in May", "occurrences": 4, "total_observations": 5, "confidence": 0.65}
  ],
  "past_analyses": [
    {"session_id": "s_20260518_001", "decision": "short", "confidence": 0.72, "outcome": null}
  ]
}
```

**Update mechanism (per session)**:
1. Load entity memories for all entities referenced in the current analysis.
2. Append new observations, key levels, narratives.
3. If a prior claim is contradicted (e.g., ECB stance changed), close the old interval (`to = now`) and open a new one.
4. Increment `verified_count`/`rejected_count` for causal pathways based on market outcome data.
5. Write back updated memories.

**Storage**: JSON files for <1K entities (simple, inspectable, git-trackable). Migrate to a document store (MongoDB or LanceDB) if entity count exceeds 1K or concurrent writes become necessary.

---

## 6. Contrastive Learning for Financial Text

### 6.1 ContraSim — Self-Supervised Clustering (OpenReview 2024)

Weighted self-supervised contrastive learning on financial headlines. Integrating ContraSim features improved WSJ headline classification by 7%. Key insight: the learned similarity space intrinsically clusters days with homogeneous market movements — without labeled data.

### 6.2 BAM Embeddings — Finance-Specific (EMNLP 2024)

"Greenback Bears and Fiscal Hawks" paper. Fine-tuned financial text embeddings on 14.3M query-passage pairs using weakly-supervised contrastive pre-training. Shows increased sensitivity to finance-specific, forward-looking, and date-specific queries.

### 6.3 DGRCL — Dynamic Graph + Contrastive Learning (arXiv 2024)

Combines dynamic temporal evolution and static relational structures via contrastive learning. Tested on NASDAQ and NYSE, significantly outperforms TGL baselines.

### 6.4 Implementable Approach for MarketMind

**Practical use case**: MarketMind produces hypothesis texts like "ECB hawkish → EUR likely to strengthen." Contrastive learning trains embeddings to map "ECB hawkish" close to "EUR strengthens" in vector space, validated by subsequent price movements.

**Implementation path**:
1. **Collect positive pairs**: When a hypothesis is verified (hypothesis text + correct outcome), that's a positive pair.
2. **Collect negative pairs**: Rejected hypotheses (hypothesis text + wrong outcome) are negative pairs.
3. **Fine-tune**: Use SimCSE or E5-style contrastive fine-tuning on a small embedding model (e.g., `all-MiniLM-L6-v2`) with MarketMind's own hypothesis-outcome data.
4. **Threshold**: Requires ~500+ verified hypotheses before fine-tuning is meaningful. Until then, use off-the-shelf BAM embeddings.

---

## 7. Recommended Implementation Path

### Phase A: Data Structures (weeks 1–2)

| Component | Tool | Data Model |
|-----------|------|------------|
| Entity memory | JSON files in `data/entity_memory/` | Schema from §5.3 |
| Session graph | NetworkX DiGraph | `(s, r, o, t, c)` quintuples from §1.2 |
| Vector store | LanceDB | Session texts + entity memory texts |
| Causal chains | NetworkX subgraph | `(cause, effect, mechanism, confidence, t)` from §3 |

### Phase B: Enrichment (weeks 3–4)

- After each session, run an extraction agent that parses the session transcript into structured quintuples and updates entity memory files.
- Build the hybrid retrieval: LanceDB vector search + NetworkX graph traversal.
- Start accumulating verified/rejected causal pathways.

### Phase C: Learning (month 2+)

- When ~500+ verified hypotheses exist, fine-tune a contrastive embedding model (SimCSE pattern) on MarketMind's own data.
- When entity count exceeds ~1K, migrate NetworkX to Neo4j Community Edition.
- Implement basic temporal link prediction: given entity state at T, predict state at T+1.

### Tools Summary

| Tool | Role | Cost | When to adopt |
|------|------|------|---------------|
| **NetworkX** | In-memory graph | Free | Day 1 |
| **LanceDB** | Vector store + document store | Free, embedded | Day 1 |
| **Neo4j Community** | Persistent graph DB + Cypher | Free | When >1K entities or need GraphRAG |
| **BAM embeddings** | Finance-specific text embeddings | Free (HuggingFace) | Day 1 for vector search |
| **Neo4j KG Builder** | Automated entity extraction | Free (Neo4j Labs) | When adopting Neo4j |
| **SimCSE / E5** | Contrastive fine-tuning framework | Free (HuggingFace) | When >500 verified hypotheses |

---

## 8. Key Papers (Quick Reference)

| Paper | Venue | Year | What it proves |
|-------|-------|------|----------------|
| FinDKG | ICAIF | 2024 | LLM-built dynamic KGs outperform ETFs for thematic investing |
| CausalStock | NeurIPS | 2024 | Causal graphs from news improve stock prediction + explainability |
| HybridRAG | arXiv | 2024 | Graph+Vector retrieval beats either alone |
| GraphRAG (Barry) | GenAIK | 2025 | KGs reduce hallucinations 6%, cut tokens 80% in finance |
| ContraSim | OpenReview | 2024 | Contrastive learning clusters market regimes without labels |
| FinTechKG | MDPI | 2024 | Temporal RGCN + FinBERT = 95% financial prediction accuracy |
| BAM Embeddings | EMNLP | 2024 | Finance-specific embeddings outperform general embeddings |
| RC2R | arXiv | 2024 | LLM+KG fusion for causal risk contagion reasoning |
