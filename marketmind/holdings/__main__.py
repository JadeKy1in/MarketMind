"""python -m marketmind.holdings {list,add,remove,inspect} (docs/S6_DESIGN.md)."""
from __future__ import annotations

import argparse
import asyncio
import sys

from marketmind.holdings import store as hs


def _ledger():
    from marketmind.ledger.store import LedgerStore, default_ledger_path
    return LedgerStore(default_ledger_path())


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m marketmind.holdings",
                                description="Owner holdings (stored in data/holdings.json, never committed)")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    a = sub.add_parser("add")
    a.add_argument("ticker")
    a.add_argument("quantity", type=float)
    a.add_argument("cost_basis", type=float, help="average cost per unit, USD")
    a.add_argument("--opened", help="YYYY-MM-DD (default today, UTC)")
    a.add_argument("--stop", type=float, help="your own stop price")
    a.add_argument("--note", default="")
    r = sub.add_parser("remove")
    r.add_argument("ticker")
    sub.add_parser("inspect")
    args = p.parse_args(argv)

    if args.cmd == "list":
        rows = hs.load()
        if not rows:
            print("没有持仓（data/holdings.json）")
        for h in rows:
            stop = f"  止损 {h.stop}" if h.stop else ""
            print(f"{h.ticker:10s} {h.quantity:>12,.4f} @ {h.cost_basis:,.4f}  自 {h.opened}{stop}  {h.note}")
        return 0
    if args.cmd == "add":
        try:
            h = hs.add(args.ticker, args.quantity, args.cost_basis, opened=args.opened,
                       stop=args.stop, note=args.note, ledger=_ledger())
        except ValueError as e:
            print(f"拒绝：{e}")
            return 2
        print(f"已记录 {h.ticker}：{h.quantity:,.4f} @ {h.cost_basis:,.4f}；账本 {h.ledger_ids[-1]}")
        return 0
    if args.cmd == "remove":
        print("已删除" if hs.remove(args.ticker) else "没有这个持仓")
        return 0
    from marketmind.holdings.inspect import run_inspection
    reports, path = asyncio.run(run_inspection(_ledger()))
    if not reports:
        print("没有持仓，跳过巡检")
        return 0
    for r in reports:
        pnl = f"{r.unrealized_return:+.1%}" if r.unrealized_return is not None else "n/a"
        print(f"{r.ticker:10s} {pnl:>8s}  {r.verdict_cn}：{r.reason}")
        for alt in r.alternatives:
            print(f"    替代 {alt['ticker']} R/R {alt['reward_risk']:.2f}")
    print(f"报告：{path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
