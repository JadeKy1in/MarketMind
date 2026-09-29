"""CLI: python -m marketmind.promotion retire {list,approve,reject} [shadow_id]

Owner decisions on retirement proposals (promotion/retirement.py, SPEC L1).
`approve` retires the shadow and starts its successor; when the proposal names a
donor, the successor methodology is one LLM rewrite of the donor's methodology.
"""
from __future__ import annotations

import argparse
import asyncio
import sys

from marketmind.promotion import retirement
from marketmind.shadows.v3.roster import retirements_path


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m marketmind.promotion")
    sub = p.add_subparsers(dest="cmd", required=True)
    ret = sub.add_parser("retire", help="retirement proposals (owner approval)")
    rsub = ret.add_subparsers(dest="action", required=True)
    rsub.add_parser("list")
    for name in ("approve", "reject"):
        rsub.add_parser(name).add_argument("shadow_id")
    args = p.parse_args(argv)

    if args.action == "list":
        props = retirement.load()["proposals"]
        if not props:
            print("没有退役提案")
        for x in props:
            s = x.get("successor") or {}
            r = x.get("reason") or {}
            print(f"{x['shadow_id']} {x['status']} 提出 {x.get('proposed_at')} "
                  f"决定 {x.get('decided_at') or '-'}｜挑战者 {r.get('challengers')}｜"
                  f"领域超额均值 {r.get('excess_domain_mean')}（{r.get('excess_n')} 笔，"
                  f"{r.get('window')}）｜接任者 {s.get('shadow_id')} 方法论来源 "
                  f"{s.get('donor_id') or '自身原方法论'}")
        return 0
    try:
        if args.action == "approve":
            data = retirement.load()
            pending = next((x for x in data["proposals"] if x["shadow_id"] == args.shadow_id
                            and x["status"] == retirement.PENDING), None)
            if pending and (pending.get("successor") or {}).get("donor_id"):
                from marketmind.config.settings import MarketMindConfig
                from marketmind.gateway.async_client import init_gateway
                cfg = MarketMindConfig()
                init_gateway(cfg.deepseek_api_key, cfg.deepseek_base_url)
            prop = asyncio.run(retirement.approve(args.shadow_id))
            s = prop["successor"]
            print(f"已退役 {args.shadow_id}；接任者 {s['shadow_id']} 从见习开始，"
                  f"方法论来源 {s.get('donor_id') or '自身原方法论'}，文件 {retirements_path().parent / s['prompt_file']}")
        else:
            prop = retirement.reject(args.shadow_id)
            print(f"已拒绝 {args.shadow_id} 的退役提案")
    except ValueError as e:
        print(f"拒绝：{e}")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
