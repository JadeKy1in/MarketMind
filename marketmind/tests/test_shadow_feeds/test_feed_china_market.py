"""Offline tests: akshare China gateway and the china_market feed (owner decision 2026-09-29).
Payload shapes copy the live responses checked 2026-09-29.
"""
import asyncio

import httpx
import pytest

from marketmind.gateway import china_akshare
from marketmind.shadow_feeds import china_market


@pytest.fixture(autouse=True)
def _data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKETMIND_DATA_DIR", str(tmp_path))
    return tmp_path


def _transport(monkeypatch, module, handler, calls=None):
    def h(req):
        if calls is not None:
            calls.append(str(req.url))
        return handler(req)
    monkeypatch.setattr(module, "_TRANSPORT", httpx.MockTransport(h))


# ── akshare (China) ─────────────────────────────────────────────────────────

class FakeAk:
    __version__ = "9.9.9"

    def __init__(self, fail=()):
        self.fail = set(fail)
        self.threads = set()

    def _rows(self, name, rows):
        import threading
        self.threads.add(threading.current_thread().name)
        if name in self.fail:
            raise ConnectionError("Remote end closed connection without response")
        return rows

    def stock_zh_index_daily(self, symbol):
        base = {"sh000300": 4000.0}.get(symbol, 3000.0)
        return self._rows(symbol, [{"date": f"2026-09-{d:02d}", "close": base + d}
                                   for d in range(1, 30)])

    def stock_hk_index_daily_sina(self, symbol):
        return self._rows("HSI", [{"date": "2026-09-28", "close": 24642.5},
                                  {"date": "2026-09-29", "close": 24523.57}])

    def stock_hsgt_hist_em(self, symbol):
        if symbol == "北向资金":
            rows = [{"日期": "2024-08-15", "当日成交净买额": 10.0},
                    {"日期": "2024-08-16", "当日成交净买额": -67.75},
                    {"日期": "2024-08-19", "当日成交净买额": float("nan")},
                    {"日期": "2026-09-29", "当日成交净买额": float("nan")}]
        else:
            rows = [{"日期": f"2026-09-{d:02d}", "当日成交净买额": 10.0} for d in range(1, 26)]
        return self._rows(symbol, rows)

    def stock_margin_account_info(self):
        return self._rows("margin", [{"日期": f"2026-09-{d:02d}", "融资余额": 25000.0 + d * 10,
                                      "融券余额": 290.0} for d in range(1, 29)])


@pytest.mark.asyncio
async def test_china_feed_lines(monkeypatch):
    fake = FakeAk(fail=("sh000688",))
    monkeypatch.setattr(china_akshare, "_AK", fake)
    lines = await china_market.fetch("2026-09-29")
    text = "\n".join(lines)
    assert "- CSI 300 4,029.00 (close 2026-09-29, 1d +0.02%" in text
    assert "STAR 50: unavailable (stock_zh_index_daily failed (ConnectionError))" in text
    assert "- Hang Seng 24,523.57 (close 2026-09-29, 1d -0.48%)" in text
    assert "Southbound" in text and "+10.00 on 2026-09-25; 5-session sum +50.00; 20-session sum +200.00" in text
    assert "margin financing balance 25,280.0 (亿元) on 2026-09-28; 5 sessions +50.0" in text
    assert ("Northbound Stock Connect net buy (HK -> mainland; 亿, Eastmoney): unavailable — source rows "
            "since 2024-08-19 carry no net-buy value (latest row 2026-09-29); last published value "
            "-67.75 on 2024-08-16") in text
    assert "akshare 9.9.9" in lines[-1] and "academic research only" in lines[-1]
    assert fake.threads and all(t.startswith("akshare") for t in fake.threads)


@pytest.mark.asyncio
async def test_china_timeout_and_total_failure(monkeypatch):
    class Slow(FakeAk):
        def stock_margin_account_info(self):
            import time
            time.sleep(0.5)
            return []
    monkeypatch.setattr(china_akshare, "_AK", Slow())
    with pytest.raises(china_akshare.AkshareUnavailable, match="timed out"):
        await china_akshare.call("stock_margin_account_info", timeout=0.05)
    await asyncio.sleep(0.6)                                   # let the worker finish
    monkeypatch.setattr(china_akshare, "_AK", FakeAk(fail=(
        "sh000300", "sh000001", "sz399006", "sh000688", "HSI", "南向资金", "北向资金", "margin")))
    with pytest.raises(RuntimeError, match="every akshare call failed"):
        await china_market.fetch("2026-09-29")
