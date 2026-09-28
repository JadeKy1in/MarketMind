"""Gateway tests never reach Coinbase Exchange: when a crypto test makes Binance and
Bybit fail, the Coinbase fallback answers 503 unless the test installs its own client."""
import httpx
import pytest


@pytest.fixture(autouse=True)
def _offline_coinbase(monkeypatch):
    from marketmind.gateway import price_history as ph
    monkeypatch.setattr(ph, "_coinbase_client", lambda: httpx.AsyncClient(
        transport=httpx.MockTransport(lambda req: httpx.Response(503, text="offline"))))
