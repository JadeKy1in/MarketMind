# Gate 1 Conversation Archiving — Research Findings

**Research date**: 2026-05-17
**Purpose**: Design a structured format for archiving AI-human "Gate" conversations so they are (1) human-readable, (2) machine-analyzable, and (3) Red Team auditable.

---

## 1. Structured Conversation Logging

### 1.1 Ecosystem Consensus: Append-Only JSONL

The AI agent ecosystem is converging on **append-only JSONL** as the default format for conversation audit trails. This format is portable, grep-friendly, line-oriented (one event per line), and trivially replayable.

**Key implementations referenced:**

| Project | Event Types | Notable Features |
|---|---|---|
| **CAI / Alias Robotics** (`DataRecorder`) | `session_start`, `session_end`, `user_message`, `assistant_message` | Tool-call correlation via `tool_call_id`; per-LLM-call recording with model, messages, tools, usage, cost, timing |
| **Go Agent Harness** (Rollout Recorder) | `run.started`, `llm.turn.requested`, `llm.turn.completed`, `tool.call.started`, `tool.call.completed`, `usage.delta` | Session replay, forking (resume from any event), date-partitioned storage `~/.harness/rollouts/YYYY-MM-DD/` |
| **LunaRoute** (JSONL Storage) | `Started`, `RequestRecorded`, `ResponseRecorded`, `ToolCallRecorded`, `StreamStarted`, `Completed`, `StatsSnapshot`, `StatsUpdated` | Zstd compression (~10x reduction), configurable retention, multi-writer coordination (JSONL + SQLite + PostgreSQL) |
| **auditlog-ai** (Python library) | Decorator-based `@log_agent` | SHA-256 hashing of inputs/outputs, append-only JSONL, async support, Supabase/PostgreSQL backends |

**Sources**:
- [CAI DataRecorder & JSONL Format](https://deepwiki.com/aliasrobotics/cai/9.1-datarecorder-and-jsonl-format)
- [Go Agent Harness — JSONL Rollout Recorder](https://github.com/dennisonbertram/go-agent-harness/issues/16)
- [LunaRoute JSONL Storage](https://deepwiki.com/erans/lunaroute/7.3-jsonl-storage)
- [auditlog-ai (PyPI)](https://pypi.org/project/auditlog-ai/)

### 1.2 Common JSONL Schema Across Ecosystem

These fields appear across nearly every implementation:

| Field | Purpose |
|---|---|
| `session_id` / `run_id` | Links all events in a conversation |
| `timestamp` | ISO 8601 UTC with millisecond precision |
| `seq` / `entry_id` | Monotonic sequence number |
| `type` | Event discriminator: `user`, `assistant`, `tool-call`, `tool-result`, `reasoning`, `system-event` |
| `role` | `user`, `assistant`, `system`, `tool` |
| `content` | Message body (text or structured blocks) |
| `tool_call_id` | Correlates tool requests with results |
| `model_id` / `provider` | Identifies the LLM used |
| `usage` / `cost` | Token counts and cost tracking |
| `input_hash` / `output_hash` | Integrity verification (SHA-256) |
| `latency_ms` / `duration_ms` | Performance metrics |
| `error` / `status` | Error tracking and success/failure |

### 1.3 IETF Standardization Effort (Feb 2026)

An active Internet-Draft (`draft-birkholz-verifiable-agent-conversations-00`) defines a **CDDL-based format** with JSON/CBOR representations for verifiable AI agent conversation records. Key features:

- Session metadata, message exchanges, tool invocations, reasoning traces (Chain-of-Thought)
- **COSE signing** for cryptographic tamper-evidence and non-repudiation
- Cross-vendor interoperability
- Maps to compliance frameworks: EU AI Act, SOC 2, PCI DSS, NIST, ISO 42001
- 11 enumerated compliance requirements: automatic logging, timestamps, actor identification, input/output recording, integrity protection, anomaly detection, human oversight, traceability

**Source**: [IETF Draft — Verifiable Agent Conversation Records](https://www.ietf.org/ietf-ftp/internet-drafts/draft-birkholz-verifiable-agent-conversations-00.html)

### 1.4 ChatGPT / Claude / DeepSeek Native Export Formats

There is **no unified JSON schema standard** across platforms. Each uses a proprietary structure:

| Platform | Detection Key | Structure | Model Info |
|---|---|---|---|
| **ChatGPT** | `mapping` with `author.role` | Tree-based: `parent`/`children` links; branching supported | `model_slug` in metadata |
| **Claude** | `chat_messages` with `sender` | Flat array; typed content blocks (`thinking`, `tool_use`, text) | Defaults to `"Claude"` (not in export) |
| **DeepSeek** | `mapping` with `message.fragments` | Fragments-based: `REQUEST`, `RESPONSE`, `THINK` | `model` field |

> "There is no equivalent of IMAP for AI conversations. No common schema. No interchange format. No RFC. Nothing." — [Standard AI Conversation Portability Does Not Exist Yet](https://dev.to/isabelsmith/standard-ai-conversation-portability-does-not-exist-yet-here-is-why-that-should-bother-you-p34)

**Relevance to MarketMind**: Since we control our own archive format (not importing from external platforms), we should design our format to be IETF-draft-aligned from the start, with JSONL as the storage layer for maximum tool compatibility and forward portability.

---

## 2. Decision Audit Trail

### 2.1 Core Insight: Transcripts Are NOT Audit Trails

A major theme across 2025-2026 literature: a flat transcript of prompts and outputs is a **debug tool**, not compliance evidence. Regulators increasingly demand a **record of the control path**: what data was retrieved, whether it was authorized, what policies fired, and what safeguards applied at the moment of decision.

> "If you capture the prompt and answer but cannot answer 'What did the system actually retrieve? Was that retrieval authorized? Did a policy check run? Was anything bypassed?' — you have a transcript, not an audit trail." — [ISACA, The AI Audit Trail: From AI Policy to AI Proof, 2026](https://www.isaca.org/resources/news-and-trends/newsletters/atisaca/2026/volume-9/the-ai-audit-trail-from-ai-policy-to-ai-proof)

### 2.2 The GSAR Pipeline (Gate → Score → Audit → Report)

From Sturna AI's experience running 347 production AI agents in regulated industries:

- **Gate**: Compliance verification at inference time (<18ms per gate), rejecting non-compliant outputs before they enter the decision chain
- **Score**: Composite compliance scores (confidence, regulatory alignment, chain consistency)
- **Audit**: Append-only event store supporting four query patterns:
  - **Forward trace** (input → all agents that touched it)
  - **Backward trace** (output → complete decision chain)
  - **Temporal query** (everything about entity X between T1 and T2)
  - **Counterfactual query** (what if Agent A had produced Y instead of Z?)
- **Report**: Automated compliance reports with regulatory citations

Each agent emits a structured `DecisionRecord` containing `agent_id`, `input_hash`, `reasoning_trace`, `confidence`, `output_hash`, and `parent_records` — forming a **directed acyclic graph (DAG)**.

**Source**: [Building a Compliant AI Agent System: Lessons from 347 Production Agents](https://dev.to/sturnaai/building-a-compliant-ai-agent-system-lessons-from-347-production-agents-74m)

### 2.3 Think-Aloud / Reasoning Capture Protocol

Multiple sources converge on the same pattern: **instruct the AI to articulate reasoning in a structured `thinking` block *during* execution, not after**.

**Appian's Drive Thinking Pattern (2025)**:
- Prompt instructs the model to place reasoning in a `"thinking"` key before the decision output
- Thinking text stored in a separate column, displayed as "AI Reasoning" readout
- Benefits: reduced hallucination (each step logically follows the last), faster course correction (users see where logic went wrong), clear audit trail

**Source**: [Drive Thinking in AI Models (Appian Docs, 2025)](https://docs.appian.com/suite/help/25.4/drive-ai-thinking.html)

**ReAct as Auditable Evidence (2026)**:
- ReAct's thinking trajectory is **not a post-hoc explanation** — it is generated during execution and bound to the action and its result
- Each ReAct step becomes a standardized execution node: `session_id`, `step_id`, `thought` (structured), `action`, `observation`, `prev_hash`, **private-key signature**, `entity_id`
- Creates a tamper-evident, cryptographically verifiable chain of reasoning, action, and feedback

**Source**: [ReAct as Auditable Evidence (CSDN, April 2026)](https://blog.csdn.net/2501_91474102/article/details/160532797)

### 2.4 Policy-Aware Six-Stage Framework (from Academia)

An October 2025 paper implements a controller that uses an LLM to execute a six-stage reasoning flow for data access decisions, with **non-negotiable policy gates applied before aggregation** (deny-by-default when context is ambiguous). This improved Exact Decision Match from 10/14 to 13/14 (92.9%) and dropped False Approval Rate on must-deny cases to zero.

Stages: Contextual interpretation → User validation → Data classification → Business purpose test → Compliance evaluation → Risk synthesis and decision (APPROVE/DENY/CONDITIONAL with machine-readable rationale).

**Source**: [Policy-Aware Generative AI for Safe, Auditable Data Access Governance (arXiv, Oct 2025)](https://arxiv.org/html/2510.23474v1)

### 2.5 Decision Rights Operating Model (Beyond RACI)

A tiered autonomy model where agents operate under explicit decision rights:

| Tier | Scope | Approval Required |
|---|---|---|
| Tier 1 | Summaries + suggested actions | None |
| Tier 2 | Create tickets under strict rules | Evidence gates (anomaly thresholds, two-signal rules) |
| Tier 3 | Parameter changes, config updates, financial actions | Human approval + evidence package |

Every tool call and approval is recorded and searchable. Applies directly to MarketMind's Gate conversation — the Gate is itself a Tier 2/3 decision point where the human approves or rejects the AI's analysis.

**Source**: [AI Decision Rights Operating Model (Infolitz, Feb 2026)](https://www.infolitz.com/blog-post/ai-decision-rights-operating-model-beyond-raci)

---

## 3. White-Box Documentation (Reasoning Transparency)

### 3.1 LLMCheckup: Conversational Examination of LLMs

An academic tool (HCINLP 2024 Workshop) for **white-box explainability** via conversational interfaces:

- **Feature attribution**: Input x Gradient, Attention, LIME, Integrated Gradients
- **Rationalization**: Chain-of-Thought prompting, counterfactual generation
- **Conversational archive**: Users can chat with any LLM about its behavior, with follow-up suggestions and custom inputs
- **Source attribution**: Parses user intents into SQL-like queries, returns explanations with feature attribution scores
- **Single-model architecture**: One LLM handles intent recognition, task execution, explanation generation, and dialogue response

**Source**: [LLMCheckup — Conversational Examination of LLMs (ACL Anthology, 2024)](https://aclanthology.org/2024.hcinlp-1.9/)

### 3.2 White-Box: Graph-Based Reasoning Transparency

A project that converts credible texts into structured **Neo4j graph databases** (~130K relationships, ~60K nodes) and uses hybrid RAG (LLaMA 3.1, Phi-3) to allow users to **trace the AI's thought process step-by-step** through the graph — providing a clear "stack trace" of how outputs are derived.

**Source**: [White-Box (Devpost)](https://devpost.com/software/whitebox-zn5u2q)

### 3.3 Practical Recommendations for MarketMind

For Gate conversation archives, white-box documentation means each turn should capture:

1. **Data snapshot**: What sources/data the AI consulted for that turn (source IDs, timestamps)
2. **Confidence annotation**: A numeric or categorical confidence level at each decision point
3. **Source attribution**: Which specific facts came from which specific sources
4. **Alternative paths considered**: A brief "what was considered but rejected" (counterfactual transparency)
5. **Policy gates triggered**: Which compliance or business rules fired during this turn

This aligns with the ISACA 2026 "Four Pillars of Proof":

1. **Who/What initiated** — authenticated identity or agent
2. **Data Lineage** — what was retrieved, referenced, filtered, denied; whether authorized
3. **Control State** — policies, safeguards, access controls in force
4. **Temporal Integrity** — exact model version, configuration, data snapshot at that micro-moment

---

## 4. Retrieval for Retrospective Analysis

### 4.1 The Evolution Path: FTS5 → Vector → Hybrid → Knowledge Graph

Teams consistently follow this maturation path for archived conversation search:

```
SQLite FTS5 (keyword/BM25) → add vector search (sqlite-vec) → hybrid orchestration → knowledge graph
```

**Source**: [Why Papr — Evolution Path](https://platform.papr.ai/overview/why-papr)

### 4.2 rchive: Hybrid FTS5 + Vector for ChatGPT/Claude Exports

An npm package (`@kaustubhdurgade/rchive`) designed specifically for AI conversation archives:

- **FTS5 full-text search** (weight 0.4)
- **Vector search via sqlite-vec** with nomic-embed embeddings (weight 0.6)
- Merged, deduped, ranked results
- Per-chunk topic extraction, summaries, "caveman" text compression for pattern detection
- MCP server integration for Claude Code

**Source**: [rchive (npm)](https://www.npmjs.com/package/@kaustubhdurgade/rchive)

### 4.3 FTS5 vs. Vector: When Each Wins

From "Why I Replaced My AI Agent's Vector Database With grep":

> For personal-scale agents (<1,000 documents), SQLite FTS5 with BM25 ranking outperforms vector search for archived dialogues. The "semantic gap" barely exists when one person writes and searches their own notes.

**Source**: [Why I Replaced My AI Agent's Vector Database With grep](https://dev.to/kuro_agent/why-i-replaced-my-ai-agents-vector-database-with-grep-59mm)

### 4.4 WeLoom: Local RAG Chat Memory with FTS5

A local-first multi-platform chat memory pipeline:

- SQLite FTS5 + trigram + LIKE fallback for retrieval
- Pattern detection through contact reports, personality profiling, relationship extraction
- Graceful degradation when FTS5 is unavailable

**Source**: [WeLoom (GitHub)](https://github.com/clearyss/WeLoom)

### 4.5 Session Intelligence: Transcript Pattern Detection

Roxabi's continuous improvement system parses archived session transcripts and extracts:

- Trend analysis over time (weekly/monthly)
- Recurring blocker detection
- Regression identification
- Idempotent re-processing (only unanalyzed sessions)

**Source**: [Session Intelligence (Roxabi)](https://github.com/Roxabi/roxabi-boilerplate/issues/227)

### 4.6 Recursive AI: Structured Facts from Archived Dialogues

Proposes extracting discrete facts, decisions, preferences, and relationships from conversations into a dedicated FTS5 table, with contradiction detection (superseding outdated facts while preserving history).

**Source**: [Recursive AI — Extract Structured Facts](https://github.com/marknutter/recursive-ai/issues/34)

---

## 5. Topic Shift & Decision Point Detection

### 5.1 Def-DTS: Deductive Reasoning for Topic Segmentation (ACL 2025)

Uses LLM-based multi-step deductive reasoning for Dialogue Topic Segmentation:
- Bidirectional context summarization
- Utterance intent classification
- Deductive topic shift detection
- Auto-labeling potential

**Source**: [Def-DTS (Findings of ACL 2025)](https://aclanthology.org/2025.findings-acl.1066/)

### 5.2 Semantic Turning Point Detector (Open Source, 2025)

A lightweight tool that recursively analyzes message chains to identify **semantic turning points** — moments where meaning, topic, or insight shift. Uses a tri-axial framework (ARC/CRA/DAO) with phi-field significance scoring and Choquet integral fusion. Distinguishes between simple topic changes and deeper **inflection moments**.

**Source**: [Semantic Turning Point Detector (GitHub)](https://github.com/gaiaverseltd/semantic-turning-point-detector)

### 5.3 Turn Relevance via Three-Way Decision (2025)

Uses three-way decision + KNN to automatically assign relevance labels to dialogue turns by measuring distance between turns and final responses. +4-6% Recall improvement.

**Source**: [Optimizing Chatbot Responsiveness (Expert Systems with Applications, 2025)](https://www.sciencedirect.com/science/article/abs/pii/S0955799725000384)

---

## 6. Recommended Architecture for MarketMind Gate Conversation Archive

### 6.1 Storage Format: JSONL with IETF-Aligned Schema

```
data/archive/YYYY/MM/DD/gate-{session_id}.jsonl
```

Each line is a typed event. The schema aligns with the IETF draft and ecosystem conventions:

```json
{
  "session_id": "gate-2026-05-17-001",
  "entry_id": 1,
  "timestamp": "2026-05-17T14:30:00.123Z",
  "type": "user_message",
  "role": "user",
  "content": {"text": "What do you think about AAPL?"},
  "turn_metadata": {
    "turn_number": 1,
    "topic_label": "position_review",
    "decision_point": false
  }
}
```

**Event types**: `session_start`, `session_end`, `user_message`, `assistant_message`, `assistant_reasoning`, `tool_call`, `tool_result`, `decision_point`, `human_override`, `system_event`

### 6.2 Decision Audit Trail Fields

Every `assistant_message` and `decision_point` event should carry a `decision_trail` block:

```json
{
  "decision_trail": {
    "confidence": "high",
    "confidence_basis": "multi_source_convergence",
    "sources_consulted": ["source_id_1", "source_id_2"],
    "data_snapshot": {
      "prices_as_of": "2026-05-17T14:29:00Z",
      "macro_data_as_of": "2026-05-17T12:00:00Z"
    },
    "alternatives_considered": ["bearish_scenario"],
    "rejection_reason": "bearish_scenario_rejected_due_to_low_volume_confirmation",
    "policy_gates_triggered": ["no_brokerage_api_rule", "position_limit_check"],
    "reasoning_trace": "Full chain-of-thought captured here..."
  }
}
```

### 6.3 Human-Readable Companion: Markdown Transcript

Alongside the JSONL, generate a Markdown transcript for human review:

```
data/archive/YYYY/MM/DD/gate-{session_id}.md
```

Format: Timestamped dialogue with embedded reasoning blocks (collapsible), decision point markers, and source attribution footnotes. This is a **rendered view** of the JSONL, not a separate source of truth.

### 6.4 Search & Retrospective Analysis: Hybrid FTS5 + Vector

For the retrospective analysis layer:

| Layer | Technology | Purpose |
|---|---|---|
| **Storage** | SQLite + FTS5 virtual table | Fast keyword retrieval, BM25 ranking |
| **Enrichment** | Vector embeddings (sqlite-vec or ChromaDB) | Semantic similarity for vocabulary mismatch |
| **Fusion** | Weighted hybrid (0.4 FTS5 / 0.6 vector) | Combined relevance scoring |
| **Pattern Detection** | Topic extraction + trend analysis | Recurring decision patterns, bias detection |
| **Consolidation** | Long-term reports | Session-to-session coherence |

### 6.5 Automatic Tagging Pipeline

On archive, each session runs through:
1. **Topic segmentation** (using LLM-based deductive reasoning per Def-DTS)
2. **Decision point detection** (turn relevance + turning point detector)
3. **Metadata extraction** (tickers discussed, decision types, confidence levels)
4. **Fact extraction** (structured facts → FTS5 table with contradiction detection)

---

## 7. Key References Summary

| Area | Key Source | Link |
|---|---|---|
| **JSONL Standard** | IETF Draft: Verifiable Agent Conversations | [ietf.org](https://www.ietf.org/ietf-ftp/internet-drafts/draft-birkholz-verifiable-agent-conversations-00.html) |
| **JSONL Implementation** | CAI DataRecorder (Alias Robotics) | [deepwiki.com](https://deepwiki.com/aliasrobotics/cai/9.1-datarecorder-and-jsonl-format) |
| **Audit Trail Philosophy** | ISACA: AI Audit Trail 2026 | [isaca.org](https://www.isaca.org/resources/news-and-trends/newsletters/atisaca/2026/volume-9/the-ai-audit-trail-from-ai-policy-to-ai-proof) |
| **GSAR Pipeline** | Sturna AI: 347 Production Agents | [dev.to](https://dev.to/sturnaai/building-a-compliant-ai-agent-system-lessons-from-347-production-agents-74m) |
| **Think-Aloud** | Appian Drive Thinking Pattern | [docs.appian.com](https://docs.appian.com/suite/help/25.4/drive-ai-thinking.html) |
| **ReAct Auditing** | CSDN: ReAct as Auditable Evidence | [blog.csdn.net](https://blog.csdn.net/2501_91474102/article/details/160532797) |
| **ChatGPT/Claude Exports** | ChatInsights v3 (comparative analysis) | [github.com](https://github.com/Eden-Eldith/ChatInsights) |
| **Conversation Portability** | dev.to: No Standard Exists | [dev.to](https://dev.to/isabelsmith/standard-ai-conversation-portability-does-not-exist-yet-here-is-why-that-should-bother-you-p34) |
| **Retrieval (FTS5+Vector)** | rchive npm package | [npmjs.com](https://www.npmjs.com/package/@kaustubhdurgade/rchive) |
| **Retrieval Evolution** | Papr Platform: FTS5→Vector→Graph | [platform.papr.ai](https://platform.papr.ai/overview/why-papr) |
| **Topic Segmentation** | Def-DTS (ACL 2025) | [aclanthology.org](https://aclanthology.org/2025.findings-acl.1066/) |
| **Turning Points** | Semantic Turning Point Detector | [github.com](https://github.com/gaiaverseltd/semantic-turning-point-detector) |
| **Turn Relevance** | Three-Way Decision (Expert Systems) | [sciencedirect.com](https://www.sciencedirect.com/science/article/abs/pii/S0955799725000384) |
| **White-Box Explainability** | LLMCheckup (ACL 2024) | [aclanthology.org](https://aclanthology.org/2024.hcinlp-1.9/) |
| **Decision Rights** | Infolitz: Beyond RACI | [infolitz.com](https://www.infolitz.com/blog-post/ai-decision-rights-operating-model-beyond-raci) |
