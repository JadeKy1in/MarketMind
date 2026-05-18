# Gate 2/3 Plan Re-Review — Post-Fix Verification

**Date**: 2026-05-18
**Review type**: Targeted fix verification (3 CRITICALs from logic audit)
**Plan reviewed**: `E:\AI_Studio_Workspace\.claude\plans\gate23-architecture.md` (v2 — Red Team logic + security audit fixes applied)

---

## Q2 (CRITICAL): Zero debiasing mechanisms — AI anchors user

**VERDICT: VERIFIED_FIXED**

The plan now implements 4 distinct debiasing mechanisms (lines 24-29):

1. **Conviction-before-evidence** (line 26): User states independent conviction BEFORE seeing any AI analysis output. Step 2.1 (lines 33-46) is explicitly titled "Independent Conviction (BEFORE Evidence)" and opens with the prompt `在展示分析结果前，你对这个方向的信心是几成？`. The response is recorded as `unaided_conviction` — "the user's belief uncontaminated by AI output" (line 39).

2. **Explicit overconfidence warning** (line 27): A calibration notice displayed before evidence, warning that AI models systematically overestimate confidence by ~15% in the 0.75-0.85 range (lines 53-58).

3. **Randomized evidence ordering** (line 28): Supporting and opposing evidence within each layer are shuffled — not all bullish first. Prevents primacy/recency ordering effects.

4. **Devil's advocate** (line 29): Step 2.8 (lines 148-162) requires the AI to construct the strongest possible counter-argument. User is then asked whether they want to adjust their initial conviction.

The core fix — asking for conviction BEFORE evidence — is structurally enforced by the step ordering: 2.1 (conviction) precedes 2.2 (evidence summary).

---

## Q4 (CRITICAL): Fragility scanner can't produce instrument price zones

**VERDICT: VERIFIED_FIXED**

Step 3.3 (lines 356-386) explicitly states: "The system validates the stop-loss using technical-level criteria (NOT fragility scanner — fragility_scanner.py monitors macro thresholds like bank_reserves and 10Y yield, which do not produce instrument-level price zones)."

The three ATR-based validation criteria replace any fragility-driven checks:

| Criterion | Mechanism | Line |
|-----------|-----------|------|
| Not too tight | Stop distance > ATR(20) x 2 from current price | 363-366 |
| Not too loose | (Entry - Stop) x PositionSize <= RiskBudget | 368-369 |
| Meaningful level | Stop at identified S/R level (L3 technical), reject arbitrary round numbers | 371-375 |

The pre-trade checklist (lines 409-411) mirrors these same three ATR-based checks. The fragility report appears only in the Gate 2 evidence summary table (line 68) as display-only ("Overall fragility score, crossed thresholds, staleness warnings") — it has no role in stop-loss validation.

---

## Q-A (CRITICAL): Conviction score double-counted with win_probability in Kelly

**VERDICT: VERIFIED_FIXED**

Two sub-questions were raised:

### 3. Does the Kelly formula use a SINGLE probability input?

**Yes.** Multiple confirmations in the plan:

- Function signature (line 276): `calibrated_win_probability: float,   # SINGLE input: model confidence → Platt-scaled → conviction-discounted`
- Kelly formula (line 297): `K% = W - (1 - W) / R` where W is the single `calibrated_win_probability`
- Explicit rationale (lines 319-333): "The Kelly formula uses exactly ONE probability input: calibrated_win_probability."
- Computation chain (line 322): `raw_model_confidence → Platt-scaled → conviction-discounted`
- Anti-pattern justification (lines 332-333): "Why not two separate inputs? Feeding both conviction_score and win_probability into the formula double-counts the same thing..."

The `conviction_score` is NOT a second input to Kelly. It is combined with the model probability *before* feeding into Kelly.

### 4. Can user conviction only DISCOUNT (not increase) the model probability?

**Yes.** The discount formula (line 328):

```
calibrated = platt_scaled * min(1.0, user_conviction / platt_scaled)
```

Confirmed by the worked example (lines 330-331):
- User says 0.60 on model 0.81: `calibrated = 0.81 * min(1.0, 0.60/0.81) = 0.81 * 0.74 = 0.60` (discounted)
- User says 0.95 on model 0.81: `calibrated = 0.81 * min(1.0, 0.95/0.81) = 0.81 * 1.0 = 0.81` (not increased)

Line 330 states the rule explicitly: "The user's conviction **cannot increase** the probability above the Platt-scaled model estimate — it can only reduce it."

The transparent display (lines 337-352) shows each step so the user can verify the math.

---

## Overall Verdict

**READY.** All 3 CRITICALs from the logic audit are VERIFIED_FIXED with clear, specific evidence in the plan text. The plan resolves anchoring bias (conviction-before-evidence flow), removes the fragility→stop-loss mis-attribution (ATR-based validation only), and eliminates the probability double-counting (single-input Kelly with conviction as discount-only).
