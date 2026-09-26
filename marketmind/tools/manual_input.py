"""Manual data input tools — copy-paste from browser, save to data/manual/."""
from __future__ import annotations
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "manual"
DATA_DIR.mkdir(parents=True, exist_ok=True)


def input_congress() -> None:
    """Paste Congress trades. Format: TICKER,MEMBER,BUY/SELL,DATE,AMOUNT"""
    print("=" * 60)
    print("  国会交易录入")
    print("  打开 capitoltrades.com 或 Google 'congress stock trades'")
    print("  每行格式: TICKER,成员名,BUY或SELL,日期,大致金额")
    print("  例子: AAPL,Pelosi,BUY,2026-05-10,1M-5M")
    print("  输入完按 Enter 两次结束")
    print("=" * 60)

    lines = []
    while True:
        line = input("> ").strip()
        if not line:
            if lines:
                break
            continue
        lines.append(line)

    trades = []
    for line in lines:
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 4:
            trades.append({
                "ticker": parts[0].upper(),
                "representative": parts[1],
                "type": "purchase" if "BUY" in parts[2].upper() else "sale",
                "transaction_date": parts[3],
                "amount": parts[4] if len(parts) > 4 else "unknown",
            })

    if trades:
        fpath = DATA_DIR / "congress_trades.json"
        with open(fpath, "w", encoding="utf-8") as f:
            json.dump(trades, f, indent=2, ensure_ascii=False)
        print(f"  已保存 {len(trades)} 条交易 → {fpath}")


def input_bluesky() -> None:
    """Paste Bluesky posts about finance/markets."""
    print("=" * 60)
    print("  Bluesky 帖子录入")
    print("  打开 bsky.app，搜索 finance 或 $AAPL")
    print("  每行粘贴一条帖子内容")
    print("  输入完按 Enter 两次结束")
    print("=" * 60)

    lines = []
    while True:
        line = input("> ").strip()
        if not line:
            if lines:
                break
            continue
        lines.append(line)

    if lines:
        fpath = DATA_DIR / "bluesky_posts.json"
        posts = [{"text": l, "timestamp": datetime.now(timezone.utc).isoformat()} for l in lines]
        with open(fpath, "w", encoding="utf-8") as f:
            json.dump(posts, f, indent=2, ensure_ascii=False)
        print(f"  已保存 {len(lines)} 条帖子 → {fpath}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python tools/manual_input.py congress|bluesky")
        sys.exit(1)
    cmd = sys.argv[1].lower()
    if cmd == "congress":
        input_congress()
    elif cmd == "bluesky":
        input_bluesky()
    else:
        print(f"未知命令: {cmd}，用 congress 或 bluesky")
