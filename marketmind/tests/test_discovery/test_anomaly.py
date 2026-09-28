"""Discovery anomaly statistics and news coverage (docs/S10_DESIGN.md §1)."""
from datetime import date, timedelta

import pytest

from marketmind.discovery.anomaly import AnomalyConfig, compute_stats, is_stale, news_coverage


def _daily(values, end="2026-09-25"):
    """Consecutive calendar days ending at `end` (weekends included: stats only use order)."""
    e = date.fromisoformat(end)
    n = len(values)
    return [((e - timedelta(days=n - 1 - i)).isoformat(), float(v)) for i, v in enumerate(values)]


def _weekly(values, end="2026-09-23"):
    e = date.fromisoformat(end)
    n = len(values)
    return [((e - timedelta(weeks=n - 1 - i)).isoformat(), float(v)) for i, v in enumerate(values)]


def _zigzag(n, base=100.0, amp=1.0):
    return [base + (amp if i % 2 else -amp) for i in range(n)]


def test_quiet_series_is_not_an_anomaly():
    s = compute_stats(_daily(_zigzag(300)), "daily")
    assert s.window == 5
    assert s.z is not None and abs(s.z) < 2
    assert 5 < s.level_pct < 95
    assert not s.new_high and not s.new_low
    assert s.triggers == [] and not s.is_anomaly and s.move == 0


def test_jump_triggers_z_and_new_high_with_upward_move():
    vals = _zigzag(300) + [110.0]
    s = compute_stats(_daily(vals), "daily")
    assert s.change == pytest.approx(110.0 - vals[-6])
    assert s.z > 2
    assert s.level_pct == 100.0 and s.new_high
    assert set(s.triggers) >= {"z", "level_high", "new_high"}
    assert s.move == 1


def test_drop_triggers_low_side_and_downward_move():
    s = compute_stats(_daily(_zigzag(300) + [90.0]), "daily")
    assert s.z < -2 and s.new_low and s.level_pct == 0.0
    assert "level_low" in s.triggers and s.move == -1


def test_level_extreme_with_a_normal_change_is_not_an_anomaly():
    # steady walk: the latest value is high in the range but the change is normal (z ~ 0.4)
    vals = [100 + (i % 20) for i in range(300)] + [118.6]
    s = compute_stats(_daily(vals), "daily")
    assert s.level_pct >= 95 and not s.new_high and abs(s.z) < 1
    assert s.triggers == [] and not s.is_anomaly


def test_level_extreme_counts_with_a_moderately_unusual_change():
    vals = [100 + (i % 20) for i in range(300)] + [118.6]
    s = compute_stats(_daily(vals), "daily", AnomalyConfig(level_needs_z=0.3))
    assert "level_high" in s.triggers and s.move == 1


def test_thresholds_come_from_config():
    vals = _zigzag(300) + [103.5]
    loose = compute_stats(_daily(vals), "daily")
    strict = compute_stats(_daily(vals), "daily", AnomalyConfig(z_threshold=50, pct_high=101.0,
                                                               pct_low=-1.0))
    assert loose.is_anomaly
    # new_high is not a threshold, so only it remains
    assert strict.triggers == ["new_high"]


def test_frequency_windows_and_overrides():
    assert compute_stats(_weekly(_zigzag(60)), "weekly").window == 4
    assert compute_stats(_weekly(_zigzag(60)), "monthly").window == 3
    assert compute_stats(_weekly(_zigzag(60)), "weekly", window=1).window == 1


def test_lookback_limits_the_distribution():
    # an old spike outside the 1-year lookback must not dampen today's z / hide a new high
    old = _daily([100.0] * 10 + [200.0] + _zigzag(500), end="2026-09-24")
    s = compute_stats(old + [("2026-09-25", 110.0)], "daily")
    assert s.lookback_start == "2025-09-25"
    assert s.new_high and s.z > 2


def test_short_history_reports_level_only():
    s = compute_stats(_daily([1.0, 2.0, 3.0, 50.0]), "daily")
    assert s.latest == 50.0 and s.z is None and s.level_pct is None
    assert not s.is_anomaly and "too little history" in s.note
    one = compute_stats([("2026-09-25", 7.0)], "weekly")
    assert one.latest == 7.0 and one.change is None and one.triggers == []


def test_min_history_days_blocks_stats_on_dense_but_short_series():
    # 40 daily observations: enough count, not enough span (60 days)
    s = compute_stats(_daily(_zigzag(40) + [150.0]), "daily")
    assert s.z is None and s.level_pct is None and not s.is_anomaly
    s2 = compute_stats(_daily(_zigzag(40) + [150.0]), "daily", AnomalyConfig(min_history_days=10))
    assert s2.is_anomaly and s2.short_history


def test_zero_dispersion_gives_no_z():
    s = compute_stats(_daily([0.0] * 200), "daily")
    assert s.z is None and s.level_pct == 50.0 and not s.is_anomaly
    assert "zero dispersion" in s.note


def test_is_stale_by_frequency():
    today = date(2026, 9, 28)
    assert not is_stale("2026-09-23", "weekly", today)
    assert is_stale("2026-08-01", "weekly", today)
    assert is_stale("2026-09-10", "daily", today)
    assert not is_stale("2026-08-01", "monthly", today)


# ── coverage ────────────────────────────────────────────────────────────────

def test_news_coverage_counts_recent_keyword_hits_case_insensitively():
    today = date(2026, 9, 28)
    news = [
        {"title": "Bank RESERVES fall again", "summary": "", "published_at": "2026-09-27T10:00:00Z"},
        {"title": "Markets", "summary": "reserve balances at the Fed dipped",
         "published_at": "Sat, 26 Sep 2026 08:00:00 GMT"},
        {"title": "Bank reserves story", "summary": "", "published_at": "2026-09-01T10:00:00Z"},  # too old
        {"title": "Unrelated", "summary": "oil"},
        {"title": "美联储银行准备金下降", "summary": ""},                          # undated counts
    ]
    kws = ("bank reserves", "reserve balances", "银行准备金")
    assert news_coverage(news, kws, today) == 3
    assert news_coverage(news, kws, today, days=30) == 4
    assert news_coverage([], kws, today) == 0
    assert news_coverage(news, (), today) == 0


def test_news_coverage_ascii_keywords_match_whole_words_and_objects():
    class Item:
        def __init__(self, title, summary="", published_at=""):
            self.title, self.summary, self.published_at = title, summary, published_at
    today = date(2026, 9, 28)
    items = [Item("Power outage hits exchange"), Item("TGA rebuild drains cash"),
             Item("The tga balance", published_at="2026-09-28T01:00:00+00:00")]
    assert news_coverage(items, ("TGA",), today) == 2
