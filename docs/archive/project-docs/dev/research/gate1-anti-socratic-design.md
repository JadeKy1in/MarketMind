# Gate 1 Research: Anti-Socratic / Non-Directive Conversation Design

**Research date**: 2026-05-18
**Scope**: Design patterns for human-AI conversation that adapts to the user (anti-Socratic), not the other way around.
**Application**: MarketMind investment decision-making conversation interface

---

## 1. Anti-Socratic / Non-Directive Methods

### 1.1 Rogerian/Client-Centered Approaches Applied to AI

The foundational reference is Carl Rogers' client-centered therapy (1950s-60s), built on three core conditions:

| Rogers' Condition | Meaning | AI Application |
|---|---|---|
| **Empathy** | Sensing the user's emotions as they experience them | Understanding a user's risk concerns, goals, and decision context |
| **Unconditional Positive Regard** | Non-judgmental acceptance | Not shaming users for past decisions; accepting their starting point |
| **Congruence / Genuineness** | Honesty, no hidden agendas | Transparency about data sources, model limitations, confidence levels |

The most iconic AI implementation of Rogerian non-directive conversation is **ELIZA** (Weizenbaum, MIT 1966), which used pattern matching to reflect user inputs back as questions rather than giving advice. A 2025 revival project, **eliz-ai**, paired the original DOCTOR script (47 keyword patterns, pronoun reflection) with GPT-4o-mini, strictly constrained to maintain Rogerian behavior -- no advice-giving, only reflective questioning. The core design challenge: preventing LLM drift into "helpful assistant" mode, requiring extensive prompt engineering and "steering files."

Japanese researchers developed **CRECA** (Context Respectful Counseling Agent), explicitly modeled on Rogers counseling. It extracts emotional words from utterances, uses reflective questions, and adds non-verbal nodding for unconditional approval -- a physical manifestation of unconditional positive regard.

Source: [ELIZA revival project](https://devpost.com/software/eliz-ai), [CRECA counseling agent](https://www.infona.pl/resource/bwmeta1.element.ieee-art-000007844978)

### 1.2 Shared Decision-Making (SDM) from Healthcare

Healthcare SDM is a collaborative process where clinicians and patients make decisions together. Its core elements map directly to financial advice:

| SDM Healthcare Element | Financial Planning Parallel |
|---|---|
| Clinician shares evidence & options | AI shares market data, projections, strategies |
| Patient articulates values & preferences | User articulates goals, risk tolerance, priorities |
| Decision aids (booklets, interactive tools) | Scenario modeling, risk visualizations, comparison tables |
| Informed patient choice | User makes informed investment decisions |

Key research finding (Yang, Bauer, Li & Hinz, 2025, HEC Paris): In a field experiment on human-AI collaboration in investment decisions, **bank customers were significantly more likely to adopt human-AI collaborative advice (79.2%) compared to pure AI advice (68.3%)**. The effect was driven by the **emotional/affective route** (trust and social influence), not by a belief that human+AI produces superior cognitive-quality advice. This directly supports MarketMind's design: the AI provides structured information, the human drives the decision.

Source: [My Advisor, Her AI and Me: Field Experiment (arXiv)](https://arxiv.org/abs/2506.03707)

**Critical nuance from UF research** (Mo Wang et al.): When users perceive a large expertise gap, they often **prefer directive advice** -- being told what to do. When they feel comparable expertise, they prefer participative, shared approaches. This means anti-Socratic design must be **adaptive**: non-directive for confident users, slightly more structured for beginners.

Source: [When advisors should take the lead in decision making (UF Warrington)](https://warrington.ufl.edu/news/mo-wang-advisors-lead-decision-making/)

### 1.3 Motivational Interviewing Bridge

**Motivational Interviewing** (Miller & Rollnick) explicitly draws on Rogers' model and is used in financial coaching. Key principles:

- **"Rolling with resistance"** -- not confronting users about poor past decisions, but exploring ambivalence and inviting change
- **Developing discrepancy** -- helping users see the gap between current behavior and their goals (without telling them)
- **Supporting self-efficacy** -- reinforcing the user's belief that they can make good decisions

Source: [Motivational interviewing in financial counselling](https://responsiblegambling.vic.gov.au/about-us/news-and-media/rolling-with-resistance-managing-difficult-client-behaviours/)

### 1.4 Vanguard's "Emotional Value" Research

Vanguard's 20+ year research program validates the relationship-centered approach:

- **~40%** of perceived value of financial advice is **emotional**, not financial
- **Behavioral coaching** (helping clients stay the course) adds approximately **1.5% annually** to net returns
- **93%** of investors say the "human element" is key; empathy and active listening are "essential qualities for building trust"
- Wealthtender 2025 study (2,568 reviews): Only **10%** of client reviews focused on investment management; **89%** centered on relationship quality, planning advice, and emotional factors

Source: [The emotional value of advice (Vanguard)](https://www.vanguard.co.uk/professional/vanguard-365/client-relationships/articulating-your-value/the-emotional-value-of-advice)

---

## 2. Question Design That Doesn't Lead

### 2.1 Open vs. Closed Question Research

Core definitions from UX research (NNGroup, Emergo by UL):

| Open Questions | Closed Questions |
|---|---|
| Invite free-form, narrative responses | Restrict to limited set (yes/no, scales) |
| Begin with *How...*, *What...*, *Tell me about...* | Begin with *Did...*, *Was...*, *Is...*, *Do you...* |
| Uncover motivations, context, mental models | Provide structure, comparability, quantifiable data |

**How to neutralize leading questions:**

| Leading (Closed) | Non-Leading (Open) |
|---|---|
| "Was that experience helpful?" | "How did you find that experience?" |
| "Did that make sense?" | "What did you think about that?" |
| "How much did you enjoy...?" | "What was your experience of...?" |
| "Do you want to sell this position?" | "What do you see when you look at this position?" |

**Key rule**: Replace *Did/Was/Is/Do you* starters with *How/What/Tell me about...*

Source: [NNGroup: Open-Ended vs. Closed Questions](https://www.nngroup.com/articles/open-ended-questions/)

### 2.2 The "What Am I Not Asking You?" Meta-Question

This is the most powerful anti-Socratic device -- it invites the user to drive exploration. Research across multiple domains shows:

- **Blind-spot surfacing**: The system probes for assumptions and gaps rather than delivering conclusions
- **Option generation**: The system presents alternatives the user didn't articulate
- **Dialogic prompting** (University of Bath framework): AI as "intellectual sparring partner" that asks questions to reveal what hasn't been considered

Implementation patterns:
- After presenting data: *"Is there another angle you'd want to explore before deciding?"*
- After a decision: *"What would make you change your mind about this?"*
- Periodic meta-checks: *"We've covered X, Y, Z. What am I not asking you that I should?"*

Source: [Dialogic prompting (University of Bath)](https://blogs.bath.ac.uk/academic-and-employability-skills/2025/09/02/from-queries-to-conversations-master-the-art-of-dialogic-prompting/)

### 2.3 How Perplexity Deep Research Handles User-Driven Exploration

Perplexity's Deep Research (Feb 2025) implements key patterns:

- **Thread continuity**: Continuous conversation threads; system remembers prior exchanges
- **Iterative research plan**: Refines research plan as it learns, mimicking human exploration
- **Query phrasing control**: Users frame questions with explicit scope parameters, domain priorities
- **Autonomous follow-up**: Proposes logical next questions/avenues the user might explore
- **Source transparency**: All information attributed to sources so user can verify and branch independently

Source: [Perplexity Deep Research (ZDNet)](https://www.zdnet.com/article/what-is-perplexity-deep-research-and-how-do-you-use-it/)

### 2.4 The Funnel Technique (Proven in Qualitative Research)

Start broad and open-ended BEFORE introducing specifics:
1. *"Walk me through how you're thinking about this sector right now."* (broad, open)
2. *"You mentioned volatility concerns -- what specifically worries you?"* (narrowing)
3. *"Here's the data on IV rank for these names. What stands out to you?"* (data-anchored)
4. *"Given all that, how are you leaning?"* (decision prompt)

This prevents priming and allows spontaneous insights to surface first.

### 2.5 Strategic Silence

Pausing after a user finishes (rather than immediately responding) often yields deeper reflection. In UI terms: leave space. Don't fill every gap with analysis.

---

## 3. Adaptive Depth: Day 1 vs. Day 30

### 3.1 Progressive Disclosure Pattern

Progressive disclosure originated in HCI (1980s) and has been adapted for AI agent systems. The core idea: "Only show the information the user needs, when they need it." Anthropic/Claude Code uses a three-layer loading model:

| Layer | What | Token Budget |
|-------|------|:---:|
| Layer 1: Metadata | Skill name + description (YAML) | ~50-100 tokens |
| Layer 2: Core Instructions | Task logic and steps | ~1K-5K tokens |
| Layer 3: Detailed Resources | Supplementary files, templates | Loaded only when needed, then purged |

This yields a 60-80% token reduction. For MarketMind, this maps to:

| Layer | Investor Context |
|-------|-----------------|
| Layer 1: Snapshot | Ticker, price, key metrics (always visible) |
| Layer 2: Core Analysis | Chart patterns, fundamentals, options flow (one click) |
| Layer 3: Deep Dive | DCF models, peer comps, macro overlay (explicit request) |

Source: [Progressive Disclosure for AI Agents (CSDN/Anthropic)](https://blog.csdn.net/m0_55049655/article/details/159694566)

### 3.2 User Profiling from Conversation History

A four-level maturity model for adaptive disclosure:

| Level | Name | Characteristic |
|-------|------|----------------|
| Level 0 | Full Loading | Everything dumped at once (early ChatGPT) |
| Level 1 | Manual Layering | Core/advanced manually split |
| Level 2 | Conditional Loading | Dynamic assembly by task/role |
| Level 3 | Adaptive Disclosure | Agent autonomously decides what to load based on user profile |

**Key research finding** (Microsoft, 2025, 25,000 Bing Copilot conversations): AI agents respond at proficient/expert levels in ~77% of conversations. **Misalignment** (agent responds below the user's expertise level) negatively impacts user experience. User engagement increases when the agent matches the user's expertise level.

Source: [Speaking the Right Language: Expertise Alignment in User-AI Interactions](https://chatpaper.com/chatpaper/zh-CN/paper/115357)

### 3.3 The Kata Three-Tier Adaptation Model

A concrete implementation blueprint (from the Kata system):

| Level | Label | AI Posture |
|-------|-------|------------|
| Beginner | New to domain | **TEACHES** -- maximum guidance, educational prompts, heavy gating |
| Intermediate | Some knowledge | **GUIDES** -- moderate guidance, suggests but doesn't force |
| Experienced | Veteran, strong opinions | **FOLLOWS** -- adapts to user conventions, minimal gates |

Critical design insight: When a veteran **overrides** a suggestion, it is treated as **input** (not friction) and fast-tracked into the system's learning. This is anti-Socratic in action: the user teaches the system.

Source: [Kata: User experience level system](https://github.com/cmbays/kata/issues/145)

### 3.4 Implementation Strategy for MarketMind

**Day 1 (new user)**:
- Full-scope questions: "Here are the key things to consider with this position..."
- Default to structured, comprehensive views
- Offer education: "Would you like me to explain how IV rank works here?"
- Explicit options: "Based on this data, three common approaches are..."

**Day 30 (known user)**:
- Personalized: "Last time we looked at NVDA, you focused on options flow. Same lens this time?"
- Skip basics user already knows
- Remember preferences: "You usually prefer weekly options over monthlies -- still the case?"
- Adaptive gate depth: Experienced users see fewer "are you sure?" prompts

**Progressive profiling signals** (passively collected):
- Average session duration
- Terminology used by user (beginner vs. expert vocabulary)
- Types of questions asked (broad vs. specific)
- Decisions made and their outcomes
- Topics user ignores or skips
- Override frequency (how often user rejects AI suggestions)

### 3.5 Context Rot Mitigation

Progressive disclosure directly counters "context rot" -- the progressive degradation of LLM performance as irrelevant context accumulates:

- **Attention dilution**: Instructions at token 50,000 have far lower compliance than those at token 500
- **Contradiction accumulation**: More context = more conflicting signals
- **Signal-to-noise collapse**: 99% of injected documentation may be irrelevant

Source: [Progressive disclosure patterns (Agentic Design)](https://agentic-design.ai/patterns/ui-ux-patterns/progressive-disclosure-patterns)

---

## 4. Handling User-Initiated Tangents

### 4.1 Conversation Tree Architecture (CTA)

A formal framework (arXiv:2603.21278, March 2026) that organizes LLM conversations as **trees of discrete, context-isolated nodes**:

| Primitive | Description |
|-----------|-------------|
| **Nodes** | Each node maintains its own local context, isolated from siblings |
| **Downstream Context Passing** | When creating a child branch, selectively passes relevant parent context |
| **Upstream Context Merging** | When deleting a branch, merges valuable findings back into the parent |
| **Cross-Node Passing** | Lateral transfer between any two nodes (siblings, non-adjacent) |
| **Volatile Nodes** | Transient exploratory branches; mandatory merge-or-purge lifecycle |

Source: [Conversation Tree Architecture (arXiv)](https://arxiv.org/html/2603.21278v1)

### 4.2 Major Platform Implementations

**OpenAI ChatGPT -- "Branch Conversations" (Sept 2025)**:
- Hover over any message, click "Branch in new chat"
- Creates a new thread inheriting context up to that message
- Original conversation preserved intact
- Compared to Git version control for conversations
- Reduces mean completion time by ~28%; user satisfaction 4.6/5 vs 3.2/5 for linear chats

**Anthropic Claude -- Branching**:
- Conversation branching with navigational arrow buttons
- Edit earlier messages and fork alternate paths

**Ably AI Transport -- DAG Model**:
- Uses `msgId`, `parentId`, `forkOf` headers to build a Directed Acyclic Graph
- Each client holds its own branch selection; tree is source of truth

### 4.3 "Yes, And" vs. "Yes, But" Response Patterns

Derived from improvisational comedy, formalized in the **SPOLIN corpus** (USC ISI, 26,000+ yes-and dialogue pairs):

| Response Type | Proportion | Description |
|---------------|:---:|-------------|
| Explicit yes-and | ~15% | Overt agreement + new context ("Yeah, and also consider...") |
| Implicit yes-and | ~78% | Agreement implied while advancing the topic |
| Yes-but | ~7% | Coherent with premise but lacks affirmative acceptance |

Critical insight: **"Yes, but" is more damaging than "No."** A flat "No" is transparent. "Yes, but" creates the illusion of listening while shutting things down.

**Application to tangent handling**:
- **"Yes, and..." (accept + extend)**: User introduces crypto → "Yes, and here's how that relates to the macro risk we were discussing..."
- **"Yes, but..." (accept + redirect)**: User introduces crypto → "I see the connection, but the data I have is equities-only. Let me note this and we can circle back..."
- **"Let's park that..." (flag + bookmark)**: "Great point. Let me flag this as a separate thread and we'll explore it after we close on the current position."

Source: [How to Understand LLMs through Improv](https://incidentdatabase.ai/blog/improv-ai/), [SPOLIN corpus](https://ar5iv.labs.arxiv.org/html/2004.09544)

### 4.4 Context Window Management for Long Conversations

Practical strategies:

1. **Context compression**: Old conversation turns compressed to semantic summaries via a cheaper model; only recent N turns kept verbatim
2. **Hierarchical Context Management (HCM)**: Nested context levels with distinct retention policies per level
3. **MemGPT-style virtual context**: Main context + external storage (OS-like memory management for LLMs)
4. **Optimal branching**: Studies suggest productivity peaks at **3-4 branches per session** before cognitive overload sets in

### 4.5 Tangible Implementation for MarketMind

When a user introduces a tangent:
1. **Acknowledge + name it**: "That's an interesting angle on Chinese ADR exposure."
2. **Offer a fork**: "Should we explore this now, or shall I create a separate thread for it?"
3. **If forked**: Save state of main conversation, open branch, flag branch for merge/purge
4. **If deferred**: Add to a sidebar "parking lot" visible throughout the session
5. **When tangent ends**: Return to main thread with a 2-line summary of where they left off
6. **On session close**: List all unexplored tangents as "ideas for next time"

---

## 5. Gate-Based Conversation Structure

### 5.1 Wizard/Stepper Patterns in Conversation

The **stage-gated pipeline** pattern (from Alfred Maestro and Kata systems) uses explicit, observable stages:

| Stage | Purpose | Example (Investment) |
|-------|---------|---------------------|
| S0: Context | Establish what we're looking at | "You want to review your NVDA position." |
| S1: Data | Present structured information | Charts, fundamentals, options flow, news sentiment |
| S2: Analysis | Interpret patterns | "Unusual put activity, IV rank elevated to 85th percentile" |
| S3: Options | Generate possible paths | "Three scenarios: hold, trim 25%, sell covered call" |
| S4: Decision Gate | User commits to a path | "Which direction feels right to you?" |
| S5: Confirmation | Verify before execution | "Confirming: sell 25% of NVDA position at market open" |
| S6: Post-Decision | Record outcome + learn | "Noted. I'll flag NVDA for review in 2 weeks." |

Source: [Alfred Maestro stage-gated pipeline (OpenAI Community)](https://community.openai.com/t/from-generic-chatgpt-to-a-tagged-auditable-self-improving-conversational-system/1362519)

### 5.2 Checkpoint-Based Dialogue Design

The **Kata system** defines explicit gate mechanics:

- **Gate States**: `future` → `pending` → `approved` / `skipped` / `rejected`
- **Gate Map**: Visibility into every gate at stage, step, and sub-step level
- **Cooldown Gate**: All sub-tasks must reach their exit gate before reflection begins

For MarketMind, explicit gates prevent the assistant from jumping ahead:
- Gate A: "Ready to look at the data?" (don't show data before user says yes)
- Gate B: "Ready to hear my analysis?" (present data first, then offer interpretation)
- Gate C: "Ready to explore your options?" (don't push to decision before analysis)
- Gate D: "Ready to decide?" (don't rush)

Source: [Kata pipeline with human gates & approval UX](https://github.com/cmbays/kata/issues/93)

### 5.3 How Bloomberg Terminal Structures Analyst Conversations

**Bloomberg IB (Instant Bloomberg)**:
- Integrated chat with 350,000+ financial decision-makers
- Share security data, screenshots, earnings events, research reports directly in chat
- **NOTE function**: Tag, publish, and collaborate on ideas
- **IB Forums**: Community-based chats enhanced by AI-powered Document Search

**Bloomberg ASKB (Agentic AI, beta)**:
- Natural language queries instead of command-based navigation
- **Coordinated network of AI agents** operating in parallel to retrieve and analyze
- Synthesizes company filings, news, sell-side research, proprietary analytics
- **ASKB Workflows**: Multi-step task descriptions (earnings prep, post-event analysis) saved as reusable templates and shared across teams
- Generates BQL code for further modeling in Excel

Key insight: Bloomberg separates **data retrieval** (ASKB) from **human collaboration** (IB). The AI doesn't replace analyst conversations -- it enriches them.

Source: [Bloomberg embeds agentic AI into the Terminal](https://www.thetradenews.com/bloomberg-embeds-agentic-ai-into-the-terminal/)

### 5.4 Making Gates Feel Natural, Not Like a Form

Design principles to avoid the "form-filling" feeling:

1. **Progress is visible but minimal**: A 6-step progress bar is a form. A subtle "2 of 4" badge is a scaffold.
2. **Gates are skippable**: Power users can say "just show me everything" to bypass gates entirely.
3. **Gates adapt to context**: If the user has already expressed clear intent ("I want to sell"), skip forward to the confirmation gate -- don't force them through option generation.
4. **Natural language triggers**: Don't use buttons labeled "Next Gate". Use conversational signposts: "Want to see what the data says?" is an implicit gate offer.
5. **Back-navigation is seamless**: Users should be able to say "wait, go back to the data" without breaking the flow.
6. **Gate only at high-stakes moments**: Gate before a decision to sell, not before showing a chart. The ratio matters -- too many gates and the user feels managed, not empowered.

### 5.5 DialogGPT / Kore.ai Orchestration Pattern

A production dialog orchestration engine with three steps:
1. **User Input & Chunk Shortlisting** -- parse what user said
2. **Intent Identification & Fulfillment Strategy** -- determine what user wants
3. **Flow Management & Fulfillment** -- execute the right conversation path

Key feature: **Ambiguity resolution as a checkpoint** -- when intent is unclear, triggers real-time clarification rather than guessing. This is anti-Socratic: the system admits it doesn't know the user's intent and asks, rather than presuming.

Source: [Kore.ai DialogGPT Orchestration](https://koredotcom.github.io/docs/agent-platform/dialog-agents/dialoggpt/)

---

## 6. Synthesis: Design Principles for MarketMind

### 6.1 Core Anti-Socratic Principle

> **The AI adapts to the USER's questioning style, not the other way around. The AI provides structured information and lets the user drive the exploration.**

### 6.2 Ten Design Rules Derived from Research

| # | Rule | Source |
|---|------|--------|
| 1 | **Ask open, don't lead** -- Replace Did/Is/Do with How/What/Tell me | NNGroup, qualitative research |
| 2 | **Reflect, don't prescribe** -- Mirror user's language back; let them discover | Rogers, ELIZA, Motivational Interviewing |
| 3 | **Offer forks, not funnels** -- When user introduces tangent, offer to branch, don't redirect | Conversation Tree Architecture, ChatGPT branching |
| 4 | **Gate at decisions, not at data** -- Only pause before stakes are real (sell/buy), not before showing a chart | Kata gating model |
| 5 | **Profile passively, not invasively** -- Learn from what user skips, asks about, overrides; never quiz them | Kata 3-tier model, Microsoft expertise alignment |
| 6 | **Start comprehensive, narrow over time** -- Day 1 full questions; Day 30 personalized | Progressive disclosure, adaptive depth |
| 7 | **"Yes, and" tangents, never "Yes, but"** -- Accept + extend, don't accept + redirect | SPOLIN corpus, improv principles |
| 8 | **Ask the meta-question** -- Periodically: "What am I not asking you that I should?" | Dialogic prompting, blind-spot surfacing |
| 9 | **Trust the emotional channel** -- 40% of advice value is emotional; relationship > returns | Vanguard research, Yang et al. field experiment |
| 10 | **Keep gates skippable** -- Power users bypass gates; gates adapt to expressed intent | Kata, Bloomberg ASKB workflows |

### 6.3 Anti-Patterns (What NOT to Do)

| Anti-Pattern | Why It Fails |
|---|---|
| Socratic leading questions ("Don't you think...?") | Imposes AI's framework, user becomes passive |
| Forcing linear progression | Blocks user's natural exploration rhythm |
| Dumping all data at once | Overwhelms; user loses sense of agency |
| Gate overuse (every step gated) | Feels like a form, undermines trust |
| Pretending to know ("Based on my analysis, you should...") | Violates non-directive principle; removes user agency |
| Ignoring tangents ("Let's stay focused on...") | Misses signal; user may have spotted something important |
| One-size-fits-all depth | Beginner overwhelmed, expert bored |

### 6.4 Open Research Questions

1. **Optimal gate frequency**: What ratio of gates-to-steps maximizes user satisfaction without feeling like a form? Preliminary evidence suggests 1 gate per 4-5 conversational turns in decision contexts.
2. **Branch lifecycle**: When should tangent branches be merged back vs. archived vs. discarded? The CTA framework proposes a "volatile node" model but implementation details remain experimental.
3. **Expertise calibration**: How many interactions does it take to reliably profile a user's expertise level? Microsoft's Bing Copilot study used aggregate data but didn't measure individual calibration time.
4. **Emotional state detection**: Should the system adapt not just to expertise but also to user emotional state (anxious, confident, rushed)? This touches on the Rogers empathy condition but adds implementation complexity.
5. **Cross-session memory**: What user preferences should persist across sessions vs. reset? Risk tolerance is stable; current mood is not.

---

## Sources

- [ELIZA revival: GPT-4o-mini constrained to 1966 Rogerian behavior](https://devpost.com/software/eliz-ai)
- [CRECA: Context Respectful Counseling Agent (IEEE)](https://www.infona.pl/resource/bwmeta1.element.ieee-art-000007844978)
- [Yang et al.: My Advisor, Her AI and Me — Field Experiment on Human-AI Investment Decisions (arXiv 2506.03707)](https://arxiv.org/abs/2506.03707)
- [Mo Wang et al.: When Advisors Should Take the Lead in Decision Making (UF Warrington)](https://warrington.ufl.edu/news/mo-wang-advisors-lead-decision-making/)
- [Motivational Interviewing in Financial Counselling](https://responsiblegambling.vic.gov.au/about-us/news-and-media/rolling-with-resistance-managing-difficult-client-behaviours/)
- [Vanguard: The Emotional Value of Advice](https://www.vanguard.co.uk/professional/vanguard-365/client-relationships/articulating-your-value/the-emotional-value-of-advice)
- [NNGroup: Open-Ended vs. Closed Questions in User Research](https://www.nngroup.com/articles/open-ended-questions/)
- [University of Bath: Dialogic Prompting](https://blogs.bath.ac.uk/academic-and-employability-skills/2025/09/02/from-queries-to-conversations-master-the-art-of-dialogic-prompting/)
- [Perplexity Deep Research (ZDNet)](https://www.zdnet.com/article/what-is-perplexity-deep-research-and-how-do-you-use-it/)
- [Progressive Disclosure for AI Agents (Claude Code)](https://blog.csdn.net/m0_55049655/article/details/159694566)
- [Progressive Disclosure UI Patterns (Agentic Design)](https://agentic-design.ai/patterns/ui-ux-patterns/progressive-disclosure-patterns)
- [Microsoft: Speaking the Right Language — Expertise Alignment in User-AI Interactions](https://chatpaper.com/chatpaper/zh-CN/paper/115357)
- [Kata: User Experience Level System (GitHub)](https://github.com/cmbays/kata/issues/145)
- [Kata: Pipeline with Human Gates & Approval UX (GitHub)](https://github.com/cmbays/kata/issues/93)
- [Conversation Tree Architecture (arXiv 2603.21278)](https://arxiv.org/html/2603.21278v1)
- [OpenAI Launches Branch Conversations (36kr)](https://eu.36kr.com/en/p/3453602336593541)
- [SPOLIN: Grounding Conversations with Improvised Dialogues (arXiv)](https://ar5iv.labs.arxiv.org/html/2004.09544)
- [How to Understand LLMs through Improv](https://incidentdatabase.ai/blog/improv-ai/)
- [Alfred Maestro: Stage-Gated Conversational Pipeline (OpenAI Community)](https://community.openai.com/t/from-generic-chatgpt-to-a-tagged-auditable-self-improving-conversational-system/1362519)
- [Bloomberg Embeds Agentic AI into the Terminal (The Trade News)](https://www.thetradenews.com/bloomberg-embeds-agentic-ai-into-the-terminal/)
- [DialogGPT Agents Orchestration (Kore.ai)](https://koredotcom.github.io/docs/agent-platform/dialog-agents/dialoggpt/)
- [Robo-Advisors Beyond Automation: Five Principles (arXiv 2509.09922)](https://ar5iv.labs.arxiv.org/html/2509.09922)
