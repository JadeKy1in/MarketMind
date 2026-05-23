"""Scout content analysis — salience computation, priority scoring, content hash caching.

Extracted from pipeline/scout.py for modular compliance (grandfather reduction).
"""
from __future__ import annotations
import hashlib
import json
import logging
import os
import re
from datetime import datetime, timezone

logger = logging.getLogger("marketmind.pipeline.scout_content")

# ── Z1: Salience regex patterns ──────────────────────────────────────────
# CRITICAL: \b word boundaries prevent "rate" matching "corporate"/"strategic" (Z1 audit Q1.1)
# Evaluation order: macro_event → earnings → filler (Z1 audit Q1.2 — broadest first
# because macro-signal articles must not be downgraded to filler or earnings)
_RE_MACRO_EVENT = re.compile(
    r"\b(?:Fed|ECB|PBOC|rate|inflation|GDP|employment|CPI|PPI)\b",
    re.IGNORECASE,
)
_RE_EARNINGS = re.compile(
    r"\b(?:earnings|revenue|profit|guidance)\b",
    re.IGNORECASE,
)
# NOTE: "mixed close" is intentionally short (11 chars) but filler-is-last ordering
# ensures macro-containing filler-prefixed headlines are correctly classified as macro.
_RE_FILLER = re.compile(
    r"\b(?:market wrap|closing bell|stocks edge|mixed close)\b",
    re.IGNORECASE,
)

# Z1: Content hash cache path (relative to scout_content.py → ../data/cache/)
_CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "cache")
_CACHE_PATH = os.path.join(_CACHE_DIR, "content_hash_tracker.json")


def compute_content_hash(title: str, summary: str) -> str | None:
    """SHA256 of lowercased + normalized title|summary. Returns None if content is empty.

    Empty-content guard (Z1 audit E3): if both title and summary are empty after
    strip, return None to avoid the well-known SHA256("") collision.
    """
    try:
        t = (title or "").strip().lower()
        s = (summary or "")[:500].strip().lower()
        if not t and not s:
            return None
        text = f"{t}|{s}"
        return hashlib.sha256(text.encode("utf-8")).hexdigest()
    except Exception:
        return None


def compute_salience_multiplier(title: str, summary: str) -> float:
    """Classify article salience via regex on title + summary[:200].

    Evaluation order (Z1 audit Q1.2): macro_event → earnings → filler.
    Returns 1.15 (macro), 1.05 (earnings), 0.85 (filler), or 1.0 (neutral).

    KNOWN LIMITATION (Z1 audit E1): patterns are English-only. Non-English
    sources (e.g., Caixin Chinese headlines) will always return 1.0.
    Chinese-language regex support is deferred to Phase Z1b/Z4.
    """
    try:
        text = f"{title or ''} {(summary or '')[:200]}"
    except Exception:
        return 1.0
    try:
        if _RE_MACRO_EVENT.search(text):
            return 1.15
        if _RE_EARNINGS.search(text):
            return 1.05
        if _RE_FILLER.search(text):
            return 0.85
        return 1.0
    except Exception:
        return 1.0


def parse_published_at(published_at: str) -> datetime | None:
    """Parse published_at string to timezone-aware datetime.

    Returns None on failure (Z1 audit E2: unparseable dates handled by caller).
    """
    if not published_at or not published_at.strip():
        return None
    ts = published_at.strip()
    # Try ISO 8601 first (API sources)
    try:
        ts_normalized = ts.replace("Z", "+00:00")
        dt = datetime.fromisoformat(ts_normalized)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        pass
    # Try dateutil if available (handles RFC 822, relative, etc.)
    try:
        from dateutil.parser import parse as dateutil_parse  # type: ignore[import-untyped]
        dt = dateutil_parse(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        pass
    return None


def compute_priority(item, now: datetime) -> float:
    """Compute priority score: 0.45*reliability + 0.25*freshness + 0.30*tier_bonus,
    multiplied by salience_multiplier. HOT max_age = 6h.

    Priority function must never raise (Z1 audit E5). All computations are
    try/except-wrapped with sane defaults.

    Args:
        item: NewsItem with source_reliability, published_at, source_tier, salience_multiplier.
        now: current UTC datetime.
    """
    # --- reliability (0.45 weight) ---
    try:
        reliability = float(getattr(item, "source_reliability", 0.5))
    except (TypeError, ValueError):
        reliability = 0.5

    # --- freshness (0.25 weight) ---
    try:
        pub_dt = parse_published_at(item.published_at)
    except Exception:
        pub_dt = None
    if pub_dt is None:
        freshness = 0.3
    else:
        try:
            hours = (now - pub_dt).total_seconds() / 3600.0
            if hours < 0:
                hours = 0.0
            max_age = 6.0
            freshness = 1.0 - hours / max_age
            freshness = max(0.0, min(1.0, freshness))
        except Exception:
            freshness = 0.3

    # --- tier_bonus (0.30 weight) ---
    try:
        tier = int(getattr(item, "source_tier", 4))
    except (TypeError, ValueError):
        tier = 4
    if tier == 1:
        tier_bonus = 1.0
    elif tier == 2:
        tier_bonus = 0.6
    elif tier == 3:
        tier_bonus = 0.4
    else:
        tier_bonus = 0.3

    # --- salience ---
    try:
        salience = float(getattr(item, "salience_multiplier", 1.0))
    except (TypeError, ValueError):
        salience = 1.0

    try:
        base = 0.45 * reliability + 0.25 * freshness + 0.30 * tier_bonus
        return base * salience
    except Exception:
        return 0.0


def load_prune_content_hash_cache(path: str) -> dict:
    """Load content hash cache from JSON, prune entries older than 72h.

    Corruption recovery (Z1 audit Q3.1): JSONDecodeError or OSError → log warning,
    delete corrupted file, return empty cache.
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return {}
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Content hash cache corrupted, resetting: %s", e)
        try:
            os.remove(path)
        except OSError:
            pass
        return {}
    if not isinstance(data, dict):
        logger.warning("Content hash cache is not a dict, resetting")
        return {}
    try:
        now = datetime.now(timezone.utc)
        cutoff = now.timestamp() - 72 * 3600
        pruned: dict = {}
        for h, ts in data.items():
            if not isinstance(h, str) or not isinstance(ts, str):
                continue
            try:
                t = datetime.fromisoformat(ts)
                if t.timestamp() >= cutoff:
                    pruned[h] = ts
            except Exception:
                continue
        return pruned
    except Exception:
        return {}


def save_content_hash_cache(path: str, cache: dict) -> None:
    """Atomically write content hash cache to JSON via temp file.

    Creates the cache directory if it doesn't exist (Z1 audit Q3.2).
    Uses os.replace() for atomic write.
    """
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp_path = path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False)
        os.replace(tmp_path, path)
    except Exception as e:
        logger.warning("Failed to save content hash cache: %s", e)
