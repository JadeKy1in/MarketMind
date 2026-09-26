# MarketMind Phase A — Core Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the MarketMind core pipeline: news collection → Flash preprocessing → Layer 1-2-3 analysis → Red Team challenge → signal resonance → decision generation → GUI gates → position patrol. Independently usable — one full daily analysis session end-to-end.

**Architecture:** Async-first pipeline with unified DeepSeek gateway. Data flows: Scout → Cache → Flash Preprocessor → Layer 1 (narrative) + Layer 2 (fundamental) in parallel → Red Team challenge → Signal Resonance → Decision Generator. Layer 3 (technical) runs independently on raw data only. GUI bridges async I/O via daemon-thread event loop + queue.Queue + root.after() polling. All outputs archived as JSON + SQLite FTS5.

**Tech Stack:** Python 3.11+, httpx (async), feedparser, yfinance, CustomTkinter, pytest + pytest-mock, SQLite FTS5

---

## File Structure

```
projects/marketmind/
├── __init__.py
├── app.py                          # CLI entry point (mock + live modes)
├── config/
│   ├── __init__.py
│   ├── settings.py                 # All constants: API keys, limits, paths
│   ├── asset_universe.py           # Robinhood-tradable asset matrix
│   └── source_authority.py         # Source tiers 1-4
├── gateway/
│   ├── __init__.py
│   ├── async_client.py             # Unified async DeepSeek gateway
│   └── token_budget.py             # TokenBudget with 429 backoff
├── pipeline/
│   ├── __init__.py
│   ├── scout.py                    # Multi-source news + 3-tier degradation
│   ├── cache.py                    # Centralized cache with TTL freshness
│   ├── flash_preprocessor.py       # Flash batch: extract, classify, denoise
│   ├── layer1_narrative.py         # Event grading, 2x2 matrix, price-in, cascade
│   ├── layer2_fundamental.py       # 5-tier progressive: macro→asset→sector→factor→ticker
│   ├── layer3_technical.py         # 3-light review + entry/exit calc (independent)
│   ├── red_team.py                 # Adversarial challenge engine
│   ├── resonance.py                # DSR/CSCV statistical framework
│   ├── decision.py                 # Decision card + "no-trade" card synthesis
│   └── position_patrol.py          # Daily position health check
├── integrity/
│   ├── __init__.py
│   ├── watchdog.py                 # M1-M4 Fabrication Watchdog
│   └── fact_checker.py             # Claim extraction + source verification
├── storage/
│   ├── __init__.py
│   ├── archivist.py                # JSON archive + SQLite FTS5 index
│   └── session.py                  # Checkpoint persistence (per-gate auto-save)
├── ui/
│   ├── __init__.py
│   ├── async_bridge.py             # Async-GUI thread bridge
│   ├── main_window.py              # Multi-panel layout with progressive disclosure
│   ├── gate_panel.py               # Gate 1/2/3 interaction panels
│   ├── dashboard_panel.py          # Analysis signal dashboard
│   ├── decision_card.py            # Structured decision card display
│   ├── position_card.py            # Position status card display
│   ├── progress.py                 # Determinate + indeterminate progress bars
│   └── pause_screen.py             # Mandatory 2-min pause Gate 2→3
└── tests/
    ├── __init__.py
    ├── conftest.py                  # Shared fixtures: mock LLM, temp dirs
    ├── test_gateway/
    │   ├── test_async_client.py
    │   └── test_token_budget.py
    ├── test_pipeline/
    │   ├── test_scout.py
    │   ├── test_cache.py
    │   ├── test_flash_preprocessor.py
    │   ├── test_layer1.py
    │   ├── test_layer2.py
    │   ├── test_layer3.py
    │   ├── test_red_team.py
    │   ├── test_resonance.py
    │   ├── test_decision.py
    │   └── test_position_patrol.py
    ├── test_integrity/
    │   ├── test_watchdog.py
    │   └── test_fact_checker.py
    ├── test_storage/
    │   ├── test_archivist.py
    │   └── test_session.py
    └── test_ui/
        ├── test_async_bridge.py
        └── test_progress.py
```

---

## Sub-Phase A.0: Foundation — Agent Roles

| Step | Who | What |
|------|-----|------|
| A.0.1 | **Architect** | Design async gateway interface, TokenBudget contract, config schema. Produce `ARCHITECTURE_HANDOFF_A0` |
| A.0.2 | **Data Engineer** | Implement `gateway/async_client.py` and `gateway/token_budget.py` per handoff. Install dependencies |
| A.0.3 | **Builder** | Implement `config/settings.py`, `config/asset_universe.py`, `config/source_authority.py`, project `__init__.py` |
| A.0.4 | **Builder** | Wire foundation together, run syntax check, commit |
| A.0.5 | **Red Team** | Audit A.0: verify imports resolve, config loads without crash, TokenBudget arithmetic correct |

---

### Task A.0.1: Architect Handoff — Foundation Design

**Agent:** Architect (Opus 1M)
**Files:** None created (design only)

Architect reads `docs/superpowers/specs/2026-05-10-marketmind-design.md` sections 10-11 and produces `ARCHITECTURE_HANDOFF_A0` covering:

1. **Async Gateway Interface** — `async_client.py`:
```python
# Exact function signatures required:

async def chat_flash(
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.3,
    max_tokens: int = 4096,
    reasoning_effort: str = "max"
) -> dict[str, Any]:
    """Single Flash call. Returns {"content": str, "usage": dict, "latency_ms": int}."""

async def chat_pro(
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.3,
    max_tokens: int = 8192,
    reasoning_effort: str = "max"
) -> dict[str, Any]:
    """Single Pro call. Returns {"content": str, "usage": dict, "latency_ms": int}."""

async def chat_batch_flash(
    prompts: list[tuple[str, str]],  # [(system, user), ...]
    temperature: float = 0.3,
    max_concurrency: int = 5
) -> list[dict[str, Any]]:
    """Concurrent Flash calls with semaphore gate."""

async def chat_with_integrity(
    model: str,  # "flash" | "pro"
    system_prompt: str,
    user_prompt: str,
    caller_agent: str,  # agent ID for watchdog tracking
    **kwargs
) -> dict[str, Any]:
    """Wrap any call with M1 protocol injection. Calls chat_flash or chat_pro internally."""

class DeepSeekGateway:
    """Singleton holding api_key, base_url, session pool."""
    def __init__(self, api_key: str, base_url: str = "https://api.deepseek.com/v1"):
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(120.0), limits=httpx.Limits(max_connections=20))
    async def close(self): ...
    async def __aenter__(self): ...
    async def __aexit__(self): ...
```

2. **TokenBudget Interface** — `token_budget.py`:
```python
@dataclass
class TokenBudget:
    daily_limit: int          # total tokens/day
    pro_call_limit: int       # max Pro calls/day
    flash_call_limit: int     # max Flash calls/day
    tokens_remaining: int
    pro_calls_remaining: int
    flash_calls_remaining: int
    last_reset: datetime
    priority_queue: list[tuple[int, str, Callable]]  # (priority, caller_id, callable)

    def can_call_pro(self) -> bool: ...
    def can_call_flash(self) -> bool: ...
    async def reserve_pro(self, estimated_tokens: int) -> bool: ...
    async def reserve_flash(self, estimated_tokens: int) -> bool: ...
    def handle_429(self, retry_after: int) -> float: ...  # returns backoff seconds
    def report(self) -> dict: ...  # {"remaining": ..., "pct_used": ...}

class Priority(enum.IntEnum):
    CRITICAL = 1    # position patrol, data integrity
    HIGH = 2        # main analysis pipeline
    NORMAL = 3      # shadow analysis
    LOW = 4         # batch preprocessing
```

3. **Config Schema** — `config/settings.py`:
```python
@dataclass
class MarketMindConfig:
    deepseek_api_key: str
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    newsapi_key: str | None = None
    gnews_key: str | None = None
    data_dir: Path = Path("data")
    archive_dir: Path = Path("data/archive")
    max_position_count: int = 6
    max_total_heat_pct: float = 0.25
    daily_token_budget: int = 2_000_000
    daily_pro_limit: int = 30
    daily_flash_limit: int = 100
    cache_ttl_seconds: int = 300
    session_checkpoint_dir: Path = Path("data/sessions")

    @classmethod
    def from_env(cls) -> "MarketMindConfig": ...  # load from env vars
```

4. **Asset Universe Schema** — `config/asset_universe.py`:
```python
@dataclass
class Asset:
    ticker: str
    name: str
    asset_class: str      # equity/etf/option/crypto
    sector: str | None
    factor_exposures: dict[str, float]  # {"rate": 0.3, "oil": -0.1, ...}
    robinhood_tradable: bool

ASSET_UNIVERSE: dict[str, Asset] = {
    # Equities
    "AAPL": Asset("AAPL", "Apple Inc.", "equity", "Technology", ...),
    # ETFs
    "SPY": Asset("SPY", "SPDR S&P 500", "etf", None, ...),
    # Crypto
    "BTC-USD": Asset("BTC-USD", "Bitcoin", "crypto", None, ...),
    # ... at least 50 assets covering all major classes
}
```

5. **Source Authority Schema** — `config/source_authority.py`:
```python
@dataclass
class Source:
    name: str
    tier: int           # 1 (primary/government) to 4 (social/rumor)
    url: str | None
    feed_type: str      # "rss" | "api" | "html" | "manual"
    reliability: float  # 0.0-1.0 based on historical accuracy
    rate_limit_rps: float
    requires_auth: bool

TIER_1_SOURCES: list[Source]  # FRED, BLS, SEC EDGAR, Federal Reserve, CFTC
TIER_2_SOURCES: list[Source]  # NewsAPI, MarketWatch, Investing.com
TIER_3_SOURCES: list[Source]  # Nikkei Asia (headlines only), social aggregators
TIER_4_SOURCES: list[Source]  # xcancel, capitoltrades (best-effort, fragile)
```

Architect commits the handoff to `.claude/handoffs/A0_foundation.md`.

---

### Task A.0.2: Data Engineer — Gateway + TokenBudget Implementation

**Agent:** Data Engineer (Sonnet 1M)
**Files:**
- Create: `projects/marketmind/gateway/__init__.py`
- Create: `projects/marketmind/gateway/async_client.py`
- Create: `projects/marketmind/gateway/token_budget.py`
- Create: `projects/marketmind/tests/test_gateway/__init__.py`
- Create: `projects/marketmind/tests/test_gateway/test_async_client.py`
- Create: `projects/marketmind/tests/test_gateway/test_token_budget.py`
- Create: `projects/marketmind/tests/conftest.py`

- [ ] **Step 1: Install dependencies**

```bash
pip install httpx pytest pytest-mock pytest-asyncio python-dotenv
```

- [ ] **Step 2: Write failing test for `chat_flash`**

```python
# tests/test_gateway/test_async_client.py
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from projects.marketmind.gateway.async_client import chat_flash, chat_pro, chat_batch_flash, chat_with_integrity, DeepSeekGateway

@pytest.mark.asyncio
async def test_chat_flash_returns_structured_response():
    mock_response = {
        "choices": [{"message": {"content": "Test analysis result"}}],
        "usage": {"total_tokens": 150, "prompt_tokens": 50, "completion_tokens": 100}
    }
    mock_client = AsyncMock()
    mock_client.post.return_value.json = AsyncMock(return_value=mock_response)
    mock_client.post.return_value.status_code = 200

    with patch("httpx.AsyncClient", return_value=mock_client):
        gateway = DeepSeekGateway(api_key="test-key")
        result = await chat_flash(
            system_prompt="You are an analyst.",
            user_prompt="Analyze AAPL."
        )
        assert "content" in result
        assert result["content"] == "Test analysis result"
        assert "usage" in result
        assert "latency_ms" in result
        assert result["latency_ms"] > 0
```

- [ ] **Step 3: Run test — verify FAIL**

```bash
python -m pytest projects/marketmind/tests/test_gateway/test_async_client.py::test_chat_flash_returns_structured_response -v
```
Expected: FAIL (module not found or function not defined)

- [ ] **Step 4: Implement `gateway/async_client.py`**

```python
"""Unified async DeepSeek gateway. All LLM calls route through here."""
from __future__ import annotations
import time
import asyncio
from typing import Any
import httpx

DEEPSEEK_BASE = "https://api.deepseek.com/v1"
DEFAULT_TIMEOUT = httpx.Timeout(120.0)
MAX_CONNECTIONS = 20

class DeepSeekGateway:
    def __init__(self, api_key: str, base_url: str = DEEPSEEK_BASE):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            timeout=DEFAULT_TIMEOUT,
            limits=httpx.Limits(max_connections=MAX_CONNECTIONS),
            headers={"Authorization": f"Bearer {api_key}"}
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()

    async def _call(
        self,
        model: str,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        max_tokens: int,
        reasoning_effort: str = "max",
    ) -> dict[str, Any]:
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        headers = {}
        if reasoning_effort:
            headers["X-Reasoning-Effort"] = reasoning_effort

        t0 = time.perf_counter()
        resp = await self._client.post(
            f"{self.base_url}/chat/completions", json=payload, headers=headers
        )
        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        if resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", 5))
            raise RateLimitError(retry_after)
        resp.raise_for_status()
        data = resp.json()
        return {
            "content": data["choices"][0]["message"]["content"],
            "usage": data.get("usage", {}),
            "latency_ms": elapsed_ms,
        }


class RateLimitError(Exception):
    def __init__(self, retry_after: int):
        self.retry_after = retry_after
        super().__init__(f"Rate limited. Retry after {retry_after}s")


_gateway: DeepSeekGateway | None = None


def init_gateway(api_key: str, base_url: str = DEEPSEEK_BASE) -> None:
    global _gateway
    _gateway = DeepSeekGateway(api_key, base_url)


async def get_gateway() -> DeepSeekGateway:
    if _gateway is None:
        raise RuntimeError("Gateway not initialized. Call init_gateway() first.")
    return _gateway


async def chat_flash(
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.3,
    max_tokens: int = 4096,
    reasoning_effort: str = "max",
) -> dict[str, Any]:
    gw = await get_gateway()
    return await gw._call(
        "deepseek-v4-flash", system_prompt, user_prompt, temperature, max_tokens, reasoning_effort
    )


async def chat_pro(
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.3,
    max_tokens: int = 8192,
    reasoning_effort: str = "max",
) -> dict[str, Any]:
    gw = await get_gateway()
    return await gw._call(
        "deepseek-v4-pro", system_prompt, user_prompt, temperature, max_tokens, reasoning_effort
    )


async def chat_batch_flash(
    prompts: list[tuple[str, str]],
    temperature: float = 0.3,
    max_concurrency: int = 5,
) -> list[dict[str, Any]]:
    semaphore = asyncio.Semaphore(max_concurrency)
    async def _one(system: str, user: str) -> dict[str, Any]:
        async with semaphore:
            return await chat_flash(system, user, temperature=temperature)
    return await asyncio.gather(*[_one(s, u) for s, u in prompts])


async def chat_with_integrity(
    model: str,
    system_prompt: str,
    user_prompt: str,
    caller_agent: str,
    **kwargs,
) -> dict[str, Any]:
    integrity_header = (
        f"[DATA_INTEGRITY_PROTOCOL v1.0] You are {caller_agent}. "
        "All numeric claims (prices, ratios, percentages, dates, amounts) MUST cite "
        "a verifiable source. If a figure is an estimate, prefix it with 'EST:'. "
        "If data is unavailable, state 'DATA_UNAVAILABLE' — never fabricate. "
        "You are bound by Law 7 (Data Integrity).\n\n"
    )
    full_system = integrity_header + system_prompt
    if model == "flash":
        return await chat_flash(full_system, user_prompt, **kwargs)
    elif model == "pro":
        return await chat_pro(full_system, user_prompt, **kwargs)
    else:
        raise ValueError(f"Unknown model: {model}")
```

- [ ] **Step 5: Run tests — verify PASS**

```bash
python -m pytest projects/marketmind/tests/test_gateway/test_async_client.py -v
```

- [ ] **Step 6: Implement `gateway/token_budget.py`**

```python
"""Token budget manager with priority queue and 429 backoff."""
from __future__ import annotations
import time
import enum
from dataclasses import dataclass, field
from collections import deque


class Priority(enum.IntEnum):
    CRITICAL = 1
    HIGH = 2
    NORMAL = 3
    LOW = 4


@dataclass
class TokenBudget:
    daily_limit: int
    pro_call_limit: int
    flash_call_limit: int
    tokens_remaining: int = 0
    pro_calls_remaining: int = 0
    flash_calls_remaining: int = 0
    last_reset: float = field(default_factory=time.time)
    _backoff_until: float = 0.0

    def __post_init__(self):
        self.tokens_remaining = self.daily_limit
        self.pro_calls_remaining = self.pro_call_limit
        self.flash_calls_remaining = self.flash_call_limit

    def _maybe_reset(self) -> None:
        now = time.time()
        if now - self.last_reset > 86400:  # 24h
            self.tokens_remaining = self.daily_limit
            self.pro_calls_remaining = self.pro_call_limit
            self.flash_calls_remaining = self.flash_call_limit
            self.last_reset = now

    def can_call_pro(self) -> bool:
        self._maybe_reset()
        return self.pro_calls_remaining > 0 and self.tokens_remaining > 0

    def can_call_flash(self) -> bool:
        self._maybe_reset()
        return self.flash_calls_remaining > 0 and self.tokens_remaining > 0

    def is_backing_off(self) -> bool:
        return time.time() < self._backoff_until

    def reserve_pro(self, estimated_tokens: int) -> bool:
        self._maybe_reset()
        if self.pro_calls_remaining <= 0 or self.tokens_remaining < estimated_tokens:
            return False
        self.pro_calls_remaining -= 1
        self.tokens_remaining -= estimated_tokens
        return True

    def reserve_flash(self, estimated_tokens: int) -> bool:
        self._maybe_reset()
        if self.flash_calls_remaining <= 0 or self.tokens_remaining < estimated_tokens:
            return False
        self.flash_calls_remaining -= 1
        self.tokens_remaining -= estimated_tokens
        return True

    def release_pro(self, actual_tokens: int) -> None:
        self.tokens_remaining += actual_tokens
        self.pro_calls_remaining += 1

    def release_flash(self, actual_tokens: int) -> None:
        self.tokens_remaining += actual_tokens
        self.flash_calls_remaining += 1

    def handle_429(self, retry_after: int) -> float:
        self._backoff_until = time.time() + retry_after + 1.0
        return self._backoff_until

    def report(self) -> dict:
        self._maybe_reset()
        return {
            "tokens_remaining": self.tokens_remaining,
            "tokens_pct_used": round((1 - self.tokens_remaining / self.daily_limit) * 100, 1),
            "pro_calls_remaining": self.pro_calls_remaining,
            "flash_calls_remaining": self.flash_calls_remaining,
            "backoff_active": self.is_backing_off(),
            "backoff_seconds_left": max(0, self._backoff_until - time.time()),
        }
```

- [ ] **Step 7: Write and run TokenBudget tests**

```python
# tests/test_gateway/test_token_budget.py
from projects.marketmind.gateway.token_budget import TokenBudget, Priority

def test_reserve_pro_deducts_correctly():
    tb = TokenBudget(daily_limit=10000, pro_call_limit=5, flash_call_limit=10)
    assert tb.can_call_pro()
    assert tb.reserve_pro(2000)
    assert tb.pro_calls_remaining == 4
    assert tb.tokens_remaining == 8000

def test_reserve_denies_when_empty():
    tb = TokenBudget(daily_limit=1000, pro_call_limit=1, flash_call_limit=0)
    assert tb.reserve_pro(1500) is False  # exceeds remaining
    assert tb.reserve_pro(500)  # ok
    assert tb.reserve_pro(100) is False  # no pro calls left

def test_release_restores_tokens():
    tb = TokenBudget(daily_limit=10000, pro_call_limit=5, flash_call_limit=10)
    tb.reserve_pro(3000)
    tb.release_pro(2500)  # only 2500 actually used
    assert tb.tokens_remaining == 9500
    assert tb.pro_calls_remaining == 5

def test_handle_429_sets_backoff():
    tb = TokenBudget(daily_limit=10000, pro_call_limit=5, flash_call_limit=10)
    assert not tb.is_backing_off()
    tb.handle_429(10)
    assert tb.is_backing_off()

def test_report_returns_expected_keys():
    tb = TokenBudget(daily_limit=10000, pro_call_limit=5, flash_call_limit=10)
    r = tb.report()
    for k in ("tokens_remaining", "tokens_pct_used", "pro_calls_remaining", "flash_calls_remaining", "backoff_active"):
        assert k in r
```

```bash
python -m pytest projects/marketmind/tests/test_gateway/test_token_budget.py -v
```

- [ ] **Step 8: Write `tests/conftest.py`**

```python
"""Shared fixtures for MarketMind tests."""
import pytest
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock


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
```

- [ ] **Step 9: Commit**

```bash
git add projects/marketmind/gateway/ projects/marketmind/tests/ requirements.txt
git commit -m "feat(A.0): async DeepSeek gateway + TokenBudget with priority queue and 429 backoff"
```

---

### Task A.0.3: Builder — Config + Asset Universe + Source Authority

**Agent:** Builder (Sonnet 1M)
**Files:**
- Create: `projects/marketmind/__init__.py`
- Create: `projects/marketmind/config/__init__.py`
- Create: `projects/marketmind/config/settings.py`
- Create: `projects/marketmind/config/asset_universe.py`
- Create: `projects/marketmind/config/source_authority.py`

- [ ] **Step 1: Implement `config/settings.py`**

```python
"""MarketMind configuration loaded from environment variables."""
from __future__ import annotations
import os
from pathlib import Path
from dataclasses import dataclass, field


@dataclass
class MarketMindConfig:
    deepseek_api_key: str = field(default_factory=lambda: os.getenv("DEEPSEEK_API_KEY", ""))
    deepseek_base_url: str = field(default_factory=lambda: os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"))
    newsapi_key: str | None = field(default_factory=lambda: os.getenv("NEWSAPI_KEY"))
    gnews_key: str | None = field(default_factory=lambda: os.getenv("GNEWS_API_KEY"))
    data_dir: Path = field(default_factory=lambda: Path(os.getenv("MARKETMIND_DATA_DIR", "data")))
    max_position_count: int = 6
    max_total_heat_pct: float = 0.25
    daily_token_budget: int = 2_000_000
    daily_pro_limit: int = 30
    daily_flash_limit: int = 100
    cache_ttl_seconds: int = 300
    session_checkpoint_dir: Path | None = None

    def __post_init__(self):
        self.data_dir = Path(self.data_dir)
        if self.session_checkpoint_dir is None:
            self.session_checkpoint_dir = self.data_dir / "sessions"

    @property
    def archive_dir(self) -> Path:
        return self.data_dir / "archive"

    @classmethod
    def from_env(cls) -> "MarketMindConfig":
        return cls()

    def validate(self) -> list[str]:
        errors = []
        if not self.deepseek_api_key:
            errors.append("DEEPSEEK_API_KEY is required")
        if self.max_position_count < 1:
            errors.append("max_position_count must be >= 1")
        if self.max_total_heat_pct <= 0 or self.max_total_heat_pct > 1:
            errors.append("max_total_heat_pct must be in (0, 1]")
        return errors
```

- [ ] **Step 2: Implement `config/asset_universe.py`**

```python
"""Robinhood-tradable asset universe."""
from dataclasses import dataclass


@dataclass
class Asset:
    ticker: str
    name: str
    asset_class: str
    sector: str | None = None
    factor_exposures: dict[str, float] | None = None

    def __post_init__(self):
        if self.factor_exposures is None:
            self.factor_exposures = {}

    @property
    def robinhood_tradable(self) -> bool:
        return self.asset_class in ("equity", "etf", "crypto")


ASSET_UNIVERSE: dict[str, Asset] = {
    "SPY": Asset("SPY", "SPDR S&P 500 ETF", "etf", None, {"beta": 1.0}),
    "QQQ": Asset("QQQ", "Invesco QQQ Trust", "etf", "Technology", {"beta": 1.2, "rate": -0.3}),
    "IWM": Asset("IWM", "iShares Russell 2000", "etf", None, {"beta": 1.1, "rate": -0.4}),
    "DIA": Asset("DIA", "SPDR Dow Jones", "etf", None, {"beta": 0.9}),
    "TLT": Asset("TLT", "iShares 20+ Year Treasury", "etf", None, {"rate": 1.0, "beta": -0.3}),
    "GLD": Asset("GLD", "SPDR Gold Trust", "etf", None, {"gold": 1.0, "beta": 0.0}),
    "SLV": Asset("SLV", "iShares Silver Trust", "etf", None, {"gold": 0.8, "beta": 0.1}),
    "USO": Asset("USO", "United States Oil Fund", "etf", "Energy", {"oil": 1.0, "beta": 0.2}),
    "UNG": Asset("UNG", "United States Natural Gas", "etf", "Energy", {"oil": 0.6, "beta": 0.1}),
    "DBA": Asset("DBA", "Invesco DB Agriculture", "etf", None, {"agri": 1.0, "beta": 0.1}),
    "EEM": Asset("EEM", "iShares MSCI Emerging Markets", "etf", None, {"beta": 1.1, "rate": -0.2}),
    "XLF": Asset("XLF", "Financial Select Sector", "etf", "Financials", {"rate": 0.5, "beta": 1.0}),
    "XLK": Asset("XLK", "Technology Select Sector", "etf", "Technology", {"beta": 1.2, "rate": -0.4}),
    "XLE": Asset("XLE", "Energy Select Sector", "etf", "Energy", {"oil": 0.9, "beta": 0.9}),
    "XLV": Asset("XLV", "Health Care Select Sector", "etf", "Healthcare", {"beta": 0.7}),
    "AAPL": Asset("AAPL", "Apple Inc.", "equity", "Technology", {"beta": 1.2, "rate": -0.3}),
    "MSFT": Asset("MSFT", "Microsoft Corp.", "equity", "Technology", {"beta": 1.1, "rate": -0.2}),
    "NVDA": Asset("NVDA", "NVIDIA Corp.", "equity", "Technology", {"beta": 1.5, "rate": -0.4}),
    "GOOGL": Asset("GOOGL", "Alphabet Inc.", "equity", "Technology", {"beta": 1.1, "rate": -0.2}),
    "AMZN": Asset("AMZN", "Amazon.com Inc.", "equity", "Consumer", {"beta": 1.1, "rate": -0.2}),
    "META": Asset("META", "Meta Platforms Inc.", "equity", "Technology", {"beta": 1.3, "rate": -0.3}),
    "TSLA": Asset("TSLA", "Tesla Inc.", "equity", "Consumer", {"beta": 1.8, "rate": -0.5, "oil": -0.2}),
    "JPM": Asset("JPM", "JPMorgan Chase & Co.", "equity", "Financials", {"rate": 0.6, "beta": 1.0}),
    "XOM": Asset("XOM", "Exxon Mobil Corp.", "equity", "Energy", {"oil": 0.9, "beta": 0.8}),
    "BTC-USD": Asset("BTC-USD", "Bitcoin", "crypto", None, {"beta": 1.5, "rate": -0.3, "gold": 0.3}),
}


def get_asset(ticker: str) -> Asset | None:
    return ASSET_UNIVERSE.get(ticker.upper())


def get_assets_by_class(asset_class: str) -> list[Asset]:
    return [a for a in ASSET_UNIVERSE.values() if a.asset_class == asset_class]


def get_assets_by_sector(sector: str) -> list[Asset]:
    return [a for a in ASSET_UNIVERSE.values() if a.sector == sector]
```

- [ ] **Step 3: Implement `config/source_authority.py`**

```python
"""Source authority tiers and health tracking."""
from dataclasses import dataclass, field
from enum import IntEnum


class SourceTier(IntEnum):
    PRIMARY = 1
    RELIABLE = 2
    FRAGILE = 3
    BEST_EFFORT = 4


class SourceStatus(IntEnum):
    WORKING = 1
    DEGRADED = 2
    DEAD = 3
    UNTESTED = 0


@dataclass
class Source:
    name: str
    tier: SourceTier
    url: str | None = None
    feed_type: str = "rss"
    reliability: float = 0.5
    rate_limit_rps: float = 1.0
    requires_auth: bool = False
    status: SourceStatus = SourceStatus.UNTESTED
    last_checked: str | None = None
    consecutive_failures: int = 0

    @property
    def is_available(self) -> bool:
        return self.status in (SourceStatus.WORKING, SourceStatus.DEGRADED)


SOURCES: list[Source] = [
    Source("FRED", SourceTier.PRIMARY, "https://fred.stlouisfed.org/rss/", "rss", 0.99, 2.0),
    Source("BLS", SourceTier.PRIMARY, "https://www.bls.gov/feed/", "rss", 0.99, 2.0),
    Source("SEC EDGAR", SourceTier.PRIMARY, "https://www.sec.gov/cgi-bin/browse-edgar", "rss", 0.99, 1.0),
    Source("Federal Reserve", SourceTier.PRIMARY, "https://www.federalreserve.gov/feeds/", "rss", 0.99, 2.0),
    Source("CFTC COT", SourceTier.PRIMARY, "https://www.cftc.gov/dea/newcot/c_disagg.txt", "api", 0.99, 1.0),
    Source("NewsAPI", SourceTier.RELIABLE, None, "api", 0.90, 10.0, True),
    Source("GNews", SourceTier.RELIABLE, None, "api", 0.85, 10.0, True),
    Source("MarketWatch", SourceTier.RELIABLE, "https://feeds.marketwatch.com/marketwatch/topstories", "rss", 0.80, 2.0),
    Source("Investing.com", SourceTier.RELIABLE, "https://www.investing.com/rss/news.rss", "rss", 0.75, 1.0),
    Source("Nikkei Asia", SourceTier.FRAGILE, "https://asia.nikkei.com/rss/feed/nikkei-asia-news", "rss", 0.70, 1.0),
    Source("xcancel", SourceTier.BEST_EFFORT, "https://rss.xcancel.com/", "rss", 0.60, 0.5),
    Source("CapitolTrades", SourceTier.BEST_EFFORT, "https://www.capitoltrades.com/", "html", 0.65, 0.5),
]


def get_working_sources() -> list[Source]:
    return [s for s in SOURCES if s.is_available]


def get_sources_by_tier(tier: SourceTier) -> list[Source]:
    return [s for s in SOURCES if s.tier == tier]
```

- [ ] **Step 4: Create `projects/marketmind/__init__.py`**

```python
"""MarketMind — AI-powered investment analysis workstation."""
__version__ = "0.1.0"
```

- [ ] **Step 5: Syntax check + commit**

```bash
python -c "import ast; [ast.parse(open(f'projects/marketmind/config/{f}').read()) for f in ('settings.py','asset_universe.py','source_authority.py')]"
git add projects/marketmind/__init__.py projects/marketmind/config/
git commit -m "feat(A.0): MarketMind config — settings, asset universe (25+ assets), source authority (4 tiers)"
```

---

### Task A.0.4: Builder — Wire Foundation + Verify

**Agent:** Builder (Sonnet 1M)

- [ ] **Step 1: Verify all modules import correctly**

```bash
cd E:\AI_Studio_Workspace
python -c "
from projects.marketmind.config.settings import MarketMindConfig
from projects.marketmind.config.asset_universe import ASSET_UNIVERSE, get_asset, get_assets_by_class
from projects.marketmind.config.source_authority import SOURCES, SourceTier, get_working_sources
from projects.marketmind.gateway.async_client import chat_flash, chat_pro, chat_batch_flash, chat_with_integrity, DeepSeekGateway
from projects.marketmind.gateway.token_budget import TokenBudget, Priority
print('All imports OK')
print(f'Assets loaded: {len(ASSET_UNIVERSE)}')
print(f'Sources loaded: {len(SOURCES)}')
"
```

- [ ] **Step 2: Run all A.0 tests**

```bash
python -m pytest projects/marketmind/tests/test_gateway/ -v
```

- [ ] **Step 3: Commit**

```bash
git add projects/marketmind/
git commit -m "feat(A.0): verify foundation imports + all gateway tests passing"
```

---

### Task A.0.5: Red Team — Foundation Audit

**Agent:** Red Team (Haiku 1M)

Red Team reads all A.0 files and produces `RED_TEAM_AUDIT_A0` covering:
1. Import chain: does every `__init__.py` expose the right symbols?
2. TokenBudget arithmetic: verify reserve → release restores exact amounts, edge cases (negative, zero, overflow)
3. Config validation: does `validate()` catch all error conditions?
4. Asset universe coverage: are gold, oil, ag, tech, crypto, credit all represented?
5. API key handling: is the key ever logged or printed?

Output to `.claude/audits/A0_foundation.md`.

---

## Sub-Phase A.1: Data Pipeline — Agent Roles

| Step | Who | What |
|------|-----|------|
| A.1.1 | **Architect** | Design Scout interface, cache API, Flash preprocessor prompt template. Produce `ARCHITECTURE_HANDOFF_A1` |
| A.1.2 | **Data Engineer** | Implement `pipeline/scout.py` with multi-source fetch + 3-tier degradation |
| A.1.3 | **Data Engineer** | Implement `pipeline/cache.py` with TTL freshness |
| A.1.4 | **Data Engineer** | Implement `pipeline/flash_preprocessor.py` — batch signal extraction |
| A.1.5 | **Builder** | Wire data pipeline end-to-end, run with mock, commit |
| A.1.6 | **Red Team** | Audit data pipeline: source health check, cache TTL compliance, Flash output schema validation |

---

### Task A.1.1: Architect Handoff — Data Pipeline Design

**Agent:** Architect (Opus 1M)

Architect reads spec sections 4.1, 11 and produces `ARCHITECTURE_HANDOFF_A1`:

1. **Scout interface** — `pipeline/scout.py`:
```python
@dataclass
class NewsItem:
    id: str                          # hash of title+url
    title: str
    url: str
    source_name: str
    source_tier: int                 # 1-4
    published_at: str                # ISO 8601
    summary: str                     # first 500 chars
    raw_text: str | None = None      # full text when available
    fetched_at: str = field(default_factory=lambda: datetime.now().isoformat())

async def fetch_all_sources(config: MarketMindConfig, cache: DataCache) -> list[NewsItem]:
    """Fetch from all working sources. Apply rate limits. Return deduplicated list."""

async def fetch_source(source: Source, config: MarketMindConfig) -> list[NewsItem]:
    """Fetch single source. Track C (RSS/API) → Track B (HTML) → Track C (paid) → Track D (human) degradation."""

def deduplicate(items: list[NewsItem]) -> list[NewsItem]:
    """Remove duplicates by title similarity (>0.85 Levenshtein ratio) and exact URL match."""
```

2. **Cache interface** — `pipeline/cache.py`:
```python
@dataclass
class CacheEntry:
    key: str
    data: Any
    cached_at: float      # time.time()
    ttl_seconds: int

class DataCache:
    def __init__(self, ttl_seconds: int = 300): ...
    async def get(self, key: str) -> Any | None: ...
    async def set(self, key: str, data: Any, ttl: int | None = None) -> None: ...
    async def invalidate(self, key: str) -> None: ...
    def stats(self) -> dict: ...  # {"size": N, "hit_rate": X%}
```

3. **Flash Preprocessor prompt template:**
```
System: You are a financial news preprocessor. Your task is to extract investable signals from news headlines.

For each article, output a structured signal:
{
  "signal_id": "SIG-{date}-{seq}",
  "event_type": "monetary_policy|corporate_action|regulation|geopolitical|macro_data",
  "event_grade": "A|B|C|D|E",  // A=monetary policy, B=corporate, C=regulation, D=geopolitical, E=macro
  "direction": "bullish|bearish|neutral",
  "confidence": 0.0-1.0,
  "affected_assets": ["ticker1", "ticker2"],
  "key_facts": ["fact1 with data source", "fact2"],
  "noise_flag": true|false,  // true if likely noise/clickbait
  "cascade_potential": "high|medium|low"  // first-order vs cascade trigger
}

Process these headlines and return only the JSON array of signals:
{headlines}

IMPORTANT: Never fabricate data. If a number is unavailable, mark as "DATA_UNAVAILABLE".
```

Architect commits handoff to `.claude/handoffs/A1_data_pipeline.md`.

---

### Task A.1.2-A.1.4: Data Engineer — Scout, Cache, Flash Preprocessor

**Agent:** Data Engineer (Sonnet 1M)
**Files:**
- Create: `projects/marketmind/pipeline/__init__.py`
- Create: `projects/marketmind/pipeline/scout.py`
- Create: `projects/marketmind/pipeline/cache.py`
- Create: `projects/marketmind/pipeline/flash_preprocessor.py`
- Create: `projects/marketmind/tests/test_pipeline/__init__.py`
- Create: `projects/marketmind/tests/test_pipeline/test_scout.py`
- Create: `projects/marketmind/tests/test_pipeline/test_cache.py`
- Create: `projects/marketmind/tests/test_pipeline/test_flash_preprocessor.py`

Detailed steps follow the TDD pattern established in A.0 — write failing test, implement, verify pass, commit. Each module is one commit.

Key implementation constraints:
- `scout.py`: Must never silently mock data. If all sources fail, return empty list with error log — never fabricate headlines.
- `cache.py`: In-memory dict + optional disk persistence. Thread-safe for async access.
- `flash_preprocessor.py`: 15 items per batch, deduplicate signals, route through `chat_batch_flash`.

---

## Sub-Phase A.2: Analysis Engines — Agent Roles

| Step | Who | What |
|------|-----|------|
| A.2.1 | **Quant Analyst** | Design Layer 1-3 methodology, Red Team adversarial protocol, DSR/CSCV rules. Produce `ANALYSIS_METHODOLOGY_A2` |
| A.2.2 | **Architect** | Convert methodology to prompt templates + interfaces. Produce `ARCHITECTURE_HANDOFF_A2` |
| A.2.3 | **Builder** | Implement `layer1_narrative.py` |
| A.2.4 | **Builder** | Implement `layer2_fundamental.py` |
| A.2.5 | **Builder** | Implement `layer3_technical.py` (independent — raw data only) |
| A.2.6 | **Builder** | Implement `red_team.py` — adversarial challenge engine |
| A.2.7 | **Builder** | Implement `resonance.py` — DSR/CSCV framework (no LLM, pure Python math) |
| A.2.8 | **Builder** | Implement `decision.py` — decision card + "no-trade" card synthesis |
| A.2.9 | **Red Team** | Audit analysis engines: logic consistency, prompt injection safety, output schema compliance |

The Builder implements each engine following the spec:

**Layer 1 (Narrative)** — Spec §4.1: Event A-E grading, 2×2 matrix (surprise × market-size), price-in scoring, cascade tracking, sentiment analysis with structured output.

**Layer 2 (Fundamental)** — Spec §4.2: Five-tier progressive: macro quadrant → asset class → sector → factor → ticker. Red Team challenge at each tier.

**Layer 3 (Technical)** — Spec §4.3: 3-light review (200WMA + daily structure + resistance), entry zone (2-3% wide), stop-loss, target, max hold days. Must NOT receive Layer 1-2 conclusions — only raw data + ticker list.

**Red Team** — Spec §8.0: Structural independence from main analysis. Must produce ≥1 A-grade objection per cycle. Rewards based on correctness, not count.

**Signal Resonance** — Spec §4.0: Python-only computation. DSR formula, CSCV/PBO calculation with PBO > 10% → "no signal". Forward validation (30-day out-of-sample).

**Decision Generator** — Synthesizes: signal resonance result + Layer 1-3 conclusions + Red Team objections → structured decision card. Parallel "no-trade" card with equal analytical depth.

---

## Sub-Phase A.3: Integrity + Storage — Agent Roles

| Step | Who | What |
|------|-----|------|
| A.3.1 | **Architect** | Design Watchdog M1-M4 protocol, storage schema. Produce handoffs |
| A.3.2 | **Builder** | Implement `integrity/watchdog.py` — M1 (prompt injection), M2 (regex claim extraction), M3 (source track verification), M4 (agent integrity scoring) |
| A.3.3 | **Data Engineer** | Implement `integrity/fact_checker.py` — reused from Robinhood, adapted to async |
| A.3.4 | **Builder** | Implement `storage/archivist.py` — JSON by date + SQLite FTS5 index |
| A.3.5 | **Builder** | Implement `storage/session.py` — per-gate checkpoint save/restore |
| A.3.6 | **Red Team** | Audit: verify M2 regex extracts all numeric patterns, test M3 track A/B routing, verify FTS5 query accuracy |

---

## Sub-Phase A.4: Position Patrol — Agent Roles

| Step | Who | What |
|------|-----|------|
| A.4.1 | **Quant Analyst** | Design patrol methodology: buy-archive comparison, cash reframing, exit condition tracking. Produce `ANALYSIS_METHODOLOGY_A4` |
| A.4.2 | **Builder** | Implement `pipeline/position_patrol.py` — daily health check, status cards (green/yellow/red) |
| A.4.3 | **Red Team** | Audit: verify all three exit conditions (logic falsified, technical breakdown, opportunity cost) trigger correctly |

---

## Sub-Phase A.5: GUI — Agent Roles

| Step | Who | What |
|------|-----|------|
| A.5.1 | **UI Engineer** | Implement `ui/async_bridge.py` FIRST — daemon thread asyncio + queue.Queue + root.after() polling. Load-test with 5 concurrent simulated 30s LLM calls |
| A.5.2 | **UI Engineer** | Implement `ui/progress.py` — determinate (percentage + ETA), indeterminate (decelerating for Pro), per-item counter for shadows |
| A.5.3 | **UI Engineer** | Implement `ui/main_window.py` — multi-panel CustomTkinter layout with sidebar navigation |
| A.5.4 | **UI Engineer** | Implement `ui/gate_panel.py` — Gate 1 (direction briefs, 80-120 words each), Gate 2 (signal resonance + Red Team), Gate 3 (decision cards) |
| A.5.5 | **UI Engineer** | Implement `ui/decision_card.py` and `ui/position_card.py` — structured card display |
| A.5.6 | **UI Engineer** | Implement `ui/pause_screen.py` — 2-min mandatory countdown between Gate 2-3, "走开。喝水。" message |
| A.5.7 | **Builder** | Integrate all GUI panels with pipeline backend via async_bridge |
| A.5.8 | **Red Team** | Audit UI: async bridge freeze-test, gate flow transitions, session checkpoint restore |

UI Engineer's first and hardest deliverable — `async_bridge.py`:
```python
"""Bridge between asyncio (LLM calls) and CustomTkinter (GUI main thread).
Pattern: daemon-thread event loop + queue.Queue + root.after() polling.
"""
import asyncio
import queue
import threading
from typing import Any, Callable, Coroutine


class AsyncBridge:
    def __init__(self, tk_root):
        self._root = tk_root
        self._loop: asyncio.AbstractEventLoop | None = None
        self._queue: queue.Queue = queue.Queue()
        self._pending: dict[str, asyncio.Task] = {}

    def start(self) -> None:
        def _run_loop():
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            self._loop.run_forever()
        t = threading.Thread(target=_run_loop, daemon=True)
        t.start()

    def submit(self, task_id: str, coro: Coroutine, callback: Callable[[Any], None]) -> None:
        async def _wrapper():
            try:
                result = await coro
                self._queue.put((task_id, "done", result, None))
            except Exception as e:
                self._queue.put((task_id, "error", None, e))
        future = asyncio.run_coroutine_threadsafe(_wrapper(), self._loop)
        self._pending[task_id] = future

    def poll(self, interval_ms: int = 100) -> None:
        try:
            while True:
                task_id, status, result, error = self._queue.get_nowait()
                if task_id in self._pending:
                    del self._pending[task_id]
        except queue.Empty:
            pass
        self._root.after(interval_ms, lambda: self.poll(interval_ms))

    def stop(self) -> None:
        if self._loop:
            self._loop.call_soon_threadsafe(self._loop.stop)
```

---

## Sub-Phase A.6: Integration + CLI — Agent Roles

| Step | Who | What |
|------|-----|------|
| A.6.1 | **Builder** | Implement `app.py` — CLI entry with `--mode daily --mock --verbose` / `--mode gui` |
| A.6.2 | **Builder** | Wire full pipeline: Scout → Cache → Flash → Layer 1-3 → Red Team → Resonance → Decision |
| A.6.3 | **Builder** | Run end-to-end mock integration test: generates complete daily report |
| A.6.4 | **Red Team** | Full pipeline audit: price hallucination check, logic consistency, coverage verification, error path testing |
| A.6.5 | **Architect** | Spot-check Red Team audit quality. Approve Phase A completion |
| A.6.6 | **Builder** | Create `scripts/marketmind_health_check.py` |

---

### Task A.6.1: CLI Entry Point

```python
# projects/marketmind/app.py
"""MarketMind entry point — CLI and GUI launcher."""
from __future__ import annotations
import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from projects.marketmind.config.settings import MarketMindConfig
from projects.marketmind.gateway.async_client import init_gateway


async def run_daily(config: MarketMindConfig, mock: bool = False, verbose: bool = False) -> int:
    """Execute full daily analysis pipeline."""
    init_gateway(config.deepseek_api_key, config.deepseek_base_url)
    # Pipeline stages executed sequentially:
    # 1. Scout news
    # 2. Flash preprocess
    # 3. Layer 1-3 analysis (1+2 parallel, 3 independent)
    # 4. Red Team challenge
    # 5. Signal resonance
    # 6. Decision generation
    # 7. Position patrol (if positions exist)
    # 8. Archive all outputs
    print("MarketMind daily pipeline complete.")
    return 0


def run_gui(config: MarketMindConfig) -> int:
    """Launch CustomTkinter GUI."""
    from projects.marketmind.ui.main_window import MainWindow
    init_gateway(config.deepseek_api_key, config.deepseek_base_url)
    app = MainWindow(config)
    app.mainloop()
    return 0


def main():
    parser = argparse.ArgumentParser(description="MarketMind — AI Investment Analysis Workstation")
    parser.add_argument("--mode", choices=["daily", "gui"], default="gui",
                        help="Run mode: daily CLI report or GUI (default: gui)")
    parser.add_argument("--mock", action="store_true",
                        help="Use mock LLM responses (no API calls)")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Verbose output")
    args = parser.parse_args()
    config = MarketMindConfig.from_env()
    errors = config.validate()
    if errors:
        for e in errors:
            print(f"[ERROR] {e}")
        return 1
    if args.mode == "gui":
        return run_gui(config)
    else:
        return asyncio.run(run_daily(config, mock=args.mock, verbose=args.verbose))


if __name__ == "__main__":
    sys.exit(main())
```

---

### Task A.6.6: Health Check Script

```python
# scripts/marketmind_health_check.py
"""MarketMind health check — syntax, imports, config validation."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

def check_syntax() -> int:
    import ast
    src_dir = Path("projects/marketmind")
    errors = 0
    for py_file in src_dir.rglob("*.py"):
        try:
            ast.parse(py_file.read_text(encoding="utf-8"))
            print(f"  OK  {py_file}")
        except SyntaxError as e:
            print(f"  FAIL {py_file}: {e}")
            errors += 1
    return errors

def check_imports() -> int:
    errors = 0
    modules = [
        "projects.marketmind.config.settings",
        "projects.marketmind.config.asset_universe",
        "projects.marketmind.config.source_authority",
        "projects.marketmind.gateway.async_client",
        "projects.marketmind.gateway.token_budget",
        "projects.marketmind.pipeline.scout",
        "projects.marketmind.pipeline.cache",
        "projects.marketmind.pipeline.flash_preprocessor",
        "projects.marketmind.pipeline.layer1_narrative",
        "projects.marketmind.pipeline.layer2_fundamental",
        "projects.marketmind.pipeline.layer3_technical",
        "projects.marketmind.pipeline.red_team",
        "projects.marketmind.pipeline.resonance",
        "projects.marketmind.pipeline.decision",
        "projects.marketmind.pipeline.position_patrol",
        "projects.marketmind.integrity.watchdog",
        "projects.marketmind.integrity.fact_checker",
        "projects.marketmind.storage.archivist",
        "projects.marketmind.storage.session",
        "projects.marketmind.ui.async_bridge",
        "projects.marketmind.ui.main_window",
        "projects.marketmind.ui.gate_panel",
        "projects.marketmind.ui.dashboard_panel",
        "projects.marketmind.ui.decision_card",
        "projects.marketmind.ui.position_card",
        "projects.marketmind.ui.progress",
        "projects.marketmind.ui.pause_screen",
    ]
    for mod in modules:
        try:
            __import__(mod)
            print(f"  OK  {mod}")
        except Exception as e:
            print(f"  FAIL {mod}: {e}")
            errors += 1
    return errors

def main():
    print("=== MarketMind Health Check ===\n")
    print("[SYNTAX]")
    syntax_errors = check_syntax()
    print(f"\nSyntax: {syntax_errors} errors")
    if syntax_errors == 0:
        print("\n[IMPORTS]")
        import_errors = check_imports()
        print(f"\nImports: {import_errors} errors")
    return 1 if syntax_errors else 0

if __name__ == "__main__":
    sys.exit(main())
```

---

## Execution Order

```
A.0 Foundation (1 session, ~30 min)
  ├── Architect → A.0.1 Handoff
  ├── Data Engineer → A.0.2 Gateway + TokenBudget
  ├── Builder → A.0.3 Config + Assets + Sources
  ├── Builder → A.0.4 Wire + Verify
  └── Red Team → A.0.5 Audit

A.1 Data Pipeline (1 session, ~30 min)
  ├── Architect → A.1.1 Handoff
  ├── Data Engineer → A.1.2-A.1.4 Scout + Cache + Flash
  ├── Builder → A.1.5 Wire + Mock run
  └── Red Team → A.1.6 Audit

A.2 Analysis Engines (2-3 sessions, ~90 min)
  ├── Quant Analyst → A.2.1 Methodology
  ├── Architect → A.2.2 Prompts + Interfaces
  ├── Builder → A.2.3-A.2.8 Implement all 6 engines
  └── Red Team → A.2.9 Audit

A.3 Integrity + Storage (1 session, ~30 min)
  ├── Architect → A.3.1 Handoff
  ├── Builder → A.3.2-A.3.5 Watchdog + FactChecker + Archivist + Session
  └── Red Team → A.3.6 Audit

A.4 Position Patrol (1 session, ~20 min)
  ├── Quant Analyst → A.4.1 Methodology
  ├── Builder → A.4.2 Implement
  └── Red Team → A.4.3 Audit

A.5 GUI (2-3 sessions, ~90 min)
  ├── UI Engineer → A.5.1-A.5.6 All UI components
  ├── Builder → A.5.7 Backend integration
  └── Red Team → A.5.8 Audit

A.6 Integration (1 session, ~30 min)
  ├── Builder → A.6.1-A.6.3 CLI + Wire + Mock E2E
  ├── Red Team → A.6.4 Full audit
  ├── Architect → A.6.5 Spot-check
  └── Builder → A.6.6 Health check script
```

**Total estimated:** 9-13 sessions, 4-6 hours of agent work (plus human review between each sub-phase).

After each sub-phase, Red Team audits → Architect reviews audit → only then proceed to next sub-phase.

---

## Optimization Scout

**Agent:** Optimization Scout (Sonnet 1M) — defined in `.claude/agents/optimization-scout.md`

The Scout runs after each sub-phase completes. It:
1. Reviews all build outputs and test results
2. Searches the web for better libraries/approaches
3. Checks Superpowers Skills marketplace for relevant skills
4. Produces `OPTIMIZATION_REPORT_A<N>` with ≤5 actionable suggestions

Reports stored at `.claude/optimization/`.
