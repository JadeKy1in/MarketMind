# Red Team Audit: Gate 1 Interaction Design — Logic / Investment Methodology

**Date**: 2026-05-18
**Auditor**: Red Team (Logic / Investment Methodology)
**Plan audited**: `docs/superpowers/plans/2026-05-18-gate1-interaction-design.md`
**Research sources**: `gate1-decision-guidance.md`, `gate1-anti-socratic-design.md`
**Focus**: Anchoring, pre-mortem, confidence communication, cognitive load, new-direction handling, 80/10/10 realism, Scout Monitor priming

---

## Executive Summary

**Verdict: NOT READY** — 3 CRITICAL, 3 HIGH, 4 MEDIUM findings. The plan's centerpiece mechanism (equal-weight cards) contradicts its own stated goal of preventing anchoring because confidence scores create an implicit ranking. Confidence communication as raw decimals (0.81) directly violates the plan's own research base. Cognitive load with 5 full cards exceeds established behavioral boundaries. The plan also drops key research findings: no user-agenda-first opening, no kill-criteria specificity for pre-mortems, and no decomposition of confidence scores. Does not meet the standard for Gate 1 — the first human touchpoint in an investment pipeline must be psychologically sound, not just structurally complete.

---

## 1. Hypothesis Card Anchoring — Equal Weight Is a Facade

**Severity: CRITICAL**

### 1.1 The Confidence Score Contradiction

The plan states: "AI 不做推荐排序" (AI does no recommendation sorting) and "每个假设用**等权重卡片**展示" (each hypothesis displayed as equal-weight card).

But the example card shows `置信度 0.81` prominently at the top. When users see:

| Card | Confidence |
|------|:---:|
| EUR 看涨 | **0.81** |
| TLT 看跌 | 0.73 |
| 大豆多头 | 0.68 |
| VIX 多头 | 0.55 |
| Gold 空头 | 0.42 |

No explicit "recommended" label is needed. The confidence score IS the recommendation. Research §4.5 (Griesdorn & Smith, 2014) explicitly warns: *"Visual display of probability info shifts preferences toward the stock with greatest probability of gain."* The scores create a de facto ranking that the user cannot un-see.

### 1.2 Serial Position Effect Is Unaddressed

Even with identical formatting, the first card in a list receives primacy. The research §1.5 recommends: *"Consider randomizing the display order between sessions."* The plan does not adopt this. No randomization, no counter-balancing, no acknowledgment that position itself is a framing variable.

### 1.3 The Power-of-Three Principle Is Violated

The research §1.1 states: *"Present 3 options maximum"* — too many choices cause paralysis (Iyengar & Jiang, Columbia). The plan says "(每个假设一张卡片，最多5张)" (up to 5). The research specifically recommends: *"Present your top 3 hypotheses (out of 3-5 generated) as direction choices. If 5 were generated, rank them by confidence and present the top 3; note the other 2 as 'also considered' that can be surfaced on request."* The plan ignores this and presents all 5.

**Recommendation**: Present 3 cards max (adopt power-of-three). Replace the single confidence number with a multi-criteria breakdown (GSCP framework §2.3): conviction, time-horizon fit, thematic alignment, catalyst clarity. This prevents any single number from dominating. Randomize display order between sessions. Move the monolithic confidence score to a secondary detail view, surfaced on user request.

---

## 2. Pre-Mortem Quality — Shallow Checkbox

**Severity: HIGH**

### 2.1 One Vague Condition vs. Required Kill Criteria

The plan's example pre-mortem:
```
⚠️ 如果这个方向错了:
   ECB 下次会议明确鸽派 → EUR 可能继续走弱
```

Annie Duke's pre-mortem methodology (research §1.3) requires: *"It is one year from now and this direction has lost half its value — what happened?"* and *"Document these triggers as kill criteria — observable conditions that would invalidate the thesis."*

The plan's example fails on three dimensions:

| Dimension | Research Requires | Plan Delivers |
|---|---|---|
| **Specificity** | Observable, falsifiable trigger | "ECB明确鸽派" — what specific language constitutes "明确鸽派"? |
| **Time-bounded** | "If X happens by Y date" | No time constraint on the trigger |
| **Multi-factor** | 2-3 independent kill conditions | Only 1 condition provided |

A proper pre-mortem for the EUR bull case should look like:
```
1. ECB drops "vigilance" language in next policy statement (June 12) → kill thesis
2. German CPI prints below 2.2% YoY in June release (June 28) → reduce position 50%
3. EUR/USD breaks below 1.05 support on weekly close → exit entirely
```

### 2.2 HVR Does Not Guarantee Kill-Criteria Quality

The plan treats the pre-mortem as an output of the HVR investigation loop. But HVR generates hypotheses — it does not necessarily generate SPECIFIC kill criteria. The plan has no check that the pre-mortem is concrete and falsifiable. An LLM-generated pre-mortem can easily produce vague language ("the trend reverses," "sentiment shifts") that sounds right but is useless for actual decision-making.

### 2.3 No Kill-Criteria Revisit Mechanism

The pre-mortem is presented once at Gate 1 and never revisited. But kill criteria require monitoring — the user needs to be alerted WHEN a trigger condition is met, not just know what it is. The plan has no connection between the pre-mortem triggers and the downstream monitoring system (Stage 4-8).

**Recommendation**: The HVR output must include structured, observable kill criteria (not free-text "if this direction is wrong"). Each criterion needs: a specific observable (data point, event, price level), a time boundary, and a consequence (kill / reduce / review). Gate 1 must surface these and allow the user to edit or add their own. A downstream monitor must track kill-criteria status and alert the user.

---

## 3. Confidence Communication — Raw Decimals Are Known-Harmful

**Severity: CRITICAL**

### 3.1 Research Explicitly Warns Against This

The plan's own research base contains multiple warnings that the plan then ignores:

| Research Source | Warning | Plan Behavior |
|---|---|---|
| Kaufmann & Weber (2015), SSRN | "Bar charts perform well except for communicating possibility of losses. People systematically underestimate risks and overestimate returns." | Shows 0.81 as a raw decimal |
| Griesdorn & Smith (2014), J. Personal Finance | "Visual display of probability info shifts preferences toward stock with greatest probability of gain." | Shows confidence score as the most visually prominent number on the card |
| MacKillop, "The Risk Talk" (§4.2) | "5% chance... translates to once every 20 years. And I can't tell you how much more than 10% it will be, or in what year it will happen." | No frequency translation, no range framing, no uncertainty acknowledgment |

### 3.2 0.81 Means Nothing — Human Probability Illiteracy

Behavioral research consistently shows:
- A 0.81 confidence score is interpreted as "this will almost certainly happen" by most users
- A 0.65 confidence score is interpreted as "this might not happen" — but the difference between 0.81 and 0.65 is only 16 percentage points
- Users treat confidence scores as prediction accuracy, not as model calibration

The Card example compounds this:
- Bull case confidence: **0.81**
- Bear case confidence: **0.45** (埋在文本中, not in the header)

The user sees 0.81 front and center. The bear case 0.45 is buried in paragraph text. Asymmetric visual weight = asymmetric psychological weight.

### 3.3 What Should Replace Raw Decimals

The research (§4.2, §4.5) recommends range-based communication with frequency framing:

Instead of `置信度 0.81`, the card should show:
```
方向强度: 强 | 正向概率: ~4 in 5 | 预期 20% 情景中跑输大盘
最可能区间: EUR/USD 1.08-1.14 (12个月) | 极端下行: ~10% 概率下探 1.02
```

**Recommendation**: Remove raw decimal confidence from the card header. Replace with: (a) a categorical strength label (弱/中/强); (b) frequency framing ("~4 in 5 scenarios"); (c) a range forecast with max upside and max downside in percentage terms with probabilities. The raw model confidence (0.81) belongs in the audit trail, not the user-facing display.

---

## 4. Cognitive Load — 75-100 Information Items on First Screen

**Severity: CRITICAL**

### 4.1 Information Density Per Card

Each card contains approximately 15-20 discrete information items:

| Section | Items |
|---|---|
| Title + confidence | 4 (name, direction, confidence number, confidence label) |
| Core logic | 3-4 facts |
| Layer 1 evidence | 1 |
| Layer 2 evidence | 1 |
| Layer 3 evidence | 1 |
| Layer 4 evidence | 1 |
| Bear case evidence | 1-2 + confidence |
| Pre-mortem | 1 condition |
| Risk + time window | 2 |

With 5 cards = **75-100 items** on the first screen. Miller's Law (7±2 chunks of working memory) suggests a user can hold approximately 5-9 items in working memory at once. The first screen alone exceeds this by 10x.

### 4.2 Choice Overload and Participation Paralysis

The research §1.1 cites: "When a 401(k) plan offered 2 options, 75% of employees enrolled. Each additional 10 options reduced participation by ~2%." The plan's "up to 5" cards pushes toward the overload zone.

Counter-argument: The plan offers three modes, and快速模式 (fast mode) mitigates this. But:
- 完整模式 is the default described in the main flow
- There is no progressive disclosure within完整模式 — all information is presented upfront

### 4.3 The Progressive Disclosure Pattern Is Available But Unused

The research (§3.1) provides a 3-layer progressive disclosure model (Snapshot → Core Analysis → Deep Dive) with a 60-80% token reduction. The plan shows Layer 2 (Core Analysis) as the default for all cards. Users should see:
- **Layer 1 (always visible)**: Direction name + categorical strength + one-line thesis + max risk
- **Layer 2 (one click)**: Full evidence for/against + pre-mortem
- **Layer 3 (explicit request)**: Source-level detail, historical analogues, correlation matrix

The plan collapses all three layers into a single card.

**Recommendation**: Cap cards at 3. Adopt the 3-layer progressive disclosure model from the research. The Gate 1 presentation should start at Layer 1 for all cards, with clear affordances to drill into Layer 2/3. The user controls the depth, not the AI.

---

## 5. New Direction Handling — No Scope Containment, No Verification Standard

**Severity: HIGH**

### 5.1 Missing T0-T3 Criteria

The plan references "复杂度分诊 T0-T3" but never defines it. What determines T0 vs. T1 vs. T2 vs. T3? Without explicit criteria, the AI's time estimate ("~2分钟" vs. "~5分钟") is arbitrary.

The gate1-time-estimation.md research is cited but its content is not incorporated. Key missing elements:
- What data sources are checked for each tier?
- Minimum evidence bar per tier (how many independent sources?)
- Time calibration (how are estimates validated?)

### 5.2 No Scope Disambiguation Before Analysis

When a user says "大豆" (soybeans), the possible interpretations are:
- Soybean futures (CBOT ZS)
- Soybean ETFs (SOYB, WEAT)
- Agricultural commodities broadly (DBA, RJA)
- US-China trade impact on soybeans
- Weather-driven supply analysis
- A specific stock a friend recommended

The plan's response immediately commits resources:
```
"大豆是个我还没分析的方向。给我 ~2分钟查数据和验证。"
```

This commits to AN analysis before asking WHAT analysis. A proper anti-Socratic response (per research §3.3, the "Detect → Validate → Offer Structure" pattern) should first scope:
```
"大豆可以指期货、ETF、或农业板块。你关注的是哪个层面？是朋友推荐的具体标的，还是对大豆价格的看法？"
```

### 5.3 No Minimum Verification Standard for New Directions

The 4-layer evidence framework (Layer 1-4 shown on the card) is applied to HVR-generated hypotheses. But when a user-initiated direction is analyzed in "~2分钟", is the same framework applied? If not, the new direction receives unequal treatment. The user may unknowingly make a decision on a shallow analysis while the HVR-generated cards received deep verification.

### 5.4 Parking Lot Is Named but Not Implemented

The research devotes an entire section (§3.1) to the Parking Lot mechanism — a visible, in-chat list of deferred topics. The plan says "Parking Lot 模式" in the pivot section but:
- No visible parking lot in the conversation flow
- No mechanism to display parked items to the user
- No closing loop ("We parked X earlier — want to revisit?")
- The existing HVR hypotheses are "orphaned" when user pivots — the plan says to offer the user a choice, but doesn't show what happens to the EUR/TLT analysis if the user commits to soybeans

**Recommendation**: Define T0-T3 explicitly with concrete criteria (data sources checked, minimum evidence bar, time bounds). Add a scope-disambiguation step before any new-direction analysis begins. Apply the 4-layer framework to user-initiated directions within the time constraint. Implement a visible parking lot that persists throughout the session and is reviewed at Gate 1 close.

---

## 6. 80/10/10 Rule — Misapplied and Unmeasurable

**Severity: MEDIUM**

### 6.1 The Ratio Belongs to the Discovery Meeting, Not Strategy Presentation

The research §2.1 (Asset-Map Three-Meeting Model) is explicit:

| Meeting | Focus | Client Air Time |
|---|---|---|
| Meeting 1 | Rapport, values, emotional discovery | 80% client |
| Meeting 2 | Technical financial data gathering | Shared |
| **Meeting 3** | **Strategy presentation, direction selection, commitment** | **Advisor presents, client decides** |

Gate 1 is Meeting 3 — strategy presentation. The 80/10/10 ratio applies to Meeting 1 (discovery), not Meeting 3 (presentation). The plan applies the discovery ratio to the presentation stage, which is a category error.

### 6.2 The Card Format Inverts the Ratio

If the AI presents 5 cards at 15-20 lines each = 75-100 lines of AI output, then the user types 2-5 lines in response, the actual ratio is closer to 90% AI / 10% user — the precise inverse of the stated goal.

### 6.3 No Measurement Mechanism

Even if 80/10/10 were the correct goal, the plan provides no operationalization:
- Token count? Turn count? Time elapsed? Words typed?
- How is the boundary between "data" (10%) and "AI input" (10%) determined when the AI is the one presenting data?
- Is the card presentation counted as "data" or "AI input"?

### 6.4 The Right Metric Is Engagement Depth, Not Air-Time Ratio

The anti-Socratic design principle is "user drives" — but that's measured by decision agency (who makes the choice, who frames the question), not by talk-time ratio. A user who spends 2 minutes reading a dense hypothesis card and then asks one sharp, well-informed question has been well-served by the AI's concise presentation — even though the time ratio was lopsided.

**Recommendation**: Drop the 80/10/10 metric from Gate 1. Replace with anti-Socratic engagement metrics: (a) number of user-initiated questions vs. AI-initiated questions; (b) number of hypotheses the user challenges or modifies; (c) whether the final direction choice matches or differs from the highest-confidence AI card. The goal is user agency, not air time.

---

## 7. Scout Monitor Placement — Bipolar Psychological Priming

**Severity: MEDIUM**

### 7.1 Priming Effect Depends on System State

The Scout Monitor is presented FIRST, before any hypothesis cards:

| System State | Priming Effect | Risk |
|---|---|---|
| 🟢 All green ("全部正常") | Complacency — "systems are fine, so the AI's analysis must be solid" | REDUCED user scrutiny of hypotheses |
| 🟡 Degradation ("有降级") | Uncertainty — "some sources are degraded, is this analysis complete?" | Appropriate skepticism, but no guidance on which hypotheses are affected |
| 🔴 PRIMARY offline | Anxiety — "a key source is down, can I trust ANY of this?" | PARALYSIS — user may defer all decisions |

The plan acknowledges none of these priming pathways.

### 7.2 Color Coding Is a Known Amplifier

Color-coded status badges (🟢🟡🔴) are documented priming mechanisms. Research on traffic-light labeling shows that green labels increase perceived safety and reduce scrutiny, while red labels trigger avoidance. Presenting a green badge before investment hypotheses may inadvertently signal "these hypotheses are safe" before the user has evaluated them.

### 7.3 The Research Recommends a User-Agenda-First Opening

The research §2.2 explicitly recommends: *"The L1 conversation should open by acknowledging the work done and asking the user: 'Before I present what I found, is there a direction or topic you've been thinking about that we should address first?'"*

And §3.4 (blank-first-agenda-item pattern): *"L1 conversation design should include a structured opening prompt that invites the user to set or modify the direction before the AI presents anything."*

The plan drops this opening entirely. Step 1 is the Scout Monitor, not the user's agenda.

### 7.4 Source Health Should Inform, Not Prime

The correct placement is AFTER the user has expressed their own direction or confirmed they want to see the AI's analysis. Source health is metadata about the analysis pipeline, not the lead story. The user should form their investment thesis first, THEN understand the information reliability behind the AI's supporting evidence.

### 7.5 Missing: Hypothesis-Level Source Reliability

When a PRIMARY source is offline, specific hypotheses that depend on that source should be flagged. If BLS is down, the EUR hypothesis (which uses CPI data) should carry a caveat. The plan treats source health as a global status, not as a per-hypothesis reliability signal.

**Recommendation**: Move the Scout Monitor to AFTER hypothesis presentation (before the guiding questions). Open with the user-agenda invitation. Add per-hypothesis source-reliability annotations: each card's evidence section should show which sources are live/healthy vs. degraded/missing. A global "N of M sources healthy" badge should not be the first thing the user sees.

---

## 8. Additional Findings

### 8.1 Guiding Questions Are Closed, Not Open (MEDIUM)

The plan's "引导问题":
```
A) 先看哪个方向的完整逻辑链？
B) 对比两个方向的反对意见？
C) 或者你有完全不同的方向想讨论？
```

The research Rule #1: *"Ask open, don't lead — Replace Did/Is/Do with How/What/Tell me."* The plan provides three closed multiple-choice options. Options A and B assume the user wants to engage with the AI's prepared framework. Only option C acknowledges the user might have their own agenda — and it's listed last.

An anti-Socratic alternative:
```
"这些是我分析出的方向。你的第一反应是什么？有没有哪个方向你特别想深入，或者你想讨论完全不同的东西？"
```

### 8.2 Risk Communication Is Categorical, Not Probabilistic (HIGH)

The card's risk display: `风险: 中等 | 时间窗口: 2-4周`

The research §4.1 (Kahneman) states: *"People mainly think of risk in terms of downside risk. They are concerned about the maximum they can lose."* The plan shows a categorical label ("中等") that conveys no concrete information about maximum downside. What does中等 mean? A 5% drawdown? A 20% drawdown? The user has no anchor.

Research §4.5 recommends range-based communication: *"Expected return: 8-15% over 12 months, with a 20% probability of drawdown exceeding -10%."* The plan must replace categorical labels with quantifiable ranges.

### 8.3 Confidence Score Has No Decomposition (MEDIUM)

The card shows `置信度 0.81` as a monolithic number. The research §2.3 (GSCP framework) recommends decomposing into criteria: *"direction X rated high on thematic alignment (0.85), medium on time horizon fit (0.60), low on near-term catalyst clarity (0.45)."*

A single number hides the trade-offs. A direction might score 0.81 because of strong thematic alignment but have low catalyst clarity — the user should see this decomposition to make an informed choice. The monolithic score obscures more than it reveals.

### 8.4 No Adaptive Depth Mechanism (LOW)

The plan shows the same card format regardless of user expertise (Day 1 vs. Day 30). The research §3.2-3.3 provides a 3-tier adaptation model (Beginner → Intermediate → Experienced) with different AI posture for each. The plan's three modes (完整/快速/追赶) are based on user TIME availability, not user EXPERTISE. An experienced investor in快速模式 still gets the same shallow presentation as a beginner in快速模式 — the information depth adapts to time, not to user capability.

---

## 9. Summary Table

| # | Severity | Category | Issue |
|---|:---:|---|---|
| 1 | **CRITICAL** | Anchoring | Confidence scores create implicit ranking; equal-weight card format is fake |
| 2 | **CRITICAL** | Confidence | Raw decimal scores (0.81) contradict research warnings; no frequency translation, no range framing |
| 3 | **CRITICAL** | Cognitive Load | 5 cards × 15-20 items = 75-100 items on first screen; violates choice paradox and working memory limits |
| 4 | HIGH | Pre-Mortem | Single vague trigger condition fails kill-criteria standard; no specificity, no time-bound, no monitoring hook |
| 5 | HIGH | New Direction | No T0-T3 criteria defined; no scope disambiguation before analysis; no minimum verification standard for user-initiated topics |
| 6 | HIGH | Risk Communication | Categorical risk label ("中等") instead of quantifiable maximum downside; contradicts Kahneman's findings |
| 7 | MEDIUM | 80/10/10 Rule | Misapplied from discovery meeting to strategy presentation; no measurement mechanism; card format inverts the ratio |
| 8 | MEDIUM | Scout Monitor | Placed first, creating bipolar priming (complacency/paralysis); contradicts research recommendation for user-agenda-first opening |
| 9 | MEDIUM | Guiding Questions | Closed multiple-choice questions (A/B/C) violate anti-Socratic "ask open, don't lead" rule |
| 10 | MEDIUM | Confidence Decomposition | Monolithic 0.81 hides multi-criteria trade-offs that research explicitly recommends surfacing |
| 11 | LOW | Adaptive Depth | Three modes based on time (完整/快速/追赶), not expertise; no user profiling mechanism |

---

## 10. Research-to-Plan Gap Analysis

The following research findings are prominent in the research documents but absent from the plan:

| Research Finding | Location in Research | Status in Plan |
|---|---|---|
| "Power of three" — present exactly 3, not 5 | §1.1 | **Dropped** — plan says "最多5张" |
| Randomize card display order between sessions | §1.5 | **Dropped** — no randomization specified |
| User-agenda-first opening | §2.2, §3.4 | **Dropped** — plan opens with Scout Monitor |
| Progressive disclosure (3-layer model) | §3.1 | **Dropped** — all layers shown at once |
| Frequency framing for probabilities | §4.2 | **Dropped** — raw decimals used |
| Range-based forecasts | §4.5 | **Dropped** — single-point confidence |
| Multi-criteria decomposition (GSCP) | §2.3 | **Dropped** — monolithic confidence score |
| S.A.F.E. risk communication framework | §4.3 | **Dropped** — categorical label used |
| Visible parking lot | §3.1 | **Dropped** — named but not implemented |
| Adaptive expertise (Beginner/Intermediate/Experienced) | §3.3 | **Dropped** — only time-based modes |
| "Yes, and" tangent handling (SPOLIN benchmark) | §4.3 | **Dropped** — pivot language is deferral, not extension |

---

## 11. PICA Compliance

| Level | Status | Notes |
|-------|:---:|------|
| PICA-Unit | N/A | This is a design audit, not a code audit. PICA-Unit applies after implementation. |
| PICA-Security | N/A | Security audit is a separate Red Team review. |
| PICA-Integration | N/A | Integration audit applies to module boundaries post-implementation. |
| **PICA-Methodology** | **FAIL** | This audit IS the methodology gate. The plan does not pass. |

---

## 12. Path to Approval

The plan requires revision addressing all CRITICAL and HIGH findings before implementation begins. Specifically:

1. **Redesign the hypothesis card format** (CRITICAL 1, 2, 3):
   - Cap at 3 cards
   - Replace monolithic confidence with multi-criteria decomposition
   - Use frequency framing and range forecasts, not raw decimals
   - Adopt 3-layer progressive disclosure (snapshot default, full evidence on click)

2. **Strengthen pre-mortem requirements** (HIGH 4):
   - Require 2-3 observable, time-bounded, falsifiable kill criteria per hypothesis
   - Add downstream monitoring hook for kill-criteria tracking

3. **Define new-direction handling** (HIGH 5):
   - Define T0-T3 triage criteria explicitly
   - Add scope-disambiguation step before analysis begins
   - Set minimum verification bar (must apply 4-layer framework even within time constraints)

4. **Quantify risk communication** (HIGH 6):
   - Replace categorical labels with percentage ranges for max upside/max downside
   - Include probability of each scenario

5. **Restructure conversation flow** (MEDIUM 7, 8, 9):
   - Open with user-agenda invitation, not Scout Monitor
   - Move Scout Monitor to after hypothesis presentation
   - Replace closed A/B/C questions with open-ended prompts
   - Add per-hypothesis source-reliability annotations

6. **Remove 80/10/10 metric** (MEDIUM 7):
   - Replace with decision-agency metrics (user-initiated questions, hypothesis challenges, choice divergence from highest-AI-confidence)

7. **Add adaptive depth** (LOW 11):
   - Profile user expertise passively; adapt card depth accordingly

---

**Next Step**: Plan author revises based on these findings. Revised plan requires a follow-up Red Team review before Step 1 (implementation) begins.
