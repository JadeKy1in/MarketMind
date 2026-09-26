"""Extract verifiable, time-anchored predictions from HypothesisResults.

Heuristic-only (no LLM) — regex patterns extract quantifiable predictions
from hypothesis text, time_window, and direction fields.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


@dataclass
class PredictableHypothesis:
    """A single verifiable prediction extracted from a hypothesis."""

    hypothesis_id: str
    hypothesis_text: str
    prediction: str
    confidence: float
    direction: str  # "above" | "below" | "within_range"
    success_value: float
    verification_metric: str
    verification_source: str  # "market_data:EUR/USD" | "FRED:CPIAUCSL" | "news:ECB_statement"
    prediction_window_days: int
    expiry_date: str
    status: str = "PENDING"
    actual_value: float | None = None
    verified_at: str | None = None
    created_at: str = ""


# ── Regex patterns for Chinese prediction text ──────────────────────────

_PRICE_ABOVE_PATTERNS = [
    re.compile(r"升至\s*(\d+\.?\d*)"),
    re.compile(r"突破\s*(\d+\.?\d*)"),
    re.compile(r"涨[到至]\s*(\d+\.?\d*)"),
    re.compile(r"上涨[到至]\s*(\d+\.?\d*)"),
    re.compile(r"上[涨升][至到]\s*(\d+\.?\d*)"),
    re.compile(r"高于\s*(\d+\.?\d*)"),
    re.compile(r"超过\s*(\d+\.?\d*)"),
]

_PRICE_BELOW_PATTERNS = [
    re.compile(r"跌至\s*(\d+\.?\d*)"),
    re.compile(r"跌破\s*(\d+\.?\d*)"),
    re.compile(r"跌[到至]\s*(\d+\.?\d*)"),
    re.compile(r"下跌[到至]\s*(\d+\.?\d*)"),
    re.compile(r"下[跌降][至到]\s*(\d+\.?\d*)"),
    re.compile(r"低于\s*(\d+\.?\d*)"),
    re.compile(r"回落[到至]\s*(\d+\.?\d*)"),
]

_PERCENT_UP_PATTERNS = [
    re.compile(r"涨\s*(\d+(?:\.\d+)?)\s*%"),
    re.compile(r"上涨\s*(\d+(?:\.\d+)?)\s*%"),
    re.compile(r"涨幅\s*(\d+(?:\.\d+)?)\s*%"),
]

_PERCENT_DOWN_PATTERNS = [
    re.compile(r"跌\s*(\d+(?:\.\d+)?)\s*%"),
    re.compile(r"下跌\s*(\d+(?:\.\d+)?)\s*%"),
    re.compile(r"跌幅\s*(\d+(?:\.\d+)?)\s*%"),
]

# Time window: map Chinese expressions to days (upper bound as spec says)
_TIME_WINDOW_MAP = {
    "24小时": 1,
    "48小时": 2,
    "1周": 7,
    "1-2周": 14,
    "2-4周": 28,
    "2周": 14,
    "3周": 21,
    "4周": 28,
    "1-3个月": 90,
    "1个月": 30,
    "2个月": 60,
    "3个月": 90,
    "4-6个月": 180,
    "6个月": 180,
    "1年": 365,
}

_TIME_UNIT_PATTERNS = [
    (re.compile(r"(\d+)-?(\d+)?\s*周"), 7),
    (re.compile(r"(\d+)-?(\d+)?\s*个?月"), 30),
    (re.compile(r"(\d+)-?(\d+)?\s*天"), 1),
    (re.compile(r"(\d+)\s*小?时"), 1 / 24),
]


def _parse_time_window_days(text: str) -> int:
    """Parse a Chinese time-window string into days (upper bound)."""
    cleaned = text.strip()
    if not cleaned or cleaned in ("N/A", "已过期", ""):
        return 30  # default

    if cleaned in _TIME_WINDOW_MAP:
        return _TIME_WINDOW_MAP[cleaned]

    for pattern, multiplier in _TIME_UNIT_PATTERNS:
        m = pattern.search(cleaned)
        if m:
            if m.group(2):
                upper = int(m.group(2))
            else:
                upper = int(m.group(1))
            return int(upper * multiplier)

    return 30


def _generate_hypothesis_id(text: str, timestamp: str) -> str:
    """Generate a stable, unique hypothesis ID from text + timestamp."""
    raw = f"{text}|{timestamp}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def extract_predictions(hypotheses: list) -> list[PredictableHypothesis]:
    """Extract verifiable predictions from a list of HypothesisResult objects.

    Only processes verdicts ACTIONABLE or HIGH_CONTENTION.
    Skips hypotheses without quantifiable numeric predictions.
    """
    results: list[PredictableHypothesis] = []
    now = datetime.now(timezone.utc)
    ts = now.isoformat()

    for h in hypotheses:
        verdict = getattr(h, "verdict", "")
        if verdict not in ("ACTIONABLE", "HIGH_CONTENTION"):
            continue

        text = getattr(h, "hypothesis", "")
        if not text:
            continue

        direction_str = getattr(h, "direction", "") or ""
        time_window = getattr(h, "time_window", "") or ""

        price_num = None
        direction = ""
        detection_source = ""

        # Try price-level patterns first (most specific)
        for pat in _PRICE_ABOVE_PATTERNS:
            m = pat.search(text)
            if m:
                price_num = float(m.group(1))
                direction = "above"
                detection_source = f"price_above:{pat.pattern[:20]}"
                break

        if price_num is None:
            for pat in _PRICE_BELOW_PATTERNS:
                m = pat.search(text)
                if m:
                    price_num = float(m.group(1))
                    direction = "below"
                    detection_source = f"price_below:{pat.pattern[:20]}"
                    break

        # Try percentage patterns (direction comes from pattern type)
        if price_num is None:
            for pat in _PERCENT_UP_PATTERNS:
                m = pat.search(text)
                if m:
                    price_num = float(m.group(1))
                    direction = "above"
                    detection_source = f"percent_up:{pat.pattern[:20]}"
                    break

        if price_num is None:
            for pat in _PERCENT_DOWN_PATTERNS:
                m = pat.search(text)
                if m:
                    price_num = float(m.group(1))
                    direction = "below"
                    detection_source = f"percent_down:{pat.pattern[:20]}"
                    break

        if price_num is None:
            continue

        # Determine verification source from direction string
        verification_source = _infer_verification_source(text, direction_str)
        verification_metric = _infer_verification_metric(text, direction_str)

        window_days = _parse_time_window_days(time_window)
        expiry = (now + timedelta(days=window_days)).strftime("%Y-%m-%d")

        confidence = getattr(h, "confidence", 0.5) or 0.5
        hypothesis_id = _generate_hypothesis_id(text, ts)

        prediction_text = (
            f"{direction_str or '标的'}将在{window_days}天内{direction} {price_num}"
        )

        results.append(
            PredictableHypothesis(
                hypothesis_id=hypothesis_id,
                hypothesis_text=text,
                prediction=prediction_text,
                confidence=confidence,
                direction=direction,
                success_value=price_num,
                verification_metric=verification_metric,
                verification_source=verification_source,
                prediction_window_days=window_days,
                expiry_date=expiry,
                status="PENDING",
                created_at=ts,
            )
        )

    return results


# ── Verification source / metric inference (heuristic, no LLM) ──────────

_ASSET_KEYWORDS: list[tuple[str, str]] = [
    ("EUR/USD", "market_data:EUR/USD"),
    ("EURUSD", "market_data:EUR/USD"),
    ("USD/JPY", "market_data:USD/JPY"),
    ("USDJPY", "market_data:USD/JPY"),
    ("GBP/USD", "market_data:GBP/USD"),
    ("GBPUSD", "market_data:GBP/USD"),
    ("黄金", "market_data:XAU/USD"),
    ("XAU", "market_data:XAU/USD"),
    ("原油", "market_data:WTI"),
    ("WTI", "market_data:WTI"),
    ("布伦特", "market_data:BRENT"),
    ("Brent", "market_data:BRENT"),
    ("标普", "market_data:SPX"),
    ("S&P", "market_data:SPX"),
    ("纳指", "market_data:NDX"),
    ("纳斯达克", "market_data:NDX"),
    ("道指", "market_data:DJI"),
    ("比特币", "market_data:BTC/USD"),
    ("BTC", "market_data:BTC/USD"),
    ("以太坊", "market_data:ETH/USD"),
    ("ETH", "market_data:ETH/USD"),
    ("CPI", "FRED:CPIAUCSL"),
    ("通胀", "FRED:CPIAUCSL"),
    ("非农", "FRED:PAYEMS"),
    ("就业", "FRED:PAYEMS"),
    ("GDP", "FRED:GDP"),
    ("美联储", "news:FOMC_statement"),
    ("FOMC", "news:FOMC_statement"),
    ("欧央行", "news:ECB_statement"),
    ("ECB", "news:ECB_statement"),
    ("日央行", "news:BOJ_statement"),
    ("BOJ", "news:BOJ_statement"),
]


def _infer_verification_source(text: str, direction_str: str) -> str:
    """Infer verification data source from text heuristics."""
    combined = f"{text} {direction_str}".upper()
    for keyword, source in _ASSET_KEYWORDS:
        if keyword.upper() in combined:
            return source
    return "market_data:unknown"


def _infer_verification_metric(text: str, direction_str: str) -> str:
    """Infer the metric to verify (close price, level, etc.)."""
    source = _infer_verification_source(text, direction_str)
    return f"{source.split(':')[-1]} close price"
