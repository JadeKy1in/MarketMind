# Heuristic Workflow v4: Token-Efficient News Investigation Architecture

**Research conducted**: 2026-05-17
**Purpose**: Design a progressively-deepening news browse-and-investigate system for MarketMind where Flash (cheap model) pre-filters and Pro (expensive model) only investigates the most promising leads.

**Current State**: MarketMind collects ~587 articles from 33 sources per session. The old approach dumps all headlines into Flash for preprocessing, then passes top signals to Pro for L1 analysis — token-inefficient, no investigative depth.

---

## 1. Progressive Disclosure Architecture

### Core Principle: Three-Tier Information Loading

The canonical pattern formalized by Anthropic (December 2025) with Agent Skills, now adopted by OpenAI, Google, GitHub, and Cursor. Adapted for news investigation:

| Tier | What | Token Cost | Trigger |
|------|------|:---:|---------|
| **L1 — Discovery** | Headlines + source authority tier + publish timestamp | ~50-100 tokens/article | Always loaded (batch-scanned by Flash) |
| **L2 — Selected Summaries** | 2-3 sentence summary + key entities + Flash score | ~200 tokens/article | Only for articles passing Flash pre-filter |
| **L3 — Full Content** | Full article text or API response data | Variable (high) | Only for confirmed investigation paths |

**Reported gains**: 60-80% reduction in token consumption, significant improvement in instruction-following accuracy.

### Reference Implementations

**Aparture "Review Gates" Pipeline** (Josh Speagle, 2025):
```
Stage 1: Fetch all items
Stage 2: Flash model runs YES/MAYBE/NO triage + 1-sentence justification per item
Gate 1: Human review decides which MAYBE items proceed
Stage 3: Scoring (0-10) only on items passing Gate 1
Stage 4: Deep analysis only on top-scored items
```

**ActuallyRelevant.news 4-Stage Pipeline**:
| Stage | Description |
|-------|-------------|
| Pre-screening | Flash model: issue-area classification, 1-10 relevance score, emotion tag (~500 articles/day) |
| Full Analysis | 12 structured fields: relevance title, topic, summary, key quote, 6 relevance factors |
| Editorial Selection | LLM discards ~50% of remaining candidates (prefer systemic shifts, concrete impact) |
| Deduplication | pgvector similarity + LLM judgment |
| **Cost**: ~$1/day total |

**OpenAI / Perplexity Deep Research Architecture**:
All use the ReAct pattern (Reasoning + Acting in a loop):
```
Think → Search → Observe → Think Again → Search Again → ... → Synthesize
```
Key insight: they do NOT fetch all documents at once. Each observation shapes the next search query. This is the progressive deepening loop we need to emulate.

### Application to MarketMind

```
SESSION_START
  │
  ├─[TIER 1] Flash scans ALL 587 headlines + source tiers
  │   Output: structured JSON with scores per article
  │   Token cost: ~587 × 100 = ~58,700 input tokens (Flash = cheap)
  │
  ├─[FLASH GATE] Articles with score ≥ 5 proceed to Tier 2
  │   Estimated survivors: ~50-100 articles
  │
  ├─[TIER 2] Flash generates structured summaries for survivors
  │   Output: 2-3 sentence summary, key entities, cross-source flags
  │   Token cost: ~75 × 200 = ~15,000 tokens (Flash)
  │
  ├─[PRO GATE] Pro model reads Tier 2 summaries, decides which to investigate
  │   Estimated investigations: ~5-15 threads
  │
  ├─[TIER 3] Pro conducts deep investigation per thread
  │   Fetches full article text, calls relevant APIs (FRED, SEC, etc.)
  │   Token cost: high but focused (5-15 threads, not 587 articles)
  │
  └─[SYNTHESIS] Pro writes final briefing from investigation results
```

---

## 2. Flash Model as Pre-Filter

### Scoring Dimensions for "Investigative Potential"

Based on Hagar et al. (2025) "LLM-Assisted News Discovery" paper (Northwestern) — o3 achieved **F1=0.94** for lead extraction with ±1 accuracy up to 92% for newsworthiness assessment.

**Flash model scoring rubric** (output as structured JSON):

```json
{
  "article_id": "src_bloomberg_20260517_001",
  "headline": "Fed signals potential rate pause amid cooling inflation",
  "source_tier": 1,
  "scores": {
    "market_impact_potential": 7,      // 0-10: Could this move markets?
    "cross_source_corroboration": 5,   // 0-10: How many other sources are reporting similar?
    "contradicts_consensus": 3,         // 0-10: Does it challenge prevailing market narrative?
    "investigative_depth_needed": 6,    // 0-10: Does this need API calls or just reading?
    "urgency_timeliness": 8            // 0-10: Is this breaking/actionable now?
  },
  "composite_score": 6.2,              // Weighted average
  "classification": {
    "category": "macro",               // macro | company | geopolitical | sentiment | technical
    "api_triggers": ["fred_cpi", "fed_minutes"],  // Which APIs would this investigation need?
    "estimated_investigation_steps": 3  // How many deepening steps expected?
  },
  "cross_source_flags": {
    "corroborated_by": ["reuters_20260517_042", "wsj_20260517_015"],
    "contradicted_by": [],
    "unique_angle": true
  },
  "decision": "INVESTIGATE"            // SKIP | MAYBE | INVESTIGATE
}
```

### Classification Taxonomy (from production systems)

**LSEG MarketPsych** text tagging engine uses:
- **Entities**: 20+ types (companies, currencies, commodities, central banks, locations)
- **Topics**: 1,000+ (accounting, litigation, sustainability, M&A, etc.)
- **Events**: 4,000+ (dividend payments, factory construction, sanctions, etc.)
- **Emotions**: 14 types (anger, fear, optimism, etc.)

For MarketMind, a simplified 5-category taxonomy:
1. **macro** — monetary policy, economic indicators, inflation, GDP, employment
2. **company** — earnings, M&A, leadership changes, product launches, regulatory actions
3. **geopolitical** — trade policy, sanctions, conflicts, elections, treaties
4. **sentiment** — social media trends, analyst upgrades/downgrades, fund flows
5. **technical** — unusual options activity, volume anomalies, insider transactions

### Flash Model Selection

**Proven small-model configurations** from research:

| Model | Use Case | Source |
|-------|----------|--------|
| Gemini 2.5 Flash | Fast triage (YES/MAYBE/NO) | Aparture default |
| GPT-4o-mini | Triage + extraction + assessment | Global Crisis Monitor |
| o4-mini | High-accuracy classification | Hagar et al. news discovery |
| Qwen 3 14B | On-premise document search (95% claim support) | On-Premise AI for Newsroom |
| Gemma 3 12B | Budget option for offline/local | On-Premise AI for Newsroom |

**Recommendation for MarketMind**: Use Anthropic's Haiku (fastest/cheapest Claude model) for Flash tier. Keeps everything in one API ecosystem, consistent tool-use format.

---

## 3. Dynamic Tool Selection

### Trigger-Condition → API-Call Mapping

Based on cascading selection patterns (skm-select, AG2 context-aware routing, Sentiment-Trading-Alpha pipeline):

```
Regex triggers (microseconds) → Semantic match (milliseconds) → LLM classification (seconds)
Fastest match wins.
```

**Implementation: Cascading Classifier for News Articles**

```python
# Stage 1: Regex/Keyword Fast-Path (deterministic, µs latency)
TRIGGER_MAP = {
    # Macro triggers
    (r"\b(Fed|FOMC|Powell|rate\s+(hike|cut|pause|decision)|inflation|CPI|PPI|PCE)\b", "macro"): [
        "fred_series",        # FRED economic data
        "eia_petroleum",      # If energy-related
        "bls_employment",     # If jobs-related
    ],
    # Company triggers
    (r"\b(earnings|revenue|EPS|guidance|SEC\s+filing|10-K|10-Q|8-K)\b", "company"): [
        "sec_edgar",          # SEC filings
        "yfinance_financials",# Stock data
        "earnings_dates",     # Earnings calendar
    ],
    # Geopolitical triggers
    (r"\b(tariff|sanction|war|conflict|invasion|coup|embargo)\b", "geopolitical"): [
        "commodity_prices",   # Oil, gold, wheat, etc.
        "currency_pairs",     # Affected FX pairs
        "shipping_indices",   # Baltic Dry, container rates
    ],
    # Sentiment triggers
    (r"\b(analyst\s+(upgrade|downgrade)|price\s+target|fund\s+flow)\b", "sentiment"): [
        "reddit_wallstreetbets",
        "bluesky_trending",
    ],
    # Technical triggers
    (r"\b(unusual\s+options|block\s+trade|dark\s+pool|insider\s+(buy|sell))\b", "technical"): [
        "options_flow",
        "insider_transactions",
    ],
}

# Stage 2: Semantic similarity (ms latency) for articles not caught by regex
# Embed headline → cosine similarity against trigger embeddings → select closest

# Stage 3: Flash model classification (s latency) as fallback
# Flash reads headline + snippet → outputs structured classification
```

### Key insight from Baidu research:
**63% of inference errors** in unoptimized agents stem from tool selection mistakes. Dynamic tool filtering reduces context window usage from **78% → 32%** and shortens response time by **41%**.

### Tool Budget per Category

| Category | Default Tool Budget | Max API Calls |
|----------|:---:|:---:|
| macro | 3 API calls | 5 |
| company | 3 API calls | 5 |
| geopolitical | 2 API calls | 4 |
| sentiment | 2 API calls | 3 |
| technical | 1 API call | 2 |

---

## 4. Investigation Depth Management

### Google's BATS Framework (December 2025)

The state-of-the-art for budget-aware AI investigation:

| Component | Mechanism |
|-----------|-----------|
| **Budget Tracker** | Continuous signal of remaining token + tool-call budget at every step |
| **Planning Module** | Adjusts stepwise effort to remaining budget |
| **Verification Module** | Decides "dig deeper" vs. "pivot" per thread |
| **LLM-as-Judge** | Selects best answer when budget exhausted |

**Results**: 40.4% fewer search calls, 19.9% fewer browse calls, 31.3% lower cost, comparable accuracy.

### BAVT (Budget-Aware Value Tree)

Models multi-hop reasoning as a dynamic search tree:
- **Budget-conditioned node selection**: uses remaining-budget ratio as scaling exponent
- **Smooth exploration→exploitation transition**: automatically shifts from broad search to focused exploitation as budget depletes
- **Theoretical guarantee**: >=1-epsilon probability of correct answer within budget

### MarketMind Investigation Limits

```python
INVESTIGATION_LIMITS = {
    "max_threads_per_session": 10,       # Hard cap on parallel investigation threads
    "max_depth_per_thread": 3,           # T1 headline → T2 summary → T3 deep analysis
    "max_api_calls_per_thread": 5,       # Prevent API call loops
    "max_flash_tokens_per_session": 100_000,   # Flash model budget
    "max_pro_tokens_per_session": 50_000,      # Pro model budget
    "min_confidence_to_decide": 0.70,    # "Close enough to decide" threshold
    "diminishing_return_threshold": 0.05, # Confidence gain per step < 5% → stop
}
```

### Diminishing Returns Detection

After each deepening step, measure confidence delta:
```
step_0_confidence = 0.0
step_1_confidence = 0.55  (after reading Tier 2 summary)
step_2_confidence = 0.72  (after first API call)      delta = +0.17
step_3_confidence = 0.75  (after second API call)     delta = +0.03  ← STOP
step_4_confidence = 0.76  (after third API call)      delta = +0.01  ← WASTE
```

### Loop Prevention (from MartinLoop governance)

| Guardrail | Mechanism |
|-----------|-----------|
| `maxIterations` | Hard cap, enforced at request level |
| `maxDelegationDepth` | Prevents A→B→C→A delegation loops |
| `budgetTracker` | Real-time remaining budget displayed in prompt |
| Graceful Termination | Summarizes progress when limit hit, does not crash |

### BG-MCTS Token Budget Alignment

From the 2025 paper "Aligning Tree-Search Policies with Fixed Token Budgets":
- **Budget-guided widening**: virtual "generative child" nodes compete; widening encouraged when budget is ample, suppressed when low
- **Late-stage completion bias**: as budget depletes, system biases toward completing existing threads rather than spawning new ones
- Implemented as PUCT exploration bonus annealing via budget sufficiency ratio

---

## 5. Parallel Hypothesis Tracking

### Structured State Tracking (JSON, not natural language)

All production multi-agent investigation systems use JSON for inter-agent handoffs — natural language handoffs are too ambiguous and token-heavy.

**Diagnosis Agents Pipeline** (investigator → verifier → solver):
```json
{
  "thread_id": "T03",
  "headline": "Fed signals potential rate pause amid cooling inflation",
  "hypotheses": [
    {
      "id": "H1",
      "statement": "Fed will pause rate hikes at next FOMC meeting",
      "confidence": 0.72,
      "supporting_evidence": [
        {"source": "article_body", "quote": "multiple Fed officials signaled comfort with current stance"},
        {"source": "fred_cpi", "value": "CPI YoY 2.8% (down from 3.1%)"}
      ],
      "contradicting_evidence": [
        {"source": "article_body", "quote": "one hawkish member warned of premature easing"}
      ],
      "investigation_steps_taken": 2,
      "investigation_steps_remaining": 1,
      "diminishing_returns_flag": false,
      "status": "ACTIVE"
    },
    {
      "id": "H2",
      "statement": "Rate pause already priced in, market reaction will be muted",
      "confidence": 0.45,
      "status": "ACTIVE"
    }
  ],
  "pruned_hypotheses": [
    {
      "id": "H3",
      "statement": "Fed will actually cut rates next meeting",
      "prune_reason": "No evidence across any source; contradicted by all officials quoted",
      "confidence_at_prune": 0.08
    }
  ]
}
```

### Tree of Thoughts Investigation Pattern

From the "Tree of Thoughts Investigation" engine:
```
Generate 3 hypotheses → Score all → Prune to top 2 → Expand survivors → Score again → Synthesize best branch
```

- **Plausibility scoring**: 0-1 per thought node, assessed by LLM
- **Pruning**: Keep top 2 hypotheses at each depth, drop the rest
- **Auto-activation**: Trigger multi-hypothesis mode at 5+ entities; simpler cases use single-pass

### Adversarial Validation (Confidence Calibration)

From the Adversarial Validator Agent pattern:
- Outputs `ValidationResult` with challenge score (0-100)
- Recalculates `revised_confidence = original * (1 - challenge_score/100)`
- **Prunes/escalates** when top hypothesis drops below 40%

### LToT: Avoiding Myopic Pruning

"Lateral Tree-of-Thoughts" (arXiv 2510.01500) identifies two failures:
1. **Breadth saturation**: near-duplicate samples waste budget
2. **Myopic pruning**: early noisy utility scores discard branches with delayed payoff

**Solution**: Separate frontier into **mainlines** (high-utility, narrow allocation) and **laterals** (logically consistent but low-utility, wide allocation). Laterals are kept alive but receive a "short probe" before judgment — a successive-halving race where each rung costs logarithmically more.

---

## 6. Concrete Flash+Pro Collaboration Architecture

### The Koda Model-Routed Sub-Agent Pattern

Assign models to roles based on cognitive demand:

| Role | Model | Task |
|------|-------|------|
| **Scout** | Flash/Haiku | Scan 587 headlines, score, classify, identify cross-source links |
| **Planner** | Pro/Sonnet | Read Flash-scored summaries, decide which threads to investigate, plan API calls |
| **Investigator** | Pro/Sonnet | Execute investigation threads: call APIs, read full text, update hypotheses |
| **Verifier** | Flash/Haiku | Cross-check claims against sources, calibrate confidence scores |
| **Reporter** | Flash/Haiku | Synthesize final briefing from structured investigation state |

**Cost savings**: Koda reports ~80% reduction vs. running everything on the most expensive model.

### Lyra SmartRouting Complexity Classification

Pre-classify each article/signal by complexity before assigning to a model:
- **TRIVIAL**: Single-source, non-contradictory, low market impact → Flash only, no Pro involvement
- **SIMPLE**: 2-3 sources, moderate confidence needed → Flash summary + single Pro review
- **MODERATE**: Multi-source with contradictions, API calls needed → Full Flash→Pro→Verify pipeline
- **COMPLEX**: Breaking news, high market impact, geopolitical → Pro-led with Flash support

### Master Investigation Loop (Pseudocode)

```python
async def run_investigation_session(news_articles: list[Article]) -> Briefing:
    # === TIER 1: Flash pre-filters all headlines ===
    flash_input = format_tier1_prompt(news_articles)  # Headlines only, ~50k tokens
    tier1_results: list[FlashScore] = await flash_model.classify(flash_input)
    
    # Flash gate: keep scores >= 5
    survivors = [a for a in tier1_results if a.composite_score >= 5]
    # ~50-100 survive from 587
    
    # === TIER 2: Flash generates summaries for survivors ===
    flash_input2 = format_tier2_prompt(survivors)  # Add snippets, ~15k tokens
    tier2_results: list[FlashSummary] = await flash_model.summarize(flash_input2)
    
    # Deduplicate cross-source clusters
    clusters = cluster_by_entity_and_topic(tier2_results)
    # ~20-40 unique story clusters from 50-100 articles
    
    # === GATE: Pro decides investigation threads ===
    pro_planning_input = format_planning_prompt(clusters)  # ~5k tokens
    investigation_plan: InvestigationPlan = await pro_model.plan(pro_planning_input)
    # Selects top 5-15 threads, assigns tool budgets
    
    # === TIER 3: Pro executes investigations ===
    investigation_state = HypothesisTracker(max_threads=10, max_depth=3)
    for thread in investigation_plan.threads:
        for depth in range(thread.max_depth):
            # Load full article content or call APIs
            evidence = await execute_tool_calls(thread.api_triggers)
            # Update hypothesis confidence
            delta = investigation_state.update(thread.id, evidence)
            # Check diminishing returns
            if delta < DIMINISHING_RETURN_THRESHOLD:
                break  # Stop deepening this thread
            if investigation_state.confidence(thread.id) >= DECISION_THRESHOLD:
                break  # Close enough to decide
    
    # === VERIFY: Flash checks consistency ===
    verify_input = format_verification_prompt(investigation_state)
    verified_state = await flash_model.verify(verify_input)
    
    # === SYNTHESIS: Pro writes final briefing ===
    # Pro only sees structured investigation state, not raw articles
    briefing = await pro_model.synthesize(verified_state)
    return briefing
```

### Token Budget Allocation

| Phase | Model | Estimated Tokens | Cost (Anthropic pricing) |
|-------|-------|:---:|:---:|
| Tier 1: Flash scans 587 headlines | Haiku | 58,700 in / 5,000 out | ~$0.08 |
| Tier 2: Flash summarizes 75 survivors | Haiku | 15,000 in / 7,500 out | ~$0.03 |
| Gate: Pro plans investigation threads | Sonnet | 5,000 in / 2,000 out | ~$0.03 |
| Tier 3: Pro investigates 10 threads | Sonnet | 30,000 in / 15,000 out | ~$0.15 |
| Verify: Flash checks consistency | Haiku | 5,000 in / 2,000 out | ~$0.01 |
| Synthesis: Pro writes briefing | Sonnet | 8,000 in / 4,000 out | ~$0.04 |
| **TOTAL per session** | | ~121,700 in / 35,500 out | **~$0.34** |

Compare to old approach (587 full summaries → Pro): estimated **$1.50-3.00/session**.

---

## 7. Implementation Priorities for MarketMind

### Phase 1: Flash Pre-Filter (Week 1)
1. Define the 5-axis scoring schema (market_impact, corroboration, contradiction, depth_needed, urgency)
2. Build Flash prompt template for batch scoring 587 headlines
3. Implement scoring output parser (structured JSON)
4. Set initial score threshold at 5 (tune via backtesting)
5. Store scores in `ScoredArticle` dataclass alongside existing `NewsArticle`

### Phase 2: Tool-Trigger Mapping (Week 1-2)
1. Implement regex fast-path classifier for 5 categories
2. Build `TRIGGER_MAP` mapping (category, confidence) → API tool list
3. Integrate with existing gateway modules (`macro_data.py`, `market_data.py`, `options_flow.py`, `earnings_dates.py`)
4. Implement tool budget enforcement per investigation thread

### Phase 3: Investigation State Machine (Week 2)
1. Build `HypothesisTracker` class with JSON state
2. Implement Tree-of-Thoughts pattern (generate 3 → prune to 2 → expand → synthesize)
3. Add diminishing returns detection
4. Add adversarial validation step (Flash verifies Pro's conclusions)

### Phase 4: Synthesis & Output (Week 2-3)
1. Build structured briefing format (hypothesis → evidence → confidence → recommendation)
2. Implement citation chain (every claim links to source article + API data)
3. Add confidence calibration (track historical accuracy of confidence scores)

---

## 8. Key References

| Source | Link | Key Contribution |
|--------|------|------------------|
| Aparture Review Gates | https://joshspeagle.com/aparture/using/review-gates.html | Flash YES/MAYBE/NO triage pattern |
| LLM-Assisted News Discovery (Hagar 2025) | https://arxiv.org/html/2509.25491 | F1=0.94 news lead extraction |
| ActuallyRelevant.news | https://community.openai.com/t/actuallyrelevant-news-ai-news-curation/1374385 | 4-stage pipeline, $1/day cost |
| Global Crisis Monitor | https://dev.to/pixari/how-i-built-a-real-time-geopolitical-event-pipeline-with-embeddings-and-llms-221p | 3-pass LLM + embedding clustering |
| On-Premise AI for Newsroom (Hagar 2025) | https://arxiv.org/html/2509.25494v1 | 5-stage pipeline, Qwen 3 14B |
| Google BATS Framework | https://www.cio.com/article/4106863/google-unveils-budget-tracker-and-bats-framework-to-rein-in-ai-agent-costs.html | Budget-aware agent architecture |
| BG-MCTS Token Budget | https://ar5iv.labs.arxiv.org/html/2602.09574 | Token-budget-conditioned tree search |
| Uncertainty-Aware MCTS | https://openreview.net/forum?id=RrLQbXCflj | Uncertainty-based pruning |
| Lateral Tree-of-Thoughts | https://arxiv.org/html/2510.01500v1 | Myopic pruning prevention |
| AG2 Context-Aware Routing | https://docs.ag2.ai/latest/docs/user-guide/advanced-concepts/pattern-cookbook/context_aware_routing/ | Dynamic agent routing |
| Koda Model-Routed Sub-Agents | https://github.com/lijunzh/koda/issues/159 | Flash→Opus→Sonnet→Flash pattern |
| Lyra SmartRouting | https://github.com/Roxabi/lyra/issues/134 | Complexity-based model selection |
| Sentiment-Trading-Alpha | https://github.com/techjeffe/Sentiment-Trading-Alpha | Geopolitical news→trade signal pipeline |
| MSCI Material News Attention | https://www.msci.com/research-and-insights/blog-post/mapping-market-turmoil-with-material-news-attention | LLM-based geopolitical risk classification |
| LSEG MarketPsych | https://www.lseg.com/en/data-analytics/market-data/quantitative-economic-data-solutions/marketpsych-analytics-and-models | Enterprise text tagging (1000+ topics, 4000+ events) |
| Anthropic Agent Skills | https://blog.csdn.net/m0_55049655/article/details/159694566 | Progressive disclosure architecture |
| Progressive Disclosure in Context Engineering | https://pub.towardsai.net/state-of-context-engineering-in-2026-cf92d010eab1 | Three-tier loading pattern |

---

**Updated**: 2026-05-17 15:30 — Research complete; 5 research questions answered with concrete implementation patterns for Flash+Pro collaboration
