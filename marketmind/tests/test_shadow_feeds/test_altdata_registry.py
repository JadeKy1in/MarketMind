"""Offline tests: Playground DATA-source registry and feed discovery (owner decision 2026-09-29).
Payload shapes copy the live responses checked 2026-09-29.
"""

import httpx
import pytest

import marketmind.shadow_feeds as sf
from marketmind.playground import playground_sources as ps


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


# ── registry and discovery ──────────────────────────────────────────────────

def test_playground_data_sources_registered_and_resolvable():
    names = {s.name for s in ps.get_data_sources()}
    assert names == {"SEC Fails-to-Deliver", "Indeed Hiring Lab Job Postings",
                     "Apple App Store Charts", "akshare China Market Data"}
    for s in ps.get_data_sources():
        assert s.loaders and s.licence and s.lag and s.url
        for spec in s.loaders:
            assert callable(ps.resolve_loader(spec))
    assert [s.name for s in ps.declared_data_sources(["SEC Fails-to-Deliver", "EE Times", "nope"])] \
        == ["SEC Fails-to-Deliver"]
    ps.AGENT_SOURCE_MAP["_tmp_agent"] = ["SEC Fails-to-Deliver", "EE Times"]
    try:
        assert [s.name for s in ps.get_core_sources(["_tmp_agent"])] == ["EE Times"]
    finally:
        del ps.AGENT_SOURCE_MAP["_tmp_agent"]


def test_new_feeds_are_discovered_and_serve_roster_shadows():
    from marketmind.shadows.v3 import roster
    names = {e.name for e in roster.ROSTER}
    feeds = {f.name: f for f in sf.discover()}
    expect = {"sec_ftd": {"squeeze_watch", "bear_tracker"},
              "indeed_postings": {"cycle_reader", "wallet_watcher"},
              "app_store_charts": {"wallet_watcher", "silicon_oracle"},
              "china_akshare": {"dragon_watch"}}
    for name, shadows in expect.items():
        assert set(feeds[name].shadows) == shadows and shadows <= names
