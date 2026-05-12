"""MarketMind configuration package."""
import json
import logging
from pathlib import Path

from marketmind.config.settings import MarketMindConfig
from marketmind.config.asset_universe import Asset, ASSET_UNIVERSE, get_asset
from marketmind.config.source_authority import Source, SourceTier, SOURCES

logger = logging.getLogger("marketmind.config")

_prompt_cache: dict | None = None


def load_shadow_prompts(path: str | None = None) -> dict:
    """Load shadow methodology prompts from JSON config. Cached after first call.

    Returns dict with keys "expert" and "daredevil", each mapping domain/variant
    names to prompt strings.
    """
    global _prompt_cache
    if _prompt_cache is not None:
        return _prompt_cache
    if path is None:
        path = str(Path(__file__).parent / "shadow_prompts.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            _prompt_cache = json.load(f)
        return _prompt_cache
    except FileNotFoundError:
        logger.error("Shadow prompts file not found: %s", path)
        return {"expert": {}, "daredevil": {}}
    except json.JSONDecodeError as e:
        logger.error("Shadow prompts JSON parse error: %s", e)
        return {"expert": {}, "daredevil": {}}
