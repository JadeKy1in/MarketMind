# Gate 1 Time Estimation Research: "Come Back Later" UX for AI Analysis

**Date**: 2026-05-17
**Scope**: How MarketMind's main AI should handle complex external material (PDFs, investment advice) during Gate 1 discussions — estimating analysis time, communicating "come back later," and triaging complexity.

---

## Table of Contents

1. [Time Estimation for LLM Analysis](#1-time-estimation-for-llm-analysis)
2. [Async Communication Patterns](#2-async-communication-patterns)
3. [Complexity Triage](#3-complexity-triage)
4. [User Experience of Waiting](#4-user-experience-of-waiting)
5. [Synthesized Recommendations for MarketMind](#5-synthesized-recommendations-for-marketmind)
6. [Sources](#sources)

---

## 1. Time Estimation for LLM Analysis

### 1.1 Token-Based Estimation Formula

The standard production formula for end-to-end LLM latency:

```
E2E_time = TTFT + (output_tokens / output_speed)
```

Where TTFT is Time-to-First-Token and output_speed is tokens/second.

**Anthropic Claude models (2026)**:

| Model | Output Speed | TTFT (p50) |
|---|---|---|
| Claude Sonnet 4.6 | ~80 tok/s | ~300ms |
| Claude Haiku 4.5 | ~80-100 tok/s | ~200ms |
| Claude Opus 4.6 (reasoning) | ~60 tok/s | ~500ms |

**Worked example — analyzing a 10-page PDF (MarketMind Gate 1):**
- Input: ~5,000 tokens (full PDF extraction)
- Expected output: ~2,000 tokens (detailed Gate 1 analysis)
- Model: Claude Sonnet 4.6
- `E2E = 0.3s + (2000 / 80) = 0.3s + 25.0s = 25.3s`

Note: This is just generation time. Multi-step analysis with tool calls adds:

| Step | Tokens In | Tokens Out | Est. Time |
|---|---|---|---|
| 1. Quick-scan triage | 500 | 200 | ~3s |
| 2. Full document analysis (PDF) | 5,000 | 1,500 | ~19s |
| 3. Gate 1 framework comparison | 3,000 | 800 | ~10s |
| 4. Verification / cross-check | 2,000 | 500 | ~7s |
| **Total** | **~10,500** | **~3,000** | **~39s** |

For multi-step reasoning with tool-call round-trips, add ~2-5s per round-trip. A 4-step analysis like the above takes approximately **45-60 seconds** of actual Generation time.

### 1.2 Multi-Step Analysis Time Estimation

The research identifies two approaches for estimating multi-step analysis time:

**A. Response Length Predictors (RLPs)** — Lightweight transformer probes that predict output token count from prompt embeddings. ISRTF scheduling achieves MAE = 19.9 tokens and R-squared = 0.852. TimeBill's RLP provides execution-time closed-form polynomials from prompt length and KV-cache size.

**B. Uncertainty-Aware Prediction** — Output length should be modeled as a log-t distribution, not a point estimate. The Tail Inflated Expectation (TIE) metric yields 2.31x per-token latency reduction for online inference compared to point estimates.

**Key finding from "Can LLMs Perceive Time?" (ICLR 2026):** LLMs cannot self-estimate their own task durations. Pre-task estimates overshoot by 4-7x. Errors reach 5-10x in multi-step agentic settings. Any time estimation MUST come from an external predictor, not the LLM itself.

### 1.3 Progress Bar Patterns for Indeterminate Tasks

**"Predicting thinking time in Reasoning models" (Raaschou-Jensen et al., 2025)** — Found that MLP probes on hidden states can predict remaining reasoning tokens with ~0.82 MAE. This enables a "practical progress bar for reasoning."

**Augment Code "Tasklist" (2025)** — Structured, stateful task objects with lifecycle:
```
todo -> in_progress -> finished / cancelled
```
Visual indicator: grey (pending) -> blue (spinning) -> green (checkmark).

**Interactive Chain-of-Thought (iCoT)** — Dual-panel: left side shows problem/variables, right side shows one reasoning block at a time with playback controls. +7.1pp verification accuracy, +13.2pp error localization.

**Key design rule from Ably research (40+ engineering teams):** "Users are willing to wait, but only if they know what's happening. Silent latency kills trust." Progress should be visible and specific — not a spinner, not "thinking...", but concrete checkpoints.

### 1.4 Prediction Models in Production (2026)

**Google Vertex AI (llm-d.ai)** — XGBoost regression model trained online on live traffic predicts TTFT and TPOT. Features: KV cache usage, input length, queue depth, running requests. ~5% MAPE accuracy. 43% improvement in P50 end-to-end latency.

**SageSched (Gan et al., 2026)** — Uncertainty-aware scheduler using cost distributions rather than point estimates. Properly handles demand uncertainty and workload hybridity.

**LMetric (Mar 2026)** — Multiplication-based: KV-aware prefill tokens x current batch size. No hyperparameter tuning. 92% reduction in TTFT, 52% in TPOT vs vLLM-v1.

---

## 2. Async Communication Patterns

### 2.1 "Come Back Later" — The Named Pattern

**Microsoft Agent Framework (March 2026)** — Introduced a dedicated **Background Responses** feature:
- Submit task -> receive **continuation token** (not blocking wait)
- Client can **poll** for results on its own schedule
- Survives network drops, resumes from where it left off
- Use case explicitly: "fire and forget — submit a task and come back later for results"

This signals platform-vendor validation of this as a first-class scenario.

### 2.2 Notification Design for Background Completion

**Claude Code Web project (DeepWiki, April 2026) — concrete implementation:**

| Mechanism | Behavior |
|---|---|
| **Unread indicators** | Blue dot on session tab when background session has new output |
| **Desktop notifications** | System-level: "Project -- Claude appears finished (worked for 45s)" |
| **Mobile fallback** | Toast banners (blue, slide-down, 5s auto-dismiss) + vibration + audio |
| **Pattern-based fast detection** | Recognizes output like "All tests passed" or "Done in 2.45s" to notify immediately |

**Critical rule:** No notification if the user is already viewing that tab. Clicking a notification switches the user directly to that session.

### 2.3 Progress Streaming — Not Spinners

**Atomicwork (April 2026)** rebuilt their chat architecture around the insight that agent conversations are evolving state:

- A user request might touch 2-3 specialist agents, multiple tool calls, taking 10+ seconds
- Instead of a spinner, they stream intermediate states: "checking access policy -> provisioning -> confirmed"
- Conversations modeled as "turns" (bounded interaction cycles)
- Core philosophy: "Every second of dead time is a second the user spends wondering whether to just do it manually instead."

### 2.4 Session Resumption Design

**The Ohno project's Session Continuity Pattern** — 5 mechanisms:
1. `handoff_notes` — 1-3 sentence summary for next session
2. `context_summary` — Detailed multi-paragraph state snapshot
3. `work_in_progress` (JSON) — Structured data (file paths, sub-task progress, partial results)
4. `task_activity` logs — Complete audit trail with typed events (created, decision, progress, blocker_set)
5. `task_handoffs` table — Sub-agent delegation results with PASS/FAIL/BLOCKED

**Recovery API** (`getSessionContext()`):
```
- in_progress_tasks
- blocked_tasks
- recent_activity (last 10)
- suggested_next_task
```

**Key design principle:** Files > in-context memory for durability. "Context windows are not free. Every token of prior conversation competes with new information. Make context windows ephemeral by design."

### 2.5 Cross-Device Continuity

**Ably Gen-2 AI UX research (2025):** Users start on desktop, walk away, expect results pushed to phone/tablet. AI should feel like a persistent presence, not tied to a fragile browser tab. The "come back later" pattern must assume cross-device resumption.

### 2.6 Human-Friendly Language

The raw "Async continue started" message is being replaced industry-wide with user-friendly versions. One A2A client hub project settled on:

> "指令已提交后台处理，你可以继续其他操作"
> ("Command submitted for background processing -- you can continue with other tasks")

For MarketMind, the message should be domain-appropriate — not technical jargon, not condescending, just clear about what's happening and when to check back.

---

## 3. Complexity Triage

### 3.1 Quick-Scan Assessment: A Pre-Parse Triage Layer

**ADE Classify (Landing AI)** — Page-by-page classification API that acts as a pre-parse triage layer:
- Evaluates raw documents concurrently, analyzing each page BEFORE expensive parsing
- Filters noise to save compute costs and prevent extraction hallucinations
- Handles mixed document bundles (invoices, bank statements, cover pages, etc.)
- Uses custom class descriptions for zero-shot accuracy
- Includes `unknown` fallback with `suggested_class` reasoning

**NCSU LVLM Triage (2024)** — Layered approach:
1. Metadata filtering (fast)
2. CLIP semantic search (medium)
3. LVLM contextual summarization (slow, only when needed)
Balances scalability with precision through progressive refinement.

### 3.2 Document Classification Heuristic (Adapted for MarketMind Gate 1)

External material brought during Gate 1 can be classified on two axes:

**Axis 1: Content Type**
| Type | Characteristics | Quick-Scan Time | Full Analysis Time |
|---|---|---|---|
| **News/Market data** | Structured, familiar format | ~1-2s | ~5-10s |
| **Investment advice (friend/forum)** | Unstructured claims, no data source | ~2-3s | ~15-25s |
| **Analyst report / PDF** | Long-form, tables, charts | ~3-5s | ~30-60s |
| **Regulatory filing** | Dense, legal language | ~3-5s | ~30-45s |
| **Mixed bundle** | Multiple document types | ~5-8s (per page) | ~60-120s |

**Axis 2: Analysis Depth Required**
| Depth Level | Trigger Condition | Steps Required | Time |
|---|---|---|---|
| **Immediate discuss** | Simple fact-check, known source | 1: Read + classify | <5s |
| **Brief analysis** | Unfamiliar claim, single source | 2: Read + fact-check | ~15-30s |
| **Deep analysis (async)** | Multi-page PDF, multi-claim, conflict with existing data | 4: Scan + Analyze + Verify + Compare | ~45-120s |

### 3.3 Quick-Scan Assessment Prompt Framework

The quick-scan should answer 3 questions before committing to full analysis:

1. **Is this material Gate-relevant?** (Does it introduce a new thesis or merely restate existing analysis?)
2. **What type of analysis does it need?** (Fact-check vs. opinion evaluation vs. data integration)
3. **Does it conflict with existing Gate 1 analysis?** (If yes -> higher urgency, deeper analysis needed)

### 3.4 Material Classification Filters

| Filter | Check | Action if Fail |
|---|---|---|
| **Source credibility** | Is the source known and tracked? | Flag for verification, not immediate discussion |
| **Data freshness** | Is the data timestamped? Within relevance window? | Downgrade priority if stale |
| **Claim multiplicity** | How many distinct claims does the material make? | >=3 claims -> escalate to deep analysis |
| **Format complexity** | PDF with tables/charts vs. plain text? | Complex format -> add 50% time buffer |
| **Conflict potential** | Does any claim contradict existing Gate 1 data? | Immediate flag, highest priority |

---

## 4. User Experience of Waiting

### 4.1 The AI Paradox: AI Makes Users MORE Impatient

**Li et al. (Journal of Consumer Psychology, 2025):** *"Time is shrinking in the eye of AI: AI agents influence intertemporal choice"*:

- Interacting with AI agents speeds up users' internal clock, making wait times feel subjectively longer
- Users who received AI advice (vs. human advice) were significantly more likely to choose immediate smaller rewards over larger delayed ones
- When described as "slower but more accurate," the impatience effect disappeared entirely
- The mere presence of AI raises user expectations for speed

**MarketMind implication:** Announce the estimated time and frame slowness as thoroughness. "This is complex material -- I'm going to analyze it carefully rather than rush. That will take about X minutes."

### 4.2 Slow Responses Damage Trust — But Only for Algorithms

**Efendic, Van de Calseyde, & Evans (Organizational Behavior and Human Decision Processes, 2020):** N=1,928 across 7 studies:

| Prediction Source | Fast Response | Slow Response |
|---|---|---|
| **Algorithm** | Judged as high quality | Judged as low quality |
| **Human** | Judged as low quality | Judged as high quality |

Users interpret algorithmic slowness as failure (the task is perceived as "easy" for machines). But reframing as "thorough verification" or "deliberate analysis" shifts the perception. **The framing of the delay matters as much as the delay itself.**

### 4.3 Financial Decision-Making Acceptable Wait Windows

**2025 Industry Benchmarks:**

| Latency Category | Time Range | Financial Use Case |
|---|---|---|
| Sub-second | 0-1s | Fraud detection, pricing, HFT |
| Real-time | 1-3s | Chatbots, recommendation |
| Tolerable | 3-10s | Internal analytics, dashboards |
| Background | >10s | Complex analysis, batch |
| **Async** | >30s | Multi-document deep analysis, PDFs |

**Specific financial data points (2025):**

- 2-second delay in financial intelligence -> 5% drop in trading volume, 8% increase in complaints
- User satisfaction drops 8-12% per second of added latency in AI-driven financial systems
- GenAI financial advisory: sub-7 seconds for 100 concurrent users (Tiger Analytics)
- European financial AI assistant: 35s -> 17s latency reduction dramatically improved engagement (Nebuly)

**Key insight:** For Gate 1 (research/analysis, not trading), users will tolerate longer waits IF the value is clear and the progress is visible. The 1-2 minute window for deep PDF analysis is acceptable if properly communicated upfront.

### 4.4 The Deliberation Pause — Why Waiting Improves Quality

**Kahneman's System 1 vs. System 2:**
- System 1: Fast, intuitive, emotional -- used by default
- System 2: Slow, deliberate, logical -- requires effort to engage
- Financial decisions made with System 2 are higher quality

**Kirchler et al. (Journal of Risk and Uncertainty, 2017):** N=1,700+ across 3 countries:
- Time pressure (7-second deadline) increased Prospect Theory's reflection effect -- subjects became more risk-averse for gains AND more risk-seeking for losses
- Time delay (7-20 second forced pause) produced less measurement noise and cleaner preference signals
- "Driven by forcing subjects to take slow decisions"

**The "Pause Principle" in leadership:** Leaders who pause -- sometimes 48+ hours -- before major decisions allow System 2 to override System 1. One CEO gained market share by pausing 3 weeks on a competitive response.

**For MarketMind: Frame the wait as a FEATURE, not a bug.** "I'm deliberately taking time on this because research shows that a brief pause improves financial decision quality. This is your System 2 check -- I'll have results in about X minutes."

### 4.5 Making Waiting Feel Productive

**Research-backed strategies:**

1. **Show concrete checkpoints, not spinners.** "Scanning document..." -> "Cross-referencing with Gate 1 data..." -> "Verifying claims..." -> "Preparing analysis..."

2. **Provide intermediate value.** Even while the full analysis runs, surface the quick-scan results: "Initial scan: 3 claims detected, 1 conflicts with existing data. Deep analysis in progress..."

3. **Use bounded uncertainty.** "This will take approximately 1-2 minutes" (not "I'll let you know when I'm done" or a precise "1:37" that's likely wrong)

4. **Give the user agency.** "Go do something else and come back. I'll have results waiting." Not "Please wait while I process..." -- passive voice vs. active permission

5. **Resume with context.** When the user returns, the first message should restate what they asked for: "I analyzed the PDF you shared about Tesla's Q4 earnings. Here's what I found against your Gate 1 positions..."

6. **Surprise completion.** If estimated 2 minutes but finishes in 45 seconds: "That was faster than expected -- here's your analysis." This creates a positive surprise vs. expectation.

---

## 5. Synthesized Recommendations for MarketMind

### 5.1 Time Estimation Implementation

**Simple heuristic formula (no ML required):**

```
estimated_seconds = ceil(
    (input_tokens / 50) +                   # reading time (50 tok/s processing)
    (expected_output_tokens / 80) +          # writing time (Sonnet 4.6: ~80 tok/s)
    (num_analysis_steps * 3) +               # tool-call round-trips (~3s each)
    buffer_seconds                           # 20% uncertainty buffer
)
```

**Quick-scan first approach:**
1. Count input tokens (number of characters / 4 for rough estimate)
2. Run triage prompt (200 tokens out, ~3s)
3. From triage, classify into one of 4 tiers with time estimates
4. Communicate the tier and estimate to user
5. Proceed or offer async

### 5.2 Time Estimation Tiers

| Tier | Material Type | Steps | Estimate | User Instruction |
|---|---|---|---|---|
| **T0: Instant** | Simple question, known source | 1 read | <5s | Discuss immediately |
| **T1: Brief** | Single claim, unfamiliar source | 2 verify | ~15-30s | "One moment while I verify this..." |
| **T2: Analysis** | Multi-claim, PDF report | 4 analyze | ~1-2 min | "Give me about 1-2 minutes to analyze..." |
| **T3: Deep** | Multi-document, conflicting data | 6+ verify | ~3-5 min | "This is complex. Go do something else -- I'll need about 3-5 minutes." |

### 5.3 User Communication Template

**For T1 (Brief, <30s):**
> "Let me verify that claim against our existing data. One moment..."

**For T2 (Analysis, 1-2m):**
> "This is a detailed report with [N] claims. I'm going to:
> 1. Scan and classify the content (~10s)
> 2. Cross-reference against your Gate 1 positions (~30s)
> 3. Verify key claims (~20s)
> 4. Prepare a comparison analysis (~20s)
> 
> Total: about 1-2 minutes. I'll show progress as I go."

**For T3 (Deep, 3-5m):**
> "This material is complex -- it's a [type] with [N] distinct claims, and [X] of them conflict with your current positions.
> 
> I need about 3-5 minutes for a proper analysis (not a rushed one). Research shows that a brief deliberation pause actually improves financial decision quality -- this is your System 2 check.
> 
> Go grab coffee or check another position. Come back and I'll have:
> - A claim-by-claim fact-check
> - Conflicts with your existing thesis flagged
> - A recommended Gate 1 pass/fail/disposition
> 
> You can also ask me to ping you when I'm done."

### 5.4 Async / "Come Back Later" Flow

```
User drops complex PDF
        |
        v
Triage prompt (~3s) -> classify Tier T2/T3
        |
        v
AI: "This is Tier 2/3. I need ~X minutes. [Progress preview]. 
     Want me to proceed, or discuss something else first?"
        |
    ----+----
    |        |
  [Proceed] [Defer]
    |        |
    v        v
AI starts    AI saves context to session state
analysis     {gate: 1, pending_material: pdf_hash, triage: {...}}
streams      "OK, I've saved this for analysis. Let's continue Gate 1."
progress          |
                  v
            When user says "analyze the PDF from earlier"
                  |
                  v
            AI loads context, runs analysis, presents results
```

### 5.5 Progress Streaming During Analysis

During a T2/T3 analysis, the AI should stream checkpoints (not a silent spinner):

```
[ ] Scanning: PDF extracted, 5,200 tokens, 3 tables detected
[x] Scanning complete -- 7 distinct claims identified
[ ] Cross-referencing: Claim 1/7 checked against Gate 1 positions
[ ] Cross-referencing: Claim 3/7 -- CONFLICT with QQQ bear thesis
[x] Cross-referencing complete -- 2 conflicts, 3 supports, 2 new
[ ] Verifying: Fact-checking conflicting claims...
[x] Verification complete
[ ] Preparing comparison analysis...
[x] Analysis ready
```

### 5.6 No-Go: What NOT to Do

| Don't | Why | Do Instead |
|---|---|---|
| "I'm thinking..." | Vague, invisible, feels like broken UX | Show specific checkpoint |
| Spinner with no explanation | Silent latency kills trust | Show what's happening |
| Precise time estimate ("1:37") | Will be wrong, breaks trust | Bounded range ("1-2 minutes") |
| Blocking wait without escape | Frustrating, no agency | Offer "proceed" or "defer" |
| Dump all results at once | Overwhelming, no intermediate value | Stream checkpoints, then summary |
| "Please wait..." (passive) | Infantilizing | "Go do something else" (permissive) |

### 5.7 Architecture Considerations

1. **External predictor, not LLM self-estimate:** LLMs cannot estimate their own task duration (4-10x error). Use token-count-based formula or a lightweight probe model.

2. **Continuation token pattern:** For async analysis, emit a unique task ID that the user can reference later: "Analysis task `G1-20260517-A3F2` is running. Say 'check G1-20260517-A3F2' to get results."

3. **Session state persistence:** Pending analysis must survive session compaction/restart. Save to filesystem as structured JSON.

4. **Cross-device awareness:** If MarketMind ever gets a web/mobile UI, notifications should fan out across devices.

5. **2-3 minute ceiling for Gate 1 async:** Beyond 5 minutes, the user has context-switched and the analysis should be presented as a fresh Gate 1 artifact, not an in-context response.

---

## 6. Sources

### Time Estimation
- Predictive Scheduling for Efficient Inference-Time Reasoning in LLMs (arXiv 2602.01237, Feb 2026) — [link](https://export.arxiv.org/abs/2602.01237)
- Predicted-Latency Based Scheduling for LLMs (llm-d.ai / Google Vertex AI, 2026) — [link](https://llm-d.ai/blog/predicted-latency-based-scheduling-for-llms)
- TimeBill: Time-Budgeted Decoding for LLMs (EmergentMind, Jan 2026) — [link](https://www.emergentmind.com/topics/time-budgeted-decoding-timebill)
- Can LLMs Perceive Time? An Empirical Investigation (ICLR 2026 Workshop, arXiv 2604.00010) — [link](https://export.arxiv.org/abs/2604.00010)
- Uncertainty-Aware Output Length Predictions (arXiv 2604.00499, Apr 2026) — [link](https://arxiv.org/abs/2604.00499v1)
- ISRTF Scheduling for LLM Inference (EmergentMind, Jan 2026) — [link](https://www.emergentmind.com/topics/isrtf-scheduling)
- LMetric: Multiplication-Based Scheduling (arXiv 2603.15202, Mar 2026) — [link](https://arxiv.org/abs/2603.15202v1)
- SageSched: Efficient LLM Scheduling (Gan et al., 2026) — [link](https://www.semanticscholar.org/paper/SageSched%3A-Efficient-LLM-Scheduling-Confronting-and-Gan-Bao/f3fc565ebd82351a3a26d15cae712099bd783c31)

### Async Communication Patterns
- Microsoft Agent Framework: Handling Long-Running Operations with Background Responses (Mar 2026) — [link](https://devblogs.microsoft.com/agent-framework/handling-long-running-operations-with-background-responses/)
- What 40+ engineering teams learned about shipping AI to users at scale (Ably, 2025) — [link](https://ably.com/blog/building-agentic-ai-at-scale)
- Gen-2 AI UX: Conversations that stay in sync across every device (Ably, 2025) — [link](https://ably.com/blog/cross-device-ai-sync)
- Background Activity and Notifications — Claude Code Web, DeepWiki (2026) — [link](https://deepwiki.com/vultuk/claude-code-web/6.4-background-activity-and-notifications)
- Why we rebuilt Atom's chat streaming architecture (Atomicwork, Apr 2026) — [link](https://www.atomicwork.com/blog/atom-chat-streaming-experience)
- Async Continue UX Evaluation (A2A Client Hub, GitHub Issue #288) — [link](https://github.com/liujuanjuan1984/a2a-client-hub/issues/288)
- Session Continuity Pattern (Ohno project, DeepWiki) — [link](https://deepwiki.com/srstomp/ohno/3.3-session-continuity-pattern)
- Beyond the Chatbox: Designing Interfaces for AI Delegation (Ken Priore, 2025) — [link](https://kenpriore.com/beyond-the-chatbox-designing-interfaces-for-ai-delegation/)

### Complexity Triage
- Introducing ADE Classify (Landing AI, 2025) — [link](https://landing.ai/blog/introducing-ade-classify)
- Enhancing Technical Document Triage: LVLMs for Image-Text Information Extraction (NCSU LAS, Nov 2024) — [link](https://ncsu-las.org/2024/11/enhancing-technical-document-triage-large-vision-language-models-for-image-text-information-extraction/)
- DocFlow AI — Government Document Triage (Devpost) — [link](https://devpost.com/software/docflow-ai-ro0ma1)

### Progress Bars & Reasoning UX
- Predicting Thinking Time in Reasoning Models (Raaschou-Jensen et al., 2025) — [link](https://ar5iv.labs.arxiv.org/html/2506.23274)
- Interactive Chain-of-Thought (iCoT) Paradigm (EmergentMind, 2025) — [link](https://www.emergentmind.com/topics/interactive-chain-of-thought-icot)
- How we solved the "AI agent black box" problem with typed tasks (Augment Code, Jul 2025) — [link](https://www.augmentcode.com/blog/how-we-built-tasklist)
- AsyncVoice Agent: Real-Time Explanation for LLM Planning and Reasoning (Oct 2025) — [link](https://huggingface.co/papers/2510.16156)

### User Psychology of Waiting
- AI Makes Consumers More Impatient (PsyPost, 2025) — [link](https://www.psypost.org/artificial-intelligence-makes-consumers-more-impatient/)
- Slow Response Times Undermine Trust in Algorithmic (but not Human) Predictions (Efendic et al., OBHDP, 2020) — [link](https://www.sciencedirect.com/science/article/abs/pii/S074959781930192X)
- My Advisor, Her AI and Me: Evidence from a Field Experiment on Human-AI Collaboration and Investment Decisions (Yang et al., 2025) — [link](https://bigquant.com/square/paper/4fc0d29f-a517-4afd-bc59-db45feccdb36)
- Faster but Not Smarter? Temporal Constraints and User Compliance with AI Explanations (Shahu et al., ACM IUI, 2025) — [link](https://dl.acm.org/doi/10.1145/3772363.3798697)
- The Effect of Fast and Slow Decisions on Risk Taking (Kirchler et al., J Risk Uncertain, 2017) — [link](https://link.springer.com/article/10.1007/s11166-017-9252-4)
- Extraneous Factors in Judicial Decisions (Danziger, Levav & Avnaim-Pesso, PNAS, 2011) — [link](https://pubmed.ncbi.nlm.nih.gov/21482790/)
- Interactivity and Illusions of Ability: How Using Generative AI Affects Investor Judgments (Wiley, 2025) — [link](https://onlinelibrary.wiley.com/doi/10.1111/1475-679X.70017)

### Token Speed & Latency Benchmarks
- What 12 LLMs Actually Cost in Production (Benchwright, May 2026) — [link](https://dev.to/benchwright/what-12-llms-actually-cost-in-production-real-data-from-benchwright-4ifl)
- LLM API Comparison 2026: Pricing, Speed, Features (MorphLLM, Mar 2026) — [link](https://www.morphllm.com/llm-api)
- Anthropic: API Pricing, Performance & Model Catalog (llm-stats.com) — [link](https://llm-stats.com/providers/anthropic)
