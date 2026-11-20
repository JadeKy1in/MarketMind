"""Main-pipeline track record vs matched_random (owner decision 2026-11-20)."""
from marketmind.ledger import comparison
from marketmind.ledger.store import LedgerEntry


def _main(eid, net, st="main", ticker="SPY", day="2026-11-01", status="settled"):
    return LedgerEntry(st, "main:l3", ticker, "long", 5, 0.6, 100, "x", entry_id=eid,
                       status=status, net_return=net if status == "settled" else None,
                       meta={"run_date": day})


def _rand(pairs_with, net, ticker="SPY", day="2026-11-01", kind="matched_random", key_only=False):
    meta = {"baseline": kind, "pairs_with": None if key_only else pairs_with,
            "pairs_key": ["main:l3", ticker, day], "run_date": day, "paired_source_type": "main"}
    return LedgerEntry("baseline", f"baseline:{kind}:main:l3", ticker, "short", 5, 0.5, 100, "b",
                       status="settled", net_return=net, meta=meta)


def test_main_only_pairs_and_line():
    rows = [_main("m1", -0.04), _rand("m1", -0.03),
            _main("m2", 0.02, ticker="QQQ"), _rand("m2", -0.01, ticker="QQQ"),
            _main("m3", -0.05, ticker="TLT", day="2026-11-02"),      # no pair
            _main("f1", 0.10, st="main_forced"), _rand("f1", -0.5),  # forced excluded
            _rand("m3", 0.9, kind="always_long"),                    # other baseline ignored
            _main("m4", None, status="pending")]                     # unsettled ignored
    rec = comparison.main_track_record(rows)
    assert rec == {"settled": 3, "wins": 1, "mean_net": round((-0.04 + 0.02 - 0.05) / 3, 6),
                   "pairs": 2, "pair_wins": 1, "mean_diff": 0.01}
    assert comparison.main_track_line(rec) == (
        "主管线未验证：已结算 3 笔，1 胜，平均 -2.33%；对同日同标的随机对照 2 对，胜 1 对，"
        "平均领先 1.00 个百分点。仅供研究，勿照做。")


def test_pairs_key_fallback_and_lagging_wording():
    rows = [_main("m1", -0.04), _rand("m1", -0.02, key_only=True)]
    line = comparison.main_track_line(comparison.main_track_record(rows))
    assert "随机对照 1 对，胜 0 对，平均落后 2.00 个百分点" in line


def test_zero_samples_line():
    assert comparison.main_track_line(comparison.main_track_record([])) == (
        "主管线未验证：已结算 0 笔，样本不足；对同日同标的随机对照 0 对，样本不足。仅供研究，勿照做。")
    line = comparison.main_track_line(comparison.main_track_record([_main("m1", -0.01)]))
    assert line.startswith("主管线未验证：已结算 1 笔，0 胜，平均 -1.00%；对同日同标的随机对照 0 对，样本不足")
