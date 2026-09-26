"""Backtest entry point — validates shadow consensus signal quality across dates."""
from __future__ import annotations
import json
import logging
import sys
from datetime import datetime, timezone

from marketmind.config.settings import MarketMindConfig


def run_backtest(config: MarketMindConfig, args) -> int:
    """Run multi-day backtest on shadow consensus signal quality."""
    from marketmind.shadows.shadow_state import ShadowStateDB
    from marketmind.backtest_runner import BacktestRunner

    logging.basicConfig(level=logging.INFO)

    shadow_db = ShadowStateDB(config.shadow.shadows_db_path)
    shadow_db.init_schema()

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    start = args.start or "2026-01-01"
    end = args.end or today

    try:
        runner = BacktestRunner(shadow_db)
        report = runner.run(start, end, args.output)
    except (ValueError, FileNotFoundError) as e:
        print(f"[ERROR] Backtest failed: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"[ERROR] Unexpected backtest error: {e}", file=sys.stderr)
        return 1

    print(json.dumps(report, indent=2) if not args.output else
          f"Backtest report written to {args.output}")

    return 0
