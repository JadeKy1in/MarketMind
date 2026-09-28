"""Watchlist with code-checkable confirmation conditions (docs/S10_DESIGN.md §3)."""
from marketmind.watchlist.conditions import SCHEMA, describe, evaluate, validate_condition
from marketmind.watchlist.runner import (
    add_items, check_all, daily_summary, dashboard_items, levels, notify_triggers,
)
from marketmind.watchlist.store import WatchItem, WatchlistStore, default_watchlist_path

__all__ = [
    "SCHEMA", "describe", "evaluate", "validate_condition",
    "add_items", "check_all", "daily_summary", "dashboard_items", "levels", "notify_triggers",
    "WatchItem", "WatchlistStore", "default_watchlist_path",
]
