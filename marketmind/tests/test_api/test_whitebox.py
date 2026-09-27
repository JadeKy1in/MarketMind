"""White box v1 (docs/S4_DESIGN.md): scoreboard, providers, routes, reporter."""
import json
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from marketmind.ledger.scoreboard import score, scoreboard
from marketmind.ledger.store import LedgerEntry, LedgerStore

SHADOW = "expert:gold:bullion_broker"


def _e(source_type="shadow", source_id=SHADOW, ticker="GLD", **kw):
    return LedgerEntry(source_type=source_type, source_id=source_id, ticker=ticker,
                       direction=kw.pop("direction", "long"), hold_bars=5,
                       confidence=kw.pop("confidence", 0.6),
                       position_usd=kw.pop("position_usd", 300.0), falsifier="x", **kw)


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Temp data dir with a ledger, a brief and a shadow run report."""
    monkeypatch.setenv("MARKETMIND_DATA_DIR", str(tmp_path))
    briefs = tmp_path / "briefs"
    briefs.mkdir()
    monkeypatch.setenv("MARKETMIND_BRIEF_DIR", str(briefs))
    store = LedgerStore(tmp_path / "ledger.db")
    ids = {}
    ids["win"] = store.add(_settled(_e(), 0.05, 15.0))
    ids["loss"] = store.add(_settled(_e(position_usd=100.0), -0.02, -2.0))
    ids["open"] = store.add(_e(ticker="SLV"))
    ids["bench"] = store.add(_settled(_e("benchmark", f"random:{SHADOW}"), 0.01, 1.0))
    ids["main"] = store.add(_e("main", "pipeline", ticker="NVDA"))
    (briefs / "2026-09-26.json").write_text(json.dumps({"date": "2026-09-26"}), "utf-8")
    (briefs / "2026-09-27.json").write_text(json.dumps(
        {"date": "2026-09-27", "has_no_trade": True, "decision_summary": "不交易",
         "decision_cards": [], "l3_green": ["NEM"]}), "utf-8")
    runs = tmp_path / "shadows" / "v3_runs"
    runs.mkdir(parents=True)
    (runs / "2026-09-27.json").write_text(json.dumps([
        {"results": [{"shadow_id": SHADOW, "status": "failed", "errors": ["bad json"]}]},
        {"results": [{"shadow_id": SHADOW, "status": "submitted", "errors": []}]}]), "utf-8")
    return store, ids, tmp_path


def _settled(e, net, pnl):
    e.status = "settled"
    e.net_return, e.pnl_usd = net, pnl
    e.excess_market, e.excess_domain = net - 0.01, net - 0.02
    e.brier = (e.confidence - (1.0 if net > 0 else 0.0)) ** 2
    e.price_source = "yfinance"
    e.settled_at = "2026-09-28T01:00:00+00:00"
    return e


# ── scoreboard ──────────────────────────────────────────────────────────────

def test_score_uses_settled_rows_only():
    rows = [_settled(_e(), 0.04, 12.0), _settled(_e(position_usd=100), -0.02, -2.0), _e()]
    for r in rows:
        r.created_at = "2026-09-27T10:00:00+00:00"
    s = score(rows)
    assert (s.records, s.settled, s.pending, s.wins) == (3, 2, 1, 1)
    assert s.win_rate == 0.5 and s.mean_net_return == pytest.approx(0.01)
    assert s.total_pnl_usd == 10.0 and s.min_position_share == pytest.approx(1 / 3, abs=1e-4)
    assert s.active_days == 1 and s.first_date == "2026-09-27"


def test_score_without_settled_rows_is_none_not_zero():
    s = score([_e()])
    assert s.win_rate is None and s.mean_net_return is None and s.mean_brier is None
    assert s.total_pnl_usd is None


def test_scoreboard_groups_by_source():
    board = scoreboard([_e(), _e("benchmark", f"random:{SHADOW}"), _e()])
    assert [(s.source_type, s.records) for s in board] == [("benchmark", 1), ("shadow", 2)]


# ── providers ───────────────────────────────────────────────────────────────

def test_ledger_filters_and_counts(env):
    from marketmind.api import whitebox
    store, ids, _ = env
    d = whitebox.get_ledger(source_type="shadow")
    assert d["total"] == 3 and d["status_counts"] == {"settled": 2, "pending": 1}
    assert whitebox.get_ledger(ticker="slv")["entries"][0]["entry_id"] == ids["open"]
    assert whitebox.get_ledger(limit=2)["limit"] == 2


def test_entry_detail_and_missing(env):
    from marketmind.api import whitebox
    _, ids, _ = env
    assert whitebox.get_entry(ids["win"])["entry"]["ticker"] == "GLD"
    assert whitebox.get_entry("0" * 16)["available"] is False


def test_brief_falls_back_to_latest(env):
    from marketmind.api import whitebox
    d = whitebox.get_brief()
    assert d["date"] == "2026-09-27" and d["dates"] == ["2026-09-26", "2026-09-27"]
    assert whitebox.get_brief("2026-01-01")["available"] is False


def test_arena_pairs_shadow_with_its_random_benchmark(env):
    from marketmind.api import whitebox
    d = whitebox.get_arena()
    row = next(r for r in d["shadows"] if r["shadow_id"] == SHADOW)
    assert row["score"]["records"] == 3 and row["score"]["settled"] == 2
    assert row["random_benchmark"]["mean_net_return"] == pytest.approx(0.01)
    assert row["last_run"]["status"] == "submitted"        # later run wins
    assert [s["source_type"] for s in d["other_sources"]] == ["main"]
    blocked = next(r for r in d["shadows"] if r["roster_status"] != "active")
    assert blocked["score"] is None


def test_promotion_log_is_honest_about_s7(env):
    from marketmind.api import whitebox
    d = whitebox.get_promotion_log()
    assert d["review_implemented"] is False and d["events"] == []
    row = next(r for r in d["rows"] if r["shadow_id"] == SHADOW)
    assert row["stage"] == "见习" and row["active_days"] == 1 and row["probation_days"] == 60
    assert any(r["stage"] == "暂缓" for r in d["rows"])


def test_health_and_token_usage(env):
    from marketmind.api import whitebox
    from marketmind.gateway import usage_tracker
    _, _, tmp = env
    usage_tracker.reset()
    usage_tracker.record({"usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}})
    usage_tracker.append_log("daily")
    usage_tracker.reset()
    h = whitebox.get_health()
    assert h["ledger"]["records"] == 5 and h["ledger"]["price_sources"] == {"yfinance": 3}
    assert h["latest_brief"] == "2026-09-27" and h["shadow_run"]["submitted"] == 1
    assert h["token_usage"][-1]["mode"] == "daily"
    assert h["token_usage"][-1]["total"]["total_tokens"] == 15


def test_cost_reads_todays_usage_log(env):
    from marketmind.api.data_providers import get_cost
    from marketmind.gateway import usage_tracker
    assert get_cost()["tokens_used"] == 0
    usage_tracker.reset()
    usage_tracker.record({"usage": {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10}})
    usage_tracker.append_log("shadows")
    usage_tracker.reset()
    c = get_cost()
    assert c["tokens_used"] == 10 and c["calls"] == 1 and c["runs"] == 1


def test_missing_ledger_is_reported(tmp_path, monkeypatch):
    from marketmind.api import whitebox
    monkeypatch.setenv("MARKETMIND_DATA_DIR", str(tmp_path))
    assert whitebox.get_ledger()["available"] is False
    assert whitebox.get_arena()["available"] is False


# ── routes ──────────────────────────────────────────────────────────────────

@pytest.fixture
def client():
    from marketmind.api.routes import app
    return TestClient(app)


def test_routes_serve_whitebox_and_legacy(client, env):
    r = client.get("/")
    assert r.status_code == 200 and "MarketMind 白箱" in r.text
    assert client.get("/legacy").status_code == 200
    for path in ("/api/wb/brief", "/api/wb/ledger", "/api/wb/arena", "/api/wb/promotion",
                 "/api/wb/health"):
        assert client.get(path).status_code == 200, path
    _, ids, _ = env
    assert client.get(f"/api/wb/ledger/{ids['win']}").json()["entry"]["entry_id"] == ids["win"]
    assert client.get("/api/wb/ledger?status=pending").json()["total"] == 2


# ── reporter ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_reporter_flags_ids_not_in_ledger(env):
    from marketmind.api import reporter
    _, ids, _ = env
    fake = AsyncMock(return_value={"content": f"赢的一笔是 [{ids['win']}]，另见 [deadbeefdeadbeef]。"})
    with patch("marketmind.api.reporter._ensure_gateway"), \
         patch("marketmind.gateway.async_client.chat_flash", fake):
        r = await reporter.ask(f"GLD 的记录 {ids['win']} 怎么样？")
    assert r["unknown_ids"] == ["deadbeefdeadbeef"] and "代码核对" in r["answer"]
    prompt = fake.call_args.args[1]
    assert ids["win"] in prompt and "records_matching_question" in prompt


@pytest.mark.asyncio
async def test_reporter_without_llm_key_says_so(env):
    from marketmind.api import reporter
    with patch("marketmind.api.reporter._ensure_gateway", side_effect=RuntimeError("no key")):
        r = await reporter.ask("今天怎么样")
    assert r["error"] == "llm_unavailable" and "DEEPSEEK_API_KEY" in r["answer"]


@pytest.mark.asyncio
async def test_reporter_empty_question():
    from marketmind.api import reporter
    assert (await reporter.ask("  "))["error"] == "question is required"


def test_render_context_truncates_recent_rows():
    from marketmind.api import reporter
    ctx = {"recent_records": [{"thesis": "x" * 1000} for _ in range(200)]}
    text, truncated = reporter.render_context(ctx)
    assert truncated and len(text) <= reporter.CONTEXT_MAX_CHARS


def test_date_parameter_cannot_escape_folder(env):
    from marketmind.api import whitebox
    for bad in ("../../config", "C:/Windows/win", "2026-09-27/../x"):
        assert whitebox.get_brief(bad)["available"] is False
        assert whitebox.get_evidence(bad)["available"] is False


def test_citation_check_catches_ids_next_to_chinese(env):
    from marketmind.api import reporter
    _, ids, _ = env
    text = f"记录{ids['win']}的收益，另见记录abcdef0123456789的收益和 ABCDEF0123456789 以及 12345"
    unknown = reporter.check_citations(text)
    assert ids["win"] not in unknown
    assert "abcdef0123456789" in unknown and "ABCDEF0123456789" in unknown
    assert "12345" not in unknown


@pytest.mark.asyncio
async def test_reporter_tolerates_bad_history(env):
    from marketmind.api import reporter
    fake = AsyncMock(return_value={"content": "ok"})
    with patch("marketmind.api.reporter._ensure_gateway"),          patch("marketmind.gateway.async_client.chat_flash", fake):
        r = await reporter.ask("hi", history="not a list")
    assert r["answer"] == "ok"


def test_alerts_read_from_db(env):
    from marketmind.api import whitebox
    from marketmind.notification.alert_log import AlertLog
    _, _, tmp = env
    log = AlertLog(str(tmp / "alerts.db"))
    log.insert({"id": "a1", "severity": "WARN", "source": "holdings", "impact_scope": "NONE",
                "title": "持仓巡检：X 建议离场", "detail": "", "action_advice": "",
                "degraded_output": 0, "timestamp": "2026-09-28T01:00:00", "resolved": 0,
                "repeat_count": 1})
    assert whitebox.get_alerts(source="holdings")["alerts"][0]["title"].startswith("持仓巡检")
    assert whitebox.get_health()["alerts"][0]["id"] == "a1"
