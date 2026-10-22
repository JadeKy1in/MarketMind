"""S9 step 1: global confidence calibration (docs/S9_DESIGN.md 第 1 步). Offline, no LLM."""
import json
import math
from datetime import date, timedelta

import numpy as np
import pytest

from marketmind.ledger import calibration as cal
from marketmind.ledger.store import LedgerEntry, LedgerStore


def _day(i: int) -> str:
    return (date(2026, 1, 1) + timedelta(days=i)).isoformat()


def _e(conf, win, day, *, st="shadow", sid="s:a", status="settled", default=False):
    e = LedgerEntry(st, sid, "SPY", "long", 5, conf, 100, "x", meta={"run_date": day},
                    created_at=f"{day}T10:00:00+00:00", confidence_is_default=default)
    e.status = status
    e.net_return = (0.01 if win else -0.01) if status == "settled" else None
    return e


def _const_sample(days=17, per_day=20, conf=0.55, win_rate=0.35, seed=1):
    rng = np.random.default_rng(seed)
    return [_e(conf, rng.random() < win_rate, _day(d)) for d in range(days) for _ in range(per_day)]


def _logit(p):
    return math.log(p / (1 - p))


def test_fit_intercept_recovers_the_exact_shift():
    y = [1] * 35 + [0] * 65
    off = [_logit(0.55)] * 100
    a = cal.fit_intercept(off, y)
    assert a == pytest.approx(_logit(0.35) - _logit(0.55), abs=1e-6)
    assert cal.fit_intercept(off, [1] * 100) <= 6.0          # all wins: finite, clamped


def test_constant_confidence_is_an_intercept_only_shift():
    rows = _const_sample()
    s = cal.compute(rows, b=200)
    wr = s["realized"]["win_rate"]
    assert s["sample"] == {"rows": 340, "days": 17, "first_day": _day(0), "last_day": _day(16)}
    assert s["stated"]["logit_sd"] == pytest.approx(0.0)
    assert s["slope"]["b_hat"] is None and s["slope"]["identifiable"] is False
    gm = s["global_map"]
    assert gm["status"] == "shift" and gm["b"] == 1.0
    assert gm["a_hat"] == pytest.approx(_logit(wr) - _logit(0.55), abs=1e-6)
    assert 0 < gm["a_shrink_weight"] <= 1 and abs(gm["a"]) <= abs(gm["a_hat"])
    assert gm["excludes_no_correction"] is True and gm["a_ci"][1] < 0
    assert abs(s["calibrated"]["mean"] - wr) < 0.03            # shrunk slightly toward 0.55
    res = s["resolution"]
    assert res["auc"] == pytest.approx(0.5) and res["resolution"] == pytest.approx(0.0)
    assert res["brier_calibrated_in_sample"] < res["brier_raw"]
    assert cal.calibrate(0.55, s) == pytest.approx(s["calibrated"]["mean"])
    assert "斜率固定为 1" in s["line"] and "不能区分输赢" in s["line"] and "17 个决策日 340 条" in s["line"]


def test_effective_sample_is_decision_days_not_rows():
    rows = _const_sample(days=9, per_day=100)                  # 900 rows, 9 days
    s = cal.compute(rows, b=100)
    assert s["sample"]["days"] == 9 and s["sample"]["rows"] == 900
    assert s["global_map"]["status"] == "none"
    assert cal.calibrate(0.55, s) == pytest.approx(0.55)       # identity
    assert "不做修正" in s["line"]
    s10 = cal.compute(_const_sample(days=10, per_day=5), b=100)
    assert s10["global_map"]["status"] == "shift"


def test_day_block_bootstrap_ci_reflects_day_clustering():
    # outcomes perfectly correlated within a day: a row-level CI would be far too narrow
    rng = np.random.default_rng(3)
    rows = []
    for d in range(20):
        w = rng.random() < 0.4
        rows += [_e(0.55, w, _day(d)) for _ in range(30)]
    s = cal.compute(rows, b=400)
    lo, hi = s["global_map"]["a_ci"]
    row_se = 1 / math.sqrt(600 * 0.4 * 0.6)                     # naive iid se of the intercept
    assert (hi - lo) / 3.92 > 3 * row_se


def test_slope_used_only_past_the_gate():
    rng = np.random.default_rng(7)

    def sample(days):
        out = []
        for d in range(days):
            for _ in range(10):
                c = float(rng.choice([0.3, 0.45, 0.55, 0.7, 0.85]))
                p = 1 / (1 + math.exp(-(-0.5 + 0.5 * _logit(c))))  # over-confident slope 0.5
                out.append(_e(c, rng.random() < p, _day(d)))
        return out
    s60 = cal.compute(sample(60), b=200)
    assert s60["slope"]["identifiable"] and s60["global_map"]["status"] == "platt"
    assert 1.0 > s60["global_map"]["b"] > 0.0
    assert s60["resolution"]["auc"] > 0.55
    s30 = cal.compute(sample(30), b=200)
    assert s30["slope"]["b_hat"] is not None and not s30["slope"]["identifiable"]
    assert s30["global_map"]["status"] == "shift" and s30["global_map"]["b"] == 1.0


def test_per_source_gate_is_reported_but_frozen():
    rng = np.random.default_rng(11)
    rows = [_e(0.6, rng.random() < 0.2, _day(d), sid="s:bad") for d in range(55) for _ in range(3)]
    rows += [_e(0.6, rng.random() < 0.5, _day(d), sid="s:short") for d in range(49) for _ in range(3)]
    s = cal.compute(rows, b=200)
    ps = s["per_source"]
    assert ps["enabled"] is False and ps["sources"] == 2 and ps["max_days"] == 55
    assert [x["source_id"] for x in ps["eligible"]] == ["s:bad"]    # 49 days: not even tested
    assert cal.calibrate(0.6, s, "s:bad") == pytest.approx(cal.calibrate(0.6, s))
    on = json.loads(json.dumps(s))
    on["per_source"]["enabled"] = True                            # what the gate would do
    assert cal.calibrate(0.6, on, "s:bad") < cal.calibrate(0.6, on)


def test_excluded_rows():
    base = _const_sample(days=12, per_day=2)
    extra = [_e(0.9, True, _day(0), st=t) for t in ("baseline", "benchmark", "watch_counterfactual",
                                                     "watch", "owner")]
    extra += [_e(0.9, True, _day(0), status="void"), _e(0.9, True, _day(0), default=True),
              _e(0.9, True, _day(0), st="temp_shadow", sid="missed_path:main"),
              _e(0.9, True, _day(30), status="open")]
    kept = [_e(0.6, True, _day(0), st=t, sid=f"{t}:x")
            for t in ("main", "main_forced", "temp_shadow", "playground")]
    s = cal.compute(base + extra + kept, b=50)
    assert s["sample"]["rows"] == len(base) + 4
    assert set(s["by_source_type"]) == {"shadow", "main", "main_forced", "temp_shadow", "playground"}


def test_shrinkage_toward_no_correction():
    assert cal._shrink(-1.0, 0.0) == (-1.0, 1.0)
    est, w = cal._shrink(-1.0, cal.PRIOR_SD)
    assert w == pytest.approx(0.5) and est == pytest.approx(-0.5)
    assert cal._shrink(-1.0, None) == (0.0, 0.0)


def test_auc_ties_and_murphy_identity():
    assert cal.auc([0.1, 0.2, 0.2, 0.3], [0, 0, 1, 1]) == pytest.approx(0.875)
    assert cal.auc([0.5, 0.5], [1, 1]) is None
    rng = np.random.default_rng(5)
    conf = rng.choice([0.5, 0.55, 0.6, 0.65], size=300)
    y = (rng.random(300) < 0.4).astype(float)
    m = cal.murphy(conf, y)
    assert m["reliability"] - m["resolution"] + m["uncertainty"] == pytest.approx(
        float(np.mean((conf - y) ** 2)))


def test_empty_ledger():
    s = cal.compute([], b=10)
    assert s["global_map"]["status"] == "none" and "还没有" in s["line"]
    assert cal.calibrate(0.6, s) == pytest.approx(0.6) and cal.calibrate(0.6, None) == 0.6


def test_refresh_writes_latest_and_leaves_the_ledger_unchanged(tmp_path):
    store = LedgerStore(tmp_path / "ledger.db")
    for e in _const_sample(days=11, per_day=3):
        store.add(e, created_at=e.created_at)
    for e in store.list():
        e.status, e.net_return, e.brier = "settled", -0.01, 0.3025
        store.update(e)
    before = [(e.entry_id, e.confidence, e.position_usd, e.brier, e.net_return, e.status)
              for e in store.list()]
    s = cal.refresh(store, tmp_path / "calibration")
    assert json.loads((tmp_path / "calibration" / "latest.json").read_text(encoding="utf-8"))["line"] == s["line"]
    assert [(e.entry_id, e.confidence, e.position_usd, e.brier, e.net_return, e.status)
            for e in store.list()] == before


@pytest.mark.asyncio
async def test_daily_report_shows_raw_vs_calibrated(tmp_path, monkeypatch):
    from marketmind.reports import daily
    monkeypatch.setenv("MARKETMIND_DATA_DIR", str(tmp_path))
    store = LedgerStore(tmp_path / "ledger.db")
    today = "2026-10-22"
    store.add(_e(0.6, True, today, status="pending"), created_at=f"{today}T10:00:00+00:00")
    summary = cal.compute(_const_sample(), b=100, today=today)
    cal.write(summary, tmp_path / "calibration")

    async def call(system, user):
        assert '"calibration"' in user and "你不要单独写这一节" in system
        return "## 今日要闻\n- x"
    r = await daily.build_report(today, store=store, call=call, brief_dir=tmp_path)
    md = r["markdown"]
    assert md.startswith("## 今日要闻")
    assert "## 确信度校准（代码计算，仅注释，不影响仓位）" in md and summary["line"] in md
    want = cal.calibrate(0.6, summary) * 100
    assert f"今日 LLM 决策 1 笔：自报确信度平均 60.0%，按全局校准后 {want:.1f}%" in md
    r2 = await daily.build_report(today, store=store, call=lambda s, u: (_ for _ in ()).throw(RuntimeError()),
                                  brief_dir=tmp_path)
    assert r2["source"] == "fallback" and "## 确信度校准" in r2["markdown"]


def test_report_without_calibration_file(tmp_path, monkeypatch):
    from marketmind.reports import daily
    monkeypatch.setenv("MARKETMIND_DATA_DIR", str(tmp_path))
    assert daily.calibration_facts("2026-10-22") is None
    assert daily.calibration_section({"date": "2026-10-22"}) == ""


def test_calibration_step_writes_under_the_config_data_dir(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from marketmind.pipeline import orchestration as orch
    store = LedgerStore(tmp_path / "ledger.db")
    orch._reset_step_failures()
    orch.calibration_step(SimpleNamespace(data_dir=str(tmp_path)))
    assert (tmp_path / "calibration" / "latest.json").exists() and not orch._step_failures
    monkeypatch.setattr(orch, "_ledger_store", lambda c: (_ for _ in ()).throw(OSError("x")))
    orch.calibration_step(SimpleNamespace(data_dir=str(tmp_path)))
    assert orch._step_failures == ["calibration"]
    orch._reset_step_failures()
    del store
