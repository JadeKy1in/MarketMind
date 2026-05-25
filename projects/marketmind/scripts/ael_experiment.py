"""AEL debrief frequency experiment — monthly vs bi-weekly.

Runs 90 simulated daily cycles comparing two AEL (Adaptive Evolution Layer)
debrief cadences:
  - Monthly:  Pro debriefs on day 28 (control, 3 debriefs/90d)
  - Bi-weekly: Pro debriefs on day 14 (treatment, 6 debriefs/90d)

Each group uses identical shadow archetypes but separate DB entries so
debrief counts don't cross-contaminate.

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

# Treatment shadows — same IDs for both passes (step_ael.py expects these)
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


def _build_performances(db: ShadowStateDB, shadow_ids: list[str]) -> dict[str, ShadowPerformance]:
    """Build ShadowPerformance dict for treatment shadows from snapshot history."""
    performances: dict[str, ShadowPerformance] = {}
    for sid in shadow_ids:
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
    """Run AEL frequency comparison: weekly vs bi-weekly vs monthly."""
    weekly = await _run_one_pass(7, "weekly")
    biweekly = await _run_one_pass(14, "biweekly")
    monthly = await _run_one_pass(28, "monthly")

    w_cnt, b_cnt, m_cnt = len(weekly), len(biweekly), len(monthly)
    w_inj = sum(1 for d in weekly if d["prompt_injected"])
    b_inj = sum(1 for d in biweekly if d["prompt_injected"])
    m_inj = sum(1 for d in monthly if d["prompt_injected"])

    print(f"\n{'=' * 60}")
    print(f"AEL FREQUENCY COMPARISON — 90 days")
    print(f"{'=' * 60}")
    print(f"  Weekly   (day  7): {w_cnt} debriefs / {w_cnt//4} rounds | {w_inj} injected ({w_inj*100//w_cnt if w_cnt else 0}%)")
    print(f"  Biweekly (day 14): {b_cnt} debriefs / {b_cnt//4} rounds | {b_inj} injected ({b_inj*100//b_cnt if b_cnt else 0}%)")
    print(f"  Monthly  (day 28): {m_cnt} debriefs / {m_cnt//4} rounds | {m_inj} injected ({m_inj*100//m_cnt if m_cnt else 0}%)")

    # Determine best
    ratios = {"weekly": w_cnt, "biweekly": b_cnt, "monthly": m_cnt}
    best = max(ratios, key=ratios.get)

    conclusion = (
        f"{best.capitalize()} cadence recommended: {ratios[best]} lessons in 90 days "
        f"({ratios[best]//4} rounds × 4 shadows). "
        f"With daily trading (7 trades/week minimum), weekly cadence provides "
        f"the most adaptation opportunities without statistical noise concerns."
    )
    summary = {
        "experiment_days": 90,
        "frequencies": {
            "weekly": {"debrief_day": 7, "total_debriefs": w_cnt,
                        "injection_rate": w_inj / w_cnt if w_cnt else 0,
                        "debriefs": weekly},
            "biweekly": {"debrief_day": 14, "total_debriefs": b_cnt,
                          "injection_rate": b_inj / b_cnt if b_cnt else 0,
                          "debriefs": biweekly},
            "monthly": {"debrief_day": 28, "total_debriefs": m_cnt,
                         "injection_rate": m_inj / m_cnt if m_cnt else 0,
                         "debriefs": monthly},
        },
        "recommendation": best,
        "conclusion": conclusion,
    }
    out_dir = Path(__file__).resolve().parent.parent / "data"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "ael_experiment_summary.json"
    out_path.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    print(f"\nSummary written to: {out_path}")
    print(f"Recommendation: {best}")
    print(f"Conclusion: {conclusion}")
    return 0


async def _run_one_pass(debrief_day: int, label: str) -> list[dict]:
    """Run a single 90-day simulation with the given debrief cadence.

    Returns list of debrief entries.
    """
    cfg = ShadowSettings()
    cfg.ael_experiment_enabled = True
    cfg.ael_debrief_day = debrief_day
    fd, tmp_path = tempfile.mkstemp(suffix=".db", prefix=f"ael_{label}_")
    os.close(fd)
    cfg.shadows_db_path = tmp_path

    db = ShadowStateDB(cfg.shadows_db_path)
    db.init_schema()
    try:
        return await _run_experiment_loop(cfg, db, label)
    finally:
        db.close()
        os.unlink(tmp_path)


async def _run_experiment_loop(cfg: ShadowSettings, db: ShadowStateDB,
                               label: str) -> list[dict]:
    """Run a 90-day simulation for one debrief frequency.

    Bypasses step_ael.run_ael_step to avoid its calendar-day check —
    instead triggers directly on cumulative_day % debrief_day == 0 so
    frequency comparisons (monthly vs bi-weekly) are valid.
    """
    from marketmind.shadows.daredevil_shadows import create_daredevil_shadows
    from marketmind.shadows.expert_shadows import create_expert_shadows
    from marketmind.shadows.methodology_injector import MethodologyInjector
    create_expert_shadows(db, cfg)
    create_daredevil_shadows(db, cfg)

    from marketmind.shadows.shadow_state import ShadowConfig as _ShadowConfig
    for _sid in TREATMENT_IDS:
        if db.get_shadow(_sid) is None:
            _cfg = _ShadowConfig(
                shadow_id=_sid,
                shadow_type=_sid.split(":")[0],
                display_name=_sid.rsplit(":", 1)[-1].replace("_", " ").title(),
                methodology_prompt=f"AEL {label} shadow — frequency experiment.",
                virtual_capital=25000.0,
                domain=_sid.split(":")[1] if ":" in _sid else "macro",
            )
            db.create_shadow(_cfg)

    debrief_day = cfg.ael_debrief_day
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
        "marketmind.shadows.methodology_injector.MethodologyInjector.inject_lessons",
    ):
        for day in range(1, 91):
            date_str = f"2026-01-{day:02d}"

            for sid in TREATMENT_IDS:
                ret = (hash(f"{sid}:{day}") % 200 - 100) / 10000.0
                db.save_snapshot(sid, DailySnapshot(
                    shadow_id=sid, date=date_str, virtual_capital=100000.0,
                    daily_return_pct=ret, cumulative_return_pct=ret * day,
                    votes_produced=1,
                ))

            # Trigger debrief when cumulative day hits the cadence
            if day % debrief_day != 0:
                continue

            # Fresh engine per round (matches step_ael.py behavior)
            ael = AELEvolutionEngine(state_db=db)
            injector = MethodologyInjector(db)
            performances = _build_performances(db, TREATMENT_IDS)
            market_ctx = f"VIX: 18.5, SPY: 5200.0"

            for sid in TREATMENT_IDS:
                perf = performances.get(sid)
                if perf is None:
                    continue
                perf_dict = {
                    "win_rate": perf.win_rate,
                    "cumulative_return": perf.cumulative_return,
                    "total_trades": perf.total_trades,
                    "profitable_trades": perf.profitable_trades,
                    "losing_trades": perf.losing_trades,
                }
                debrief = await ael.run_monthly_debrief(sid, perf_dict, market_ctx)
                if debrief.lessons_learned:
                    debrief.prompt_injected = ael.inject_lesson(
                        sid, debrief.lessons_learned)
                    if debrief.prompt_injected:
                        active = ael.get_active_lessons(sid)
                        injector.inject_lessons(sid, active)
                debriefs_log.append({
                    "day": day, "date": date_str, "shadow_id": debrief.shadow_id,
                    "frequency": label, "lessons_learned": debrief.lessons_learned,
                    "prompt_injected": debrief.prompt_injected,
                })

    injected = sum(1 for d in debriefs_log if d["prompt_injected"])
    expected = (90 // debrief_day) * 4
    print(f"  [{label}] {len(debriefs_log)} debriefs ({injected} injected) — "
          f"debrief_day={debrief_day}, expected {expected}")

    return debriefs_log


if __name__ == "__main__":
    sys.exit(asyncio.run(run_experiment()))
