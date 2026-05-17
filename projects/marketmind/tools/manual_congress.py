"""Manual Congress trading data entry tool.

Usage:
    python tools/manual_congress.py

This tool provides a human-operated fallback for Congress trading data now that
all automated sources are dead (House Stock Watcher S3 403, Senate Stock Watcher
503/TLS, CapitolTrades BFF 503).

The user manually copies data from CapitolTrades.com or efd.senate.gov, pastes
it as JSON, and the tool validates and appends it to a JSONL file.

Programmatic access: import load_manual_congress_trades() — returns the same
shape as insider_sources.fetch_congress_trades() for drop-in compatibility.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "manual"
DATA_DIR.mkdir(parents=True, exist_ok=True)

JSONL_PATH = DATA_DIR / "congress_trades.jsonl"

REQUIRED_FIELDS = ["politician_name", "ticker", "transaction_type", "date", "amount_range"]

VALID_TRANSACTION_TYPES = {"buy", "sell"}

SOURCE_URLS = {
    "Senate": "https://efdsearch.senate.gov/ (Periodic Transaction Reports)",
    "House": "https://disclosures-clerk.house.gov/ (Financial Disclosure Reports)",
    "CapitolTrades": "https://www.capitoltrades.com/trades (Free aggregator, easiest to copy from)",
}


# ---------------------------------------------------------------------------
# Reader — compatible with insider_sources.fetch_congress_trades() return type
# ---------------------------------------------------------------------------


def load_manual_congress_trades() -> list[dict]:
    """Read manually-entered Congress trades from the JSONL file.

    Returns a list of dicts, compatible shape with
    insider_sources.fetch_congress_trades() which returns list[Any].

    Each dict contains: politician_name, ticker, transaction_type, date,
    amount_range, saved_at (ISO 8601 UTC timestamp), and any extra fields
    the user provided.
    """
    if not JSONL_PATH.exists():
        return []

    trades: list[dict] = []
    with open(JSONL_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                trades.append(json.loads(line))
            except json.JSONDecodeError:
                print(f"[WARN] Skipping malformed JSON line in {JSONL_PATH}: {line[:80]}...",
                      file=sys.stderr)
    return trades


# ---------------------------------------------------------------------------
# CLI — interactive entry
# ---------------------------------------------------------------------------


def _print_source_help() -> None:
    """Print the list of official sources where to get Congress trade data."""
    print()
    print("官方数据来源:")
    for name, url in SOURCE_URLS.items():
        print(f"  {name}: {url}")
    print()


def _validate_trade(trade: dict, index: int) -> list[str]:
    """Validate a single trade dict. Returns a list of error messages (empty = valid)."""
    errors: list[str] = []

    for field in REQUIRED_FIELDS:
        if field not in trade or trade[field] is None or str(trade[field]).strip() == "":
            errors.append(f"  记录 #{index + 1}: 缺少必填字段 '{field}'")

    if errors:
        return errors

    tx_type = str(trade["transaction_type"]).strip().lower()
    if tx_type not in VALID_TRANSACTION_TYPES:
        errors.append(
            f"  记录 #{index + 1}: transaction_type 必须是 'buy' 或 'sell'，当前: '{tx_type}'"
        )

    ticker = str(trade["ticker"]).strip().upper()
    if not ticker.isalpha() or len(ticker) < 1 or len(ticker) > 5:
        errors.append(
            f"  记录 #{index + 1}: ticker 格式无效: '{ticker}'"
        )

    return errors


def _read_json_input() -> str:
    """Read multi-line JSON from stdin until an empty line.

    On Windows, EOF (Ctrl+Z) is also treated as terminator.
    """
    print("=" * 60)
    print("  国会交易数据录入")
    _print_source_help()
    print("请粘贴从 CapitolTrades.com 或 efd.senate.gov 复制的最新国会交易数据")
    print("（JSON格式，留空退出）:")
    print()
    print("JSON 格式示例:")
    print('  [')
    print('    {')
    print('      "politician_name": "Nancy Pelosi",')
    print('      "ticker": "AAPL",')
    print('      "transaction_type": "buy",')
    print('      "date": "2026-05-15",')
    print('      "amount_range": "$1M-$5M"')
    print('    }')
    print('  ]')
    print("=" * 60)

    lines: list[str] = []
    while True:
        try:
            line = input()
        except EOFError:
            break
        stripped = line.strip()
        if not stripped and lines:
            break
        if stripped:
            lines.append(stripped)

    return "\n".join(lines)


def _parse_and_save(raw_json: str) -> int:
    """Parse JSON input, validate, and append to JSONL. Returns count saved."""
    try:
        data = json.loads(raw_json)
    except json.JSONDecodeError as e:
        print(f"[ERROR] JSON 解析失败: {e}", file=sys.stderr)
        return 0

    # Normalize: accept single object or list
    if isinstance(data, dict):
        data = [data]
    elif not isinstance(data, list):
        print("[ERROR] 输入必须是 JSON 对象或数组", file=sys.stderr)
        return 0

    # Validate all records
    all_errors: list[str] = []
    for i, trade in enumerate(data):
        if not isinstance(trade, dict):
            all_errors.append(f"  记录 #{i + 1}: 不是 JSON 对象")
            continue
        all_errors.extend(_validate_trade(trade, i))

    if all_errors:
        print("[ERROR] 验证失败:")
        for err in all_errors:
            print(err, file=sys.stderr)
        return 0

    # Annotate each trade with timestamp and normalize fields
    saved_at = datetime.now(timezone.utc).isoformat()
    for trade in data:
        trade["saved_at"] = saved_at
        trade["ticker"] = str(trade["ticker"]).strip().upper()
        trade["transaction_type"] = str(trade["transaction_type"]).strip().lower()

    # Append to JSONL
    try:
        with open(JSONL_PATH, "a", encoding="utf-8") as f:
            for trade in data:
                f.write(json.dumps(trade, ensure_ascii=False) + "\n")
    except OSError as e:
        print(f"[ERROR] 无法写入文件 {JSONL_PATH}: {e}", file=sys.stderr)
        return 0

    return len(data)


def main() -> None:
    """Main entry point for manual Congress trade entry."""
    raw_json = _read_json_input()

    if not raw_json.strip():
        print("未输入任何数据，退出。")
        sys.exit(0)

    count = _parse_and_save(raw_json)
    if count > 0:
        print(f"\n已保存 {count} 条交易记录 → {JSONL_PATH}")
    else:
        print("\n未保存任何记录。", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
