"""Shared fixtures for MarketMind tests."""
import pytest
import tempfile
from pathlib import Path


def pytest_configure(config):
    config.addinivalue_line(
        "filterwarnings",
        "ignore::DeprecationWarning:feedparser.*"
    )
    config.addinivalue_line(
        "markers",
        "vcr: mark test as using VCR.py cassette (may require network for first recording)",
    )
    config.addinivalue_line(
        "markers",
        "slow: real network / paid API calls; skipped unless MARKETMIND_LIVE_TESTS=1",
    )


def pytest_collection_modifyitems(config, items):
    """Real-API tests are opt-in. They used to run whenever DEEPSEEK_API_KEY was set,
    which made every local run spend tokens and take ~14 min instead of ~3."""
    import os
    if os.environ.get("MARKETMIND_LIVE_TESTS") == "1":
        return
    skip = pytest.mark.skip(reason="real API test; set MARKETMIND_LIVE_TESTS=1 to run")
    for item in items:
        if "slow" in item.keywords:
            item.add_marker(skip)


@pytest.fixture
def temp_dir():
    with tempfile.TemporaryDirectory() as td:
        yield Path(td)


@pytest.fixture
def mock_flash_response():
    return {
        "content": "Mock Flash analysis result.",
        "usage": {"total_tokens": 200, "prompt_tokens": 80, "completion_tokens": 120},
        "latency_ms": 450,
    }


@pytest.fixture
def mock_pro_response():
    return {
        "content": "Mock Pro deep analysis result with more detail.",
        "usage": {"total_tokens": 500, "prompt_tokens": 100, "completion_tokens": 400},
        "latency_ms": 3200,
    }


# ── VCR.py recording helper ────────────────────────────────────────────────
# Pass as before_record_request= to any VCR recorder. The news cassette fixtures
# (vcr_news / vcr_news_offline) live in tests/test_pipeline/conftest.py, their only
# users; the root copies were shadowed there and have been removed.


def _drop_request_body(request):
    """Request bodies can carry credentials (e.g. Bluesky createSession sent the app
    password in its JSON body, recorded 2026-05 and scrubbed 2026-09-29). Matching
    never uses the body, so it is not recorded at all."""
    request.body = None
    return request


# ── Network guard ───────────────────────────────────────────────────────────
# The offline suite must not reach the internet (real calls made it slow and
# nondeterministic, and some cost money). Any non-loopback connection or DNS
# lookup raises NetworkBlockedError unless the test is marked `slow` or
# MARKETMIND_LIVE_TESTS=1. VCR replay patches the HTTP layer, so cassette tests
# never reach a socket.

class NetworkBlockedError(RuntimeError):
    """A test tried to reach the network without being marked slow/live."""


_LOOPBACK_NAMES = {"localhost", "localhost.localdomain", "ip6-localhost", ""}


def _is_loopback(host) -> bool:
    if host is None:
        return True
    if isinstance(host, bytes):
        host = host.decode("ascii", "ignore")
    host = str(host).strip("[]").lower()
    if host in _LOOPBACK_NAMES:
        return True
    import ipaddress
    try:
        return ipaddress.ip_address(host.split("%", 1)[0]).is_loopback
    except ValueError:
        return False


def _check_address(address, what: str) -> None:
    if isinstance(address, (str, bytes)):          # AF_UNIX path
        return
    host = address[0] if isinstance(address, tuple) and address else None
    if not _is_loopback(host):
        raise NetworkBlockedError(
            f"offline test suite: {what} to {address!r} blocked. Mock the call, or mark "
            f"the test @pytest.mark.slow (runs only with MARKETMIND_LIVE_TESTS=1).")


@pytest.fixture(autouse=True)
def _block_network(request, monkeypatch):
    import os
    if os.environ.get("MARKETMIND_LIVE_TESTS") == "1" or "slow" in request.keywords:
        yield
        return
    import asyncio.proactor_events
    import asyncio.selector_events
    import socket

    real_connect, real_connect_ex = socket.socket.connect, socket.socket.connect_ex
    real_getaddrinfo = socket.getaddrinfo

    def connect(self, address):
        _check_address(address, "connect")
        return real_connect(self, address)

    def connect_ex(self, address):
        _check_address(address, "connect")
        return real_connect_ex(self, address)

    def getaddrinfo(host, *args, **kwargs):
        _check_address((host,), "DNS lookup")
        return real_getaddrinfo(host, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket.socket, "connect_ex", connect_ex)
    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)
    # asyncio's proactor loop (Windows default) connects with ConnectEx, not
    # socket.connect; an IP-literal address never goes through getaddrinfo.
    for cls in (asyncio.proactor_events.BaseProactorEventLoop,
                asyncio.selector_events.BaseSelectorEventLoop):
        real = cls.sock_connect

        async def sock_connect(self, sock, address, _real=real):
            _check_address(address, "connect")
            return await _real(self, sock, address)
        monkeypatch.setattr(cls, "sock_connect", sock_connect)
    yield


@pytest.fixture(autouse=True)
def _offline_equity_universe():
    """Tests never download the NASDAQ symbol files: the equity universe is
    'unavailable' unless a test installs its own via set_equity_universe()."""
    from marketmind.universe import reset_equity_universe, set_equity_universe
    set_equity_universe(None)
    yield
    reset_equity_universe()


@pytest.fixture(autouse=True)
def _no_alpaca_credentials(monkeypatch):
    """Price-history tests never call Alpaca with the owner's real keys; tests
    that exercise the Alpaca path set fake credentials themselves."""
    monkeypatch.delenv("ALPACA_API_KEY_ID", raising=False)
    monkeypatch.delenv("ALPACA_API_SECRET_KEY", raising=False)


@pytest.fixture(autouse=True)
def _offline_global_quotes(monkeypatch):
    """Eastmoney / Tencent / Twelve Data fallbacks never hit the network in
    tests; tests of those parsers call them with their own mock payloads."""
    from marketmind.gateway import global_quotes

    async def _none(ticker, years=5):
        return None
    monkeypatch.setattr(global_quotes, "from_eastmoney", _none)
    monkeypatch.setattr(global_quotes, "from_tencent", _none)
    monkeypatch.setattr(global_quotes, "from_twelvedata", _none)


@pytest.fixture(autouse=True)
def _no_real_claude(monkeypatch):
    """Tests never reach the owner's Claude subscription, whatever MARKETMIND_LLM
    the machine is set to (docs/LLM_PROVIDER.md); provider tests set it themselves."""
    monkeypatch.setenv("MARKETMIND_LLM", "deepseek")


@pytest.fixture(autouse=True)
def _no_run_notice_or_step_markers(monkeypatch):
    """Scheduled-run tests never open the "MarketMind is running" window
    (scripts/run_notice.py), and no test resumes from real step markers."""
    monkeypatch.setenv("MARKETMIND_RUN_NOTICE", "0")
    monkeypatch.delenv("MARKETMIND_RUN_KEY", raising=False)
    monkeypatch.delenv("MARKETMIND_STEPS_FILE", raising=False)
    # scheduled_run.main sets BLAS thread limits in os.environ; restore them after the test
    import os
    for name in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
        monkeypatch.setenv(name, os.environ.get(name, ""))


@pytest.fixture(autouse=True)
def _offline_shadow_feeds(monkeypatch):
    """Shadow runs in tests never fetch marketmind/shadow_feeds over the network;
    feed tests call their fetch functions with mocked HTTP themselves."""
    import marketmind.shadow_feeds as sf

    async def _none(entry_names, today, feeds=None):
        return {}
    monkeypatch.setattr(sf, "gather", _none)


@pytest.fixture(autouse=True)
def _isolated_data_dir(tmp_path_factory, monkeypatch):
    """Tests never write into the real data/ directory: 2026-09-29, ~2,500 test alerts were
    found in data/alerts.db. Every test gets its own data dir unless it sets one itself."""
    monkeypatch.setenv("MARKETMIND_DATA_DIR", str(tmp_path_factory.mktemp("data")))
    # runtime files under marketmind/.claude (briefs, calibration, metrics, kill-switch state)
    monkeypatch.setenv("MARKETMIND_CLAUDE_DIR", str(tmp_path_factory.mktemp("claude")))
    from marketmind.notification import alert_manager
    monkeypatch.setattr(alert_manager, "_alert_manager", None)


@pytest.fixture(autouse=True)
def _offline_binance(monkeypatch):
    """No test reaches Binance (first crypto price source): it answers 503 unless
    the test installs its own client or replaces _from_binance."""
    import httpx
    from marketmind.gateway import price_history as ph
    monkeypatch.setattr(ph, "_binance_client", lambda: httpx.AsyncClient(
        transport=httpx.MockTransport(lambda req: httpx.Response(503, text="offline"))))


@pytest.fixture(autouse=True)
def _offline_coinbase(monkeypatch):
    """No test reaches Coinbase Exchange (third crypto price fallback): when a test
    makes Binance and Bybit fail, Coinbase answers 503 unless the test installs
    its own client."""
    import httpx
    from marketmind.gateway import price_history as ph
    monkeypatch.setattr(ph, "_coinbase_client", lambda: httpx.AsyncClient(
        transport=httpx.MockTransport(lambda req: httpx.Response(503, text="offline"))))
