"""API route tests using FastAPI TestClient with mocked data providers.

Patch targets are in marketmind.api.routes namespace because routes.py uses
`from marketmind.api.data_providers import <name>` — the names are bound
in routes, not in data_providers.
"""
from __future__ import annotations

import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient

from marketmind.api.routes import app


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


def _mock_inject_result():
    from marketmind.pipeline.info_injector import InjectedItem, InjectionResult
    r = InjectionResult()
    r.items = [InjectedItem(
        content="test content", source_type="user_text",
        source_label="test", char_count=12, timestamp="2026-05-22T00:00:00Z",
    )]
    r.total_chars = 12
    return r


COST_MOCK = {
    "pro_calls": 5, "pro_limit": 50,
    "flash_calls": 20, "flash_limit": 100,
    "tokens_used": 50000, "token_budget": 2_000_000,
    "monthly_est": 42.5, "circuit_breaker": "closed",
}


# ── Health ────────────────────────────────────────────────────────────

def test_health_returns_ok(client):
    with patch("marketmind.api.routes.get_health") as m:
        m.return_value = {"status": "ok", "uptime": "1:00:00", "sources_ok": 10, "sources_total": 10}
        r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_health_internal_error(client):
    """Health handler has no try/except — provider error propagates as 500."""
    with patch("marketmind.api.routes.get_health", side_effect=RuntimeError("DB down")):
        with pytest.raises(RuntimeError, match="DB down"):
            client.get("/api/health")


# ── Cost ──────────────────────────────────────────────────────────────

def test_cost_returns_structure(client):
    with patch("marketmind.api.routes.get_cost", return_value=COST_MOCK):
        r = client.get("/api/cost")
    assert r.status_code == 200
    data = r.json()
    assert data["pro_calls"] == 5
    assert data["flash_limit"] == 100
    assert data["circuit_breaker"] == "closed"


def test_cost_db_unavailable(client):
    with patch("marketmind.api.routes.get_cost", side_effect=Exception("DB down")):
        r = client.get("/api/cost")
    assert r.status_code == 200
    assert r.json() == {"status": "error"}


# ── Portfolio ─────────────────────────────────────────────────────────

def test_portfolio_returns_positions(client):
    mock = {
        "positions": [{"symbol": "AAPL", "qty": 10, "market_value": 1500}],
        "total_value": 1500, "cash_pct": 98.5, "patrol_status": "idle",
        "updated": "2026-05-22T00:00:00Z",
    }
    with patch("marketmind.api.routes.get_portfolio", return_value=mock):
        r = client.get("/api/portfolio")
    assert r.status_code == 200
    data = r.json()
    assert len(data["positions"]) == 1
    assert data["positions"][0]["symbol"] == "AAPL"


def test_portfolio_db_unavailable(client):
    with patch("marketmind.api.routes.get_portfolio", side_effect=Exception("DB down")):
        r = client.get("/api/portfolio")
    assert r.status_code == 200
    data = r.json()
    assert data["positions"] == []
    assert data["cash_pct"] == 100


# ── Shadows Overview ──────────────────────────────────────────────────

def test_shadow_overview_returns_tiers(client):
    mock = {"tiers": {"elite": 2, "excellent": 3, "normal": 6, "endangered": 0},
            "total": 11, "graduates": 2, "evolutions_today": 0, "challenger_trials": 0, "diversity": "normal"}
    with patch("marketmind.api.routes.get_shadow_overview", return_value=mock):
        r = client.get("/api/shadows/overview")
    assert r.status_code == 200
    assert r.json()["tiers"]["elite"] == 2


def test_shadow_overview_db_unavailable(client):
    with patch("marketmind.api.routes.get_shadow_overview", side_effect=Exception("DB down")):
        r = client.get("/api/shadows/overview")
    assert r.status_code == 200
    assert r.json() == {"tiers": {}, "total": 0, "graduates": 0}


# ── Shadows Rankings ──────────────────────────────────────────────────

def test_shadow_rankings_returns_top5(client):
    mock = {"top5": [{"name": "Alpha", "tier": "elite", "score": 0.95}]}
    with patch("marketmind.api.routes.get_shadow_rankings", return_value=mock):
        r = client.get("/api/shadows/rankings")
    assert r.status_code == 200
    assert r.json()["top5"][0]["name"] == "Alpha"


def test_shadow_rankings_db_unavailable(client):
    with patch("marketmind.api.routes.get_shadow_rankings", side_effect=Exception("DB down")):
        r = client.get("/api/shadows/rankings")
    assert r.status_code == 200
    assert r.json() == {"top5": []}


# ── Decision History ──────────────────────────────────────────────────

def test_decision_history_returns_decisions(client):
    mock = {"decisions": [{"date": "2026-05-22", "ticker": "NVDA", "direction": "long",
                           "confidence": 0.85, "result": "pending"}]}
    with patch("marketmind.api.routes.get_decision_history", return_value=mock):
        r = client.get("/api/history/decisions")
    assert r.status_code == 200
    assert r.json()["decisions"][0]["ticker"] == "NVDA"


def test_decision_history_db_unavailable(client):
    with patch("marketmind.api.routes.get_decision_history", side_effect=Exception("DB down")):
        r = client.get("/api/history/decisions")
    assert r.status_code == 200
    assert r.json() == {"decisions": []}


# ── Info Inject ───────────────────────────────────────────────────────

def test_info_inject_post_returns_ok(client):
    with patch("marketmind.pipeline.info_injector.inject_user_info", return_value=_mock_inject_result()), \
         patch("marketmind.api.routes.add_log_entry"):
        r = client.post("/api/info/inject", json={"text": "NVDA looks bullish", "files": []})
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert data["items"] == 1


def test_info_inject_empty_text(client):
    from marketmind.pipeline.info_injector import InjectionResult
    with patch("marketmind.pipeline.info_injector.inject_user_info", return_value=InjectionResult()), \
         patch("marketmind.api.routes.add_log_entry"):
        r = client.post("/api/info/inject", json={"text": "", "files": []})
    assert r.status_code == 200
    assert r.json()["items"] == 0


# ── Dashboard ─────────────────────────────────────────────────────────

def test_dashboard_returns_html(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]


# ── Log ───────────────────────────────────────────────────────────────

def test_log_returns_entries(client):
    mock = [{"time": "12:00:00", "level": "info", "message": "System started"}]
    with patch("marketmind.api.routes.get_log_entries", return_value=mock):
        r = client.get("/api/log")
    assert r.status_code == 200
    assert r.json()["entries"][0]["level"] == "info"
