"""AEL 1-month experiment runner.

Runs 30 simulated daily cycles to verify the AEL (Adaptive Evolution Layer)
monthly debrief mechanism. Treatment shadows receive Pro debriefs on day 28.

Usage:
    cd projects/marketmind && python scripts/ael_experiment.py
"""
from __future__ import annotations

import asyncio
import json
import os
import random
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from marketmind.config.settings import ShadowSettings
from marketmind.shadows.ael_evolution import AELDebriefResult, AELEvolutionEngine
from marketmind.shadows.ranking_engine import ShadowPerformance
from marketmind.shadows.shadow_data_types import DailySnapshot
from marketmind.shadows.shadow_mother import ShadowOrchestrationResult
from marketmind.shadows.shadow_state import ShadowStateDB

TREATMENT_IDS = [
    "daredevil:range_bound:sideways_scout",
    "daredevil:weekly:trend_rider",
    "expert:tech:silicon_oracle",
    "expert:macro:cycle_reader",
]

LESSON_TEMPLATES = [
    "Avoid new positions during FOMC weeks. Scale into momentum with 50% initial size.",
    "Cut losers at -2% max. Let winners run past initial target by 20% before trailing stop.",
    "Reduce exposure when VIX > 25. Stack confirmations before entering trend-following trades.",
    "Fade extreme sentiment readings. Mean-revert only when RSI crosses below 30 on daily.",
]


def _build_performances(db: ShadowStateDB) -> dict[str, ShadowPerformance]:
    """Build ShadowPerformance dict for treatment shadows from snapshot history."""
    performances: dict[str, ShadowPerformance] = {}
    for sid in TREATMENT_IDS:
        snapshots = db.get_snapshot_history(sid, days=90)
        if not snapshots:
            continue
        returns = [s.daily_return_pct or 0.0 for s in snapshots
                   if s.daily_return_pct is not None]
        cum = sum(returns)
        wr = sum(1 for r in returns if r > 0) / len(returns) if returns else 0.5
        performances[sid] = ShadowPerformance(
            shadow_id=sid, daily_returns=returns, cumulative_return=cum,
            max_drawdown=abs(min(returns)) if returns else 0.01,
            max_drawdown_duration_days=0, win_rate=wr, total_trades=len(returns),
            profitable_trades=sum(1 for r in returns if r > 0),
            losing_trades=sum(1 for r in returns if r <= 0),
            abstention_days=0,
            cagr=cum * 252 / len(returns) if returns else 0.0,
        )
    return performances


async def run_experiment() -> int:
    """Run 30-day AEL experiment with mock data. Returns exit code."""
    cfg = ShadowSettings()
    cfg.ael_experiment_enabled = True
    cfg.ael_debrief_day = 28
    fd, tmp_path = tempfile.mkstemp(suffix=".db", prefix="ael_experiment_")
    os.close(fd)
    cfg.shadows_db_path = tmp_path

    db = ShadowStateDB(cfg.shadows_db_path)
    db.init_schema()
    try:
        await _run_experiment_loop(cfg, db)
    finally:
        db.close()
        os.unlink(tmp_path)
    return 0


async def _run_experiment_loop(cfg: ShadowSettings, db: ShadowStateDB) -> None:
    from marketmind.shadows.daredevil_shadows import create_daredevil_shadows
    from marketmind.shadows.expert_shadows import create_expert_shadows
    create_expert_shadows(db, cfg)
    create_daredevil_shadows(db, cfg)
    ae = AELEvolutionEngine()
    control_pairs = ae.ensure_control_replicas(db)
    print(f"Control replicas: {len(control_pairs)} created")

    debriefs_log: list[dict] = []

    mock_results = {
        sid: AELDebriefResult(
            shadow_id=sid, month="2026-06",
            win_rate=0.52 + random.random() * 0.08,
            cumulative_return=0.03 + random.random() * 0.06,
            total_trades=25, failure_patterns=["overtrading"],
            success_patterns=["momentum scaling"],
            lessons_learned=LESSON_TEMPLATES[i % len(LESSON_TEMPLATES)],
        )
        for i, sid in enumerate(TREATMENT_IDS)
    }

    async def _mock_debrief(self, sid, perf, mkt_ctx=""):
        return mock_results.get(sid, AELDebriefResult(
            shadow_id=sid, month="2026-06", win_rate=0.5,
            cumulative_return=0.0, total_trades=0,
            failure_patterns=[], success_patterns=[], lessons_learned="",
        ))

    with patch(
        "marketmind.shadows.ael_evolution.AELEvolutionEngine.run_monthly_debrief",
        _mock_debrief,
    ), patch(
        "marketmind.shadows.methodology_evolver.MethodologyInjector.inject_lessons",
    ):
        from marketmind.shadows.step_ael import run_ael_step

        for day in range(1, 91):
            month = "06" if day <= 30 else "07" if day <= 60 else "08"
            dom = day if day <= 30 else day - 30 if day <= 60 else day - 60
            date_str = f"2026-{month}-{dom:02d}"

            for sid in TREATMENT_IDS:
                ret = (hash(f"{sid}:{day}") % 200 - 100) / 10000.0
                db.save_snapshot(sid, DailySnapshot(
                    shadow_id=sid, date=date_str, virtual_capital=100000.0,
                    daily_return_pct=ret, cumulative_return_pct=ret * day,
                    votes_produced=1,
                ))

            result = ShadowOrchestrationResult(date=date_str)
            await run_ael_step(cfg, db, _build_performances(db),
                               {"VIX": 18.5, "SPY": 5200.0}, date_str, result)

            for debrief in result.ael_debriefs:
                entry = {
                    "day": day, "date": date_str, "shadow_id": debrief.shadow_id,
                    "month": debrief.month, "win_rate": debrief.win_rate,
                    "cumulative_return": debrief.cumulative_return,
                    "lessons_learned": debrief.lessons_learned,
                    "prompt_injected": debrief.prompt_injected,
                }
                debriefs_log.append(entry)
                status = "INJECTED" if debrief.prompt_injected else "REJECTED"
                print(f"[Day {day:2d}] AEL {status}: {debrief.shadow_id}")

    print(f"\n{'=' * 60}")
    print(f"AEL EXPERIMENT SUMMARY — 90 days (3 months), {len(debriefs_log)} lessons")
    print(f"{'=' * 60}")

    summary: dict = {
        "experiment_days": 90, "debrief_day": 28,
        "total_debriefs": len(debriefs_log), "lessons_by_shadow": {},
        "debriefs": debriefs_log,
    }
    for entry in debriefs_log:
        sid = entry["shadow_id"]
        summary["lessons_by_shadow"].setdefault(sid, []).append({
            "lesson": entry["lessons_learned"],
            "injected": entry["prompt_injected"],
        })

    for sid, lessons in summary["lessons_by_shadow"].items():
        short = sid.rsplit(":", 1)[-1]
        print(f"\n  {short} ({sid}):")
        for l in lessons:
            tag = "[INJECTED]" if l["injected"] else "[REJECTED]"
            print(f"    {tag} {l['lesson'][:90]}")

    out_dir = Path(__file__).resolve().parent.parent / "data"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "ael_experiment_summary.json"
    out_path.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    print(f"\nSummary written to: {out_path}")


if __name__ == "__main__":
    sys.exit(asyncio.run(run_experiment()))
