"""MarketMind configuration package."""
import json
import logging
import time
from pathlib import Path

from marketmind.config.settings import MarketMindConfig
from marketmind.config.asset_universe import Asset, ASSET_UNIVERSE, get_asset
from marketmind.config.source_authority import Source, SourceTier, SOURCES

logger = logging.getLogger("marketmind.config")

_prompt_cache: dict | None = None
_prompt_cache_mtime: float = 0.0


def load_shadow_prompts(path: str | None = None, reload: bool = False,
                        stale_after_seconds: int = 0) -> dict:
    """Load shadow methodology prompts from JSON config.

    Args:
        path: Path to the JSON file (default: config/shadow_prompts.json).
        reload: If True, force re-read from disk, bypassing cache.
        stale_after_seconds: If > 0, re-read if file mtime is older than this many seconds.

    Returns dict with keys "expert" and "daredevil".
    """
    global _prompt_cache, _prompt_cache_mtime
    if path is None:
        path = str(Path(__file__).parent / "shadow_prompts.json")

    if not reload and _prompt_cache is not None:
        if stale_after_seconds > 0:
            try:
                file_mtime = Path(path).stat().st_mtime
                if time.time() - file_mtime < stale_after_seconds:
                    return _prompt_cache
            except OSError:
                return _prompt_cache
        else:
            return _prompt_cache

    try:
        with open(path, "r", encoding="utf-8") as f:
            _prompt_cache = json.load(f)
        _prompt_cache_mtime = time.time()
        logger.info("Shadow prompts loaded from %s", path)
        return _prompt_cache
    except FileNotFoundError:
        logger.error("Shadow prompts file not found: %s", path)
        return {"expert": {}, "daredevil": {}}
    except json.JSONDecodeError as e:
        logger.error("Shadow prompts JSON parse error: %s", e)
        return {"expert": {}, "daredevil": {}}
