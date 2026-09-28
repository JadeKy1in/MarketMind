"""MarketMind configuration loaded from environment variables and .env file."""
from __future__ import annotations
import os
from pathlib import Path
from dataclasses import dataclass, field

# Load .env file if present (no dependency on python-dotenv)
def _load_dotenv() -> None:
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return
    with open(env_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key, val = key.strip(), val.strip()
            if key and val and key not in os.environ:
                os.environ[key] = val

_load_dotenv()


@dataclass
class ShadowSettings:
    """Shadow configuration. S3 (docs/S3_DESIGN.md): shadows run from marketmind/shadows/v3 (roster + ledger)."""
    shadows_enabled: bool = True


@dataclass
class MarketMindConfig:
    deepseek_api_key: str = field(default_factory=lambda: os.getenv("DEEPSEEK_API_KEY", ""), repr=False)
    deepseek_api_keys: list[str] = field(default_factory=lambda: [
        k.strip() for k in os.getenv("DEEPSEEK_API_KEYS", "").split(",") if k.strip()
    ], repr=False)
    deepseek_base_url: str = field(default_factory=lambda: os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"))
    newsapi_key: str | None = field(default_factory=lambda: os.getenv("NEWSAPI_KEY"))
    gnews_key: str | None = field(default_factory=lambda: os.getenv("GNEWS_API_KEY"))
    # Accept both the short names used in code and the providers' conventional names.
    fred_key: str = field(default_factory=lambda: os.getenv("FRED_KEY") or os.getenv("FRED_API_KEY", ""), repr=False)
    eia_key: str = field(default_factory=lambda: os.getenv("EIA_KEY") or os.getenv("EIA_API_KEY", ""), repr=False)
    data_dir: Path = field(default_factory=lambda: Path(os.getenv("MARKETMIND_DATA_DIR", "data")))
    event_confidence_discount_enabled: bool = True
    max_position_count: int = 6
    max_total_heat_pct: float = 0.25
    daily_token_budget: int = 2_000_000
    daily_pro_limit: int = 30
    daily_flash_limit: int = 100
    cache_ttl_seconds: int = 300
    proxy_url: str = field(default_factory=lambda: os.getenv("HTTP_PROXY", os.getenv("HTTPS_PROXY", "")))
    session_checkpoint_dir: Path | None = None
    position_protection_days: int = 60
    market_open_utc: str = "13:30"  # US equity market open in UTC (9:30 AM ET during EDT Mar-Nov; 14:30 during EST Nov-Mar)
    shadow: ShadowSettings = field(default_factory=ShadowSettings)

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
