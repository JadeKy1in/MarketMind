"""Dashboard is local-only: Host allowlist, same-origin writes and WebSocket handshakes."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from marketmind.api.routes import app

LOCAL = "http://127.0.0.1:8520"
WS = "ws://127.0.0.1:8520/ws"


@pytest.fixture
def client() -> TestClient:
    return TestClient(app, base_url=LOCAL)


@pytest.mark.parametrize("host", ["evil.example.com", "evil.example.com:8520", "127.0.0.1.nip.io:8520",
                                  "testserver"])
def test_foreign_host_header_is_refused(client, host):
    r = client.get("/api/log", headers={"host": host})
    assert r.status_code == 400 and r.json()["error"] == "invalid host header"


@pytest.mark.parametrize("host", ["127.0.0.1:8520", "localhost:8520", "localhost", "[::1]:8520"])
def test_local_host_headers_are_served(client, host):
    assert client.get("/api/log", headers={"host": host}).status_code == 200


def test_extra_host_from_environment(client, monkeypatch):
    monkeypatch.setenv("MARKETMIND_ALLOWED_HOSTS", "mybox.lan")
    assert client.get("/api/log", headers={"host": "mybox.lan:8520"}).status_code == 200


@pytest.mark.parametrize("origin", ["http://evil.example.com", "null", "http://localhost:9999",
                                    "http://127.0.0.1:8520.evil.com"])
def test_cross_origin_post_is_refused(client, origin):
    r = client.post("/api/pipeline/progress", headers={"origin": origin}, json={"stage": "x"})
    assert r.status_code == 403 and r.json()["error"] == "cross-origin request refused"
    r = client.delete("/api/chat/history", headers={"origin": origin})
    assert r.status_code == 403


def test_same_origin_and_originless_posts_pass(client):
    assert client.post("/api/pipeline/progress", headers={"origin": LOCAL}, json={}).status_code == 200
    assert client.post("/api/pipeline/progress", json={}).status_code == 200      # local script
    assert client.post("/api/pipeline/progress", headers={"host": "localhost:8520",
                                                          "origin": "http://localhost:8520"},
                       json={}).status_code == 200


def test_cross_origin_get_is_not_blocked(client):
    # a foreign page cannot read the answer (no CORS); only Host guards reads
    assert client.get("/api/log", headers={"origin": "http://evil.example.com"}).status_code == 200


def test_holdings_write_still_needs_header(client):
    r = client.post("/api/wb/holdings", headers={"origin": LOCAL}, json={"ticker": "AAPL"})
    assert r.status_code == 403 and "X-MarketMind" in r.json()["error"]


def test_websocket_accepts_dashboard_origin(client):
    with client.websocket_connect(WS, headers={"origin": LOCAL}) as ws:
        ws.send_text("ping")
        assert ws.receive_text() == "pong"


@pytest.mark.parametrize("headers", [{"origin": "http://evil.example.com"}, {},
                                     {"origin": "http://localhost:8520"}])
def test_websocket_refuses_foreign_or_missing_origin(client, headers):
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(WS, headers=headers):
            pass
    assert exc.value.code == 1008


def test_websocket_refuses_rebound_host(client):
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(WS, headers={"host": "evil.example.com:8520",
                                                      "origin": "http://evil.example.com:8520"}):
            pass
