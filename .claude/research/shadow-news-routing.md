# Shadow News Routing: Classification + Domain Dispatch for 15+8 Agent System

**Date**: 2026-05-18
**Context**: MarketMind Phase H — route 345 daily news articles to 15 domain-expert shadows + 8 daredevil agents (23 total consumers). Each agent sees only relevant news. Current approach: hardcoded keyword lists per shadow (fragile, misses novel terms, no daredevil support).

---

## 1. LLM-Based News Classification

### Approach: Haiku 4.5 Batch Classification (Multi-Label)

Use Haiku 4.5 via Anthropic Batch API to classify every headline + snippet into the 15 domain taxonomy. Multi-label output — one article can tag to gold + macro + volatility simultaneously.

**Cost estimate (345 articles/day):**

| Component | Tokens | Cost |
|-----------|--------|------|
| Prompt (taxonomy + instructions, cached) | ~800 input | — |
| 345 headlines+snippets (~40 tok each) | ~13,800 input | $0.014 (standard) |
| Classification output (~15 labels × 3 tok) | ~1,550 output | $0.008 (standard) |
| **Daily total (standard API)** | | **~$0.022** |
| **Daily total (Batch API, 50% off)** | | **~$0.011** |
| **Monthly (~21 trading days)** | | **~$0.23** |

With prompt caching (90% off cached input tokens), the cost drops further — effectively free at this scale. The Batch API 24-hour SLA is fine: classify yesterday's news overnight, shadows consume results in the morning.

**Why Haiku over keyword matching:**
- Handles novel terms (new sanctions regime, emerging sector names)
- Captures cross-domain relevance (oil price spike → energy + industrials + EM)
- Multi-label output maps naturally to fan-out routing
- 345 articles is well below any rate limit

### Academic backing

- **BASIR (April 2025)**: Fine-tuned embeddings + LLMs achieve 0.605 weighted F1 on 81-sector classification. LLM-only ranking reaches 0.997 NDCG. Key finding: LLMs match or exceed fine-tuned models for classification when taxonomy is well-defined.
- **LabelFusion (Dec 2025)**: On 10-class multi-label Reuters-21578, zero-shot LLM achieves 75.9% F1. Hybrid LLM+RoBERTa with MLP voting reaches 96.0% macro F1. The zero-shot baseline is strong enough for routing — you don't need the hybrid for dispatch decisions.
- **FactSet production pipeline**: Migrated from Boolean rules to DistilBERT multi-label classification with confidence scoring + category-specific thresholds. Multi-dimensional tagging (one article → many categories) is the default.

### Taxonomy structure

Map MarketMind's 15 domains to standard financial classification:
- **Sector-based**: tech, healthcare, financials, consumer, industrials, energy, RE, metals
- **Asset-class**: gold, crypto, bonds, FX
- **Cross-cutting**: volatility, macro, EM

RavenPack's taxonomy provides a reference: 56 event groups, 6,900+ event categories, entity-level tagging. Their enrichment metadata (relevance 0-100, novelty days, sentiment) is worth emulating — pass relevance + sentiment alongside the domain tag.

---

## 2. News Routing Architecture

### Tiered pipeline (recommended)

```
345 articles → [T1: Keyword fast-path] → [T2: Haiku classification] → [T3: Fan-out dispatch]
                   ↓ free, ~2ms                    ↓ ~$0.01/day            ↓ per-agent queues
              ~60% articles routed          ~40% ambiguous/esoteric     23 agent inboxes
```

**Tier 1 — Keyword fast-path (free, deterministic)**
Keep the existing keyword lists but use them as a pre-filter, not the sole router. Articles matching clear keywords (e.g., "gold" + "ETF", "Fed" + "rate") skip Tier 2 and go directly to relevant agent inboxes. This handles ~60% of articles for free.

**Tier 2 — Haiku classification (cheap, semantic)**
Articles that don't match any keyword or match ambiguously (e.g., "copper surge" — is it metals, industrials, or macro?) go through Haiku multi-label classification. The classifier returns domain tags + confidence + relevance score.

**Tier 3 — Fan-out dispatch**
Each domain tag maps to one or more agent inboxes. A single article tagged `[gold, macro, volatility]` lands in 3 expert inboxes + potentially all daredevils (if confidence > threshold).

### Macro-event broadcast

Articles tagged `macro` with relevance > 80 or confidence > 0.9 go to ALL agents. This handles FOMC minutes, NFP reports, CPI surprises, geopolitical shocks — events where domain expertise is secondary to "the world just changed."

Implementation: a `broadcast` flag in the classification output. If set, bypass per-agent routing and push to all 23 inboxes.

### Hybrid: Haiku + embedding similarity fallback

For articles where Haiku confidence < 0.6, fall back to embedding similarity against a labeled corpus of past articles:
1. Pre-compute embeddings for 500 representative articles per domain (7,500 total)
2. At classification time, compute cosine similarity of new article against domain centroids
3. Route to top-2 domains by similarity if Haiku is uncertain

This costs ~$0.001/day (embedding API calls for ~5 uncertain articles) and catches edge cases Haiku is unsure about.

**Research backing**: vLLM Semantic Router uses signal fusion (keyword + regex + embedding + BERT) with fast paths short-circuiting before ML inference. CSDN hybrid routing benchmarks show 95% accuracy with P90 latency ~50ms by using embedding fast-path for 90% of queries + LLM fallback for 10%.

---

## 3. Agent-Initiated Information Retrieval

### Query budget model

Each agent gets a daily query budget (tokens or API calls). Agents decide when and how to spend it — they don't passively consume routed news; they actively request additional data.

**Implementation pattern:**

```
Agent receives domain-routed news inbox → reads headlines
  → decides: "I need more data on story X"
  → calls tool: search_news("gold ETF flows last 5 days", max_results=10)
  → cost deducted from budget
  → results appended to agent context
```

**Budget allocation** (per agent, per day):
| Agent type | Daily budget | Rationale |
|-----------|:---:|------|
| Domain expert | 5 queries | Focused on one domain, routed news is usually sufficient |
| Daredevil | 10 queries | Needs cross-domain context to form contrarian views |
| Macro | 10 queries | Highest information surface area |

Total: (15 × 5) + (8 × 10) + (1 × 10) = 165 queries/day maximum. At ~$0.002 per Haiku search query, that's ~$0.33/day ceiling — cheap insurance against information gaps.

### Tool definition (Anthropic tool-use pattern)

```python
{
    "name": "search_news",
    "description": "Search news archive and external sources for specific information",
    "parameters": {
        "query": "string — natural language, e.g. 'gold ETF inflows past week'",
        "max_results": "int — 1-20, default 10",
        "date_range": "string — 'today', 'week', 'month', optional"
    }
}
```

### Research backing

- **BATS framework (Google, Nov 2025)**: Budget-aware tool-use. Agents given explicit remaining-budget signals in their context make better decisions about when to "dig deeper" vs. "pivot." Without budget awareness, agents hit a performance ceiling regardless of budget size. 68% of enterprise agent deployments hit budget overruns from runaway tool loops.
- **MCP-Zero (June 2025)**: Proactive tool requests reduce token consumption by 98% vs. injecting all tool schemas upfront. Agents request tools on demand rather than carrying thousands of definitions in context.
- **MarketSenseAI (April 2026)**: Deployed multi-agent equity system routing 4 specialist agents (News, Fundamentals, Dynamics, Macro) through a synthesis agent. Specialist contributions are adaptively weighted by market regime — a pattern directly applicable to daredevil weighting.

### Anti-pattern to avoid

Do NOT give agents unbounded search. Without a budget constraint, agents will loop on "just one more search" — the BATS research shows this is the #1 cause of cost overruns in production. Every tool call MUST decrement a counter visible in the agent's context window.

---

## 4. Cost Optimization Summary

| Layer | Technique | Daily cost | Cumulative |
|-------|-----------|:---:|:---:|
| T1 | Keyword pre-filter | $0.00 | $0.00 |
| T2 | Haiku Batch classification (345 articles) | $0.01 | $0.01 |
| T3 | Embedding fallback (~5 uncertain articles) | $0.001 | $0.011 |
| — | Agent query budgets (max 165 queries) | $0.33 | $0.34 |
| — | Prompt caching (Haiku system prompt) | -$0.005 savings | $0.335 |
| **Total daily** | | | **~$0.34** |
| **Total monthly** | ~21 trading days | | **~$7.07** |

### Deduplication: fetch once, serve many

When two agents request the same external data (e.g., both gold and metals agents query "copper inventory levels"), the result is cached by query hash. Second agent gets cached result, no API cost. Implement with a simple in-memory TTL cache (5-minute expiry for news queries).

---

## 5. Implementation Roadmap (Recommended Sequence)

1. **Build taxonomy + Haiku classifier** (1 day). Define 15-domain taxonomy with descriptions, few-shot examples per domain. Test on 100 labeled articles from past week. Measure precision/recall per domain.
2. **Implement Tier 1 fast-path** (0.5 day). Keep existing keyword lists, add pre-filter logic. Route matches directly, send remainder to Tier 2.
3. **Implement Tier 2 Haiku batch pipeline** (0.5 day). Batch API overnight classification, store results in shadow state.
4. **Add fan-out dispatch + broadcast** (0.5 day). Map domain tags to agent inboxes. Broadcast macro events to all agents.
5. **Add agent query budgets** (1 day). Define tool schema, implement budget tracking, add cache layer.
6. **Add embedding fallback** (0.5 day, optional). Only if Tier 2 confidence is frequently low on real data.

**Total: ~4 days implementation.** Start with Tiers 1-2-3 (classification + dispatch) and iterate on agent query budgets based on observed agent behavior.

---

## References

- BASIR: Budget-Assisted Sectoral Impact Ranking. arXiv:2504.13189 (April 2025)
- LabelFusion: LLM + RoBERTa hybrid for financial news classification. HFEPX (Dec 2025)
- FactSet: Replacing rule-based tagging with DistilBERT. FactSet Insights (2025)
- RavenPack News Analytics: 6,900 event categories, 56 event groups, entity-level enrichment
- Bloomberg BICS: 7-level industry classification, 53,000+ firms
- BATS: Budget-Aware Tool-Use Enables Effective Agent Scaling. Google/NYU (Nov 2025)
- MCP-Zero: Proactive Toolchain Construction. Xiamen Univ/USTC (June 2025)
- MarketSenseAI: Multi-Agent LLM Equity System. arXiv:2604.17327 (April 2026)
- vLLM Semantic Router: Hybrid signal fusion for prompt classification routing

> **Key judgment**: Haiku 4.5 batch classification is the right backbone for this problem. At $0.01/day, it's cheaper than the engineering time to maintain keyword lists. The 3-tier pipeline (keyword → Haiku → embedding fallback) gives you free routing for obvious cases, semantic understanding for ambiguous ones, and a safety net for the uncertain edge. Agent query budgets close the loop: agents consume routed news passively but can actively pull more data when they need it, within a hard cost ceiling.
