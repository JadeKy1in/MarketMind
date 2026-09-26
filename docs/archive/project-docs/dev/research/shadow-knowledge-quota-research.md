# Shadow Ecosystem Research: Agent Knowledge Persistence + Token Budget Systems

**Date**: 2026-05-18
**Context**: MarketMind Phase I shadow ecosystem redesign — each shadow needs agent-level memory that persists across daily runs, and tiered Flash quotas (ELITE=7, EXCELLENT=6, etc.) that govern data-retrieval spend decisions.

---

## Topic 1: AI Agent Experience Persistence

### The Core Problem

Most AI agents are stateless — each session starts cold, with no awareness of prior analyses, discovered patterns, or past mistakes. In MarketMind's shadow ecosystem, this means every daily run re-learns the same lessons about sector behavior, data quality traps, and correlation patterns. The field is converging on the insight that **structured, multi-layer memory** is necessary, not optional — raw context window extension fails at scale.

### Memory Architectures in Production

**Letta (formerly MemGPT) — OS-Inspired Memory Hierarchy**

The dominant research architecture treats LLM memory like an operating system: core memory (actively in context) vs. archival memory (externally stored, paged in on demand). Agents self-edit their memory blocks — persona, user info, episodic traces — and decide what to keep hot vs. cold. On the LoCoMo retrieval benchmark, Letta's filesystem-backed approach scored 74.0% using GPT-4o-mini, beating Mem0's 68.5%. The key insight is *transparent memory management* — developers can inspect exactly what the agent is retaining and why.

**Relevance to MarketMind**: Each shadow could maintain a "persona block" (its specialty, past accuracy, known biases) and an "episodic block" (key findings from prior daily runs). The shadow reads its persona at session start, runs analysis, then writes back updated self-knowledge.

**LangMem — Three Memory Types (LangChain, May 2025)**

LangMem structures agent memory into three distinct types:
- **Semantic memory**: Facts the agent knows ("EV stocks correlate with lithium prices in Q3")
- **Procedural memory**: Rules and behaviors ("Always cross-check Polygon data against SEC filings for biotech earnings dates")
- **Episodic memory**: Past interactions as few-shot examples ("Last time NVDA beat estimates by 15%, my bullish analysis was accurate; when it beat by 2%, I was wrong")

This three-layer model maps naturally to MarketMind's needs: semantic = sector knowledge, procedural = methodology refinement, episodic = track record of each shadow's calls.

**Hindsight (Vectorize.io) — Four Memory Networks**

Hindsight achieved 91.4% accuracy on LongMemEval by maintaining four separate memory networks: world facts, agent experiences, entity summaries, and evolving beliefs. Multi-session question accuracy improved from 21.1% to 79.7%. The separation prevents cross-contamination — a shadow's evolving belief about Tesla doesn't corrupt its factual knowledge about EV subsidies.

### The "Memory Curse" — When More Memory Hurts

A critical 2026 finding from CMU's FOCAL Lab: across 7 LLMs and 500-round social dilemma games, expanding accessible history **degraded cooperation in 18 of 28 settings**. The cause is not paranoia but *eroding forward-looking intent* — agents become history-following and risk-minimizing. Critically, Chain-of-Thought reasoning amplified the curse; explicit deliberation over long histories hardened negative patterns.

**Lesson for MarketMind**: Raw accumulation of past analysis is dangerous. Shadows that re-read their full 6-month analysis history may become overcautious or pattern-locked. Memory needs **curation and summarization**, not just accumulation. The cure is *memory sanitization* — replacing raw history with structured, forward-looking summaries.

### Capability Erosion in Self-Evolving Agents

Yu et al. (UIUC, 2026) demonstrated *capability erosion* as a fundamental failure mode: agents adapting to new task distributions progressively degrade previously acquired capabilities. Under GPT-5.1 optimization, simple-task performance dropped from 41.8% to baseline. Their **Capability-Preserving Evolution (CPE)** principle constrains destructive drift during self-modification.

**Lesson for MarketMind**: If shadows modify their own methodology prompts over time (e.g., "I've learned to trust X data source more"), they risk losing skills that were useful in different market regimes. A bull-market-optimized shadow may fail when volatility returns. Preservation requires explicit regularization — e.g., keeping a frozen copy of the original prompt and diffing against it each cycle.

### Consolidation Defects

Zhang et al. (2026) showed that LLM-driven memory consolidation introduces errors that compound over time. Memories follow an **inverted-U utility curve**: useful initially, then degrading below the no-memory baseline. Even consolidating from ground-truth solutions, GPT-5.4 failed on 54% of ARC-AGI problems it had previously solved. The finding: **episodic-only memory** (raw trajectories without consolidation) outperformed consolidation-based approaches by 2x accuracy.

**Lesson for MarketMind**: Instead of having a shadow summarize its week into "lessons learned," store the raw analysis trajectory and let the next run's shadow retrieve relevant episodes via similarity search. Let the LLM do the synthesis at retrieval time, not at storage time.

### Lessons-Learned Propagation Patterns

The Codified Context paper (2026) documented a 26,200-line context infrastructure across 283 coding sessions and found three effective propagation patterns:

1. **Symptom-Cause-Fix Tables**: Structured artifacts distilled from debugging sessions, embedded into domain-specialist agent specifications
2. **Agent Creation from Failure**: New specialized agents spawned when a failure class repeats; the agent spec encodes accumulated knowledge
3. **Append-Only Event Logs**: Immutable records of decisions and pitfalls, queryable by tag/type/severity

**Relevance to MarketMind**: Shadows should maintain append-only decision logs. When multiple shadows independently flag the same data quality issue with Polygon, that pattern becomes elevated to a system-wide warning. Individual shadow memory feeds collective intelligence.

### Open-Source Memory Systems for Daily-Run Agents

| System | Best Fit | Key Feature |
|--------|----------|-------------|
| YourMemory | Long-horizon recall | Ebbinghaus forgetting curve — memories decay naturally, high-utility ones persist |
| Mneme | Multi-session task tracking | No vector DB needed; human-approval gate for permanent facts |
| Dory | Append-only knowledge | Query by tag/severity; immutable event log |
| Suemo | Graph-based memory | Contradiction detection; bi-temporal nodes |

### Recommendations for MarketMind Shadows

1. **Multi-layer memory per shadow**: Ephemeral (current run) → Session (today's analysis) → Long-term (track record, methodology tweaks) → Entity (sector facts). Retrieve via hybrid vector + keyword + graph.
2. **Append-only lesson log**: Each shadow writes one structured entry per daily run: `{date, call_made, confidence, outcome_pending, data_quality_issues[], methodology_notes}`.
3. **No raw history re-reading**: Summarize each week into a compact "self-model" block. Keep raw episodes for retrieval but don't inject the full history into context.
4. **Capability preservation check**: After 10 runs, diff the shadow's current prompt against its original. Flag capability drift for human review.
5. **Cross-shadow propagation**: A shared "sector watch" log where shadows flag anomalies — if 3+ shadows independently observe the same pattern, elevate to a system alert.

---

## Topic 2: Token Budget and Quota Systems for Competing Agents

### The State of the Art

Token budget management for multi-agent systems is a rapidly maturing field in 2025-2026, driven by the realization that simply granting agents larger budgets doesn't improve performance — agents need explicit budget *awareness*.

### Budget-Aware Agent Architectures

**Budget-Aware Tool-Use (Google, Nov 2025)**

Google's framework demonstrated that agents with explicit budget tracking achieved comparable accuracy to unbudgeted agents while using **40.4% fewer search calls, 19.9% fewer browse calls, and ~31% lower cost**. The mechanism is simple: a Budget Tracker injects continuous signals (remaining tokens, remaining tool calls) into the prompt at each step. A companion Planning Module dynamically switches between "dig deeper" and "pivot" strategies based on remaining budget.

**Relevance to MarketMind**: Each shadow's quota isn't just a hard cap — it's a *signal injected into the prompt* that shapes behavior. An ELITE shadow (quota=7) might decide to retrieve 3 additional data sources; a NORMAL shadow (quota=5) might retrieve only 1 and rely more on cached data. The shadow should be *aware* of its remaining quota at each decision point.

**TALE: Token-Budget-Aware Reasoning (ACL 2025)**

TALE introduced "Token Elasticity" — the counterintuitive finding that overly strict budgets can *increase* token usage as models struggle to compress reasoning. TALE lets models self-estimate a reasonable budget per question, saving ~68% of tokens while keeping accuracy within ~2-5% of full Chain-of-Thought.

**Lesson for MarketMind**: Flash quotas shouldn't be absolute caps that force shadows to truncate mid-reasoning. Set quotas as *soft targets* with a small overflow buffer (e.g., ELITE=7 target, but allow 8 if the shadow is mid-analysis). Hard cutoffs mid-thought produce garbage output.

### Auction and Bidding Mechanisms

**DALA: Dynamic Auction-based Language Agent (Nov 2025)**

The most directly applicable research for MarketMind. DALA reframes inter-agent communication as an economic resource-allocation problem:

- Agents submit candidate messages with bids proportional to informational utility
- A centralized auctioneer selects winning speakers each round
- Both episode-level and round-level token budgets are enforced
- Losing messages are never completed — their tokens aren't charged
- Emergent behaviors: strategic silence, tiered communication (full/summary/keywords/silence), dynamic adaptation to budget tightness
- Achieved SOTA on MMLU (84.32%), GSM8K (96.18%), HumanEval (91.21%) while using 14x fewer tokens than prior SOTA

**Relevance to MarketMind**: Shadows could *bid* for additional quota beyond their tier. An ELITE shadow with a high-conviction signal could bid Flash tokens from its accumulated "savings" to run an extra deep-dive. NORMAL shadows with nothing interesting to analyze might *sell* their unused quota (via credit transfer) to higher-tier shadows. This creates a market — quota flows to the highest-value analysis.

### Cloud AI Quota Systems

Azure API Management's `llm-token-limit` policy is the most relevant production system. It supports:

- **Rate limits**: tokens-per-minute (burst protection)
- **Quotas**: token budgets over Hourly/Daily/Weekly/Monthly periods
- **Per-subscription keys**: tiered service levels (High QoS: 1000 tokens/min; Low QoS: 100 tokens/min)
- **Pre-screening**: estimates prompt tokens before forwarding to the LLM backend

STACKIT's AI Model Serving uses dual-dimension limits (RPM + TPM) with **burst capacity** for short traffic spikes—generation tokens weighted 5x more than prompt tokens. EPAM AI DIAL Core proposes cost-based rate limiting alongside token limits ($100/day, $1000/month).

**Lesson for MarketMind**: MarketMind should track both per-day quotas and per-run burst limits. Separate prompt tokens (cheaper) from generation tokens (more expensive) in the quota calculation. Cost-weight the quota — a deep analysis that costs $0.30 is different from a quick scan at $0.02.

### Quota Rollover: Pros and Cons

No published research explicitly addresses quota rollover for agent systems, but the patterns from cloud rate limiting and economic mechanism design yield a clear analysis:

**Arguments FOR rollover:**
- Smooths bursty workloads — Tuesday's quiet market lets Wednesday accumulate extra capacity for Fed-day analysis
- Rewards efficiency — shadows that conserve quota on low-signal days can deploy it on high-signal days
- Reduces wasteful "use it or lose it" spending — agents won't burn tokens on marginal analyses just to avoid waste
- Matches real-world analyst behavior — human analysts budget their time across the week, not per day

**Arguments AGAINST rollover:**
- Accumulation risk — if all shadows hoard quota for months and then simultaneously deploy, you get a cost spike
- Fairness degradation — ELITE shadows that are consistently efficient accumulate massive banks, widening the gap vs. NORMAL
- Reduced daily urgency — if every day is "save for later," the system loses its daily analysis cadence
- Implementation complexity — tracking rollover, caps, decay, and expiration adds state management burden

**Recommended hybrid approach for MarketMind:**

| Mechanism | Setting |
|-----------|---------|
| Daily base quota | Tier-based (ELITE=7, EXCELLENT=6, NORMAL=5, etc.) |
| Max rollover | 2x daily quota (cap prevents hoarding) |
| Rollover decay | 20% per day on banked quota above 1x daily (prevents infinite accumulation) |
| Quota floor | Each shadow always gets at least its base tier daily regardless of bank |
| Emergency override | If a major market event triggers, all shadows get +2 base quota for the day; rollover suspended |

The decay mechanism is key: it means saving is useful (you can deploy up to 2x on a big day) but not optimal long-term (20% daily decay on excess means hoarding is expensive). This mirrors biological forgetting curves (YourMemory's Ebbinghaus decay), where unused resources naturally diminish.

### Scaling Science: When More Agents Hurt

Google's 2025 "Science of Scaling Agent Systems" paper (180 configurations, 5 architectures, 4 benchmarks) found:

- **Capability saturation**: Once single-agent baseline exceeds ~45% accuracy, adding agents yields diminishing or negative returns
- **Error amplification**: Independent architectures amplify errors 17.2x; centralized coordination compresses to 4.4x
- **Tool-coordination trade-off**: When tools exceed 8, multi-agent overhead grows exponentially

**Lesson for MarketMind**: Beyond a certain number of shadows per sector (~5-7), coordination overhead dominates and the quota system becomes the bottleneck. The current tier structure (ELITE/EXCELLENT/NORMAL) already provides a natural throttling mechanism — only top-tier shadows get the extra quota needed for deep analysis.

### AgentBalance: Optimizing Under Budget

AgentBalance (HKUST, Dec 2025) formalizes the problem as tri-objective optimization: maximize performance under explicit token-cost and latency budgets. Key finding: **backbone (LLM model) choice dominates the cost-performance frontier** more than agent topology. A weaker model with perfect coordination often outperforms a strong model with poor coordination at the same token budget.

**Lesson for MarketMind**: The Flash tier assignment should consider not just quota but also model selection. An ELITE shadow with a cheaper model might underperform an EXCELLENT shadow with a better model. The tier should govern both quota AND model access.

### Recommendations for MarketMind's Quota System

1. **Budget-aware prompting**: Inject `[Quota: 5/7 remaining | Today's spend: $0.12]` into each shadow's system prompt at decision points. Shadows should see their remaining budget before choosing whether to fetch additional data.
2. **Soft targets with overflow buffer**: ELITE=7 target, allow 8 with a "budget exceeded" warning injected into the prompt. Hard cutoffs at +30% of base.
3. **Rollover with decay**: Up to 2x daily cap, 20% daily decay on banked amount above 1x. This prevents hoarding while rewarding efficiency.
4. **Market mechanism (phase II)**: Shadows bid unused quota to others. An ELITE shadow with a high-conviction signal can request additional quota from idle NORMAL shadows. The "auctioneer" (orchestration layer) allocates based on expected value.
5. **Cost-weighted accounting**: Track actual dollar cost, not just token count. Prompt tokens, generation tokens, and tool-call overhead have different cost profiles. Budget in dollars, enforce in tokens.
6. **Cap the shadow count**: No more than 5-7 active shadows per sector. Beyond this, coordination overhead from the quota system itself eats the marginal benefit. Use the tier system to naturally throttle.

---

## Cross-Cutting Insights

Both research areas converge on the same principle: **explicit structure beats implicit accumulation**. Raw memory degrades; structured memory persists. Raw token budgets get wasted; budget-aware agents optimize. MarketMind's shadow ecosystem should treat both memory and quota as first-class architecture concerns, with explicit mechanisms for:

- **Retrieval-time synthesis** (don't consolidate memories — store raw episodes and let the LLM synthesize at read time)
- **Budget signals in prompts** (shadows see their remaining quota at each decision fork)
- **Decay as a feature** (old memories and hoarded quota both degrade naturally, forcing relevance)
- **Cross-shadow propagation** (shared logs, not shared context; structured flags, not raw analysis)

---

**References**:
- Letta (MemGPT): letta.com/blog/benchmarking-ai-agent-memory
- LangMem: LangChain SDK docs (May 2025)
- The Memory Curse: Liu et al., arXiv:2605.08060 (CMU FOCAL Lab, 2026)
- Capability-Preserving Evolution: Yu et al., arXiv:2605.09315 (UIUC, 2026)
- Memory Consolidation Defects: Zhang et al. (May 2026)
- Hindsight: github.com/vectorize-io/hindsight
- YourMemory: github.com/sachitrafa/YourMemory
- Mneme: github.com/CVPaul/mneme
- Codified Context: arXiv:2602.20478v1 (2026)
- Budget-Aware Tool-Use: Google & UCSB, arXiv:2511.17006 (Nov 2025)
- TALE: arXiv:2412.18547 (ACL 2025 Findings)
- DALA: Fan et al., arXiv:2511.13193 (Nov 2025)
- Science of Scaling Agent Systems: Kim et al., arXiv:2512.08296 (Google, Dec 2025)
- AgentBalance: Cai et al., arXiv:2512.11426 (HKUST, Dec 2025)
- Azure API Management llm-token-limit policy: learn.microsoft.com
