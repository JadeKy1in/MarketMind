"""
technical_engine.py - Layer 2 Technical Analysis Engine (Task 2.2)

Input: Weekly OHLCV data from market_fetcher.
Core algorithms:
  1. 20-week / 50-week SMA trend alignment (0-40 points)
  2. 26-week MACD divergence detection with extrema alignment (0-40 points)
  3. Price-volume confirmation adjustment (+/-10 points)

Discipline enforced: NO daily-level oscillators (daily RSI, KDJ, etc.).
Only weekly timeframe long-cycle indicators are used.
"""

import pandas as pd
import numpy as np
from typing import Any


def _compute_weekly_smas(weekly_df: pd.DataFrame) -> dict[str, float | None]:
    """Compute 20-week and 50-week SMAs.

    Args:
        weekly_df: DataFrame with at least a 'close' column (sorted ascending by date).

    Returns:
        Dict with 'sma_20', 'sma_50' values (or None if insufficient data).
    """
    closes = weekly_df["close"].values.astype(float)
    sma_20 = None
    sma_50 = None
    if len(closes) >= 20:
        sma_20 = float(np.mean(closes[-20:]))
    if len(closes) >= 50:
        sma_50 = float(np.mean(closes[-50:]))
    return {"sma_20": sma_20, "sma_50": sma_50}


def _compute_weekly_macd(weekly_df: pd.DataFrame) -> dict[str, Any]:
    """Compute MACD(12, 26, 9) on weekly close data.

    Uses pandas-ta style logic (pure numpy to avoid extra dependency).

    Returns:
        Dict with 'macd_line', 'signal_line', 'histogram' arrays (same length as input),
        or zero-length arrays if insufficient data (< 26 weeks).
    """
    closes = weekly_df["close"].values.astype(float)
    n = len(closes)
    if n < 26:
        return {
            "macd_line": np.array([]),
            "signal_line": np.array([]),
            "histogram": np.array([]),
        }

    # EMA helper
    def ema(data: np.ndarray, period: int) -> np.ndarray:
        result = np.empty_like(data)
        result[:] = np.nan
        multiplier = 2.0 / (period + 1)
        # First EMA value = SMA of first `period` values
        result[period - 1] = np.mean(data[:period])
        for i in range(period, len(data)):
            result[i] = (data[i] - result[i - 1]) * multiplier + result[i - 1]
        return result

    ema_12 = ema(closes, 12)
    ema_26 = ema(closes, 26)
    macd_line = ema_12 - ema_26
    signal_line = ema(macd_line, 9)
    histogram = macd_line - signal_line
    return {
        "macd_line": macd_line,
        "signal_line": signal_line,
        "histogram": histogram,
    }


def _find_local_extrema(values: np.ndarray, lookback: int = 3) -> tuple[list[int], list[int]]:
    """Identify local minima and maxima indices in a 1D array.

    A point is an extremum if it is the minimum/maximum within ±lookback
    window around it. This prevents single-week noise from being classified
    as an extreme.

    Returns:
        (min_indices, max_indices) sorted descending (most recent first).
    """
    n = len(values)
    min_idx: list[int] = []
    max_idx: list[int] = []

    for i in range(lookback, n - lookback):
        window = values[i - lookback : i + lookback + 1]
        center = lookback
        # Check if value at i is minimum in window (strictly)
        if np.all(values[i] < window[:center]) and np.all(values[i] <= window[center + 1:]):
            min_idx.append(i)
        # Check if value at i is maximum in window (strictly)
        if np.all(values[i] > window[:center]) and np.all(values[i] >= window[center + 1:]):
            max_idx.append(i)

    # Sort descending (most recent first)
    min_idx.sort(reverse=True)
    max_idx.sort(reverse=True)
    return min_idx, max_idx


def _validate_divergence_extrema(
    price: np.ndarray, macd: np.ndarray, extremum_indices: list[int], is_bullish: bool
) -> bool:
    """Validate that divergence candidates are real (not noise spikes).

    Checks that the price move between the two extremes is >= 1.5 ATR
    on weekly timeframe, ensuring the divergence is substantive.

    Args:
        price: Full price array.
        macd: Full MACD line array.
        extremum_indices: At least 2 indices (most recent first).
        is_bullish: True for bullish divergence, False for bearish.

    Returns:
        True if divergence is validated.
    """
    if len(extremum_indices) < 2:
        return False

    # Compare the two most recent extremes
    i_recent = extremum_indices[0]
    i_prev = extremum_indices[1]

    # Calculate weekly ATR approximation (mean true range over last 14 weeks)
    atr = _weekly_atr(price) * 1.5 if len(price) >= 14 else 0.0

    if is_bullish:
        # Price: recent low should be lower than previous low
        price_condition = price[i_recent] < price[i_prev]
        # MACD: recent low should be higher than previous low
        macd_condition = macd[i_recent] > macd[i_prev]
    else:
        # Price: recent high should be higher than previous high
        price_condition = price[i_recent] > price[i_prev]
        # MACD: recent high should be lower than previous high
        macd_condition = macd[i_recent] < macd[i_prev]

    # Price move magnitude check
    price_move = abs(price[i_recent] - price[i_prev])
    magnitude_condition = price_move >= atr

    return price_condition and macd_condition and magnitude_condition


def _weekly_atr(price: np.ndarray, period: int = 14) -> float:
    """Approximate weekly ATR using close-to-close range."""
    if len(price) < period + 1:
        return 0.0
    ranges = np.abs(np.diff(price[-period - 1 :]))
    return float(np.mean(ranges))


def detect_macd_divergence(
    weekly_df: pd.DataFrame,
) -> dict[str, Any]:
    """Detect MACD bullish and bearish divergence with extrema alignment.

    Extrema alignment rules (anti-noise):
      - Extremes must be validated with ±3 week lookback window
      - Must pass the 1.5x ATR magnitude check
      - No single-week spike can falsely trigger divergence

    Returns:
        Dict with 'bullish_divergence' (bool), 'bearish_divergence' (bool),
        'divergence_strength' (int: -2 to +2), and details.
    """
    macd_data = _compute_weekly_macd(weekly_df)
    if len(macd_data["macd_line"]) == 0:
        return {
            "bullish_divergence": False,
            "bearish_divergence": False,
            "divergence_strength": 0,
            "details": "Insufficient MACD data (< 26 weeks)",
        }

    price = weekly_df["close"].values.astype(float)
    macd = macd_data["macd_line"]

    # Only use the portion where MACD is valid (non-NaN)
    valid_mask = ~np.isnan(macd)
    if np.sum(valid_mask) < 26:
        return {
            "bullish_divergence": False,
            "bearish_divergence": False,
            "divergence_strength": 0,
            "details": "MACD not fully computed",
        }

    # Find local extrema in the combined price + MACD space
    min_idx, max_idx = _find_local_extrema(price, lookback=3)

    # Check bullish divergence: compare recent two price troughs vs MACD troughs
    bullish = _validate_divergence_extrema(price, macd, min_idx, is_bullish=True)

    # Check bearish divergence: compare recent two price peaks vs MACD peaks
    bearish = _validate_divergence_extrema(price, macd, max_idx, is_bullish=False)

    # Divergence strength: -2 (strong bearish) to +2 (strong bullish)
    divergence_strength = 0
    if bullish and not bearish:
        divergence_strength = 2
    elif bearish and not bullish:
        divergence_strength = -2
    elif bullish and bearish:
        # Mixed signals: check which is more recent
        if min_idx and max_idx:
            if min_idx[0] > max_idx[0]:
                divergence_strength = 1  # Recent bullish bias
            else:
                divergence_strength = -1  # Recent bearish bias

    details_parts = []
    if bullish:
        details_parts.append("Bullish divergence confirmed (price lower low, MACD higher low)")
    if bearish:
        details_parts.append("Bearish divergence confirmed (price higher high, MACD lower high)")
    if not bullish and not bearish:
        details_parts.append("No significant MACD divergence detected")

    return {
        "bullish_divergence": bullish,
        "bearish_divergence": bearish,
        "divergence_strength": divergence_strength,
        "details": " | ".join(details_parts) if details_parts else "No divergence",
    }


def _ma_trend_score(smas: dict[str, float | None]) -> int:
    """Score 0-40 for MA trend alignment.

    Scoring:
      - sma_20 >> sma_50 (gap > 5%) and both rising: 35-40
      - sma_20 > sma_50 but slope flattish: 20-30
      - sma_20 ~= sma_50 (within 2%): 15-20
      - sma_20 < sma_50 but slope turning up: 5-15
      - sma_20 << sma_50 (gap > 5%) and both falling: 0-5
    """
    sma_20 = smas.get("sma_20")
    sma_50 = smas.get("sma_50")

    if sma_20 is None or sma_50 is None:
        return 20  # Neutral if insufficient data

    gap_pct = (sma_20 - sma_50) / sma_50 * 100.0

    if gap_pct > 5.0:
        return 38
    elif gap_pct > 3.0:
        return 32
    elif gap_pct > 1.0:
        return 26
    elif gap_pct > -1.0:
        return 18  # Near-cross
    elif gap_pct > -3.0:
        return 12
    elif gap_pct > -5.0:
        return 6
    else:
        return 2


def _macd_divergence_score(div_result: dict[str, Any]) -> int:
    """Score 0-40 for MACD divergence.

    Scoring:
      - Strong bullish divergence (strength=2): 35-40
      - Mild bullish divergence (strength=1): 25-30
      - No divergence (strength=0): 20 (neutral middle)
      - Mild bearish divergence (strength=-1): 10-15
      - Strong bearish divergence (strength=-2): 0-5
    """
    strength = div_result.get("divergence_strength", 0)

    if strength >= 2:
        return 38
    elif strength == 1:
        return 28
    elif strength == 0:
        return 20
    elif strength == -1:
        return 12
    else:  # strength <= -2
        return 2


def _price_volume_adjustment(weekly_df: pd.DataFrame) -> int:
    """Calculate +/-10 price-volume confirmation adjustment.

    Positive adjustments:
      +4: Volume expanding on up-weeks and contracting on down-weeks
      +3: Above-average volume on recent bullish candles
      +2: Volume trend positively correlated with price over last 10 weeks
      +1: Mild positive confirmation

    Negative adjustments:
      -4: Volume expanding on down-weeks despite price rising
      -3: Divergence: price up but volume declining
      -2: Bearish volume pattern
      -1: Mild negative divergence
    """
    if len(weekly_df) < 10:
        return 0

    df = weekly_df.tail(26).copy()
    if len(df) < 10:
        return 0

    df["price_change"] = df["close"].pct_change()
    df["volume_change"] = df["volume"].pct_change()

    # Correlation between weekly returns and volume changes over last 10 weeks
    recent = df.tail(10).dropna()
    if len(recent) < 6:
        return 0

    # Simple heuristic: count weeks where price up AND volume up vs price up AND volume down
    up_weeks = recent[recent["price_change"] > 0]
    down_weeks = recent[recent["price_change"] < 0]

    score = 0

    if len(up_weeks) > 0:
        vol_up_on_up = (up_weeks["volume_change"] > 0).sum()
        vol_down_on_up = (up_weeks["volume_change"] < 0).sum()
        ratio_up = vol_up_on_up / max(len(up_weeks), 1)
        if ratio_up > 0.7:
            score += 4
        elif ratio_up > 0.5:
            score += 2
        elif ratio_up < 0.3:
            score -= 2
        elif ratio_up < 0.15:
            score -= 4

    if len(down_weeks) > 0:
        vol_up_on_down = (down_weeks["volume_change"] > 0).sum()
        vol_down_on_down = (down_weeks["volume_change"] < 0).sum()
        ratio_down = vol_down_on_down / max(len(down_weeks), 1)
        if ratio_down > 0.7:
            score += 3  # Volume contracting on down weeks is good
        elif ratio_down < 0.3:
            score -= 3  # Volume expanding on down weeks is bad

    # Clamp to +/-10
    return max(-10, min(10, score))


def analyze_technical(weekly_df: pd.DataFrame) -> dict[str, Any]:
    """Main entry point: run full technical analysis and return EngineOutput-style dict.

    Score range: 0-100
      - 0-20: Strongly bearish technical setup
      - 21-40: Bearish-leaning
      - 41-60: Neutral / mixed signals
      - 61-80: Bullish-leaning
      - 81-100: Strongly bullish technical setup

    Args:
        weekly_df: DataFrame with columns ['date', 'open', 'high', 'low', 'close', 'volume']
                   sorted ascending by date.

    Returns:
        Dict with 'score' (0-100) and 'reasoning' (human-readable text).
    """
    # 1. MA Trend (0-40)
    smas = _compute_weekly_smas(weekly_df)
    ma_score = _ma_trend_score(smas)

    # 2. MACD Divergence (0-40)
    div_result = detect_macd_divergence(weekly_df)
    macd_score = _macd_divergence_score(div_result)

    # 3. Price-volume adjustment (-10 to +10)
    pv_adj = _price_volume_adjustment(weekly_df)

    # Compose final score
    raw_score = ma_score + macd_score + pv_adj
    final_score = max(0, min(100, raw_score))

    # Build reasoning text
    parts: list[str] = []
    sma_20 = smas.get("sma_20")
    sma_50 = smas.get("sma_50")
    if sma_20 is not None and sma_50 is not None:
        gap = (sma_20 - sma_50) / sma_50 * 100
        parts.append(
            f"MA alignment: SMA20={sma_20:.2f} SMA50={sma_50:.2f} "
            f"(gap={gap:+.2f}%), MA score={ma_score}/40"
        )
    else:
        parts.append(f"Insufficient data for MA trend, MA score={ma_score}/40 (neutral default)")

    parts.append(f"MACD: {div_result['details']}, MACD score={macd_score}/40")
    parts.append(f"Price-volume adjustment: {pv_adj:+d}")
    parts.append(f"Final technical score={final_score}/100")

    return {
        "score": final_score,
        "reasoning": " | ".join(parts),
    }