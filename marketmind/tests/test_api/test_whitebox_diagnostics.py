"""White box: ecosystem health, promotion diagnostics and Playground pages (read functions + routes)."""
import json

import pytest
from fastapi.testclient import TestClient

from marketmind.ecosystem import run_ecosystem
from marketmind.ledger.store import LedgerEntry, LedgerStore
from marketmind.shadows.v3 import roster

DAYS = ("2026-01-05", "2026-01-06", "2026-01-07")


@pytest.fixture
def data(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKETMIND_DATA_DIR", str(tmp_path))
    return tmp_path


def _herding_ledger(tmp):
    """Every active roster shadow long SPY on three days, trend WATCH: a behavioural herd."""
    store = LedgerStore(tmp / "ledger.db")
    for d in DAYS:
        for r in roster.active(tmp):
            store.add(LedgerEntry(source_type="shadow", source_id=r.shadow_id, ticker="SPY",
                                  direction="long", hold_bars=1, confidence=0.55, position_usd=100.0,
                                  falsifier="x", meta={"run_date": d, "llm": "m"}),
                      created_at=f"{d}T15:00:00Z")
    (tmp / "trend").mkdir()
    for d in DAYS:
        (tmp / "trend" / f"{d}.json").write_text(json.dumps({"full": {"SPY": {"state": "WATCH"}}}),
                                                 encoding="utf-8")
    return store


# ── ecosystem ───────────────────────────────────────────────────────────────

def test_ecosystem_missing_report_says_so(data):
    from marketmind.api import whitebox
    d = whitebox.get_ecosystem()
    assert d["available"] is False and "生态健康尚未运行" in d["reason"]
    assert whitebox.get_ecosystem("bad")["available"] is False


def test_ecosystem_view_of_a_real_report(data):
    from marketmind.api import whitebox
    _herding_ledger(data)
    doc = run_ecosystem(data, today="2026-01-07")
    d = whitebox.get_ecosystem()
    assert d["available"] and d["date"] == "2026-01-07" and d["summary"] == doc["summary"]
    flag = d["herding"]["flags"][0]
    assert (flag["group"], flag["direction"], flag["verdict"]) == ("us_equity_index", "long", "behavioural")
    # three days of data: P&L N_eff is insufficient and says why, trends are insufficient
    pnl = d["diversity"]["pnl"]
    assert pnl["n_eff"] is None and pnl["note"] and pnl["unexpected_clusters"] == []
    assert d["degradation"]["beat_random_trend"]["trend"] == "insufficient"
    assert d["homogenisation"]["llm"]["flag"] is True
    assert d["homogenisation"]["news_source"]["status"] == "not_recorded"
    assert d["integrity"]["zombies"] == [] and d["integrity"]["orphans"] == []
    assert d["stagnation"]["flags"] == [] and d["stagnation"]["insufficient"] > 0
    assert whitebox.get_ecosystem("2026-01-07")["date"] == "2026-01-07"
    assert whitebox.get_ecosystem("2026-01-08")["available"] is False


def test_ecosystem_marks_unexpected_duplicate_clusters(data):
    from marketmind.api import whitebox
    (data / "ecosystem").mkdir()
    (data / "ecosystem" / "2026-01-07.json").write_text(json.dumps({
        "date": "2026-01-07", "summary": "[ecosystem] x",
        "diversity": {"pnl": {"eligible": 5, "n_eff": 3.2, "clusters": [
            {"members": ["a", "b"], "expected": False}, {"members": ["c", "trial:c1"], "expected": True}]},
            "direction": {"eligible": 0, "n_eff": None, "note": "needs >= 2 actors"}}}), encoding="utf-8")
    d = whitebox.get_ecosystem()
    assert d["diversity"]["pnl"]["unexpected_clusters"] == [{"members": ["a", "b"], "expected": False}]
    assert d["diversity"]["direction"]["n_eff"] is None and d["diversity"]["direction"]["note"]
    assert d["herding"]["flags"] == [] and d["integrity"]["zombies"] == []


# ── promotion diagnostics ───────────────────────────────────────────────────

FACTORS_OK = {
    "status": "ok", "source": "french", "factors": ["MKT", "SMB", "HML"], "window": ["2026-01-02", "2026-06-30"],
    "obs": 120, "alpha_annual": 0.083, "alpha_t": 2.4, "alpha_p": 0.02,
    "betas": {"MKT": {"beta": 0.9, "se": 0.1, "t": 9.0}, "SMB": {"beta": 0.1, "se": 0.2, "t": 0.5},
              "HML": {"beta": -0.4, "se": 0.1, "t": -4.0}},
    "r2": 0.61, "adj_r2": 0.6, "meaningful": True, "notes": [],
    "drift": {"status": "ok", "flags": ["HML"], "flags_family": []}}
PAPER_LIVE_OK = {"status": "ok", "trades": 45, "record_days": 70, "extra_cost_mean": 0.0012,
                 "extra_cost_median_bps": 9.5, "paper_mean_excess_domain": 0.004,
                 "live_mean_excess_domain": 0.0028, "unknown_cost": 0,
                 "capacity": {"adv_share": 0.01, "breaches": 2, "priced": 40, "capacity_usd_p10": 55000.0},
                 "live_ready": True, "live_ready_checks": {"sample": True, "capacity": True}}


def _state(tmp, **extra):
    (tmp / "promotion").mkdir(exist_ok=True)
    (tmp / "promotion" / "state.json").write_text(json.dumps(
        {"updated_at": "2026-09-28", **extra}), encoding="utf-8")


def test_diagnostics_missing_is_reported(data):
    from marketmind.api import whitebox
    d = whitebox.get_diagnostics()
    assert d["available"] is False and d["rows"] == [] and "因子诊断" in d["reason"]


def test_diagnostics_rows_ok_and_insufficient(data):
    from marketmind.api import whitebox
    _state(data, diagnostics_meta={"french_last_day": "2026-06-30"}, diagnostics={
        "S": {"factors": FACTORS_OK, "paper_live": PAPER_LIVE_OK},
        "T": {"factors": {"status": "insufficient", "reason": "< 40 daily observations", "obs": 12},
              "paper_live": {"status": "insufficient", "trades": 3, "live_ready": False,
                             "live_ready_checks": {"sample": False}}}})
    d = whitebox.get_diagnostics()
    assert d["available"] and d["meta"]["french_last_day"] == "2026-06-30"
    s, t = d["rows"]
    f, p = s["factors"], s["paper_live"]
    assert f["alpha_annual"] == pytest.approx(0.083) and f["alpha_t"] == 2.4 and f["r2"] == 0.61
    assert [b["factor"] for b in f["main_betas"]] == ["MKT", "HML", "SMB"]     # by |t|
    assert f["drift"]["flags"] == ["HML"]
    assert p["extra_cost_mean_bps"] == pytest.approx(12.0) and p["capacity_breaches"] == 2
    assert p["live_ready"] is True
    assert t["factors"] == {"status": "insufficient", "reason": "< 40 daily observations", "obs": 12,
                            "window": None}
    assert t["paper_live"]["status"] == "insufficient" and t["paper_live"]["live_ready"] is False


# ── Playground ─────────────────────────────────────────────────────────────

def test_playground_agents_counts_stage_and_pair(data):
    from marketmind.api import whitebox
    store = LedgerStore(data / "ledger.db")
    for i, (t, status) in enumerate((("SPY", "pending"), ("QQQ", "open"), ("TLT", "pending"))):
        e = LedgerEntry(source_type="playground", source_id="playground:memory_desk", ticker=t,
                        direction="long", hold_bars=5, confidence=0.6, position_usd=300.0,
                        falsifier="x", meta={"run_date": f"2026-09-2{i}"})
        e.status = status
        store.add(e, created_at=f"2026-09-2{i}T15:00:00Z")
    store.add(LedgerEntry(source_type="playground", source_id="playground:ghost", ticker="SPY",
                          direction="short", hold_bars=5, confidence=0.6, position_usd=300.0, falsifier="x"))
    _state(data, shadows={"playground:memory_desk": {"stage": "probation", "metrics": {}}})
    d = whitebox.get_playground()
    assert d["available"] and d["ledger"]
    ids = [a["agent_id"] for a in d["agents"]]
    assert ids.index("memory_desk_control") == ids.index("memory_desk") + 1
    assert ["memory_desk", "memory_desk_control"] in d["pairs"]
    md = next(a for a in d["agents"] if a["agent_id"] == "memory_desk")
    assert md["records"] == 3 and md["status_counts"] == {"pending": 2, "open": 1}
    assert md["latest"][0]["ticker"] == "TLT" and md["stage"] == "见习"
    assert md["pair_with"] == "memory_desk_control" and md["is_control"] is False
    assert md["primary_metric"] and md["domain_benchmark"] and md["author"]
    ctl = next(a for a in d["agents"] if a["agent_id"] == "memory_desk_control")
    assert ctl["is_control"] and ctl["records"] == 0 and ctl["stage"] is None and ctl["latest"] == []
    assert d["unknown_sources"] == [{"source_id": "playground:ghost", "records": 1}]


def test_playground_without_ledger(data):
    from marketmind.api import whitebox
    d = whitebox.get_playground()
    assert d["available"] and d["ledger"] is False
    assert all(a["records"] == 0 for a in d["agents"])


# ── routes and page ─────────────────────────────────────────────────────────

def test_new_routes_and_page_tabs(data):
    from marketmind.api.routes import app
    client = TestClient(app, base_url="http://127.0.0.1:8520")
    for path in ("/api/wb/ecosystem", "/api/wb/diagnostics", "/api/wb/playground"):
        r = client.get(path)
        assert r.status_code == 200 and "available" in r.json(), path
    assert client.get("/api/wb/ecosystem?date=2026-01-07").json()["available"] is False
    page = client.get("/").text
    for token in ('id="s-ecosystem"', 'id="s-playground"', "/api/wb/ecosystem", "/api/wb/diagnostics",
                  "/api/wb/playground", "生态健康"):
        assert token in page, token
