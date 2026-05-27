"""Pipeline metrics recorder — daily snapshot of key stage outputs.

Every pipeline run records a row to pipeline_metrics.jsonl. The weekly
tactical audit reads these to analyze stage-level trends.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("marketmind.pipeline.metrics")

METRICS_LOG = "pipeline_metrics.jsonl"


@dataclass
class PipelineMetrics:
    date: str = ""
    run_mode: str = "daily"
    mock: bool = False

    # Stage 2: Flash Triage
    flash_total_scored: int = 0
    flash_high_impact: int = 0
    flash_avg_impact: float = 0.0
    flash_classification_counts: dict = field(default_factory=dict)

    # Stage 2b: HVR Investigation
    hvr_articles_investigated: int = 0
    hvr_signals_found: int = 0

    # Stage 3: L1 Narrative
    l1_grade: str = ""
    l1_quadrant: str = ""
    l1_direction: str = ""
    l1_price_in: float = 0.0

    # Stage 4: L2+L3
    l2_ticker_candidates: int = 0
    l3_green_lights: int = 0
    l3_yellow_lights: int = 0
    l3_red_lights: int = 0

    # Stage 6: Red Team
    red_team_challenges: int = 0
    red_team_severe: int = 0

    # Stage 7: Resonance
    resonance_dsr: float = 0.0
    resonance_pbo: float = 0.0
    resonance_passed: bool = False
    resonance_verdict: str = ""

    # Stage 8: Decision
    decision_cards: int = 0
    decision_no_trade: bool = False

    # Calibration (from previous run)
    calib_accuracy: float | None = None
    calib_total: int = 0

    def to_dict(self) -> dict:
        return {
            "date": self.date, "run_mode": self.run_mode, "mock": self.mock,
            "flash_total_scored": self.flash_total_scored,
            "flash_high_impact": self.flash_high_impact,
            "flash_avg_impact": self.flash_avg_impact,
            "flash_classification_counts": self.flash_classification_counts,
            "hvr_articles_investigated": self.hvr_articles_investigated,
            "hvr_signals_found": self.hvr_signals_found,
            "l1_grade": self.l1_grade, "l1_quadrant": self.l1_quadrant,
            "l1_direction": self.l1_direction, "l1_price_in": self.l1_price_in,
            "l2_ticker_candidates": self.l2_ticker_candidates,
            "l3_green_lights": self.l3_green_lights,
            "l3_yellow_lights": self.l3_yellow_lights,
            "l3_red_lights": self.l3_red_lights,
            "red_team_challenges": self.red_team_challenges,
            "red_team_severe": self.red_team_severe,
            "resonance_dsr": self.resonance_dsr,
            "resonance_pbo": self.resonance_pbo,
            "resonance_passed": self.resonance_passed,
            "resonance_verdict": self.resonance_verdict,
            "decision_cards": self.decision_cards,
            "decision_no_trade": self.decision_no_trade,
            "calib_accuracy": self.calib_accuracy,
            "calib_total": self.calib_total,
        }


def _metrics_dir() -> Path:
    d = Path(__file__).resolve().parent.parent / ".claude" / "metrics"
    d.mkdir(parents=True, exist_ok=True)
    return d


def record_metrics(m: PipelineMetrics) -> None:
    """Append a pipeline metrics snapshot to the log."""
    m.date = m.date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        fpath = _metrics_dir() / METRICS_LOG
        with open(fpath, "a", encoding="utf-8") as f:
            f.write(json.dumps(m.to_dict(), ensure_ascii=False) + "\n")
    except Exception:
        logger.debug("Failed to record pipeline metrics for %s", m.date, exc_info=True)


def load_recent_metrics(days: int = 7) -> list[dict]:
    """Load the most recent N days of pipeline metrics."""
    fpath = _metrics_dir() / METRICS_LOG
    if not fpath.exists():
        return []
    entries: list[dict] = []
    with open(fpath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return entries[-days:]


def collect_metrics_from_session(
    flash_results: list | None = None,
    hvr_results: dict | None = None,
    l1_result=None,
    l2_result=None,
    l3_result=None,
    red_team_report=None,
    resonance=None,
    decision=None,
    calib_accuracy: float | None = None,
    calib_total: int = 0,
    mock: bool = False,
) -> PipelineMetrics:
    """Build PipelineMetrics from pipeline session objects."""
    m = PipelineMetrics(date=datetime.now(timezone.utc).strftime("%Y-%m-%d"), mock=mock)

    if flash_results:
        m.flash_total_scored = len(flash_results)
        if m.flash_total_scored > 0:
            impacts: list[float] = []
            counts: dict[str, int] = {}
            for r in flash_results:
                scores = r.scores if hasattr(r, 'scores') else r.get("scores", {})
                classification = r.classification if hasattr(r, 'classification') else r.get("classification", "?")
                impacts.append(scores.get("market_impact", 0))
                counts[classification] = counts.get(classification, 0) + 1
            m.flash_avg_impact = sum(impacts) / len(impacts)
            m.flash_high_impact = sum(1 for i in impacts if i >= 5)
            m.flash_classification_counts = counts

    if hvr_results:
        m.hvr_articles_investigated = hvr_results.get("articles_investigated", 0)
        m.hvr_signals_found = hvr_results.get("signals_found", 0)

    if l1_result:
        m.l1_grade = getattr(l1_result, 'event_grade', '') or ''
        m.l1_quadrant = getattr(l1_result, 'matrix_quadrant', '') or ''
        m.l1_direction = getattr(l1_result, 'sentiment_direction', '') or ''
        m.l1_price_in = getattr(l1_result, 'price_in_score', 0.0) or 0.0

    if l2_result:
        m.l2_ticker_candidates = len(getattr(l2_result, 'ticker_candidates', []) or [])
    if l3_result:
        m.l3_green_lights = len(getattr(l3_result, 'green_lights', []) or [])
        m.l3_yellow_lights = len(getattr(l3_result, 'yellow_lights', []) or [])
        m.l3_red_lights = len(getattr(l3_result, 'red_lights', []) or [])

    if red_team_report:
        challenges = getattr(red_team_report, 'challenges', []) or []
        m.red_team_challenges = len(challenges)
        m.red_team_severe = sum(1 for c in challenges if getattr(c, 'severity', '') in ('high', 'critical'))

    if resonance:
        m.resonance_dsr = getattr(resonance, 'dsr', 0.0) or 0.0
        m.resonance_pbo = getattr(resonance, 'pbo', 0.0) or 0.0
        m.resonance_passed = getattr(resonance, 'passed', False)
        m.resonance_verdict = getattr(resonance, 'verdict', '') or ''

    if decision:
        m.decision_cards = len(getattr(decision, 'decision_cards', []) or [])
        m.decision_no_trade = getattr(decision, 'no_trade_card', None) is not None

    m.calib_accuracy = calib_accuracy
    m.calib_total = calib_total
    return m
