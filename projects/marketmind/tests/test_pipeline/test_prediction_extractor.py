"""Tests for prediction_extractor — heuristic prediction extraction from HypothesisResults."""
from __future__ import annotations

import pytest
from marketmind.pipeline.prediction_extractor import (
    PredictableHypothesis,
    _generate_hypothesis_id,
    _parse_time_window_days,
    extract_predictions,
)


class FakeHypothesisResult:
    """Minimal HypothesisResult stub for testing."""

    def __init__(
        self,
        hypothesis="",
        verdict="ACTIONABLE",
        confidence=0.75,
        direction="",
        time_window="",
    ):
        self.hypothesis = hypothesis
        self.verdict = verdict
        self.confidence = confidence
        self.direction = direction
        self.time_window = time_window


def test_extract_price_prediction_above():
    hypotheses = [
        FakeHypothesisResult(
            hypothesis="EUR/USD将在美联储降息后升至1.1500，突破关键阻力位",
            direction="EUR/USD 看涨",
            time_window="2-4周",
        )
    ]
    results = extract_predictions(hypotheses)
    assert len(results) == 1
    p = results[0]
    assert p.direction == "above"
    assert p.success_value == 1.15
    assert p.prediction_window_days == 28
    assert p.status == "PENDING"
    assert p.verification_source == "market_data:EUR/USD"
    assert p.expiry_date  # non-empty


def test_extract_price_prediction_below():
    hypotheses = [
        FakeHypothesisResult(
            hypothesis="原油价格可能跌破65.00美元，受需求疲软影响",
            direction="原油 看跌",
            time_window="1-3个月",
        )
    ]
    results = extract_predictions(hypotheses)
    assert len(results) == 1
    p = results[0]
    assert p.direction == "below"
    assert p.success_value == 65.0
    assert p.prediction_window_days == 90


def test_non_quantifiable_skipped():
    """Hypotheses without numeric predictions are skipped."""
    hypotheses = [
        FakeHypothesisResult(
            hypothesis="市场情绪偏向谨慎，但缺乏明确方向",
            direction="震荡",
            time_window="1周",
        )
    ]
    results = extract_predictions(hypotheses)
    assert len(results) == 0


def test_actionable_only_processed():
    """Only ACTIONABLE and HIGH_CONTENTION verdicts are processed."""
    actionable = FakeHypothesisResult(
        hypothesis="黄金将突破2100美元",
        verdict="ACTIONABLE",
        direction="黄金 看涨",
        time_window="2周",
    )
    high_c = FakeHypothesisResult(
        hypothesis="黄金可能跌至1950美元",
        verdict="HIGH_CONTENTION",
        direction="黄金 看跌",
        time_window="1个月",
    )
    discarded = FakeHypothesisResult(
        hypothesis="黄金将突破3000美元",
        verdict="DISCARD",
        direction="黄金 看涨",
    )
    monitor = FakeHypothesisResult(
        hypothesis="黄金将突破4000美元",
        verdict="MONITOR",
        direction="黄金 看涨",
    )

    results = extract_predictions([actionable, high_c, discarded, monitor])
    assert len(results) == 2


def test_extract_percentage_up():
    hypotheses = [
        FakeHypothesisResult(
            hypothesis="标普500指数将在财报季后上涨5%",
            direction="S&P 500 看涨",
            time_window="1个月",
        )
    ]
    results = extract_predictions(hypotheses)
    assert len(results) == 1
    assert results[0].direction == "above"
    assert results[0].success_value == 5.0


def test_extract_percentage_down():
    hypotheses = [
        FakeHypothesisResult(
            hypothesis="纳指可能下跌3%，因科技股估值过高",
            direction="纳斯达克 看跌",
            time_window="2-4周",
        )
    ]
    results = extract_predictions(hypotheses)
    assert len(results) == 1
    assert results[0].direction == "below"
    assert results[0].success_value == 3.0


def test_time_window_parsing():
    assert _parse_time_window_days("2-4周") == 28
    assert _parse_time_window_days("1-3个月") == 90
    assert _parse_time_window_days("1周") == 7
    assert _parse_time_window_days("N/A") == 30
    assert _parse_time_window_days("") == 30
    assert _parse_time_window_days("24小时") == 1
    assert _parse_time_window_days("3周") == 21


def test_hypothesis_id_stable():
    id1 = _generate_hypothesis_id("黄金突破2100", "2026-05-18T00:00:00Z")
    id2 = _generate_hypothesis_id("黄金突破2100", "2026-05-18T00:00:00Z")
    id3 = _generate_hypothesis_id("黄金突破2200", "2026-05-18T00:00:00Z")
    assert id1 == id2
    assert id1 != id3


def test_infer_verification_source():
    hypotheses = [
        FakeHypothesisResult(
            hypothesis="美联储加息将推动美元走强",
            direction="USD 看涨",
            verdict="ACTIONABLE",
            time_window="1个月",
        )
    ]
    results = extract_predictions(hypotheses)
    # No numeric prediction in this text, so skipped
    assert len(results) == 0


def test_price_above_variant_突破():
    hypotheses = [
        FakeHypothesisResult(
            hypothesis="比特币将突破95000美元关键心理关口",
            direction="BTC 看涨",
            time_window="2周",
        )
    ]
    results = extract_predictions(hypotheses)
    assert len(results) == 1
    assert results[0].direction == "above"
    assert results[0].success_value == 95000.0
    assert results[0].verification_source == "market_data:BTC/USD"
