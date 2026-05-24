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
import re
from datetime import datetime, timezone

from marketmind.config.investigation_config import MAX_HYPOTHESES_PER_SESSION, MAX_PRO_CALLS_PER_SESSION
from marketmind.gateway.async_client import chat_flash, chat_pro
from marketmind.pipeline.flash_preprocessor import FlashSignal
from marketmind.pipeline.hvr_cycle import _classify_layer_interpretation, run_hvr_cycle
from marketmind.pipeline.investigation_direction import (
    estimate_risk_level,
    estimate_time_window,
    extract_direction,
)
from marketmind.pipeline.investigation_prompts import (
    _BEAR_CASE_SYSTEM,
    _EXPECTATION_GAP_SYSTEM,
    _NARRATIVE_PROMPT,
    _PRE_ACT_SYSTEM,
)
from marketmind.pipeline.investigation_types import HypothesisResult, InvestigationConfig
from marketmind.pipeline.verification_chain import VerificationResult

logger = logging.getLogger("marketmind.pipeline.investigation_loop")

# ── Type forward-compatibility ──────────────────────────────────────────────────
# flash_triage.py not yet built — alias FlashSignal until it exists.
# TODO: Replace with `from marketmind.pipeline.flash_triage import TriageResult`
#       when flash_triage.py is implemented.
TriageResult = FlashSignal


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
    content = re.sub(r",\s*([}\]])", r"\1", content)
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        start = content.find("{")
        end = content.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(content[start : end + 1])
            except json.JSONDecodeError:
                pass
    return None


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


# ── Narrative generation ────────────────────────────────────────────────────────


async def _generate_layer_narratives(result: HypothesisResult) -> HypothesisResult:
    """Generate one-sentence narratives for each verification layer using Flash LLM.

    Also populates direction (heuristic), risk_level (heuristic), time_window
    (heuristic), and core_logic (Flash LLM). Layer narratives are generated via
    a single cheap Flash call.

    Args:
        result: HypothesisResult with verification scores populated.

    Returns:
        Same HypothesisResult with narrative fields filled in.
    """
    # Heuristic fields (no LLM needed)
    result.direction = extract_direction(result.hypothesis)
    result.risk_level = estimate_risk_level(result.confidence, result.bear_case_confidence)
    result.time_window = estimate_time_window(result.verdict)

    # Generate layer narratives + core_logic via Flash LLM
    try:
        prompt = _NARRATIVE_PROMPT.format(
            hypothesis=result.hypothesis[:800],
            refined_hypothesis=result.refined_hypothesis[:800],
            l1=result.verification.layer_1_market,
            l2=result.verification.layer_2_fundamental,
            l3=result.verification.layer_3_multisource,
            l4=result.verification.layer_4_historical,
        )
        response = await chat_flash(
            system_prompt="You are a financial editor. Write concise, specific Chinese narratives. Return JSON only.",
            user_prompt=prompt,
            temperature=0.3,
            max_tokens=4096,
        )
        content = response.get("content", "")
        parsed = _parse_json_strict(content)
        if parsed:
            result.layer_1_narrative = str(parsed.get("layer_1_narrative", ""))
            result.layer_2_narrative = str(parsed.get("layer_2_narrative", ""))
            result.layer_3_narrative = str(parsed.get("layer_3_narrative", ""))
            result.layer_4_narrative = str(parsed.get("layer_4_narrative", ""))
            result.core_logic = str(parsed.get("core_logic", ""))
            logger.debug("Layer narratives generated: core_logic=%s", result.core_logic[:80])
        else:
            logger.warning("_generate_layer_narratives: Flash response parse failed: %.200s", content)
    except Exception as e:
        logger.error("_generate_layer_narratives: Flash call failed: %s", e)
        # Narratives remain empty strings on failure — non-blocking

    return result


# ── Phase 1: Pre-Act planning ───────────────────────────────────────────────────


async def _pre_act_planning(
    headlines: list[TriageResult],
    pro_calls_counter: list[int] | None = None,
) -> list[str]:
    """Pro scans top headlines → identifies themes → generates testable hypotheses.

    Args:
        headlines: Top-ranked triaged headlines (FlashSignal objects).
        pro_calls_counter: Mutable [int] counter for per-session Pro call cap.

    Returns:
        List of hypothesis strings (max MAX_HYPOTHESES_PER_SESSION).
    """
    if not headlines:
        logger.warning("Pre-Act planning: no headlines provided")
        return []

    # H-SEC-2: check Pro call cap before LLM call
    if pro_calls_counter is not None and pro_calls_counter[0] >= MAX_PRO_CALLS_PER_SESSION:
        logger.warning(
            "Pre-Act planning: Pro call cap reached (%d/%d) — skipping",
            pro_calls_counter[0], MAX_PRO_CALLS_PER_SESSION,
        )
        return []

    # Build a compact headline summary for Pro
    headline_lines = []
    for i, h in enumerate(headlines[:30]):  # at most 30 headlines for context
        source = getattr(h, "headline", "") or getattr(h, "source_headline", "") or getattr(h, "signal_id", f"SIG-{i}")
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
            max_tokens=16384,
        )
        if pro_calls_counter is not None:
            pro_calls_counter[0] += 1
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


async def _expectation_gap_check(
    hypothesis: str,
    pro_calls_counter: list[int] | None = None,
) -> float:
    """Check how much of this hypothesis is already priced in by the market.

    Uses Pro to assess CME FedWatch, options IV, current prices, and analyst
    consensus relative to the claim made by the hypothesis.

    Args:
        hypothesis: The hypothesis text to evaluate.
        pro_calls_counter: Mutable [int] counter for per-session Pro call cap.

    Returns:
        Gap ratio: |actual - priced_in| / priced_in. Range [0, 1].
        >0.15 = worth investigating (thesis is not fully priced in).
    """
    # H-SEC-2: check Pro call cap before LLM call
    if pro_calls_counter is not None and pro_calls_counter[0] >= MAX_PRO_CALLS_PER_SESSION:
        logger.warning(
            "Expectation gap: Pro call cap reached (%d/%d) — using neutral default",
            pro_calls_counter[0], MAX_PRO_CALLS_PER_SESSION,
        )
        return 0.50  # neutral default when cap is hit

    try:
        system = _EXPECTATION_GAP_SYSTEM.format(hypothesis=hypothesis[:1500])
        result = await chat_pro(
            system_prompt=system,
            user_prompt=f"Assess how much of this hypothesis is priced in: {hypothesis[:1000]}",
            temperature=0.2,
        )
        if pro_calls_counter is not None:
            pro_calls_counter[0] += 1
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


# ── Phase 4: Adversarial bear case ──────────────────────────────────────────────


async def _adversarial_bear_check(
    result: HypothesisResult,
    pro_calls_counter: list[int] | None = None,
) -> HypothesisResult:
    """Generate mandatory bear case via skeptical short-seller Pro persona.

    C8 fix: The adversarial self-check must be a real Pro call with a
    dedicated persona prompt, not an empty placeholder. If the bear case
    confidence exceeds bear_discount * main confidence, the verdict is
    upgraded to HIGH_CONTENTION by the caller.

    Args:
        result: HypothesisResult from HVR cycle (without bear case).
        pro_calls_counter: Mutable [int] counter for per-session Pro call cap.

    Returns:
        Same HypothesisResult with bear_case and bear_case_confidence populated.
    """
    # H-SEC-2: check Pro call cap before LLM call
    if pro_calls_counter is not None and pro_calls_counter[0] >= MAX_PRO_CALLS_PER_SESSION:
        logger.warning(
            "Bear case: Pro call cap reached (%d/%d) — using placeholder",
            pro_calls_counter[0], MAX_PRO_CALLS_PER_SESSION,
        )
        result.bear_case = "BEAR CASE SKIPPED — Pro call cap reached."
        result.bear_case_confidence = 0.30
        return result

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
        )
        if pro_calls_counter is not None:
            pro_calls_counter[0] += 1
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
    pro_calls_used: list[int] = [0]  # H-SEC-2: mutable counter for per-session Pro call cap

    t_start = datetime.now(timezone.utc)
    logger.info(
        "Investigation loop: %d headlines, max %d hypotheses, max %d rounds each, Pro cap=%d",
        len(selected_headlines),
        cfg.max_hypotheses,
        cfg.max_deepening_steps,
        MAX_PRO_CALLS_PER_SESSION,
    )

    # 1. Pre-Act: Pro scans → generates hypotheses
    hypotheses = await _pre_act_planning(selected_headlines, pro_calls_used)
    if not hypotheses:
        logger.warning("Investigation loop: no hypotheses generated — aborting")
        return []

    results: list[HypothesisResult] = []

    for i, h in enumerate(hypotheses[: cfg.max_hypotheses]):
        logger.info("Investigating H%d/%d: %s", i + 1, len(hypotheses), h[:120])

        # 2. Expectation gap: is this already priced in?
        gap = await _expectation_gap_check(h, pro_calls_used)
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
        hvr_result = await run_hvr_cycle(h, max_rounds=cfg.max_deepening_steps, config=cfg, pro_calls_counter=pro_calls_used)
        hvr_result.expectation_gap = gap

        # 4. Adversarial bear case (C8 fix — mandatory)
        if cfg.adversarial_required:
            hvr_result = await _adversarial_bear_check(hvr_result, pro_calls_used)

        # 5. Classify verdict
        hvr_result.verdict = _determine_verdict(
            confidence=hvr_result.confidence,
            expectation_gap=gap,
            bear_confidence=hvr_result.bear_case_confidence,
            config=cfg,
        )

        # 6. Generate hypothesis card narratives (direction, risk, time window, layer narratives)
        hvr_result = await _generate_layer_narratives(hvr_result)

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

    # Phase H: enrich hypotheses with causal and flow decomposition
    enrichable = [r for r in results if r.verdict in ("ACTIONABLE", "HIGH_CONTENTION")]
    if enrichable:
        from marketmind.pipeline.causal_decomposition import decompose_hypothesis, CausalDecomposition
        from marketmind.pipeline.flow_decomposition import attribute_flows, FlowAttribution

        async def _enrich_one(result: HypothesisResult) -> None:
            """Run causal + flow decomposition for one hypothesis. Never raises."""
            try:
                causal_task = decompose_hypothesis(result)
                flow_task = attribute_flows(result)
                causal, flow = await asyncio.gather(causal_task, flow_task, return_exceptions=True)
                if isinstance(causal, CausalDecomposition):
                    result.causal = causal
                    logger.info("Causal decomposition: %s -> %s (force=%.3f)",
                                result.hypothesis[:60], causal.asset_class, causal.net_directional_force)
                elif isinstance(causal, Exception):
                    logger.warning("Causal decomposition failed: %s", causal)
                if isinstance(flow, FlowAttribution):
                    result.flow = flow
                    logger.info("Flow attribution: %s -> %d entities (dominant=%s/%s)",
                                result.hypothesis[:60], len(flow.entities),
                                flow.dominant_buyer, flow.dominant_seller)
                elif isinstance(flow, Exception):
                    logger.warning("Flow decomposition failed: %s", flow)
            except Exception as e:
                logger.warning("Phase H enrichment failed for hypothesis: %s", e)

        await asyncio.gather(*[_enrich_one(r) for r in enrichable])

    elapsed = (datetime.now(timezone.utc) - t_start).total_seconds()
    actionable = sum(1 for r in results if r.verdict == "ACTIONABLE")
    logger.info(
        "Investigation loop complete: %d hypotheses in %.1fs — %d ACTIONABLE, %d PRICED_IN, %d Pro calls used",
        len(results),
        elapsed,
        actionable,
        sum(1 for r in results if r.verdict == "PRICED_IN"),
        pro_calls_used[0],
    )

    return results
