"""Scout monitoring report — daily source health report and Z0 metrics recording.

Extracted from pipeline/scout.py for modular compliance (grandfather reduction).
"""
from __future__ import annotations
import json as _json
import os as _os
from datetime import datetime, timezone

from marketmind.config.source_authority import SourceTier, SourceStatus


def record_z0_metrics(sources, counts, issues, rss_count, api_count, rss_health, pre_dedup, post_dedup) -> None:
    """Z0 baseline: append per-run metrics to .claude/metrics/baseline.jsonl (accumulates across days)."""
    try:
        metrics_root = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", ".claude", "metrics")
        _os.makedirs(metrics_root, exist_ok=True)
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source_count": len(sources),
            "rss_article_count": rss_count,
            "api_article_count": api_count,
            "rss_health_score": round(rss_health, 3),
            "pre_dedup_total": pre_dedup,
            "post_dedup_total": post_dedup,
            "issues": issues[:10],
        }
        fpath = _os.path.join(metrics_root, "baseline.jsonl")
        with open(fpath, "a", encoding="utf-8") as f:
            f.write(_json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        pass


def print_scout_report(sources: list, counts: dict[str, int], issues: list[str], total: int) -> None:
    """Print daily source monitoring report after news collection."""
    tier_names = {SourceTier.PRIMARY: '核心', SourceTier.RELIABLE: '可靠',
                  SourceTier.FRAGILE: '脆弱', SourceTier.BEST_EFFORT: '尽力'}

    working = sum(1 for s in sources if s.status == SourceStatus.WORKING and counts.get(s.name, 0) > 0)
    empty = sum(1 for s in sources if counts.get(s.name, 0) == 0)
    degraded = sum(1 for s in sources if s.status == SourceStatus.DEGRADED)

    print(f"\n{'='*60}")
    print(f"  每日新闻源监测报告")
    print(f"  总文章: {total} | 活跃源: {working} | 空源: {empty} | 降级: {degraded}")
    print(f"  {'='*60}")

    for s in sources:
        c = counts.get(s.name, 0)
        tier = tier_names.get(s.tier, '?')
        if s.status == SourceStatus.DEAD:
            flag = '[DEAD]'
        elif s.status == SourceStatus.DEGRADED:
            flag = '[DEGRADED]'
        elif c == 0:
            flag = '[EMPTY]'
        else:
            flag = ''
        print(f"  [{tier}] {s.name}: {c}篇 {flag}".strip())

    if issues:
        print(f"\n  [警告] 以下源需要关注:")
        for issue in issues[:10]:
            print(f"    - {issue}")
        if len(issues) > 10:
            print(f"    - ... 还有 {len(issues) - 10} 个问题")

    print(f"  {'='*60}\n")
