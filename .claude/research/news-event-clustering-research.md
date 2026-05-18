# News Event Clustering & Cross-Article Correlation — Research Findings

**Date**: 2026-05-17  
**Context**: MarketMind collects ~587 financial news articles per session from 35 sources. Currently each article is processed independently. We need to cluster related articles into themes/events so the AI can reason about connected signals.

---

## Table of Contents

1. [Financial News Event Clustering Methods](#1-financial-news-event-clustering-methods)
2. [Cross-Article Correlation for Investment Signals](#2-cross-article-correlation-for-investment-signals)
3. [LLM-Based Clustering — Cost & Efficiency](#3-llm-based-clustering--cost--efficiency)
4. [Production Systems & Open-Source Examples](#4-production-systems--open-source-examples)
5. [Token-Efficient Architecture for MarketMind](#5-token-efficient-architecture-for-marketmind)
6. [Recommendation](#6-recommendation)

---

## 1. Financial News Event Clustering Methods

### 1.1 BERTopic + Domain-Specific Embeddings (Current SOTA)

**BERTopic** has emerged as the dominant framework for financial news clustering in 2025-2026, consistently outperforming classical methods (LDA, NMF).

Key evidence:

- **Chen et al. (2023/updated 2025)** — Comparative study on 38,240 financial news articles. BERTopic achieved highest coherence scores, best interpretability, and reasonable computing time vs. LDA and Top2Vec.

- **Chakkarwar & Tamane (2026)** — On 50,000 Indian business news headlines. BERTopic demonstrated superior contextual coherence for discriminating between closely related financial subdomains.

- **Hayrapetyan & Gevorgyan (2025)** — *"From Headlines to Forecasts: Narrative Econometrics in Equity Markets"* (J. Risk Financial Manag.). BERTopic with similarity-distilled BERT embeddings on Microsoft news. Three narrative clusters (Media & Public Perception, Currency & Macro, Tech & Semiconductor Ecosystem) significantly predicted stock returns in ARIMA-X models (p < 0.01).

**Game-changer: FinTextSim** (Jehnen, Villalba-Diez & Ordieres-Meré, 2026, Frontiers in AI):
- Sentence-transformer fine-tuned for financial text
- +71% improvement in intratopic similarity over generic embeddings
- -108% reduction in intertopic similarity
- +2 percentage points in ROC-AUC and F1-score for corporate performance prediction
- Outperforms all-MiniLM-L6-v2, all-mpnet-base-v2, and even FinBERT for topic modeling

**FinMTEB Benchmark** (EMNLP 2025): The standard benchmark for financial embeddings. 64 datasets, 7 tasks including Clustering. Key finding: domain-adapted models (Fin-E5) significantly outperform general-purpose models. GitHub: https://github.com/yixuantt/FinMTEB

### 1.2 Entity-Based Clustering

**FUNNEL Framework** (Nordansjo, Fourong & Qasim, 2025, Digital Finance):
- NER-based ensemble labeling integrating weak keyword heuristics + spaCy transformer NER
- Weighted voting for article-stock association
- Outperforms original FNSPID labels on Magnificent Seven stocks
- Produces entity-level sentiment signals mapped to specific companies

**GPT-Derived Entity Networks** (Miori & Petrov, 2025, Int. J. Data Science and Analytics):
- GPT-3.5 extracts key entities from WSJ articles
- Builds weekly co-occurrence graphs
- Fuzzy community detection clusters entities into interpretable topics
- High fragmentation in entity communities correlates with financial market dislocations

### 1.3 LLM-Refined Clustering (Emerging Frontier)

**LLM-Refined Dynamic Topic Clustering** (OpenReview 2025):
- Pipeline: OpenAI embeddings → UMAP + HDBSCAN clustering → GPT-4 topic refinement/deduplication
- Produces higher quality and more stable topics than LDA and BERTopic alone
- First application of GPT-4-assisted clustering refinement
- Topics have high predictive power for macroeconomic and stock forecasting

**Investment Decisions with UMAP+HDBSCAN** (J. Investment Strategies, Risk.net):
- Fine-tuned LLM → sentence embeddings → UMAP → HDBSCAN → investment signals
- Outperforms S&P 500 on risk-adjusted basis (June 2018 - June 2023)
- Uncorrelated with Fama-French factors (diversification benefit)
- Data: YouTube social media + 100+ mainstream financial news outlets

### 1.4 Temporal Event Extraction

**PosEKE-GPT2** (Nature Scientific Reports, 2025):
- Reformulates event extraction as text-to-structure generation
- Enhanced positional encoding + external knowledge augmentation
- 90.61 F1 on DuEE-Fin, 88.85 on FewFC datasets

**LLM-Enhanced Multi-Causal Event Mining** (Springer, 2025):
- Fine-tuned LLaMA + GNN multi-hop reasoning on event graphs
- Detects multi-cause, multi-effect chains in financial texts
- 5-10% F1 improvement on FinCausal 2022

---

## 2. Cross-Article Correlation for Investment Signals

### 2.1 Graph-Based Approaches

**Lead-Follower Factor** (Tencent Cloud / academic research, 2023):
- Built directed news co-occurrence graph from ~1M news articles covering S&P 500 (2016-2020)
- Defines *lead stocks* (mentioned in headlines) and *follower stocks* (mentioned in body text)
- Key findings:
  - Strong return co-movement between lead and follower stocks, even after controlling for Fama-French factors
  - Graph degree centrality (monthly) is a significant predictor of cross-sectional returns with positive alpha
  - Same-industry co-movement is strongest, but cross-industry effects are also significant

**HIST Model — Three-Network Graph Clustering** (Tencent Cloud, 2023):
- Three graph networks: Industry Chain, Supply Chain, News Co-occurrence
- Leiden community detection for temporal clustering of stocks
- Combined clusters achieved 14.10% annualized excess return with information ratio of 2.061
- Demonstrates that graph-cluster-based features carry valuable incremental information beyond traditional sector classifications

### 2.2 Causal Chain Detection

**Word Influencer Networks (WIN)** (Balashankar et al., ACL 2018):
- Unsupervised learning framework building word-word influencer relationships from news streams
- Measures how appearance of one word influences emergence of another set of words in the future
- Validated 67% of causal evidence through direct edges, 33% through paths of length 2
- Applied to stock price prediction: 2 orders of magnitude lower prediction error vs. comparable causal graph methods

### 2.3 Narrative Tracking

**GPT-Derived Narrative Networks** (Miori & Petrov, 2025):
- GPT-3.5 extracts entities and sentiments from WSJ articles
- Weekly co-occurrence graphs with fuzzy community detection
- Narrative evolution tracked as dynamic graph structure
- Fragmentation in network communities predicts financial market dislocations

**MENTOR Multi-Agent Framework** (Chen et al., 2025):
- Teacher-student iterative reasoning for event and narrative trend prediction
- Progressive subtasks: detecting trending events → forecasting future events from narratives → predicting industry index performance
- Outperforms StkFEP and SEP baselines with portfolio-level backtest improvements

### 2.4 Equity2Vec — Graph Embeddings for News

- Constructs heterogeneous graphs (company-industry-article nodes) from financial news
- Uses GraphSAGE with Sigma Transformer news encodings
- Factorizes news co-occurrence matrix to learn dense vector representations per stock
- Uses both long-term (rolling window co-occurrence) and short-term (dynamic graph) signals
- Outperforms FinBERT for direction prediction tasks

### 2.5 Key Insight for MarketMind

The common pattern across all successful approaches: **build a graph where nodes are entities (ticker, country, sector) and edges are co-occurrence within articles**, then apply community detection. This surfaces causal chains naturally — e.g., ECB + EUR/USD + German PMI all appear in the same community because news articles often mention them together during related events.

---

## 3. LLM-Based Clustering — Cost & Efficiency

### 3.1 Embedding-Based vs. Prompt-Based

**Finding: Embedding-based clustering is dramatically cheaper and more scalable than prompt-based clustering for routine grouping.**

**Evidence:**

- **LATTE Framework** (Kireev et al., 2025): Found that direct use of LLMs on long event sequences is "computationally expensive and impractical in real-world pipelines." Their embedding approach "significantly reduces inference cost and input size" while outperforming SOTA on financial datasets.

- **EMH Stock Clustering** (Wang et al., 2025): Benchmarked three methods:
  - Price-correlation clustering: RMSE 1.963
  - LLM Embeddings (text-embedding-3-large, weekly headlines): RMSE 2.301
  - GICS human-defined sectors: RMSE 2.333

  LLM embeddings outperform GICS but underperform price correlation for short-horizon. All differences statistically significant.

### 3.2 Practical Batch Size Limits for Prompt-Based Clustering

**Single-call clustering is unreliable beyond ~200-500 headlines**, even with 1M-token context windows:

- Output hesitation: Models often cap themselves at ~2,000 tokens of generated text
- Hallucination risk increases with output size demanded
- Structured JSON output helps but doesn't solve the fundamental attention-spread problem

**Workarounds for large batches:**

| Pattern | Description | Best For |
|---------|-------------|----------|
| **Hierarchical tree consolidation** | 50 headlines/batch → merge clusters in consolidation calls → repeat until final themes | 500-2000 headlines |
| **Bounded batching with cursor** | Fixed-size batches (30-50), deterministic merge rules post-hoc | Predictable pipelines |
| **Embeddings + LLM hybrid** | Embeddings for bulk clustering, LLM only for theme naming/refinement | Cost-sensitive, high-volume |
| **DataFrame parallelization** | Tools like Daft manage batching, parallelization, caching | Production pipelines |

### 3.3 Cost Comparison Estimate

For ~600 headlines (MarketMind's scale):

| Approach | API Calls | Estimated Cost | Time |
|----------|-----------|---------------|------|
| Single-call prompt clustering (all 600 at once) | 1 | $0.30-0.80 (Claude 150K input, ~5K output) | 10-30s |
| Batched prompt clustering (12 batches x 50) | 12 | $0.50-1.20 | 2-4 min |
| **Embedding-based clustering** (Flash embeddings) | 1 (embed 600 headlines) | **$0.01-0.03** | **<5s** |
| Embeddings + LLM theme labeling | 1 embed + 1 LLM | $0.05-0.15 | <10s |
| Pre-clustering by ticker (regex) + embeddings per group | 1 embed | $0.01-0.03 | <5s |

**Bottom line: Embedding-based clustering costs 10-30x less than prompt-based for routine operation.**

### 3.4 When to Use LLM Directly

Prompt-based clustering is appropriate for:
- Final theme naming and narrative synthesis (1 call after embeddings do the heavy lifting)
- Resolving ambiguous edge cases (few articles, not bulk)
- Generating cross-theme narratives ("how does ECB rate hold + German PMI + EUR/USD connect?")

LLMs should NOT be used for:
- Routine article-to-cluster assignment (embeddings handle this)
- Daily bulk clustering of 600+ articles
- Any task where cosine similarity over embeddings produces equivalent results

---

## 4. Production Systems & Open-Source Examples

### 4.1 RavenPack

**Scale**: 300M+ documents/month from 40,000+ sources. Processing since 2003.

**Architecture** (5 stages):
1. **Ingestion & Normalization**: Multi-protocol (HTTP/FTP/TCP), multi-format (XML/HTML/JSON) → single internal format
2. **Entity Detection**: 12M+ entities, fine-tuned DistilBERT with 16 entity types and BIO tagging. Combines rule-based Lisp grammar + deep learning.
3. **Event Detection**: 7,400+ event types. Pattern-based matching ("company X does Y to company Z").
4. **Sentiment Scoring**: Base sentiment (expert panels) + contextual modifiers at sentence/event/document levels
5. **Analytics Generation**: Structured records with sub-second latency

**How they cluster/deduplicate:**
- **Novelty scoring**: Each document gets information novelty score. If 100 outlets report same earnings, only first gets high novelty score.
- **Event taxonomy clustering**: All detected events map to 7,400-event taxonomy. Stories naturally cluster under same event type + entity combination.
- **Source network analysis**: Maps information flow between sources; identifies originators vs. replicators.
- **Feature hierarchy trees** (2023 research): Dynamic approach breaking datasets into smaller features organized hierarchically.

**Multi-stage search ranking** (Bigdata.com):
1. Candidate generation: Fast approximate hybrid search (semantic + lexical)
2. First-phase ranking: Vector similarity, source intelligence, freshness, sentiment
3. Second-phase reranking: Cross-encoders for high precision

### 4.2 AlphaSense (includes acquired Sentieo)

**Scale**: Hundreds of millions of documents (filings, transcripts, research, news, expert calls).

**Core NLP technologies:**
- **Smart Synonyms**: Tens of thousands of financial-domain synonym mappings. Context-aware (e.g., "Chase" = J.P. Morgan vs. verb vs. person).
- **Company Name Recognition (CNR)**: Home-grown solution for recognizing, disambiguating, classifying company mentions.
- **Relevancy Scoring**: Multi-factor model combining semantics, source quality, document structure, recency, entity aboutness.
- **Boilerplate Detection**: Identifies and filters legally required non-substantive text, reducing noise by up to 5x.

**Topic clustering approach:**
1. **Document-level theme extraction**: On transcript/filing load, NLP tailored to financial language extracts key themes
2. **Topic clustering**: Related concepts captured under umbrella themes using clustering algorithms. e.g., "Production" umbrella → manufacturing expenses, production capacity, supply chain
3. **Scoring & ranking**: Each theme gets composite relevance score. Sortable by mentions, sentiment, QoQ change, overall relevance
4. **Real-time streaming**: Theme extraction runs as transcripts appear (not pre-computed offline)

**ASLLM** (proprietary LLM, 2023):
- Task-based approach for specific market intelligence workflows
- Fine-tuned on decade of aggregated financial content
- RAG-grounded outputs with citation to specific sentences
- Multi-model guardrails (one model checks another's work)

### 4.3 Bloomberg Terminal — Key Themes (NSTM)

**Scale**: 1.5M headlines/day from ~170,000 sources (~17 stories/second).

**Two-stage clustering pipeline:**
1. **Online incremental clustering** (at ingestion):
   - Stories embedded via Neural Variational Document Model (NVDM) — VAE capturing latent topic structure
   - Cosine similarity between embeddings
   - Incoming stories merged with closest existing cluster or form new one
2. **Hierarchical Agglomerative Clustering** (at query time):
   - HAC with complete linkage to reduce fragmentation
   - Dendrogram cut at similarity threshold of 0.86 (optimized via 1,000+ manually annotated article pairs)

**Summary generation** (for each cluster):
- OpenIE (unsupervised rule-based) extracts predicate-argument tuples from dependency parse trees
- BERT-based Sentence Compression (trained on 10,000 manually annotated examples) classifies sub-tokens as keep/delete
- Sequence-pair ranker scores candidate summaries against cluster articles

**Result**: 44,000 stories on a major news day → 5 easy-to-understand key themes, each expandable.

**BloombergGPT**: 50B-param LLM trained on 700B tokens (363B proprietary financial). Outperforms general models on financial NLP tasks.

### 4.4 Reuters — News Tracer & Seeded Clustering

**News Tracer** (social media breaking news):
- Filters ~500M daily tweets through boosted filters (spam/ad/profanity removal)
- Clusters similar tweets by word/topic similarity
- 40-factor veracity scoring (verified accounts, follower count, links/images, ALL CAPS penalty, confirmation/debunking patterns)
- Newsworthiness assessment for alert triggering
- Proven results: 8-min head start on Brussels bombings, 15-min on Chelsea bombing

**Seeded Clustering System** (U.S. Patent 11,632,254):
- Three-step: candidate dataset → initial clusters (nearness/duplicate) → merge with editorially-supplied seed documents
- Dual evidence: digital signatures (unstructured text) + named entity tags (Calais engine)
- Agglomerative clustering with hierarchical sub-topic generation

### 4.5 Open-Source Projects

| Project | Description | Key Methods | Production Ready? |
|---------|-------------|-------------|:---:|
| **[davidjosipovic/news-trend-analysis](https://github.com/davidjosipovic/news-trend-analysis)** | End-to-end NLP pipeline: BERTopic, FinBERT, DistilBART, Streamlit | HDBSCAN, UMAP, KeyBERT | Yes (GH Actions + Railway) |
| **[Refinath/news-event-impact-detector](https://github.com/Refinath/news-event-impact-detector)** | Financial event classification + stock return impact | FinBERT, regression models | Partial (research) |
| **[dukeblue1994-glitch/chronicle](https://github.com/dukeblue1994-glitch/chronicle)** | Intelligent event detection via semantic embeddings, MinHash LSH, HDBSCAN | HDBSCAN, embeddings, LSH dedup | Yes |
| **[ruoheng-du/topic-modeling-sentiment-analysis](https://github.com/ruoheng-du/topic-modeling-sentiment-analysis)** | BERTopic + FinBERT for Chinese financial discourse | BERTopic, FinBERT | Research |
| **[ZhafranR/BERTopic-Indonesia-Finance-News](https://huggingface.co/ZhafranR/BERTopic-Indonesia-Finance-News)** | Pre-trained BERTopic on 74,933 Indonesian finance articles | BERTopic (UMAP+HDBSCAN) | Ready-to-use model |
| **[newbiethetest/gupiao_shijian](https://github.com/newbiethetest/gupiao_shijian)** | Chinese stock/financial event extraction + clustering | SinglePass, KMeans, LDA, TF-IDF | Partial |
| **[shainarace/Reuters](https://shainarace.github.io/Reuters/clustering-hdbscan.html)** | Clustering 21,578 Reuters newswires | SVD, GloVe, UMAP, HDBSCAN | Methodology documentation |
| **[yixuantt/FinMTEB](https://github.com/yixuantt/FinMTEB)** | Embedding benchmark: 64 datasets, 7 tasks | Clustering evaluation | Benchmark |

**Top recommendation for MarketMind**: `davidjosipovic/news-trend-analysis` — most complete end-to-end reference pipeline with BERTopic + FinBERT + Streamlit + automated scheduling.

### 4.6 Common Production Patterns

All four production systems (RavenPack, AlphaSense, Bloomberg, Reuters) follow a **layered architecture**:

1. Fast ingestion & normalization
2. Entity/event extraction → structured metadata
3. Semantic encoding → embeddings for similarity
4. Deduplication/novelty filtering → collapse repetitive coverage
5. Theme/topic clustering → group related concepts
6. Scoring & ranking → multi-factor relevance models
7. Delivery/serving → APIs, real-time feeds, summaries

**Key insight**: Financial news clustering in production is NOT one algorithm. It is a pipeline of interconnected components that collectively turn millions of daily articles into structured, searchable, clusterable analytics.

---

## 5. Token-Efficient Architecture for MarketMind

### 5.1 Context: 150K Token Budget, ~600 Articles/Session

At ~600 articles per session, the token budget is tight if we send full article text to LLMs. A typical financial news article is 300-800 tokens. Even at 300 tokens average, 600 articles = 180K tokens — already exceeding budget before any system prompt or output.

**Strategy: Two-stage pre-clustering reduces what hits LLM context by 90-95%.**

### 5.2 Proposed Architecture: Three-Tier Clustering

```
                    ┌─────────────────────────────────┐
                    │   ~600 raw articles              │
                    └──────────────┬──────────────────┘
                                   │
                    ┌──────────────▼──────────────────┐
                    │  TIER 1: Regex Pre-Clustering    │
                    │  - Extract ticker mentions       │
                    │  - Extract country/region        │
                    │  - Extract sector keywords       │
                    │  - Group by entity overlap       │
                    │  COST: 0 tokens (pure regex)     │
                    └──────────────┬──────────────────┘
                                   │
              ┌───────────────────┼───────────────────┐
              ▼                   ▼                   ▼
    ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
    │ Group A     │     │ Group B     │     │ Group N     │
    │ (Tech/AAPL) │     │ (Macro/ECB) │     │ (Energy)    │
    │ ~50 arts    │     │ ~40 arts    │     │ ~80 arts    │
    └──────┬──────┘     └──────┬──────┘     └──────┬──────┘
           │                   │                   │
           └───────────────────┼───────────────────┘
                               │
                    ┌──────────▼──────────────────┐
                    │  TIER 2: Semantic Clustering  │
                    │  - Flash embeddings per group │
                    │  - Cosine similarity matrix   │
                    │  - HDBSCAN or threshold-based  │
                    │    sub-clustering              │
                    │  COST: ~0.1 tokens/headline    │
                    │    = ~60 tokens total          │
                    └──────────┬──────────────────┘
                               │
                    ┌──────────▼──────────────────┐
                    │  TIER 3: LLM Theme Synthesis  │
                    │  - Per-cluster: headlines →   │
                    │    theme name + narrative      │
                    │  - Cross-cluster: detect       │
                    │    causal chains                │
                    │  COST: ~20-30 clusters ×       │
                    │    ~500 tokens = 10-15K tokens  │
                    └──────────────────────────────┘
```

### 5.3 Tier 1: Regex Pre-Clustering (Zero Tokens)

Extract structured metadata from each headline/article with regex:

```python
# Examples of zero-token extraction
TICKER_PATTERN = r'\$[A-Z]{1,5}\b|\([A-Z]{1,5}\)|[A-Z]{2,5}(?=\s+(?:shares|stock|plung|surge|jump|fall|rise|dip|rally))'
COUNTRY_PATTERN = r'\b(US|China|Japan|Germany|UK|France|India|Brazil|Canada|Australia|...)\b'
SECTOR_PATTERN = r'\b(tech|semiconductor|energy|oil|banking|real estate|healthcare|pharma|...)\b'
CURRENCY_PATTERN = r'\b(EUR/USD|USD/JPY|GBP/USD|AUD/USD|USD/CAD|...)\b'
INDEX_PATTERN = r'\b(S&P 500|Nasdaq|Dow Jones|FTSE 100|DAX|Nikkei|Hang Seng|Shanghai Composite|...)\b'
```

**Pre-grouping strategy:**
1. Extract all entities from each article's headline (tickers, countries, sectors, currencies, indices)
2. Build entity overlap graph: articles share an edge if they have >= 1 entity in common
3. Apply connected components or Louvain community detection to form initial groups
4. Articles with no entities (or weak overlap) → "general/unclassified" bucket

**Expected outcome**: ~600 articles → 15-25 entity-based pre-groups of 20-80 articles each.

### 5.4 Tier 2: Flash Embedding-Based Semantic Clustering

Within each pre-group, compute embeddings and cluster:

**Embedding model**: Use Flash (Anthropic) or text-embedding-3-small (OpenAI) — both <$0.02 per 1M tokens.

For 600 headlines averaging 20 words each = ~12,000 words = ~16,000 tokens → ~$0.0003 for embedding.

**Clustering algorithm**: HDBSCAN (the most commonly used in financial NLP literature):
- Automatically determines number of clusters (no k to specify)
- Handles noise points (articles that don't fit any cluster)
- Parameter: `min_cluster_size` — tune per pre-group size

Alternative: Simple cosine similarity threshold. If cosine_sim >= 0.75, merge into same event. Simpler, faster, and the NSTM system at Bloomberg uses essentially this approach with threshold 0.86.

**Expected outcome**: 15-25 pre-groups → 30-50 semantic event clusters.

### 5.5 Tier 3: LLM Theme Synthesis (Minimal Tokens)

For each cluster, send a compact prompt to Flash:

```
System: You analyze financial news event clusters. For each cluster, produce:
1. Theme name (short phrase)
2. Core narrative (1 sentence)
3. Signal direction: BULLISH / BEARISH / NEUTRAL
4. Entities involved (comma-separated tickers/countries)

Input format per cluster:
CLUSTER ID: <id>
HEADLINES:
- [article_id_1] Headline text (source, timestamp)
- [article_id_2] Headline text (source, timestamp)
... (max 15 representative headlines)

Output: JSON with fields: theme_name, narrative, signal_direction, entities
```

With 30-50 clusters, this costs 30-50 small LLM calls. Each call: ~200 tokens input (15 headlines) + ~100 tokens output = ~300 tokens. Total: ~9,000-15,000 tokens. That fits within a 150K budget with room to spare.

**For cross-cluster causal chains** (the "ECB + German PMI + EUR/USD" problem), add a final consolidation prompt:

```
You see these event clusters detected in today's financial news:
[list of all cluster themes with brief descriptions and entities]

Identify 3-5 cross-theme causal chains. Example:
"ECB rate hold → EUR weakens → German exporters benefit → DAX futures rise"

Output: List of causal chains with supporting evidence from clusters.
```

This is 1 additional call of ~2,000-3,000 tokens input + ~500 tokens output.

### 5.6 Token Budget Summary

| Component | Tokens | % of 150K Budget |
|-----------|--------|:---:|
| Tier 1: Regex pre-clustering | 0 | 0% |
| Tier 2: Embeddings (600 headlines) | ~16,000 input (but embeddings are batched, not in context window) | 0%* |
| Tier 3: Per-cluster theme synthesis (40 clusters x 300 tokens) | ~12,000 | 8% |
| Tier 3: Cross-cluster causal chain detection (1 call) | ~3,000 | 2% |
| **Total LLM context tokens** | **~15,000** | **10%** |

*Embedding API calls are separate from chat context window.

**Remaining budget for other analysis**: ~135,000 tokens (90% of budget).

### 5.7 Implementation Complexity

| Component | Effort | Dependencies |
|-----------|--------|-------------|
| Regex entity extraction | 1-2 days | `re` module only |
| Entity overlap graph + community detection | 1 day | `networkx`, `python-louvain` |
| Embedding generation (API) | 1 day | Anthropic/OpenAI API key |
| Cosine similarity matrix + HDBSCAN | 1 day | `sklearn`, `hdbscan` |
| LLM theme synthesis prompts | 1 day | Anthropic/OpenAI API key |
| Integration + testing with real data | 2-3 days | All above |
| **Total** | **~7-9 days** | |

---

## 6. Recommendation

### 6.1 Recommended Architecture

**Three-tier pipeline: Regex pre-clustering → Embedding-based semantic clustering → LLM theme synthesis.**

This matches the pattern used by every major production system (RavenPack, AlphaSense, Bloomberg, Reuters) while staying within MarketMind's 150K token budget.

### 6.2 Why This Approach

1. **Proven in production**: Every financial data platform uses entity-first, then semantic clustering, then LLM refinement. None cluster raw full-text at scale.

2. **Token-efficient**: Only ~10% of the 150K budget is consumed by event clustering, leaving 90% for the core analysis pipeline.

3. **Cost-effective**: Embedding 600 headlines costs <$0.01. LLM theme synthesis for 40 clusters costs ~$0.05-0.15. Total clustering cost per session: <$0.20.

4. **Interpretable**: Entity pre-groups provide human-understandable segmentation (ticker/country/sector). Semantic clusters surface actual event structure. LLM synthesis produces readable narratives.

5. **Extensible**: Each tier is independently upgradeable. If Flash embeddings improve, swap in. If a better clustering algorithm emerges (e.g., BERTopic), swap that in. LLM prompts evolve separately.

### 6.3 Alternative: Simpler Two-Tier (If Time-Constrained)

If 7-9 days is too long, a simpler two-tier approach:

1. **Tier 1**: Regex pre-clustering by ticker overlap (same as above)
2. **Tier 2**: Prompt-based clustering within each pre-group — send 20-50 headlines to Flash with "Group these into events" instruction. Flash is fast and cheap enough that this could work for 15-25 groups.

This cuts implementation to ~3-4 days but uses more tokens (~40,000-60,000) and costs more ($0.30-0.50/session). Still viable within the 150K budget.

### 6.4 Key Papers to Read for Deeper Understanding

| Paper | Key Finding | Link |
|-------|-------------|------|
| NSTM: Real-Time News Overview at Bloomberg | NVDM + HAC pipeline, threshold 0.86 | [arXiv:2006.01117](https://arxiv.org/abs/2006.01117) |
| FinTextSim | +71% intratopic similarity for financial embeddings | [Frontiers in AI, 2026](https://www.frontiersin.org/journals/artificial-intelligence/articles/10.3389/frai.2026.1752103/full) |
| LLM-Refined Dynamic Topic Clustering | GPT-4 refinement produces better topics than BERTopic | [OpenReview](https://openreview.net/forum?id=k6x4mFwXfz) |
| FinMTEB Benchmark | Domain models beat general models for financial clustering | [EMNLP 2025](https://arxiv.org/abs/2502.10990) |
| Narratives from GPT-Derived Networks | Fragmented entity communities predict market dislocations | [Springer](https://link.springer.com/article/10.1007/s41060-024-00516-x) |
| UMAP+HDBSCAN for Investment | Beats S&P 500 on risk-adjusted basis | [J. Investment Strategies](https://www.risk.net/node/7961561) |
| Word Influencer Networks | Causal chains from news word co-occurrence | [ACL 2018](https://aclanthology.org/W18-3109/) |

---

**Sources:**
- [From Headlines to Forecasts: Narrative Econometrics in Equity Markets](https://econpapers.repec.org/article/gamjjrfmx/v_3a18_3ay_3a2025_3ai_3a9_3ap_3a524-_3ad_3a1752477.htm)
- [Automatic detection of relevant information through LDA on financial news](https://econpapers.repec.org/paper/arxpapers/2404.01338.htm)
- [BERTopic: Neural Topic Modeling Framework](https://www.emergentmind.com/topics/bertopic)
- [A LLM-Refined Dynamic Topic Clustering Framework for Business Forecasts](https://openreview.net/forum?id=k6x4mFwXfz)
- [Evaluating Traditional And Transformer-Based Topic Models For Indian Financial News Analytics](https://www.xlescience.org/index.php/IJASIS/article/view/1039)
- [FinTextSim: domain-specific sentence-transformer for financial disclosures](https://www.frontiersin.org/journals/artificial-intelligence/articles/10.3389/frai.2026.1752103/full)
- [Financial sentiment analysis with FUNNEL](https://link.springer.com/article/10.1007/s42521-025-00162-3)
- [Narratives from GPT-derived networks of news and a link to financial markets dislocations](https://link.springer.com/article/10.1007/s41060-024-00516-x)
- [LLM-enhanced multi-causal event causality mining in financial texts](https://link.springer.com/article/10.1007/s44443-025-00330-w)
- [Harnessing Generative LLMs for Enhanced Financial Event Entity Extraction](https://ui.adsabs.harvard.edu/abs/2025arXiv250414633C/abstract)
- [MENTOR: multi-agent framework for event and narrative trend prediction](https://link.springer.com/article/10.1631/FITEE.2500608)
- [Investment decisions driven by fine-tuned LLMs and UMAP-supported clustering and HDBSCAN](https://www.risk.net/node/7961561)
- [FinMTEB: Finance Massive Text Embedding Benchmark](https://github.com/yixuantt/FinMTEB)
- [Is All the Information in the Price? LLM Embeddings versus the EMH in Stock Clustering](https://arxiv.org/abs/2509.01590v1)
- [NSTM: Real-Time Query-Driven News Overview Composition at Bloomberg](https://ar5iv.labs.arxiv.org/html/2006.01117)
- [Use AI to sort through market-moving news (Bloomberg)](https://www.bloomberg.com/professional/insights/trading/use-ai-to-sort-through-market-moving-news/)
- [System and engine for seeded clustering of news events (Reuters Patent)](https://patents.justia.com/patent/11663254)
- [RavenPack Technology: News Aggregation & Classification](https://www.ravenpack.com/technology/)
- [AlphaSense Themes Announcement](https://www.alpha-sense.com/blog/product/themes-announcement/)
- [GitHub: news-trend-analysis (BERTopic + FinBERT pipeline)](https://github.com/davidjosipovic/news-trend-analysis)
- [GitHub: news-event-impact-detector (FinBERT + regression)](https://github.com/Refinath/news-event-impact-detector)
- [GitHub: chronicle (semantic embeddings + HDBSCAN event detection)](https://github.com/dukeblue1994-glitch/chronicle)
- [GitHub: gupiao_shijian (Chinese stock news event extraction)](https://github.com/newbiethetest/gupiao_shijian)
- [Clustering 21,578 Reuters Newswires with HDBSCAN](https://shainarace.github.io/Reuters/clustering-hdbscan.html)
- [Words + Returns: Teaching Embeddings to Invest in Themes (CIKM 2025)](https://cognaptus.com/blog/2025-08-26-words-returns-teaching-embeddings-to-invest-in-themes/)
- [LATTE: Learning Aligned Transactions and Textual Embeddings for Bank Clients](https://arxivlens.com/PaperView/Details/latte-learning-aligned-transactions-and-textual-embeddings-for-bank-clients-9046-05761a62)
