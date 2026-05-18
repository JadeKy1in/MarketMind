# Shadow Ecosystem: Multi-Agent Communication & Methodology Research

**Date**: 2026-05-18
**Purpose**: Research for MarketMind shadow ecosystem redesign — 23+ AI agents (15 experts + 8 daredevils), 7-day isolation period, cross-shadow interaction after isolation.

---

## Part 1: Multi-Agent Communication Patterns (Post-Isolation)

### 1.1 Lessons from Pod Shop Hedge Funds

Multi-strategy hedge funds (Citadel, Millennium, Point72, Balyasny) operate a "pod" architecture directly analogous to MarketMind's shadow ecosystem:

- **Semi-autonomous pods**: Each pod is an independent investment team with its own P&L, risk limits, and strategy. Millennium runs 300+ pods.
- **Isolation by design**: Pods do NOT share investment ideas or positions. Each pod's alpha signals are guarded within their silo.
- **Shared infrastructure**: Centralized risk management, execution pipelines, data feeds, and capital allocation serve all pods.
- **Failure containment**: If one pod hits a drawdown limit (e.g., 5% triggers risk reduction, 7.5% forces wind-down), the broader platform is insulated.

**Key risk (BlackRock 2026 Crowding Warning)**: Despite formal isolation, hidden correlation emerges when pods share data feeds, AI models, and macro narratives. Under stress, what appears diversified across dozens of independent teams can behave like a single crowded trade. This directly applies to MarketMind — if all shadows converge on the same LLM-derived conclusions, the "independent analysis" guarantee is hollow.

### 1.2 AutoGen: Async Message-Passing Architecture

Microsoft's AutoGen models all coordination as asynchronous, message-driven conversations. Its architecture is the closest fit for deferred communication:

- **Mailbox-based message queues**: Agents publish/consume messages independently with no central orchestrator (Actor model).
- **Multiple topologies**: One-to-one, group chats, nested sub-conversations, sequential handoffs — all built on async primitives.
- **Checkpoint/restore**: v0.4 added checkpoint-recovery so long-running async conversations can pause and resume.
- **Human-in-the-loop via UserProxyAgent**: Agents defer decisions to a human and resume asynchronously when input arrives.

**Caveat**: Microsoft has deprioritized AutoGen in favor of the broader Microsoft Agent Framework (MAF). For production systems expected to live beyond 2026, LangGraph or CrewAI are safer long-term bets.

### 1.3 Store-and-Retrieve: The "Delayed Sharing" Pattern

Neither AutoGen nor CrewAI natively supports "agent A produces output → stores it → agent B reads it days later." This pattern requires explicit implementation via memory protocols:

**CoDe (Communication Delay-Tolerant Multi-Agent Collaboration)** — The most directly relevant research paper. Agents extract long-term *intent* from delayed messages and fuse them with a dual alignment mechanism (intent alignment + timeliness decay). Supports both fixed and time-varying delays across decision intervals. This is effectively a mathematical model for MarketMind's 7-day isolation window.

**SAMEP (Secure Agent Memory Exchange Protocol)** — Five operations: Store (encrypts + persists with embeddings), Retrieve (validates access + decrypts), Search (vector similarity with access controls), Update, Delete. Allows agents to store findings with access gating and retrieve them later under cryptographic isolation guarantees.

**Mesh Memory Protocol (MMP)** — Cross-session agent-to-agent collaboration using Cognitive Memory Blocks (CMBs) with content-hash lineage tracing. Key principle: "Memory that survives session restarts is relevant because of how it was stored, not how it is retrieved." Agents store judgments during isolation; after the isolation period lifts, they retrieve with lineage verification rather than raw peer signals.

**Markspace (stigmergic coordination)** — Agents leave traces in a shared environment (five mark types: Actions, Observations, Warnings, etc.) with configurable decay. Action marks are permanent; observations decay over time. This maps naturally to MarketMind's isolation: shadows produce marks during the 7-day window, and after the window, marks with surviving relevance (based on decay/threshold) become visible to peers.

### 1.4 Recommended Pattern for MarketMind

The best fit is a **stigmergic store-and-retrieve architecture with timed access control**:

1. Each shadow produces analysis into a private store during the 7-day isolation period.
2. A central access controller enforces time-based gates: before T+7, no cross-read; after T+7, read access opens.
3. Retrieval includes provenance verification (which shadow, which day, which methodology version) so the reader knows the context of whatever they're reading — not just the raw conclusion.
4. A decay function (inspired by CoDe's timeliness alignment) discounts older analyses when newer contradictory evidence emerges.

This avoids both extremes: full isolation forever (loses cross-pollination) and premature sharing (creates groupthink).

---

## Part 2: AI Agent Methodology Versioning

### 2.1 Prompt-as-Config Architecture

Best practice in 2025-2026 is to separate prompt lifecycle from application deployment:

- **Prompts live outside code**: Stored in a registry, config store, or version-controlled YAML/JSON files.
- **Immutable versions**: Every prompt change produces a new version with semantic versioning (major: model/architecture change; minor: significant improvement; patch: bug fix or wording tweak).
- **Independent rollout**: Prompt changes should NOT require application redeployment. This decouples methodology iteration from code release cycles.
- **Environment tagging**: `dev`, `staging`, `production` with a clean promotion path.

### 2.2 Git-Native Prompt Versioning Tools

Several tools have emerged that apply Git-like workflows to prompts specifically:

| Tool | Key Features |
|------|-------------|
| **PIT (Prompt Information Tracker)** | Semantic versioning with Jinja2 variable detection, A/B testing (scipy t-tests), regression testing, security scanning (OWASP LLM Top 10, injection detection, PII scanning), git-style hooks/worktrees/stash/bundles |
| **Intentry** | Open protocol with `.prompt` file format, event-sourced version store, semantic diff engine, TypeScript/Python/Go SDKs |
| **prompt-git-manager** | Git-native with semantic diff (detects variable/constraint/tone changes), risk classification (LOW/MEDIUM/HIGH), CI guardrails for PRs |
| **prompt-vcs** | Single `prompts.yaml` or multi-file storage, lockfile mechanism, A/B testing, output validation (JSON schema, regex, length) |
| **InstructVault** | Git-first: prompts as YAML/JSON in Git, releases are tags/SHAs, CI validates on every commit |

**Recommendation for MarketMind**: Use a prompt-as-config approach with a `methodologies/` directory in the repo. Each shadow's methodology is a versioned YAML file (e.g., `shadow-expert-03/v2.1.0.yaml`). The git history provides the immutable audit trail. A `methodology-registry.yaml` index file maps shadow_id → active version → fallback version.

### 2.3 Quantitative Comparison of Methodology Versions

To compare methodology v1 vs v2 for the same shadow, use a **balanced scorecard** approach deployed as offline A/B tests:

**Metric categories** (adapted from Meta's Llama production framework):

| Metric Type | Example for MarketMind |
|-------------|----------------------|
| **Quality (Goal)** | Signal precision (true positives / total signals), LLM-as-judge analysis coherence score |
| **Business (Goal)** | Decision accuracy rate (shadow's call matches eventual outcome) |
| **Risk (Guardrail)** | Overfitting score, correlation with crowd (anti-groupthink measure) |
| **Efficiency (Guardrail)** | Token cost per analysis, latency per cycle |

**Statistical rigor**: Use power analysis to determine sample size (alpha=0.05, beta=0.80), run over multiple market cycles (minimum 1-2 weeks of daily runs), apply two-proportion Z-tests for binary metrics and t-tests for continuous scores.

**Blind comparison protocol**: When comparing methodology versions, the evaluator agent should NOT know which version is baseline vs candidate. Judge output labeled A/B, then unblind post-evaluation and produce a structured report on *why* one won (instruction-following scores, categorized improvements by priority).

**Golden test set**: Curate 50-200 historical market scenarios with validated "correct" analyses. Every methodology change must pass the golden test set + 5-10 adversarial edge cases before it reaches production.

### 2.4 Continuous Monitoring for Methodology Drift

From the PRISM framework (May 2026): LLM behavioral drift is a first-class reliability concern. Four dominant failure classes to monitor daily:

1. **Tool Call Skip** — Shadow omits a required analysis step
2. **Rule Violation** — Shadow ignores an explicit methodology constraint
3. **Step Reordering** — Shadow performs analysis steps out of sequence
4. **Step Collapsing** — Shadow skips intermediate reasoning to reach a terminal state

Beyond automated metrics, daily re-run of test suites against the production methodology detects regressions within a 24-hour window. Every output must be traceable to the exact methodology version + model + inference settings that produced it.

### 2.5 Preserving Old Versions as Benchmarks

The core requirement — old methodology versions remain active as historical benchmarks — is best served by:

1. **Immutable archives**: Old methodology YAML files remain in the repo forever. Never delete or overwrite.
2. **Benchmark shadow**: After v2 is promoted to production, v1 continues running daily as a "benchmark shadow" with no power to influence decisions. Its output is compared against v2 to track whether the change produced sustained improvement.
3. **Rollback readiness**: Every methodology change must include a documented, one-command rollback path to the previous version. This is critical when a methodology change looks good in backtesting but degrades in live conditions.
4. **Traceability**: Every shadow's daily output links back to the exact methodology version that produced it. This enables post-hoc analysis ("was our Q2 underperformance caused by methodology drift across multiple shadows?").

---

## References

### Multi-agent communication
- CoDe: Communication Delay-Tolerant Multi-Agent Collaboration — arxiv:2501.05207
- SAMEP: Secure Agent Memory Exchange Protocol — arxiv:2507.10562
- Mesh Memory Protocol — arxiv:2604.19540
- Markspace (PyPI) — stigmergic coordination with configurable decay
- Millennium Pod System — confluencegp.com, HBR case IN2113
- BlackRock 2026 Hedge Fund Outlook: Crowding Warning — hedgeco.net

### Methodology versioning
- PIT: Prompt Information Tracker — github.com/itisrmk/pit
- Intentry — github.com/intentry/intentry
- prompt-git-manager — pypi.org/project/prompt-git-manager
- prompt-vcs — pypi.org/project/prompt-vcs
- PRISM: Prompt Reliability via Iterative Simulation and Monitoring — arxiv:2605.15665
- Llama A/B Testing Framework — llama.com/docs/deployment/a-b-testing
- Arize: Prompt Templates as Configs — arize.com/blog (April 2026)
- Dueling Prompts — github.com/tgurgick/dueling-prompts
