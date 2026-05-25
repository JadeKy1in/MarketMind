# LLM Multi-Step Investigative Reasoning: Patterns & Best Practices

**Research date**: 2026-05-17
**Purpose**: Concrete prompt patterns and architecture patterns for MarketMind's news analysis heuristic pipeline.
**Scope**: 5 research questions spanning reasoning frameworks, tool orchestration, context management, hypothesis-driven investigation, and token-efficient design.

---

## Table of Contents

1. [RQ1: Multi-Step Investigation Frameworks](#rq1-multi-step-investigation-frameworks)
2. [RQ2: Tool-Use Orchestration](#rq2-tool-use-orchestration)
3. [RQ3: Context Window Management](#rq3-context-window-management)
4. [RQ4: Hypothesis-Driven Investigation](#rq4-hypothesis-driven-investigation)
5. [RQ5: Token-Efficient Agent Design](#rq5-token-efficient-agent-design)
6. [Recommended Architecture for MarketMind](#recommended-architecture-for-marketmind)
7. [Implementation Priority Matrix](#implementation-priority-matrix)

---

## RQ1: Multi-Step Investigation Frameworks

### 1.1 ReAct (Reasoning + Acting) — The Baseline

**How it works**: Interleave Thought → Action → Observation in a continuous loop. The LLM thinks about what it needs, calls a tool, observes the result, then thinks again.

**Prompt pattern**:
```
You are an investigative analyst. For each step, output:
1. THOUGHT: What you need to find out and why
2. ACTION: The tool to call with parameters
3. WAIT for observation
4. Repeat until conclusion

Always ground every claim in tool output. Never speculate without evidence.
```

**When to use**: Simple, fixed-sequence workflows with few tools (2-5). Good baseline for MarketMind's current pipeline.

**Known failure modes** (2025-2026 research):
- **Context bloat**: Thought-Action-Observation history rapidly fills context window
- **Exploration-order sensitivity**: Conclusions depend on which evidence is found first (EoG, Jan 2026)
- **Infinite loops**: Agent repeats unsuccessful actions without strategic retreat
- **Run-to-run non-determinism**: High Pass@k but low Majority@k reliability

### 1.2 Pre-Act — Plan Before You Leap

**Source**: [Pre-Act: Multi-Step Planning and Reasoning Improves Acting in LLM Agents](https://arxiv.org/html/2505.09970v2) (May 2025)

**Key finding**: Pre-Act outperforms ReAct by 70% in Action Recall. A fine-tuned Llama 70B surpassed GPT-4 with 69.5% improvement in action accuracy and 28% improvement in goal completion rate.

**Prompt pattern**:
```
Before any analysis, draft a multi-step plan:
1. What is the investigation goal?
2. What evidence do you need to find?
3. What order should you search? (prioritize highest-signal first)
4. What would convince you the answer is NOT what you expect?

Then execute each step in order. After each step, check:
- Did you find what you expected?
- Does the plan need refinement?
- Is there a faster path to the answer?

Update the plan only when evidence contradicts assumptions.
```

**MarketMind application**: Before analyzing a breaking news event, generate a research plan: "I will (1) check source credibility, (2) cross-reference with 2 independent sources, (3) assess market impact magnitude, (4) compare to historical analogues." Execute each step, refine only when evidence demands it.

### 1.3 Tree-of-Thoughts (ToT) — Parallel Hypothesis Exploration

**Source**: [ToTRL: Unlock LLM Tree-of-Thoughts Reasoning](https://arxiv.org/html/2505.12717v2) (2025)

**Key finding**: GPT-4 + CoT → 4% success on Game of 24; GPT-4 + ToT → 74% success.

**When to use**: High-stakes analysis where exploring multiple hypotheses in parallel improves accuracy. For MarketMind: assessing whether a news event is bullish, bearish, or neutral from multiple interpretive frameworks.

**Prompt pattern** (BFS variant, capped at 3 branches, depth 3):
```
For this analysis, generate 3 competing hypotheses:
- Hypothesis A: [e.g., "This is a temporary dip; buy the rumor"]
- Hypothesis B: [e.g., "This is the start of a structural shift"]
- Hypothesis C: [e.g., "This is noise; no actionable signal"]

For each hypothesis, evaluate confidence (0-100). Prune any hypothesis below 30.

For remaining hypotheses, gather 2 pieces of evidence FOR and 2 pieces AGAINST. 
Score each piece by credibility (1-5).

Select the hypothesis with the strongest evidence-to-confidence ratio.
Output: FINAL_JUDGMENT: <hypothesis letter> with <X%> confidence.
Counter-argument: "This could be wrong if <condition>."
```

**Cost warning**: ToT can consume ~100x more tokens than CoT. Limit to high-ambiguity situations only.

### 1.4 Reflexion — Self-Critique with Grounding

**Key finding** (2025 consensus): Reflexion is powerful but degrades into "cognitive stagnation" without external grounding. The "Mirror Loop" paper (Oct 2025) shows information change drops ~55% after 3+ reflection cycles without new external input.

**Prompt pattern** (grounded Reflexion, max 3 iterations):
```
After your initial analysis:

ROUND 1 — Self-Critique:
"What's the weakest claim in my analysis? What evidence would disprove it?"

ROUND 2 — External Verification:
Retrieve 1 piece of external data that could falsify your conclusion.
If found: revise. If not found: increase confidence by 10%.

ROUND 3 — Final Verification:
"Has any new information emerged that contradicts my line of reasoning?"
If yes: revise. If no: finalize.

HARD STOP: Do not iterate beyond 3 rounds. The marginal benefit is near zero.
```

**MarketMind application**: After generating a market-impact assessment, run 1 round of self-critique + 1 round of external data check. Stop at 2 rounds — research shows >3 layers of reflection yields diminishing returns and risks "rewriting instead of improving."

### 1.5 Plan-and-Solve — Two-Phase Architecture

**Core principle**: Separate planning from execution. The LLM acts as architect (drafting the blueprint), then as worker (following it).

**Architecture pattern**:
```
Phase 1 — PLAN:
  Input: Investigation goal + known constraints
  Output: Ordered list of sub-tasks, each with:
    - goal (one sentence)
    - tool to use
    - expected output format
    - failure mode (what to do if this sub-task fails)

Phase 2 — SOLVE:
  For each sub-task in order:
    Execute the sub-task
    Store intermediate results in structured format
    Check: does this sub-task's output change the plan?
    If yes: insert a RE-PLAN checkpoint before continuing
```

**When to use**: Multi-source news analysis where you need to integrate data from multiple APIs (sentiment analysis, volume data, options flow, social media) before forming a conclusion.

### 1.6 Decision Matrix — Which Framework When

| Situation | Framework | Why |
|-----------|-----------|-----|
| Simple lookup or single-source analysis | ReAct | Low overhead, sufficient for linear tasks |
| Multi-source integration with dependencies | Pre-Act | Plan first avoids thrashing across APIs |
| High-ambiguity classification (bullish/bearish/neutral) | ToT (capped) | Parallel hypotheses prevent anchoring bias |
| Final report quality assurance | Reflexion (2 rounds) | Catch weak claims before publication |
| Complex multi-stage investigation | Plan-and-Solve | Separation of planning and execution reduces token waste |

---

## RQ2: Tool-Use Orchestration

### 2.1 When to Call Tools vs. Reason from Context

**Decision heuristic**:
```
BEFORE calling a tool, ask:
1. Is this information already in my context window? → DON'T call
2. Is this information I can REASON about from known facts? → DON'T call
3. Is this information that requires EXTERNAL, TIME-SENSITIVE data? → CALL
4. Is this a FOLLOW-UP to a previous tool call? → Check if previous output suffices
```

**Anti-pattern**: "Let me search to make sure" when the answer is already in the conversation. This is the #1 source of token waste in agent loops.

### 2.2 Tool Selection Strategy

**Tiered tool architecture** (from Anthropic's Tool Search Tool, Nov 2025):

```
Tier 1 — ALWAYS LOADED (core reasoning tools):
  - search_news(query, limit=5)
  - get_market_context(symbol)
  - get_historical_analogues(event_type)

Tier 2 — DEFERRED LOADING (specialized tools):
  - get_options_flow(symbol, date)      # Only for volatility analysis
  - get_insider_transactions(symbol)    # Only for governance analysis
  - get_social_sentiment(symbol)        # Only for retail sentiment

Tier 3 — RARELY LOADED (edge cases):
  - get_regulatory_filings(symbol, type)
  - get_institutional_holdings(symbol)
```

**Result**: Anthropic's deferred loading reduces context from ~77K → ~8.7K tokens (85% reduction), accuracy from 79.5% → 88.1%.

### 2.3 "Thinking Before Searching" Pattern

**Key insight**: The LLM should form a hypothesis FIRST, then search to validate/falsify, rather than searching blindly and trying to extract signal from noise.

**Prompt pattern**:
```
BEFORE ANY TOOL CALL:

1. THINK: "Based on what I already know, my hypothesis is: [X]"
2. IDENTIFY: "The critical unknown is: [Y]"
3. DECIDE: "I need to call [tool Z] because it's the most direct way to resolve [Y]"
4. CALL the tool with specific, narrow parameters
5. AFTER RESULTS: "This confirms/refutes/partially supports my hypothesis because [reason]"

NEVER: Call a tool without first stating what you expect to find and why.
```

### 2.4 Programmatic Tool Calling (PTC) — Code as Action

**Source**: Anthropic's "Programmatic Tool Calling" (Beta, Nov 2025)

**Concept**: Instead of the model orchestrating tool-by-tool through natural language, it writes Python code that calls tools in a sandbox. Loops, conditionals, and aggregation happen in code, not in the conversation. Only the final result returns to context.

**When to use**: Data-heavy, repetitive operations (e.g., "check sentiment for 50 tickers").
**When to avoid**: Single lookups, small datasets, simple fixed-order calls.

**Result**: 37-98% token reduction, lower latency, more reliable control flow.

### 2.5 Tool Definition Best Practices

From Anthropic and OpenAI docs (2025):

1. **Add `input_examples` to tool definitions**: Improves parameter accuracy from 72% → 90%.
2. **Keep schemas minimal**: Only include parameters the agent truly needs. Extra params confuse tool selection.
3. **Group related operations**: Avoid micro-tools. "get_stock_data" is better than "get_price", "get_volume", "get_pe_ratio" as separate tools.
4. **Use XML/Markdown delimiters** to separate tool output from reasoning context, preventing injection.

**Good tool definition pattern**:
```python
{
    "name": "search_financial_news",
    "description": "Search for recent financial news articles about a topic or company.",
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query. Be specific."},
            "date_range": {"type": "string", "enum": ["today", "week", "month"]},
            "sources": {"type": "array", "items": {"type": "string"}, "description": "Optional: restrict to specific sources"}
        },
        "required": ["query"]
    },
    "input_examples": [
        {"query": "Fed interest rate decision June 2026", "date_range": "week"},
        {"query": "NVIDIA earnings guidance revision", "date_range": "month", "sources": ["reuters", "bloomberg"]}
    ]
}
```

---

## RQ3: Context Window Management

### 3.1 The Core Problem

As an agent investigates, it accumulates: tool call descriptions + tool outputs + reasoning traces + conversation history. This grows unboundedly. The 2025 research consensus: **agents fail on long trajectories primarily due to context saturation**, not reasoning ability.

### 3.2 Hierarchical Summarization (Three-Tier)

**Source**: [koladilip/hierarchical-context-ai-agent](https://github.com/koladilip/hierarchical-context-ai-agent) (2025), [AgentFold](https://nufind.nu.edu.sa/EdsRecord/edsarx,edsarx.2510.24699) (Oct 2025)

**Pattern**:
```
Tier 1 — ANCIENT CONTEXT (turns 1-N):
  Highly compressed executive summary (3-5 bullet points)
  Format: "Previously established: [fact 1], [fact 2], [fact 3]"

Tier 2 — MIDDLE CONTEXT (turns N/2 to N):
  Medium-detail structured summary
  Format: Per-source summaries with key quotes and credibility scores

Tier 3 — RECENT CONTEXT (last 5 turns):
  Full message history, verbatim tool outputs
  Format: Uncompressed

Tier 4 — WORKING MEMORY (current turn):
  Active hypotheses, pending verifications, open questions
  Format: Structured JSON
```

**Measured outcomes**: 2x conversation capacity (100+ turns), 95% fact preservation (vs 70% baseline), 36% token reduction.

### 3.3 AgentFold — Proactive Context Folding

**Source**: [AgentFold: Long-Horizon Web Agents with Proactive Context Management](http://arxiv.org/abs/2510.24699) (Oct 2025)

**Core concept**: The agent decides WHEN and WHAT to compress, rather than waiting for context to overflow. At each step, it performs a "folding" operation:
- **Granular condensations**: Fine-grained details kept for active investigation threads
- **Deep consolidations**: Entire multi-step sub-tasks abstracted into a single summary line

**Result**: AgentFold-30B achieves 36.2% on BrowseComp, surpassing o4-mini and matching much larger models.

**Prompt pattern for MarketMind**:
```
After each major source analysis, decide:

IF the source CONFIRMS the leading hypothesis:
  → Deep consolidation: "Source X confirms H1 (credibility: high). No new details."

IF the source CONTRADICTS the leading hypothesis:
  → Keep granular: full evidence, specific quote, credibility assessment

IF the source is NEUTRAL/unrelated:
  → Deep consolidation: "Source X is irrelevant to current investigation."

This preserves context for surprising/disconfirming evidence while compressing confirmatory data.
```

### 3.4 ReSum — Periodic Context Summarization

**Source**: [ReSum: Unlocking Long-Horizon Search Intelligence via Context Summarization](https://arxiv.org/abs/2509.13313) (Sep 2025)

**Key mechanism**: Converts growing interaction histories into compact reasoning states. The agent periodically "resets" its working context by summarizing everything into a structured state, then continues from that compressed representation.

**Prompt pattern**:
```
[COMPRESSION CHECKPOINT — every 5 turns]

Summarize your investigation state into this structured format:

{
  "goal": "one sentence",
  "leading_hypothesis": "most likely conclusion so far",
  "confidence": 0-100,
  "evidence_for": ["key finding 1", "key finding 2"],
  "evidence_against": ["counterpoint 1"],
  "unresolved_questions": ["what still needs checking"],
  "sources_consulted": ["source1 (credibility: X/5)", "source2 (credibility: Y/5)"],
  "next_steps": ["immediate action 1", "immediate action 2"]
}

After compression, continue from this state. The full history is archived;
you should reason from this summary unless you detect a contradiction.
```

### 3.5 Progressive Disclosure for News Sources

**Pattern for hierarchical news browsing**:
```
LEVEL 1 — Headline scan (20-50 words each):
  "Scan headlines from 10 sources. Identify 3 that are most relevant.
   Output: [headline, source, relevance 1-5, reason]"

LEVEL 2 — Summary read (100-200 words each):
  "For the 3 selected articles, read the first 3 paragraphs.
   Output: [key claim, evidence cited, author stance]"

LEVEL 3 — Full-text deep dive:
  "For articles scoring relevance 4+, read the full text.
   Output: [detailed analysis, counter-claims, data points cited]"

DECISION GATE between each level:
  "Is this article worth reading deeper, or is it redundant with already-analyzed sources?"
```

This prevents the common failure mode of loading 10 full articles into context when only 1-2 are actually informative.

---

## RQ4: Hypothesis-Driven Investigation

### 4.1 The Core Loop: Generate → Verify → Refine

Instead of summarizing news, the agent should FORM AND TEST HYPOTHESES.

**Prompt pattern** (HVR loop):
```
PHASE 1 — HYPOTHESIS GENERATION:
Given the headline "[HEADLINE]", generate 3 competing hypotheses about market impact:
  H1: [Bullish interpretation — why this is good for the asset]
  H2: [Bearish interpretation — why this is bad for the asset]  
  H3: [Neutral/noise — why this doesn't matter]

For each hypothesis, assign a PRIOR probability based on historical analogues.

PHASE 2 — VERIFICATION:
For each hypothesis, answer:
  1. What evidence would CONFIRM this hypothesis?
  2. What evidence would DISPROVE this hypothesis?
  3. What's the SINGLE MOST DIAGNOSTIC data point that could distinguish H1 from H2?

Then search for that diagnostic data point FIRST.

PHASE 3 — REFINEMENT:
  - Update probabilities based on evidence found
  - If confidence < 60% for all hypotheses: "Insufficient evidence for any conclusion. Flag as AMBIGUOUS."
  - If confidence > 80% for one hypothesis: Finalize with supporting evidence.
  - If 60-80%: Generate one more round of verification.
```

### 4.2 Adversarial Falsification Pattern

**Source**: Multiple 2025 papers on adversarial LLM investigation — "Testing the Constraint Engine" (PhilArchive, Nov 2025), "Eliciting Language Model Behaviors with Investigator Agents" (ICML 2025)

**Key insight**: The LLM should actively try to DISPROVE its own conclusions, not just find supporting evidence. This counters confirmation bias.

**Prompt pattern**:
```
After reaching a preliminary conclusion:

ADVERSARIAL CHECK:
"Assume my conclusion is WRONG. What's the most likely reason it's wrong?
  - Am I over-weighting recent news?
  - Am I ignoring contradictory data?
  - Am I pattern-matching to a historical event that doesn't apply?"

"MOST DANGEROUS COUNTERFACTUAL:
If the opposite of my conclusion were true, what evidence would I expect to see?
Search for that evidence now."

"CONFIDENCE CALIBRATION:
Based on what I FOUND vs. what I expected to find:
  Original confidence: [X%]
  Adjusted confidence: [Y%]
  Reason for adjustment: [specific evidence or lack thereof]"
```

### 4.3 Confidence Calibration Pattern

**Source**: Reflexion research (2025), Mirror Loop paper (Oct 2025)

**Pattern**:
```
CALIBRATION CHECK:

For each claim in your analysis, rate:
  - VERIFIABLE: "I can point to specific tool output that supports this" → confidence 70-95%
  - INFERRED: "I reasoned this from patterns but didn't directly observe it" → confidence 40-70%
  - SPECULATIVE: "This is plausible but I have no direct evidence" → confidence 10-40%

Mark INFERRED and SPECULATIVE claims explicitly in output with [INFERRED] or [SPECULATIVE] tags.

Rule: If >30% of your claims are INFERRED or SPECULATIVE, flag the entire analysis
as LOW CONFIDENCE and recommend human review.
```

### 4.4 "What Would Disprove This" Adversarial Reasoning

**Source**: Multiple 2025 adversarial reasoning papers (POATE attack, Logicbreaks, HAUNT framework)

**Prompt pattern**:
```
After analysis, answer these questions explicitly:

1. "What single piece of new information would most change my conclusion?"
2. "Which assumption is most fragile — the one that, if wrong, collapses the whole analysis?"
3. "What's the counter-narrative? Who would disagree with this and why?"
4. "If this analysis were wrong, what would the world look like tomorrow?"
5. "Is there a simpler explanation that doesn't require my complex chain of reasoning?"

FAIL SAFE: If you cannot answer question 1, your analysis is too vague. Be more specific.
```

---

## RQ5: Token-Efficient Agent Design

### 5.1 Small-Model Triage Architecture

**Source**: [Local-Splitter](https://arxiv.org/abs/2604.12301) (April 2026), [MemFlow](https://arxiv.org/html/2605.03312v1) (May 2026)

**Pattern**: Route simple tasks to a small model, complex tasks to a large model.

**Local-Splitter's 7 tactics** (measured 45-79% cloud token savings):

| # | Tactic | When to Apply |
|---|--------|---------------|
| T1 | **Local Routing** — classify as TRIVIAL/COMPLEX | Every request. Trivial answered locally (zero cloud tokens). |
| T2 | **Prompt Compression** — shorten before forwarding | Long prompts with boilerplate or repeated context |
| T3 | **Semantic Caching** — return cached response for near-duplicates | Repetitive queries (e.g., "check AAPL sentiment" every hour) |
| T4 | **Draft-Review** — local model drafts, cloud reviews | Analysis that needs quality check but not full regeneration |
| T5 | **Minimal-Diff** — extract only changed context | Incremental updates to existing analysis |
| T6 | **Structured Intent Extraction** — parse verbose into structured | User queries wrapped in natural language |
| T7 | **Prompt Caching** — tag stable prefixes with `cache_control` | Always. Stable system prompts and tool definitions should be cached. |

**MarketMind application**:
```
Layer 1 — Haiku (cheap, fast):
  - Source credibility checks (is this a known reliable outlet?)
  - Headline relevance scoring (is this about my watchlist?)
  - Duplicate detection (have I already seen this story?)
  - Sentiment polarity (is this positive, negative, or neutral in tone?)

Layer 2 — Sonnet (balanced):
  - Multi-source cross-referencing (do 3 sources agree?)
  - Context-aware event classification (earnings, M&A, regulatory, macro)
  - Historical analogue matching (has this pattern occurred before?)

Layer 3 — Opus (expensive, thorough):
  - Complex multi-factor impact assessment
  - Counter-narrative generation and adversarial review
  - Final report synthesis with confidence calibration
  - Edge cases where Haiku/Sonnet confidence < 60%
```

### 5.2 Semantic Caching of Intermediate Reasoning

**Source**: [Sutradhara](https://arxiv.org/html/2601.12967v1) (Microsoft Research, Jan 2026)

**Key insight**: KV cache hit rates collapse in agentic workloads because LRU eviction thrashes shared prefixes. Solution: priority-aware eviction with semantic metadata tagging.

**Pattern for MarketMind**:
```python
# Cache intermediate results with semantic keys
CACHE = {
    "sentiment:AAPL:2026-05-17": {"score": 0.72, "sources": 12, "at": "2026-05-17T14:30Z"},
    "crossref:tariff-announcement-may2026": {"agreement": 0.85, "sources": ["bloomberg", "reuters", "wsj"], "at": "..."},
    "historical:fed-rate-hike-tech-impact": {"pattern": "short-term dip, medium recovery", "examples": [...]},
}

# Before calling expensive model:
if cached and cache_age < freshness_threshold:
    return cached_result  # Skip expensive call
```

### 5.3 Structured Output to Reduce Re-Prompting

**Key insight**: When the LLM outputs unstructured prose, downstream consumers often need to re-prompt to extract structured data. Output JSON/Markdown schema directly.

**Pattern**:
```
Instead of:
  "AAPL is looking bullish because of strong iPhone sales..."

Output:
```json
{
  "ticker": "AAPL",
  "sentiment": "bullish",
  "confidence": 78,
  "key_factors": [
    {"factor": "iPhone sales beat", "impact": "positive", "credibility": 4},
    {"factor": "Services revenue growth", "impact": "positive", "credibility": 4}
  ],
  "counter_risks": ["China regulatory uncertainty", "supply chain constraints"],
  "historical_analogue": "Q3 2024 post-earnings rally",
  "analogue_match_quality": 65,
  "needs_human_review": false,
  "analysis_depth": "medium"
}
```

This eliminates the need for a separate parsing step and enables downstream consumers to read fields directly.

### 5.4 Mastra-Style Observational Memory

**Source**: Mastra Observational Memory (2026), 94.87% on LongMemEval

**Pattern** — Two background agents compress context:
```
OBSERVER Agent (runs after each turn):
  - Condenses conversation into timestamped, prioritized observations
  - Compression ratio: 5-40x
  - Output: JSON array of observations with priority tags

REFLECTOR Agent (runs periodically):
  - Rewrites observation history
  - Merges duplicate observations
  - Drops low-priority items
  - Uses intelligent forgetting (high-priority items retained, low-priority fade)

Priority levels:
  🔴 HIGH — contradictory evidence, disconfirming findings
  🟡 MEDIUM — new supporting evidence, source credibility assessments
  🟢 LOW — confirmatory evidence from already-consulted sources
  ⚪ FORGETTABLE — procedural steps, tool call metadata, redundant facts
```

### 5.5 Constant-Cost Semantic Memory

**Source**: Semvec (2026) — patent-pending

**Concept**: Replace unbounded conversation history with a fixed-size semantic state vector plus tiered memory. ~76% token reduction on 48-turn runs.

**Trade-off**: Loses verbatim recall but preserves semantic meaning. Good for long-running MarketMind sessions where preserving every tool output is unnecessary, but preserving the *meaning* of what was learned is critical.

---

## Recommended Architecture for MarketMind

### Composite Architecture: Pre-Act + HVR + Tiered Context + Model Router

```
┌─────────────────────────────────────────────────────────────┐
│                    MARKETMIND HEURISTIC PIPELINE              │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  ┌──────────┐    ┌───────────────┐    ┌──────────────────┐  │
│  │ INGEST   │───▶│ PRE-ACT PLAN  │───▶│ HVR INVESTIGATE  │  │
│  │ Headline │    │ 1. Goal set   │    │ H: 3 hypotheses  │  │
│  │ + Source │    │ 2. Tool plan  │    │ V: verify each   │  │
│  │          │    │ 3. Prune plan │    │ R: refine, score │  │
│  └──────────┘    └───────────────┘    └────────┬─────────┘  │
│                                                  │            │
│                    ┌─────────────────────────────┘            │
│                    ▼                                          │
│  ┌─────────────────────────────────────────────┐             │
│  │         TIERED MODEL ROUTER                  │             │
│  │                                              │             │
│  │  Haiku (T1): source check, dedup, sentiment │             │
│  │  Sonnet (T2): cross-ref, classify, analogue  │             │
│  │  Opus  (T3): multi-factor, adversarial, synth│             │
│  └─────────────────────────────────────────────┘             │
│                    │                                          │
│                    ▼                                          │
│  ┌─────────────────────────────────────────────┐             │
│  │         CONTEXT MANAGEMENT LAYER             │             │
│  │                                              │             │
│  │  Tier 1: Ancient (compressed summary)        │             │
│  │  Tier 2: Middle (structured per-source)      │             │
│  │  Tier 3: Recent (full verbatim)              │             │
│  │  Tier 4: Working memory (current hypotheses) │             │
│  │                                              │             │
│  │  Compression checkpoints every 5 turns       │             │
│  │  Adversarial falsification check             │             │
│  └─────────────────────────────────────────────┘             │
│                    │                                          │
│                    ▼                                          │
│  ┌─────────────────────────────────────────────┐             │
│  │         OUTPUT: STRUCTURED JUDGMENT          │             │
│  │                                              │             │
│  │  { ticker, sentiment, confidence,            │             │
│  │    evidence_for, counter_risks,              │             │
│  │    needs_human_review, analysis_depth }      │             │
│  └─────────────────────────────────────────────┘             │
│                                                               │
└─────────────────────────────────────────────────────────────┘
```

### Prompt Template: MarketMind Heuristic Workflow

```
SYSTEM: You are a financial news heuristic analyst. Your job is NOT to predict 
markets — it's to assess the QUALITY and IMPACT of information.

RULES:
1. Never make price predictions. Assess information quality and potential impact.
2. Every claim must cite a source tool output.
3. Mark INFERRED vs VERIFIED claims explicitly.
4. If confidence < 60%, flag for human review.
5. Compress context after every 5 tool calls (see COMPRESSION protocol below).

═══ PHASE 1: PLAN ═══

Given the headline: "{headline}" from source: "{source}" at time: "{timestamp}"

Generate a RESEARCH PLAN:
- GOAL: What question am I trying to answer?
- TOOLS: Which tools do I need, in what order?
- HYPOTHESES: 3 competing interpretations (H1, H2, H3)
- DIAGNOSTIC: What's the SINGLE MOST DISCRIMINATING piece of evidence?

═══ PHASE 2: INVESTIGATE ═══

For each hypothesis:
  SEARCH for confirming AND disconfirming evidence
  SCORE each source's credibility (1-5)
  UPDATE hypothesis probability based on evidence

For contradictory evidence:
  PRIORITIZE disconfirming evidence (it's more informative than confirming)

═══ PHASE 3: SYNTHESIZE ═══

IS THERE CONSENSUS across multiple independent sources?
  Yes → confidence +20%
  No  → confidence -20%

IS THE COUNTER-NARRATIVE plausible?
  Yes → flag as "contested" regardless of confidence

WHAT'S MY MOST FRAGILE ASSUMPTION?
  Identify it explicitly

═══ PHASE 4: ADVERSARIAL CHECK ═══

"If I'm wrong, what's the most likely reason?"
"Who would disagree with this assessment and why?"
"What new information tomorrow would prove this wrong?"

═══ OUTPUT FORMAT: JSON ═══

{
  "ticker": "SYMBOL",
  "event_type": "earnings|M&A|macro|regulatory|other",
  "hypotheses": [
    {"id": "H1", "interpretation": "...", "probability": X},
    {"id": "H2", "interpretation": "...", "probability": Y},
    {"id": "H3", "interpretation": "...", "probability": Z}
  ],
  "leading_hypothesis": "H1",
  "confidence": 0-100,
  "evidence_for": [...],
  "evidence_against": [...],
  "fragile_assumption": "...",
  "counter_narrative": "...",
  "needs_human_review": true/false,
  "sources": [{"name": "...", "credibility": 1-5, "url": "..."}],
  "infra_reasoning_notes": "self-documented reasoning chain"
}
```

---

## Implementation Priority Matrix

| Priority | Pattern | Effort | Impact | When to Implement |
|:---:|---|:---:|:---:|---|
| **P1** | Structured JSON output format | Low | High | Immediately — reduces downstream parsing |
| **P2** | Pre-Act planning before investigation | Low | High | Replace current linear ReAct loop |
| **P3** | Hypothesis Generation-Verification-Refinement (HVR) loop | Medium | Very High | Core of heuristic analysis rewrite |
| **P4** | Tiered context management (4 tiers) | Medium | High | Essential for multi-source analysis |
| **P5** | Small-model triage (Haiku → Sonnet → Opus) | Medium | Medium | When token costs exceed budget |
| **P6** | Adversarial falsification check | Low | High | Add to every analysis completion |
| **P7** | Semantic caching of intermediate results | Medium | Medium | When repetitive queries are common |
| **P8** | Programmatic Tool Calling (PTC) | High | High | When doing batch operations on 10+ tickers |
| **P9** | Tree-of-Thoughts parallel exploration | High | Medium | Only for high-ambiguity cases (confidence < 40%) |
| **P10** | Mastra-style Observer/Reflector agents | High | Medium | When sessions regularly exceed 20+ turns |

---

## Key Sources

### RQ1 — Investigation Frameworks
- [Pre-Act: Multi-Step Planning and Reasoning Improves Acting in LLM Agents](https://arxiv.org/html/2505.09970v2) (May 2025)
- [EoG: Think Locally, Explain Globally — Graph-Guided LLM Investigations](https://export.arxiv.org/abs/2601.17915) (Jan 2026)
- [Reasoning Court: Combining Reasoning, Action, and Judgment](https://ui.adsabs.harvard.edu/abs/2025arXiv250409781W/abstract) (Apr 2025)
- [ToTRL: Unlock LLM Tree-of-Thoughts Reasoning Potential](https://arxiv.org/html/2505.12717v2) (2025)
- [StoC-TOT: Stochastic Tree-of-Thought with Constrained Decoding](https://aclanthology.org/2025.knowledgenlp-1.12/) (ACL 2025)

### RQ2 — Tool Orchestration
- [Anthropic Programmatic Tool Calling](https://www.ikangai.com/code-as-action-the-pattern-behind-programmatic-tool-calling/) (Nov 2025)
- [GraphReAct: Reasoning and Acting for Multi-step Graph Inference](https://arxiv.org/html/2605.07357v2) (May 2026)
- [OLIVIA: Online Learning via Inference-time Action Adaptation](https://browse-export.arxiv.org/abs/2605.11169) (May 2026)
- [Tool Orchestrator — Universal Programmatic Tool Calling](https://github.com/Brainwires/tool-orchestrator)

### RQ3 — Context Management
- [AgentFold: Long-Horizon Web Agents with Proactive Context Management](http://arxiv.org/abs/2510.24699) (Oct 2025)
- [ReSum: Unlocking Long-Horizon Search Intelligence via Context Summarization](https://arxiv.org/abs/2509.13313) (Sep 2025)
- [SLIM: Simple Lightweight Information Management](https://arxiv.org/abs/2510.18939) (Oct 2025)
- [WebCoach: Self-Evolving Web Agents with Cross-Session Memory](https://arxiv.org/html/2511.12997v1) (Nov 2025)
- [Hierarchical Context AI Agent](https://github.com/koladilip/hierarchical-context-ai-agent) (2025)

### RQ4 — Hypothesis-Driven Investigation
- [The Mirror Loop: Recursive Non-Convergence in Generative Reasoning Systems](https://arxiv.org/abs/2510.21861) (Oct 2025)
- [Testing the Constraint Engine: Adversarial Self-Interrogation](https://philarchive.org/rec/SANTTC-6) (Nov 2025)
- [Eliciting Language Model Behaviors with Investigator Agents](https://icml.cc/virtual/2025/poster/46145) (ICML 2025)
- [ReflCtrl: Controlling LLM Reflection via Representation Engineering](https://lilywenglab.github.io/ReflCtrl/) (NeurIPS 2025)
- [MAPS: Self-Reflection with Auto-Prompting](https://www.emergentmind.com/topics/multi-layered-self-reflection-with-auto-prompting-maps) (Jun 2025)

### RQ5 — Token-Efficient Design
- [Local-Splitter: Seven Tactics for Reducing Cloud LLM Token Usage](https://arxiv.org/abs/2604.12301) (Apr 2026)
- [MemFlow: Intent-Driven Memory Orchestration for Small Language Model Agents](https://arxiv.org/html/2605.03312v1) (May 2026)
- [Sutradhara: Orchestrator-Engine Co-design for Agentic Inference](https://arxiv.org/html/2601.12967v1) (Jan 2026)
- [GenericAgent: Token-Efficient Self-Evolving LLM Agent](https://arxiv.org/abs/2604.17091) (Apr 2026)
- [AgentInfer: Co-Design of Inference Architecture and System](https://arxiv.org/abs/2512.18337v2) (Dec 2025)

### Claude-Specific (2026)
- [Anthropic Claude Managed Agents: Dreaming, Multiagent, Outcomes](https://sdtimes.com/ai/new-in-claude-managed-agents-dreaming-outcomes-and-multiagent-orchestration/) (May 2026)
- [Building Autonomous OSINT Agent with Claude Tool Use API](https://www.freecodecamp.org/news/build-autonomous-agent-in-python-using-claude/)
- [Anthropic Tool Calling 2.0 - Tool Search & Deferred Loading](https://zhuanlan.zhihu.com/p/2018418114488975827) (Nov 2025)
