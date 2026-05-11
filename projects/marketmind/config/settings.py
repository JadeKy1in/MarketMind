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
