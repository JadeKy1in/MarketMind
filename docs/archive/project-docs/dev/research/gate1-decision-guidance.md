# Gate 1 — Direction Selection Decision Guidance

**Purpose**: Research how professional financial advisors and investment platforms guide clients through DIRECTION SELECTION (asset class/sector choice, not stock picking).

**Research date**: 2026-05-17
**Applies to**: MarketMind L1 stage — presenting 3-5 actionable hypotheses after HVR investigation loop
**Mode**: Anti-Socratic (user drives, AI provides ammunition)

---

## Summary of Findings

Three core principles emerge from the research:

1. **Present 3 options maximum** — the "power of three" is a behavioral science constant: too many choices cause paralysis; too few feel pushy.
2. **Lead with goals, not products** — reframe from "which sector?" to "what outcome are you solving for?"
3. **The AI's job is ammunition, not advocacy** — present evidence equally for/against each direction; let the user triangulate.

The sections below synthesize findings across four research questions.

---

## 1. Decision Framing for Asset Allocation

### 1.1 The "Power of Three"

Multiple sources converge on presenting **3 options** as the optimal number for client decision-making.

- **Choice paradox research (Iyengar & Jiang, Columbia)**: When a 401(k) plan offered 2 options, 75% of employees enrolled. Each additional 10 options reduced participation by ~2%. Too many choices produce paralysis. (*StreetDirectory, Investment Executive*)
- **Good-Better-Best framing**: Advisors present three tiers where the middle option is the intended recommendation. The middle option naturally draws selection because it appears to offer a "deal" relative to the premium tier while being defensible relative to the budget tier. (*Financial-Planning.com, Bunnell Idea Group*)
- **Application to MarketMind**: Present your top 3 hypotheses (out of 3-5 generated) as direction choices. If 5 were generated, rank them by confidence and present the top 3; note the other 2 as "also considered" that can be surfaced on request.

### 1.2 Balanced Evidence Presentation

The core anti-bias technique is presenting evidence equally for and against each direction.

**Reframing around goals (Harold Evensky)**:
- Instead of evaluating a direction as "good/bad," reframe around: *"How does this direction advance your financial goals? What alternative directions could also serve those goals?"*
- The key reframe: shift from "gains vs. losses" (anchored to a reference price) to "progress toward objectives."

**CFA Institute Standard V(B)** — the ethical standard requires advisors to:
- Disclose significant limitations and risks associated with the investment process
- Distinguish between fact and opinion in analysis
- Use reasonable judgment in identifying which factors are important and include them in client communications
- Notify clients of changes that materially affect the process

These translate directly to the anti-Socratic L1 presentation: every hypothesis gets equal treatment, every hypothesis includes its own risks/limitations, and the distinction between "what the data shows" (fact) and "what the data implies" (opinion) is explicit.

### 1.3 Pre-Mortem: "What Would Make This Direction Wrong?"

**Definition** (AlphaTheory.com, Annie Duke): *"Create premortems that ask the question: 'It is one year from now and this direction has lost half its value — what happened?'"*

**How it works**:
- Assume the investment direction has already failed
- Work backward to identify what could have triggered the failure
- Document these triggers as "kill criteria" — observable conditions that would invalidate the thesis

**Application**: Each hypothesis card presented to the user should include a pre-mortem section: *"This direction would be wrong if [2-3 specific, observable conditions]."* This provides the ammunition for the user to challenge any direction, which is the core of the anti-Socratic mode.

### 1.4 Devil's Advocate Structure

**Internal practice** (Bill Nygren / Oakmark, Ben Claremon / Cove Street):
- Assign someone (or an AI sub-process) the specific role of arguing against each direction
- Formal process: one party presents the case FOR, another presents the case AGAINST, then decision-makers vote
- Core question: *"What is the strongest reason to do something else? What is the worst-case scenario? Can you live with it?"*

**Application**: The AI should, for each hypothesis, explicitly present the strongest counter-argument. Not as afterthought — as a structured section. This shows the user that the AI is not "selling" any direction, just arming them with the full picture.

### 1.5 Framing Sequence Matters

Chris Gilchrist (Money Marketing) identifies that the **order** in which advisors address risk dimensions creates a framing effect:

| Starting Point | Tends to Produce |
|---|---|
| Risk Required (what return do you need?) | More ambitious allocations |
| Risk Capacity (how much can you afford to lose?) | More cautious allocations |
| Attitude to Risk (how do you feel about risk?) | Can go either way; risk of poor compromise |

**Application**: Present all hypotheses in a consistent structure (confidence, logic chain, pre-mortem, counter-argument, risk/reward profile) so that framing order does not bias toward any single direction. Consider randomizing the display order between sessions.

---

## 2. Structured Conversation Flows

### 2.1 The Three-Meeting Discovery Model (Asset-Map)

The prevailing structured approach to direction selection in wealth management uses a three-meeting model:

| Meeting | Focus | Client Air Time |
|---|---|---|
| **Meeting 1** | Rapport, values, emotional discovery | 80% client |
| **Meeting 2** | Technical financial data gathering | Shared |
| **Meeting 3** | Strategy presentation, direction selection, commitment | Advisor presents, client decides |

**Application**: In the L1 conversation, the AI has completed its equivalent of Meetings 1-2 (HVR investigation). L1 is Meeting 3: strategy presentation with the client driving the selection.

### 2.2 Agenda Setting with Client Autonomy

**Dan Richards (Advisor Perspectives)** recommends leaving the **first agenda item blank** and asking: *"What's happened since we last met that I should know about?"* This creates space for emergent client topics before any prepared material.

**Two-sided agenda** (SmartAsset):
1. Share the prepared agenda in advance so clients can add items
2. At meeting start, confirm collaboratively: *"Here's what I prepared based on our last conversation. Does that still feel right, or is there something new?"*

**Application**: The L1 conversation should open by acknowledging the work done (HVR investigation) and asking the user: *"Before I present what I found, is there a direction or topic you've been thinking about that we should address first?"*

### 2.3 Multi-Criteria Decision Analysis, Conversationally

The GSCP (Godel's Scaffolded Cognitive Prompting) framework for wealth management decomposes direction selection into:
1. **Decomposition** — break the direction decision into criteria (conviction, time horizon, risk capacity, thematic alignment)
2. **Branching** — explore each direction as a decision branch
3. **Meta-cognition** — surface what assumptions each direction depends on
4. **External verification** — cross-reference against independent data

**Application**: Rather than presenting hypotheses as flat cards, present them across consistent evaluation criteria. The user sees not just "direction X scored 0.72," but "direction X rated high on thematic alignment (0.85), medium on time horizon fit (0.60), low on near-term catalyst clarity (0.45)."

### 2.4 The Kitces/Richards Overconfidence Conversation

A three-question framework that helps clients self-discover risk tolerance without the advisor lecturing:

1. *"If you proceed with this direction and it works out as expected, how would your life be different?"* (upside discovery)
2. *"If you made this choice and you were wrong, how would your life be different?"* (downside discovery)
3. *"Have there been things you were really certain about in the past that didn't work out as planned?"* (calibration)

The key insight: clients typically realize the **upside is marginal** while the **downside is significant** — creating natural restraint without the advisor having to be the bearer of bad news.

**Application**: After presenting hypotheses, ask the user these three questions about the directions they are leaning toward. The AI acts as facilitator, not judge.

### 2.5 The "80/10/10" Rule (RFG Advisory)

In discovery meetings: 80% of meeting time = client's life/dreams/fears/vision; 10% = money/numbers; 10% = advisor's input.

**Application in L1**: The AI presents hypotheses concisely (the 10%), then lets the user explore, question, and redirect (the 80%). The AI should resist the urge to "guide" the user toward its highest-confidence hypothesis.

---

## 3. Handling User-Initiated Topics (Graceful Pivot)

### 3.1 The "Parking Lot" Method

A widely documented facilitation technique that applies directly to L1 conversations.

**Mechanism** (Meeteor.com, StarlingBS, Biz417):
- Maintain a visible (in-chat) "Parking Lot" for off-agenda topics the user raises
- Acknowledge and validate: *"That's a great point — let me note it so we don't lose it, and we can come back to it after we work through the prepared hypotheses."*
- Review the parking lot at conversation's end; assign priority; schedule into the next interaction

**Key distinction (Conceptboard)** — use a Parking Lot Matrix (value vs. ease) when the parking lot is large, so the user sees that parked items will be prioritized, not lost.

### 3.2 The Graceful Pivot Language

When the user says "actually, I want to talk about X instead," the advisor's verbal skill determines whether the user feels heard or dismissed.

**Advisorpedia's technique**: *"I know we had prepared material on Y, but X sounds important. Would you like us to focus on X now and reschedule Y, or would it work to address X briefly first?"*

**Advisor Perspectives' advice**: When a life change derails the agenda, sometimes *"that conversation ends up consuming the whole meeting and we reschedule."* The principle: the client's emergent priority takes precedence over the advisor's prepared agenda.

**Investment Executive's proactive pivot**: *"Some clients I've spoken to have told me they've read articles about [topic] that is causing concern. Is this something you'd like to talk about?"*

### 3.3 Anti-Socratic Pivot Framework

Since the "anti-Socratic method" is not a formally named concept but describes a real and growing trend, here is a synthesized framework for handling user-initiated topics in L1:

| Stage | What the AI Does | What the AI Does NOT Do |
|---|---|---|
| **Detect** | Notice the user is steering toward topic X | Interrupt or redirect back to prepared material |
| **Validate** | *"That's an interesting direction. I have some data on X, and I can explore it with you."* | Say "we should stick to the prepared hypotheses" |
| **Offer structure** | *"I can adapt: I'll work through what I know about X using the same framework — conviction, catalysts, risks, counter-arguments. Sound good?"* | Say "I'll recommend direction X because it scores highest" |
| **Maintain record** | Add any skipped hypotheses to a visible "Parked" / "Later" list | Discard the prepared work entirely without acknowledging it |
| **Close the loop** | At conversation end, return to parked items: *"We parked directions A and B earlier. Would you like me to prepare analysis on those for our next session?"* | Assume the user forgot or doesn't care about parked items |

### 3.4 Blank First Agenda Item Pattern

**WealthTender / Grant Hicks "Super 7"**: Includes a blank first item for client-led topics, plus "On Track" check, goals update, checklists, and feedback loops. The blank first item signals that the client's agenda is welcome — and expected.

**Application**: L1 conversation design should include a structured opening prompt that invites the user to set or modify the direction before the AI presents anything.

---

## 4. Risk Communication — Honest But Not Paralyzing

### 4.1 Kahneman's Insight: Clients Think in Terms of Maximum Loss

In an interview with Harold Evensky (*Financial Advisor* magazine), Daniel Kahneman stated:

> *"People mainly think of risk in terms of downside risk. They are concerned about the maximum they can lose. So that's what risk means. In contrast, the professional view defines risk in terms of variance, and doesn't discriminate gains from losses. There is a great deal of miscommunication and misunderstanding because of these very different views of risk."*

**Application**: For each hypothesis, communicate risk in terms the user naturally thinks about — maximum downside, not standard deviation. Standard deviation and Sharpe ratios are supplementary, not primary.

### 4.2 Scott MacKillop's "The Risk Talk" — Honest Without Paralyzing

This is the closest practical articulation of "honest but not paralyzing":

> *"If I tell you there is only a 5% chance your portfolio will decline by more than 10% in a given year, that may sound like a small probability. But what I'm really telling you is that you should expect a decline of at least 10% once every 20 years. And I can't tell you how much more than 10% it will be, or in what year it will happen."*

The talk works because it:
1. States the probability plainly
2. Translates it into a human time scale ("once every 20 years")
3. Acknowledges what is unknown ("I can't tell you how much more or when")

**Application**: For each hypothesis, translate statistical risk metrics into plain-language time scales: *"This direction has a ~65% probability of beating the market over 12 months, which means in roughly 1 out of 3 scenarios, it underperforms."*

### 4.3 Structured Risk Communication Frameworks

Multiple named frameworks exist for risk communication. All share the pattern: **acknowledge the pain honestly, then re-anchor to purpose, data, and controllable actions.**

| Framework | Source | Stages |
|---|---|---|
| **4 Ps** | Brinker Capital / Dr. Daniel Crosby | Purpose → Proof → People → Process |
| **S.A.F.E.** | RFG Advisory / Brendan Frazier | Seek to Understand → Anchor to Their 'Why' → Facts and Figures → Ease Anxiety with Action |
| **4-Box** | Capital Group | Acknowledge → Perspective → Confidence → Opportunity |
| **Risk-Narrative** | Altss | Known Risks → Internal Safeguards → Evidence of Learning → Scenario Plan |

**Application**: Adopt the S.A.F.E. structure for L1 direction presentation:
- **Seek** — first understand what the user cares about (goals, concerns)
- **Anchor** — connect each direction to their stated goals, not abstract metrics
- **Facts** — present data, probabilities, and evidence transparently
- **Ease** — end each hypothesis with actionable next steps: "If you choose this direction, the next step is [specific research/deployment action]"

### 4.4 Graham Bentley's Risk = Likelihood x Impact

Bentley argues risk communication must be honest, unbiased, and present all scenarios:

> *"The process needs to be honest, unbiased and present all possible scenarios — however unpalatable to the adviser's beliefs — to allow clients to make informed decisions and potentially reassess their goals."*

**The key client question**: *"If we get to the point you want to realize your goal and there isn't enough money to pay for it, how would you feel?"*

**Application**: For each hypothesis, quantify both dimensions: likelihood of thesis playing out, and impact if it does (positive) / if it does not (negative). The product of these is the real risk.

### 4.5 Visual Risk Communication Research

Three academic papers provide evidence on how to present risk ranges (not single-point estimates):

| Study | Key Finding |
|---|---|
| Kaufmann & Weber (2015), *SSRN* | Bar charts perform well except for communicating **possibility of losses**. People systematically underestimate risks and overestimate returns. |
| Griesdorn & Smith (2014), *J. Personal Finance* | Visual display of probability info **shifts preferences toward the stock with greatest probability of gain**. Investors take more risk when shown visuals vs. numbers. |
| Kaufmann et al. (2013), *Management Science* | "Risk tool" (experience sampling + graphics) increases risky allocation, lowers perceived risk, yet **improves recall accuracy** of expected return and loss probability. |

**Application**: Use range-based communication (e.g., *"Expected return: 8-15% over 12 months, with a 20% probability of drawdown exceeding -10%"*) rather than single-point forecasts. This is both more accurate and builds more trust. Use probability language (*"65% likelihood"*, *"1 in 3 scenarios"*) rather than certainty language (*"will outperform"*).

### 4.6 Annie Duke & Morgan Housel: Decision Hygiene for Risk Communication

From the CFA Institute Annual Conference, three tools for navigating risk without false certainty:

1. **Make forecasts explicit** — write down beliefs, reasons, and facts. Separate the decision process from the outcome.
2. **Demand the broadest view** — survey the widest range of possible paths. *"Doing well over a long period of time is not about finding the right answer — it's about being able to thrive amid the broadest range of outcomes."* (Housel)
3. **Embrace humility** — *"The more humility you have… the people who do well through any financial crisis tend to be the people who don't do too much and just say, 'Okay, I'm just going to cover my bases.'"* (Housel)

**Application**: Every hypothesis should include an explicit "belief statement" that the AI is making — what it is betting on, what data supports it, and what data would invalidate it. This is Annie Duke's "forecast explicit" rule.

---

## 5. Synthesis: Anti-Socratic Direction Selection Pattern

### 5.1 Template: Hypothesis Card Structure

For each of the 3-5 directions presented in L1, the following structure ensures anti-Socratic presentation (AI provides ammunition, user drives):

```
### Direction: [Name]
**Confidence Score**: [0.0-1.0] (based on [N] independent signal sources)

#### Core Thesis
[2-3 sentence logic chain: IF [condition] THEN [sector] benefits because [mechanism]]

#### Evidence For (3 strongest signals)
1. [Signal] — [Source] — [Recency]
2. [Signal] — [Source] — [Recency]
3. [Signal] — [Source] — [Recency]

#### Evidence Against (strongest counter-argument)
- [Counter-signal or limitation] — [Source]

#### Risk Profile
- **Maximum Upside**: [estimated gain range] over [time horizon]
- **Maximum Downside**: [estimated loss range] over [time horizon]
- **Probability of Positive Outcome**: [X%] (meaning ~[1 in Y] underperformance scenarios)
- **Key Dependency**: [single most important assumption this direction hinges on]

#### Pre-Mortem: This Direction Would Be Wrong If...
1. [Observable condition that would invalidate the thesis]
2. [Observable condition that would invalidate the thesis]

#### Time Sensitivity
- [Catalyst timeline: when does this thesis play out or expire?]
- [Window status: open now / approaching / closed]

#### Next Step If Selected
[Specific research or deployment action the user would take]
```

### 5.2 Conversation Flow

```
OPEN: Invite user's agenda
  "Before I present what my investigation found, is there a direction
   or topic you've been thinking about that we should address first?"

  If user has topic → pivot to §3.4 (parking lot / graceful pivot)
  If user defers → proceed

PRESENT: Hypothesis cards in parallel
  - Present all 3-5 hypotheses with equal structure (see §5.1)
  - Do NOT rank or recommend — present as equal-tier options
  - Use the user's language from earlier context where possible
  - Avoid certainty language ("will" → "suggests", "indicates")

FACILITATE: User explores
  - User can ask for deeper evidence, challenge assumptions, or compare directions
  - AI responds with data, not persuasion
  - If user asks "which do you recommend?" → "Here is the evidence for each.
    The one that aligns with your goals depends on [criteria]. What matters
    most to you right now?"

CLOSE: Confirm direction + park the rest
  - User selects direction (or combination, or "none, let's explore X instead")
  - Selected direction → transition to L2 (implementation planning)
  - Unselected directions → move to "Parked" list, available for future sessions
  - If user pivoted to emergent topic → park all original directions, work the
    new topic, and offer to return to original set at next session
```

### 5.3 Key Anti-Socratic Rules

| DO (Anti-Socratic) | DON'T (Socratic / Leading) |
|---|---|
| Present evidence equally for/against each direction | Ask leading questions that steer toward the AI's preferred direction |
| Use probability language ("65% likelihood") | Use certainty language ("will outperform") |
| Let the user ask follow-up questions first | Ask the user "have you considered that X might be better?" |
| Distinguish fact from opinion explicitly | Blend data with interpretation without labeling which is which |
| Include pre-mortem/contra evidence for EVERY direction | Only mention risks for directions the AI considers weaker |
| Accept user pivot gracefully — park, don't resist | Say "we should focus on the prepared material first" |
| Offer criteria for comparison; let user weigh them | Assign composite scores that hide the user's value judgments |
| Use range-based forecasts | Use single-point predictions |

---

## 6. Source Index

### Decision Framing
- [Iyengar & Jiang — Choice Paradox research, cited via StreetDirectory](https://origin.streetdirectory.com/etoday/-wacljl.html)
- [Bunnell Idea Group — Three Options Technique](https://bunnellideagroup.com/the-secret-to-getting-clients-that-arent-sure-exactly-what-they-want/)
- [Chris Gilchrist — All Roads Lead to Different Risk Outcomes, Money Marketing](https://www.moneymarketing.co.uk/advisers/chris-gilchrist-all-roads-lead-to-different-risk-outcomes/)
- [CFA Institute — Standard V(B): Communication with Clients](https://www.cfainstitute.org/standards/professionals/code-ethics-standards/standards-of-practice-v-b)
- [Harold Evensky — Artful Framing, Financial Advisor Magazine](https://www.fa-mag.com/news/artful-framing-31061.html)

### Pre-Mortem & Devil's Advocate
- [AlphaTheory.com — Best Practices Part Two (Pre-Mortem)](https://www.alphatheory.com/blog/alpha-theory-best-practices-part-two)
- [Morningstar — The Value of Playing Devil's Advocate in Investing](https://www.morningstar.com/financial-advisors/value-playing-devils-advocate-investing)
- [AcquirersMultiple — Bill Nygren Stock Selection Devil's Advocate Reviews](https://acquirersmultiple.com/2022/03/bill-nygren-stock-selection-devils-advocate-reviews/)
- [Unicorn Consultants — Who is Your Devil's Advocate?](https://unicornconsultants.com.au/who-is-your-devils-advocate/)

### Conversation Frameworks
- [Advisor Perspectives — Asset-Map in the Client-Discovery Process](https://www.advisorperspectives.com/articles/2021/04/06/using-asset-map-in-the-client-discovery-process)
- [RFG Advisory — 4 Pillars of a High-Impact Discovery Meeting](https://rfgadvisory.com/blog/4-pillars-of-the-ultimate-discovery-meeting/)
- [Cannon Financial Institute — Priorities Discovery Program](https://www.cannonfinancial.com/enterprise-programs/priorities-discovery)
- [InvestmentNews — How Advisors Can Turn First Meetings into Lasting Clients](https://www.investmentnews.com/goria/practice-management/how-advisors-can-turn-first-meetings-into-lasting-clients/261715)
- [Kitces.com — Iceberg Follow-Up Model: Fact → Situation → Feeling](https://www.kitces.com/blog/iceberg-follow-up-model-discovery-questions-prospect-financial-advisor-client/)
- [AIM Framework — The UHNW Institute](https://www.uhnwinstitute.org/aim-framework/)

### Emergent Topic Handling
- [Meeteor — Is Your Meeting Off-Track? Try the Backburner (Parking Lot)](https://www.meeteor.com/post/meeting-backburner-parking-lot)
- [Conceptboard — Parking Lot Matrix Template](https://conceptboard.com/blog/parking-lot-matrix-template/)
- [Advisor Perspectives (Richards) — The Best Way to Start a Client Meeting](https://approd.advisorperspectives.com/articles/2011/06/07/the-best-way-to-start-a-client-meeting)
- [Advisorpedia — How to Turn a Coffee Chat Into a Client](https://www.advisorpedia.com/growth/how-to-turn-a-coffee-chat-into-a-client-without-sounding-salesy/)
- [WealthTender — The Super 7 Client Agenda Checklist](https://wealthtender.com/advisors/practice-management/client-agenda-checklist/)

### Risk Communication
- [FA Magazine — Clients Misbehavin' (Kahneman interview on maximum loss)](https://www.fa-mag.com/news/article-908.html?print)
- [Financial Advisor IQ — When Clients Freak Out, Give Them the "Risk Talk" (MacKillop)](https://financialadvisoriq.com/c/608324/68594/when_clients_freak_give_them_risk_talk)
- [Money Marketing — Graham Bentley: Why Risk Conversations Need Overhauling](https://www.moneymarketing.co.uk/opinion/graham-bentley-why-risk-conversations-need-to-be-overhauled/)
- [AdvisorHub — Kitces & Carl: The Overconfident Conversation](https://www.advisorhub.com/resources/the-overconfident-conversation-and-walking-clients-back-from-the-greed-ledge-kitces-and-carl/)
- [Envestnet — 4 Ps System for Talking Clients Through Market Volatility (Crosby)](https://www.envestnet.com/financial-intel/four-step-system-talking-clients-through-market-volatility-guest-post-dr-daniel)
- [RFG Advisory — S.A.F.E. Framework (Frazier)](https://rfgadvisory.com/blog/safe-framework-brendan-frazier/)
- [Capital Group — How to Have Better Client Conversations](https://www.capitalgroup.com/advisor/practicelab/articles/have-better-client-conversations.html)
- [Altss — The Risk-Narrative Communication Framework](https://altss.com/knowledge-center/frameworks/the-risk-narrative-communication-framework)
- [ThinkAdvisor — The Word That Scares Away Your Clients (Scott West/Invesco)](https://www.thinkadvisor.com/2012/07/26/the-word-that-scares-away-your-clients)

### Decision Science
- [CFA Institute — Annie Duke and Morgan Housel: Three Tools for Navigating Risk and Uncertainty](https://rpc.cfainstitute.org/blogs/enterprising-investor/2020/annie-duke-and-morgan-housel-three-tools-for-navigating-risk-and-uncertainty)
- [Schroders — Probability and Decision-Making with Annie Duke](https://www.schroders.com/en-gb/uk/intermediary/insights/probability-a-decision-making-with-annie-duke/)
- [Schroders — Base Rates and Countering 'Tilt' with Annie Duke](https://www.schroders.com/en-gb/uk/intermediary/insights/base-rates-and-countering-tilt-with-annie-duke/)
- [a16z — How to Decide, Convey vs. Convince (Duke)](https://a16z.com/podcast/a16z-podcast-how-to-decide-convey-vs-convince-more/)

### Academic Research
- [Kaufmann & Weber (2015), SSRN — Framing Effects and Risk Perception: Testing Graphical Representations of Risk](https://papers.nonprod.ssrn.com/sol3/papers.cfm?abstract_id=2606615)
- [Griesdorn & Smith (2014), J. Personal Finance — Does Visually Displaying Probability Outcomes Change Stock Selection?](https://scholar.google.ch/citations?user=OqV6obAAAAAJ&hl=en&view_op=view_citation)
- [Kaufmann et al. (2013), Management Science — Experience Sampling and Graphical Displays on Investment Risk Appetite](https://dl.acm.org/doi/10.1287/mnsc.1120.1607)

### Platforms & UI
- [Hexaware — Boosting Asset and Wealth Management with Robo Advisors](https://hexaware.com/case-study/powering-asset-management-wealth-management-with-robo-financial-advisors/)
- [Dribbble — Case Study on EasyVest (SoluteLabs Design)](https://dribbble.com/shots/21629255-Case-Study-on-EasyVest)
- [INSART — Next-Gen Robo-Advisor Architecture](https://insart.com/next-gen-robo-advisor-architecture-for-startups/)
- [Passiv.com — Modern Portfolio Theory: How to Balance Expected Returns Against Risk](https://passiv.com/blog/modern-portfolio-theory/)

---

**Document Status**: COMPLETE
**Research completed**: 2026-05-17
**Next Step**: Convert research into L1 conversation flow design in MarketMind's layer1 module
