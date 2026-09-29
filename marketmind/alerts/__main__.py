"""python -m marketmind.alerts {run,ack,list,test-notify} (docs/S8_DESIGN.md)."""
from __future__ import annotations

import argparse
import asyncio
import sys


def _store():
    from marketmind.ledger.store import LedgerStore, default_ledger_path
    return LedgerStore(default_ledger_path())


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m marketmind.alerts")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="evaluate today's alerts (trend changes + annotations)")
    r.add_argument("--crypto-only", action="store_true", help="weekend: crypto instruments only")
    a = sub.add_parser("ack", help="record your response to an alert")
    a.add_argument("entry_id")
    a.add_argument("decision", choices=["accept", "reject"])
    a.add_argument("--note", default="")
    sub.add_parser("list", help="alerts in the ledger and your responses")
    sub.add_parser("test-notify", help="send a test message to every configured channel")
    args = p.parse_args(argv)

    from marketmind.alerts import runner
    if args.cmd == "run":
        from marketmind.alerts.notify import send
        report = asyncio.run(runner.run_alerts(_store(), notifier=send,
                                               crypto_only=args.crypto_only))
        src = report["trend_source"]
        print(f"模式：{'观察（不推送）' if report['mode'] == runner.OBSERVE else '正式'}；"
              f"趋势来源 {src['source']}（{src.get('universe') or '不可用'}）；"
              f"触发 {len(report['fired'])}，WATCH {len(report['near_misses'])}")
        if not src["available"]:
            print(f"  趋势来源不可用：{src.get('reason')}")
        for f in report["fired"]:
            print(f"  {f['kind']} {f['ticker']}：{f['status_cn']}；账本 {f['entry_id'] or '（离场只进报告）'}")
        return 0
    if args.cmd == "ack":
        try:
            r = runner.record_response(args.entry_id, args.decision, args.note, store=_store())
        except ValueError as e:
            print(f"拒绝：{e}")
            return 2
        print(f"已记录：{r['entry_id']} {r['decision']}")
        return 0
    if args.cmd == "list":
        responses = runner.load_responses()
        rows = _store().list(source_type="alert")
        if not rows:
            print("账本里还没有警报")
        for e in rows:
            r = responses.get(e.entry_id, {}).get("decision", "未回应")
            ret = f"{e.net_return:+.1%}" if e.net_return is not None else e.status
            print(f"{e.entry_id} {e.created_at[:10]} {e.source_id} {e.ticker} {r} {ret}")
        return 0
    from marketmind.alerts.notify import send
    results = asyncio.run(send("MarketMind 测试消息", "推送渠道测试：收到这条说明配置正确。"))
    if not results:
        print("没有配置任何推送渠道")
        return 1
    for r in results:
        print(f"{r['channel']}: {'成功' if r['ok'] else '失败'}（HTTP {r['status']}）")
    return 0 if all(r["ok"] for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
