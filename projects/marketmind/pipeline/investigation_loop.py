"""HVR investigation loop — Pro-driven heuristic news analysis with expectation gap and adversarial self-check.

Fixes Red Team findings C6 (missing expectation gap analysis) and C8 (adversarial
self-check was an empty placeholder). The loop:

  1. Pre-Act: Pro scans top headlines → forms 3-5 testable hypotheses
  2. Expectation gap: for each hypothesis, check market priced-in percentage
  3. HVR loop: Hypothesize → Verify (4-layer) → Refine (max 3 rounds)
  4. Adversarial self-check: mandatory bear case via skeptical Pro persona
  5. Ranked hypotheses with verdicts, confidence scores, and logic chains

Replaces the passive signal consumption in layer1_narrative.py with an active
investigation engine that browses, challenges, and refines financial claims.
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from marketmind.config.investigation_config import (
    ADVERSARIAL_BEAR_CASE_REQUIRED,
    BEAR_CASE_CONFIDENCE_DISCOUNT,
    CONFIDENCE_ACTION_THRESHOLD,
    CONFIDENCE_WATCH_THRESHOLD,
    DIMINISHING_RETURNS_THRESHOLD,
    EXPECTATION_GAP_THRESHOLD,
    MAX_API_CALLS_PER_THREAD,
    MAX_DEEPENING_STEPS_PER_THREAD,
    MAX_HYPOTHESES_PER_SESSION,
    MIN_CORROBORATION_FOR_HIGH_CONF,
)
from marketmind.config.source_independence import count_independent_sources
from marketmind.gateway.async_client import chat_flash, chat_pro
from marketmind.pipeline.flash_preprocessor import FlashSignal
from marketmind.pipeline.verification_chain import VerificationResult, verify_claim

logger = logging.getLogger("marketmind.pipeline.investigation_loop")

# ── Type forward-compatibility ──────────────────────────────────────────────────
# flash_triage.py not yet built — alias FlashSignal until it exists.
# TODO: Replace with `from marketmind.pipeline.flash_triage import TriageResult`
#       when flash_triage.py is implemented.
TriageResult = FlashSignal


# ── Data types ──────────────────────────────────────────────────────────────────


@dataclass
class InvestigationConfig:
    """Runtime investigation parameters. Defaults loaded from investigation_config."""

    max_hypotheses: int = MAX_HYPOTHESES_PER_SESSION
    max_deepening_steps: int = MAX_DEEPENING_STEPS_PER_THREAD
    max_api_calls: int = MAX_API_CALLS_PER_THREAD
    diminishing_threshold: float = DIMINISHING_RETURNS_THRESHOLD
    expectation_gap_threshold: float = EXPECTATION_GAP_THRESHOLD
    confidence_action: float = CONFIDENCE_ACTION_THRESHOLD
    confidence_watch: float = CONFIDENCE_WATCH_THRESHOLD
    adversarial_required: bool = ADVERSARIAL_BEAR_CASE_REQUIRED
    bear_discount: float = BEAR_CASE_CONFIDENCE_DISCOUNT


@dataclass
class HypothesisResult:
    """Output of one complete HVR investigation thread.

    Attributes:
        hypothesis: The final (possibly refined) hypothesis text.
        expectation_gap: |actual - priced_in| ratio. >0.15 = worth investigating.
        verification: Full 4-layer VerificationResult from verification_chain.
        refined_hypothesis: The hypothesis after all refinement rounds.
        confidence: Composite confidence (0-1) after refinement.
        bear_case: Adversarial counter-argument — mandatory.
        bear_case_confidence: How strong the bear case is (0-1).
        verdict: ACTIONABLE | MONITOR | DISCARD | PRICED_IN | HIGH_CONTENTION.
        logic_chain: Step-by-step reasoning trace from all HVR rounds.
    """

    hypothesis: str
    expectation_gap: float
    verification: VerificationResult
    refined_hypothesis: str
    confidence: float
    bear_case: str
    bear_case_confidence: float
    verdict: str  # ACTIONABLE | MONITOR | DISCARD | PRICED_IN | HIGH_CONTENTION
    logic_chain: list[str] = field(default_factory=list)


# ── Pre-Act planning prompt ─────────────────────────────────────────────────────

_PRE_ACT_SYSTEM = """You are a senior macro analyst scanning financial headlines to identify testable hypotheses.

For the headlines provided:
1. Group related headlines into 2-5 themes (e.g., monetary policy shift, commodity supply shock, sector rotation).
2. For each theme, formulate a SPECIFIC, FALSIFIABLE hypothesis. A falsifiable hypothesis makes a concrete claim that can be verified or refuted with data.
3. Each hypothesis must include: WHAT is changing, WHY it matters, and WHAT data would prove it wrong.

Rules:
- Maximum {max_hypotheses} hypotheses.
- Each hypothesis must be 1-2 sentences.
- Avoid vague statements like "markets are uncertain" — be specific.
- Reference specific assets, sectors, or economic indicators where possible.

Return ONLY a JSON object:
{{"hypotheses": ["hypothesis 1 text", "hypothesis 2 text", ...]}}

Do NOT include markdown, explanations, or any text outside the JSON object."""


# ── Expectation gap prompt ──────────────────────────────────────────────────────

_EXPECTATION_GAP_SYSTEM = """You are assessing whether a financial hypothesis is already priced in by markets.

Hypothesis: {hypothesis}

Check these data sources to determine what the market currently expects:
- For rate claims: CME FedWatch or equivalent futures pricing
- For event risk: options implied volatility (elevated IV = market already pricing uncertainty)
- For price claims: current price vs claimed price
- For macro claims: analyst consensus, previous data prints, forward guidance

Return ONLY a JSON object:
{{"priced_in_pct": <int 0-100>, "rationale": "<one sentence explaining why>"}}

where priced_in_pct = what percentage of this thesis is already reflected in current market prices.
Gap = (100 - priced_in_pct) / 100.

IMPORTANT: If market data is unavailable, state "DATA_UNAVAILABLE" in rationale and set priced_in_pct to 50 (neutral). Never fabricate numbers."""


# ── HVR refinement prompt ───────────────────────────────────────────────────────

_HVR_REFINE_SYSTEM = """You are refining a financial hypothesis based on verification results.

Original hypothesis: {hypothesis}

Verification results:
- Market Pricing layer (0-1): {l1_score} — {l1_interpretation}
- Fundamental Data layer (0-1): {l2_score} — {l2_interpretation}
- Multi-Source News layer (0-1): {l3_score} — {l3_interpretation}
- Historical Pattern layer (0-1): {l4_score} — {l4_interpretation}
- Composite confidence: {confidence}
- Verdict: {verdict}
- Contradictions: {contradictions}

Refinement rules:
1. If confidence >= 0.80: Keep the hypothesis as-is. It is verified.
2. If confidence <= 0.30: ABANDON. State "HYPOTHESIS_ABANDONED" and explain why.
3. If 0.30 < confidence < 0.80: REFINE. Adjust the hypothesis to account for which layers supported/refuted it. Narrow the claim, add conditions, or change scope.

Return ONLY a JSON object:
{{"refined_hypothesis": "<refined text or HYPOTHESIS_ABANDONED>",
 "action": "KEEP | ABANDON | REFINE",
 "rationale": "<one sentence>"}}"""


# ── Adversarial bear case prompt ────────────────────────────────────────────────

_BEAR_CASE_SYSTEM = """You are now a skeptical short-seller. You MUST argue AGAINST the following hypothesis.
Provide at least ONE quantitative counter-argument (with specific numbers) and ONE qualitative counter-argument (logical flaw in the thesis).

Hypothesis: {hypothesis}

Supporting evidence: {verification_summary}

You have 300 words maximum. Be specific and ruthless. Attack the weakest link in the chain.

Return ONLY a JSON object:
{{"bear_case": "<your 300-word bear argument>",
 "confidence": <float 0-1 — how likely the bear case is to be correct>,
 "strongest_counterpoint": "<the single most damaging argument>"}}"""


# ── Helpers ─────────────────────────────────────────────────────────────────────


def _parse_json_strict(content: str) -> dict | None:
    """Extract JSON object from LLM response, handling markdown wrapping."""
    if not content:
        return None
    content = content.strip()
    # Strip markdown code fences
    if content.startswith("```"):
        lines = content.split("\n")
        if len(lines) > 1:
            content = "\n".join(lines[1:])
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        # Try to find JSON object boundaries
        start = content.find("{")
        end = content.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(content[start : end + 1])
            except json.JSONDecodeError:
                pass
    return None


def _classify_layer_interpretation(score: float) -> str:
    """Human-readable label for a layer verification score."""
    if score >= 0.80:
        return "strongly supports"
    elif score >= 0.60:
        return "moderately supports"
    elif score >= 0.40:
        return "neutral / inconclusive"
    elif score >= 0.20:
        return "moderately contradicts"
    else:
        return "strongly contradicts"


def _determine_verdict(
    confidence: float,
    expectation_gap: float,
    bear_confidence: float,
    config: InvestigationConfig,
) -> str:
    """Classify hypothesis into verdict tier.

    Order matters:
      1. PRICED_IN — gap too small, no trade value (C6 fix).
      2. Confidence tiers — ACTIONABLE/MONITOR/DISCARD by score.
      3. HIGH_CONTENTION — applies ONLY to ACTIONABLE/MONITOR tiers
         where the bear case is strong enough to warrant caution (C8 fix).
         Low-confidence hypotheses are already DISCARD, no need to override.
    """
    # C6 fix: expectation gap below threshold → priced_in, no trade value
    if expectation_gap < config.expectation_gap_threshold:
        return "PRICED_IN"

    # Determine base confidence tier first
    if confidence >= config.confidence_action:
        base = "ACTIONABLE"
    elif confidence >= config.confidence_watch:
        base = "MONITOR"
    else:
        return "DISCARD"

    # C8 fix: bear case override — only for hypotheses worth considering
    if bear_confidence > config.bear_discount * confidence:
        return "HIGH_CONTENTION"

    return base


# ── Phase 1: Pre-Act planning ───────────────────────────────────────────────────


async def _pre_act_planning(headlines: list[TriageResult]) -> list[str]:
    """Pro scans top headlines → identifies themes → generates testable hypotheses.

    Args:
        headlines: Top-ranked triaged headlines (FlashSignal objects).

    Returns:
        List of hypothesis strings (max MAX_HYPOTHESES_PER_SESSION).
    """
    if not headlines:
        logger.warning("Pre-Act planning: no headlines provided")
        return []

    # Build a compact headline summary for Pro
    headline_lines = []
    for i, h in enumerate(headlines[:30]):  # at most 30 headlines for context
        source = getattr(h, "source_headline", "") or getattr(h, "signal_id", f"SIG-{i}")
        direction = getattr(h, "direction", "neutral")
        conf = getattr(h, "confidence", 0.5)
        event_type = getattr(h, "event_type", "unknown")
        headline_lines.append(
            f"[{i}] [{direction.upper()}] {event_type} (conf={conf:.0%}) — {source}"
        )

    user_prompt = "## Top Headlines\n" + "\n".join(headline_lines)

    try:
        system = _PRE_ACT_SYSTEM.format(max_hypotheses=MAX_HYPOTHESES_PER_SESSION)
        result = await chat_pro(
            system_prompt=system,
            user_prompt=user_prompt,
            temperature=0.4,
            max_tokens=2048,
        )
        content = result.get("content", "")
        parsed = _parse_json_strict(content)
        if parsed and "hypotheses" in parsed and isinstance(parsed["hypotheses"], list):
            hypotheses = parsed["hypotheses"][:MAX_HYPOTHESES_PER_SESSION]
            logger.info("Pre-Act: generated %d hypotheses", len(hypotheses))
            for j, h in enumerate(hypotheses):
                logger.debug("  H%d: %s", j + 1, h[:120])
            return hypotheses
        else:
            logger.warning("Pre-Act: unexpected response format: %.200s", content)
            return []
    except Exception as e:
        logger.error("Pre-Act planning failed: %s", e)
        return []


# ── Phase 2: Expectation gap check ──────────────────────────────────────────────


async def _expectation_gap_check(hypothesis: str) -> float:
    """Check how much of this hypothesis is already priced in by the market.

    Uses Pro to assess CME FedWatch, options IV, current prices, and analyst
    consensus relative to the claim made by the hypothesis.

    Args:
        hypothesis: The hypothesis text to evaluate.

    Returns:
        Gap ratio: |actual - priced_in| / priced_in. Range [0, 1].
        >0.15 = worth investigating (thesis is not fully priced in).
    """
    try:
        system = _EXPECTATION_GAP_SYSTEM.format(hypothesis=hypothesis[:1500])
        result = await chat_pro(
            system_prompt=system,
            user_prompt=f"Assess how much of this hypothesis is priced in: {hypothesis[:1000]}",
            temperature=0.2,
            max_tokens=1024,
        )
        content = result.get("content", "")
        parsed = _parse_json_strict(content)
        if parsed and "priced_in_pct" in parsed:
            priced_in = max(0.0, min(100.0, float(parsed.get("priced_in_pct", 50))))
            gap = (100.0 - priced_in) / 100.0
            logger.debug(
                "Expectation gap: priced_in=%d%%, gap=%.3f — %s",
                int(priced_in),
                gap,
                parsed.get("rationale", "no rationale")[:120],
            )
            return gap
        else:
            logger.warning("Expectation gap: could not parse response: %.200s", content)
            return 0.50  # neutral default
    except Exception as e:
        logger.error("Expectation gap check failed: %s", e)
        return 0.50  # neutral on failure


# ── Phase 3: HVR loop ───────────────────────────────────────────────────────────


async def _hvr_cycle(
    hypothesis: str,
    max_rounds: int = 3,
    config: InvestigationConfig | None = None,
) -> HypothesisResult:
    """HVR: Hypothesize → Verify (4-layer) → Refine (repeat if gain > 5%).

    The audit finding (Druckenmiller discipline): "Failure to confirm" is NOT
    "refine." If verification confidence drops below 0.30, we ABANDON rather
    than refining to a weaker version.

    Args:
        hypothesis: Initial hypothesis string.
        max_rounds: Maximum refinement rounds (default 3, from config).
        config: InvestigationConfig with thresholds.

    Returns:
        HypothesisResult with final hypothesis, verification, logic chain.
    """
    cfg = config or InvestigationConfig()
    current_hypothesis = hypothesis
    logic_chain: list[str] = []
    last_confidence = 0.0
    final_verification: VerificationResult | None = None
    api_calls_used = 0

    # Initial verification before entering refinement loop
    verification = await verify_claim(claim=current_hypothesis)
    api_calls_used += 1
    final_verification = verification
    last_confidence = verification.weighted_confidence
    logic_chain.append(
        f"R0 (initial): hypothesis='{current_hypothesis[:100]}', "
        f"confidence={verification.weighted_confidence:.3f}, "
        f"verdict={verification.verdict}"
    )

    # If already strong — done
    if verification.weighted_confidence >= cfg.confidence_action:
        logger.info(
            "HVR: hypothesis verified on first pass (conf=%.3f)", verification.weighted_confidence
        )
    else:
        # Refinement loop
        for round_num in range(1, max_rounds + 1):
            if api_calls_used >= cfg.max_api_calls:
                logger.warning("HVR: max API calls (%d) reached, stopping", cfg.max_api_calls)
                break

            # Check: is current confidence too low? Abandon rather than refine.
            if verification.weighted_confidence < 0.30:
                logger.info(
                    "HVR: confidence below abandon threshold (%.3f < 0.30) — abandoning",
                    verification.weighted_confidence,
                )
                logic_chain.append(
                    f"R{round_num}: ABANDONED — confidence={verification.weighted_confidence:.3f} "
                    f"below 0.30 threshold. Not refining a contradicted thesis."
                )
                break

            # Refine: ask Pro to update the hypothesis based on verification
            refined = await _refine_hypothesis(
                current_hypothesis, verification, cfg
            )
            api_calls_used += 1

            action = refined.get("action", "REFINE")
            if action == "ABANDON":
                logic_chain.append(
                    f"R{round_num}: ABANDONED by refinement agent — {refined.get('rationale', '')}"
                )
                break
            elif action == "KEEP":
                logic_chain.append(f"R{round_num}: KEPT — hypothesis verified, no changes needed")
                break

            # REFINE: update hypothesis and re-verify
            current_hypothesis = refined.get("refined_hypothesis", current_hypothesis)
            verification = await verify_claim(claim=current_hypothesis)
            api_calls_used += 1
            final_verification = verification

            gain = verification.weighted_confidence - last_confidence
            logic_chain.append(
                f"R{round_num}: refined hypothesis, "
                f"confidence={verification.weighted_confidence:.3f} "
                f"(gain={gain:+.3f}), verdict={verification.verdict}"
            )

            # Diminishing returns check
            if abs(gain) < cfg.diminishing_threshold:
                logger.info(
                    "HVR: diminishing returns (gain=%.3f < %.3f) — stopping refinement",
                    abs(gain),
                    cfg.diminishing_threshold,
                )
                break

            last_confidence = verification.weighted_confidence

            # If refined to high confidence — done
            if verification.weighted_confidence >= cfg.confidence_action:
                logger.info("HVR: refined to actionable confidence (%.3f)", verification.weighted_confidence)
                break

    confidence = final_verification.weighted_confidence if final_verification else 0.0

    return HypothesisResult(
        hypothesis=hypothesis,
        expectation_gap=0.0,              # filled in by caller
        verification=final_verification or VerificationResult(
            claim=hypothesis,
            layer_1_market=0.50,
            layer_2_fundamental=0.50,
            layer_3_multisource=0.50,
            layer_4_historical=0.50,
            weighted_confidence=0.0,
            verdict="UNVERIFIED",
        ),
        refined_hypothesis=current_hypothesis,
        confidence=confidence,
        bear_case="",                     # filled in by caller
        bear_case_confidence=0.0,         # filled in by caller
        verdict="DISCARD",                # filled in by caller
        logic_chain=logic_chain,
    )


async def _refine_hypothesis(
    hypothesis: str,
    verification: VerificationResult,
    config: InvestigationConfig,
) -> dict:
    """Ask Pro to refine a hypothesis based on 4-layer verification results.

    Returns dict with keys: refined_hypothesis, action (KEEP|ABANDON|REFINE), rationale.
    """
    contradictions = verification.contradiction_detail or "none detected"
    system = _HVR_REFINE_SYSTEM.format(
        hypothesis=hypothesis,
        l1_score=verification.layer_1_market,
        l1_interpretation=_classify_layer_interpretation(verification.layer_1_market),
        l2_score=verification.layer_2_fundamental,
        l2_interpretation=_classify_layer_interpretation(verification.layer_2_fundamental),
        l3_score=verification.layer_3_multisource,
        l3_interpretation=_classify_layer_interpretation(verification.layer_3_multisource),
        l4_score=verification.layer_4_historical,
        l4_interpretation=_classify_layer_interpretation(verification.layer_4_historical),
        confidence=verification.weighted_confidence,
        verdict=verification.verdict,
        contradictions=contradictions,
    )

    try:
        result = await chat_pro(
            system_prompt=system,
            user_prompt=f"Refine this hypothesis based on the verification data above.\nHypothesis: {hypothesis}",
            temperature=0.3,
            max_tokens=1536,
        )
        content = result.get("content", "")
        parsed = _parse_json_strict(content)
        if parsed and "refined_hypothesis" in parsed:
            return parsed
        else:
            logger.warning("Refinement: could not parse response: %.200s", content)
            return {"refined_hypothesis": hypothesis, "action": "KEEP",
                    "rationale": "parse failed — keeping original"}
    except Exception as e:
        logger.error("HVR refinement call failed: %s", e)
        return {"refined_hypothesis": hypothesis, "action": "KEEP",
                "rationale": f"API error: {e}"}


# ── Phase 4: Adversarial bear case ──────────────────────────────────────────────


async def _adversarial_bear_check(result: HypothesisResult) -> HypothesisResult:
    """Generate mandatory bear case via skeptical short-seller Pro persona.

    C8 fix: The adversarial self-check must be a real Pro call with a
    dedicated persona prompt, not an empty placeholder. If the bear case
    confidence exceeds bear_discount * main confidence, the verdict is
    upgraded to HIGH_CONTENTION by the caller.

    Args:
        result: HypothesisResult from HVR cycle (without bear case).

    Returns:
        Same HypothesisResult with bear_case and bear_case_confidence populated.
    """
    verification_summary = (
        f"Weighted confidence: {result.verification.weighted_confidence:.3f}. "
        f"Verdict: {result.verification.verdict}. "
        f"L1 (market): {result.verification.layer_1_market:.2f}, "
        f"L2 (fundamental): {result.verification.layer_2_fundamental:.2f}, "
        f"L3 (multisource): {result.verification.layer_3_multisource:.2f}, "
        f"L4 (historical): {result.verification.layer_4_historical:.2f}. "
        f"Sources: {', '.join(result.verification.sources_used[:5]) if result.verification.sources_used else 'none'}."
    )

    system = _BEAR_CASE_SYSTEM.format(
        hypothesis=result.refined_hypothesis,
        verification_summary=verification_summary,
    )

    try:
        response = await chat_pro(
            system_prompt=system,
            user_prompt=f"Challenge this hypothesis as a skeptical short-seller:\n{result.refined_hypothesis}",
            temperature=0.5,
            max_tokens=1536,
        )
        content = response.get("content", "")
        parsed = _parse_json_strict(content)
        if parsed and "bear_case" in parsed:
            result.bear_case = parsed.get("bear_case", "")
            result.bear_case_confidence = float(parsed.get("confidence", 0.3))
            strongest = parsed.get("strongest_counterpoint", "")
            logger.debug(
                "Bear case: confidence=%.3f, strongest: %s",
                result.bear_case_confidence,
                strongest[:120],
            )
        else:
            logger.warning("Bear case: could not parse response: %.200s", content)
            result.bear_case = "BEAR CASE GENERATION FAILED — could not parse Pro response."
            result.bear_case_confidence = 0.30
    except Exception as e:
        logger.error("Adversarial bear check failed: %s", e)
        result.bear_case = f"BEAR CASE GENERATION FAILED — API error: {e}"
        result.bear_case_confidence = 0.30

    return result


# ── Main orchestration ──────────────────────────────────────────────────────────


async def run_investigation_loop(
    selected_headlines: list[TriageResult],
    config: InvestigationConfig | None = None,
) -> list[HypothesisResult]:
    """Full investigation pipeline: Pre-Act → Expectation Gap → HVR → Bear Case → Verdict.

    This is the Pro-level investigation engine that replaces the old
    layer1_narrative.py passive signal consumption. Pro browses like a human
    analyst: scan, hypothesize, check what's priced in, verify through
    independent data layers, refine, and generate adversarial bear case.

    Args:
        selected_headlines: Top-ranked triage results that Pro selected for
            deeper investigation. In descending impact order.
        config: Runtime thresholds. Defaults from investigation_config.py.

    Returns:
        List of HypothesisResult, ranked by confidence (highest first).
        Results with verdict PRICED_IN are included but deprioritized.
    """
    cfg = config or InvestigationConfig()
    t_start = datetime.now(timezone.utc)
    logger.info(
        "Investigation loop: %d headlines, max %d hypotheses, max %d rounds each",
        len(selected_headlines),
        cfg.max_hypotheses,
        cfg.max_deepening_steps,
    )

    # 1. Pre-Act: Pro scans → generates hypotheses
    hypotheses = await _pre_act_planning(selected_headlines)
    if not hypotheses:
        logger.warning("Investigation loop: no hypotheses generated — aborting")
        return []

    results: list[HypothesisResult] = []

    for i, h in enumerate(hypotheses[: cfg.max_hypotheses]):
        logger.info("Investigating H%d/%d: %s", i + 1, len(hypotheses), h[:120])

        # 2. Expectation gap: is this already priced in?
        gap = await _expectation_gap_check(h)
        if gap < cfg.expectation_gap_threshold:
            logger.info("  H%d: priced_in (gap=%.3f < %.3f) — skipping deep verification", i + 1, gap, cfg.expectation_gap_threshold)
            # Create a minimal result for priced-in hypotheses
            results.append(HypothesisResult(
                hypothesis=h,
                expectation_gap=gap,
                verification=VerificationResult(
                    claim=h,
                    layer_1_market=0.0,
                    layer_2_fundamental=0.0,
                    layer_3_multisource=0.0,
                    layer_4_historical=0.0,
                    weighted_confidence=0.0,
                    verdict="UNVERIFIED",
                ),
                refined_hypothesis=h,
                confidence=0.0,
                bear_case="SKIPPED — hypothesis is fully priced in, no adversarial check needed.",
                bear_case_confidence=0.0,
                verdict="PRICED_IN",
                logic_chain=[f"Expectation gap={gap:.3f} < threshold={cfg.expectation_gap_threshold:.3f} → PRICED_IN"],
            ))
            continue

        # 3. HVR cycle: Hypothesize → Verify → Refine
        hvr_result = await _hvr_cycle(h, max_rounds=cfg.max_deepening_steps, config=cfg)
        hvr_result.expectation_gap = gap

        # 4. Adversarial bear case (C8 fix — mandatory)
        if cfg.adversarial_required:
            hvr_result = await _adversarial_bear_check(hvr_result)

        # 5. Classify verdict
        hvr_result.verdict = _determine_verdict(
            confidence=hvr_result.confidence,
            expectation_gap=gap,
            bear_confidence=hvr_result.bear_case_confidence,
            config=cfg,
        )
        results.append(hvr_result)
        logger.info(
            "  H%d: verdict=%s conf=%.3f gap=%.3f bear_conf=%.3f",
            i + 1,
            hvr_result.verdict,
            hvr_result.confidence,
            gap,
            hvr_result.bear_case_confidence,
        )

    # Rank by confidence (highest first), but ACTIONABLE before MONITOR before DISCARD/PRICED_IN
    _verdict_rank = {"ACTIONABLE": 0, "MONITOR": 1, "HIGH_CONTENTION": 2, "DISCARD": 3, "PRICED_IN": 4}
    results.sort(key=lambda r: (_verdict_rank.get(r.verdict, 5), -r.confidence))

    elapsed = (datetime.now(timezone.utc) - t_start).total_seconds()
    actionable = sum(1 for r in results if r.verdict == "ACTIONABLE")
    logger.info(
        "Investigation loop complete: %d hypotheses in %.1fs — %d ACTIONABLE, %d PRICED_IN",
        len(results),
        elapsed,
        actionable,
        sum(1 for r in results if r.verdict == "PRICED_IN"),
    )

    return results
