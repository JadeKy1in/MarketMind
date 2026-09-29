"""CLI: python -m marketmind.ecosystem [--day YYYY-MM-DD] [--data-dir DIR] [--dry-run] [--json]

Runs the ecosystem health checks on the ledger (read-only) and writes
<data dir>/ecosystem/<day>.json; --dry-run prints without writing anything.
"""
from __future__ import annotations

import argparse
import json
import sys

from marketmind.ecosystem.runner import run_ecosystem


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m marketmind.ecosystem")
    p.add_argument("--day", help="as-of New York date (default: today)")
    p.add_argument("--data-dir", help="data directory (default: MARKETMIND_DATA_DIR or ./data)")
    p.add_argument("--dry-run", action="store_true", help="do not write the report file")
    p.add_argument("--json", action="store_true", help="print the full report")
    args = p.parse_args(argv)
    doc = run_ecosystem(args.data_dir, today=args.day, write=not args.dry_run)
    if args.json:
        print(json.dumps(doc, ensure_ascii=False, indent=1, default=str))
    print(doc["summary"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
