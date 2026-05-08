#!/usr/bin/env python3
"""
Phase 8.4 红蓝对抗极限压测 (Adversarial Stress Test)

对 BeliefStateManager 的三个极端攻击场景进行兵棋推演：
  场景 1 — 信息茧房狂热 (The Echo Chamber)
  场景 2 — 黑天鹅多空双杀 (The Schizophrenia Test)
  场景 3 — 高频噪音轰炸 (The Noise Bombardment)

运行: python scripts/run_stress_test_8_4.py
"""

import datetime
import json
import os
import sys
from typing import Any, Dict, List, Tuple

# Add project root to sys.path
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.join(_SCRIPT_DIR, "..", "projects", "robinhood")
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from src.belief_types import (
    BeliefObservation,
    BeliefSource,
    BeliefStatus,
    ResolutionStrategy,
)
from src.belief_state_manager import (
    BeliefManagerConfig,
    BeliefStateManager,
)


# ============================================================
# Helpers
# ============================================================

def _make_obs(value: float, confidence: float,
              source: BeliefSource = BeliefSource.INFERRED,
              ts: str = "2026-01-01T00:00:00.000000Z") -> BeliefObservation:
    return BeliefObservation(
        value=value,
        confidence=confidence,
        source=source,
        timestamp=ts,
    )


def _get_ts(day: int, hour: int = 0) -> str:
    return f"2026-01-{day:02d}T{hour:02d}:00:00.000000Z"


def _header(title: str) -> None:
    width = 72
    print()
    print("#" * width)
    print(f"  {title}")
    print("#" * width)


def _subheader(title: str) -> None:
    print()
    print(f"--- {title} ---")


# ============================================================
# 场景 1: 信息茧房狂热 (The Echo Chamber)
# ============================================================

def run_scenario_1() -> Dict[str, Any]:
    _header("场景 1: 信息茧房狂热 (The Echo Chamber)")

    manager = BeliefStateManager(BeliefManagerConfig(gamma=1.0))
    pid = manager.register_node(
        "宏观衰退",
        proposition_id="macro-recession",
        alpha=1.0, beta=1.0,
    )

    BEAR_VALUE = 0.05
    BEAR_CONF = 0.95
    BULL_VALUE = 0.95
    BULL_CONF = 0.95

    # Phase A: 茧房构建
    _subheader("Phase A: 10 条高置信度熊市观测")

    for i in range(10):
        snap = manager.ingest_observation(
            pid, _make_obs(BEAR_VALUE, BEAR_CONF, ts=_get_ts(i + 1))
        )
        print(f"  [{i+1:2d}] alpha={snap.node.alpha:.4f}, beta={snap.node.beta:.4f}, "
              f"E[t]={snap.expectation:.4f}, Var={snap.uncertainty:.6f}, "
              f"score={snap.score:.4f}")

    snap_before = manager.get_snapshot(pid)
    var_final = snap_before.uncertainty
    var_initial = 1.0 / 12.0  # Beta(1,1) theoretical variance

    print(f"\n  方差缩减率: {(1 - var_final / var_initial) * 100:.1f}%"
          f" ({var_initial:.6f} -> {var_final:.6f})")

    # Phase B: 反向冲击
    _subheader("Phase B: 反向冲击 -- 注入牛市观测")

    reversal_count = 0
    for i in range(30):
        snap = manager.ingest_observation(
            pid, _make_obs(BULL_VALUE, BULL_CONF, ts=_get_ts(11 + i))
        )
        reversal_count += 1
        if snap.expectation >= 0.5:
            break

    snap_after = manager.get_snapshot(pid)
    print(f"  需要 {reversal_count} 条牛市观测将 E[t] 拉回 >= 0.5")
    print(f"  最终状态: alpha={snap_after.node.alpha:.4f}, "
          f"beta={snap_after.node.beta:.4f}, "
          f"E[t]={snap_after.expectation:.4f}")

    assert 5 <= reversal_count <= 18, (
        f"Reversal should require 5-18 bullish obs; got {reversal_count}"
    )

    result = {
        "scenario": "1 - 信息茧房狂热",
        "initial_var": round(var_initial, 6),
        "final_var": round(var_final, 6),
        "variance_shrink_pct": round((1 - var_final / var_initial) * 100, 2),
        "reversal_count": reversal_count,
        "final_expectation": round(snap_after.expectation, 6),
        "status": "PASS" if 5 <= reversal_count <= 18 else "FAIL",
    }

    print(f"\n  >>> 场景 1 战果: {result['status']}")
    return result


# ============================================================
# 场景 2: 黑天鹅多空双杀 (The Schizophrenia Test)
# ============================================================

def run_scenario_2() -> Dict[str, Any]:
    _header("场景 2: 黑天鹅多空双杀 (The Schizophrenia Test)")

    manager = BeliefStateManager(BeliefManagerConfig(
        gamma=1.0, conflict_threshold=0.3
    ))

    # Phase A: 双节点，初始期望差距 < 0.3
    _subheader("Phase A: 创建双节点，初始差距低于冲突阈值")

    id_a = manager.register_node(
        "TSLA 走势", proposition_id="tsla-bull-A",
        alpha=5.0, beta=3.0,
        source=BeliefSource.SHADOW_PREDICTION,
    )
    id_b = manager.register_node(
        "TSLA 走势", proposition_id="tsla-bear-B",
        alpha=3.0, beta=5.0,
        source=BeliefSource.SHADOW_PREDICTION,
    )

    snap_a_initial = manager.get_snapshot(id_a)
    snap_b_initial = manager.get_snapshot(id_b)
    delta_initial = abs(snap_a_initial.expectation - snap_b_initial.expectation)
    conflicts_before = manager.list_conflicts()

    print(f"  节点 A: E[t]={snap_a_initial.expectation:.4f}")
    print(f"  节点 B: E[t]={snap_b_initial.expectation:.4f}")
    print(f"  初始差距 DE={delta_initial:.4f}  (阈值=0.3)")
    print(f"  冲突记录数: {len(conflicts_before)}")

    assert delta_initial < 0.3
    assert len(conflicts_before) == 0

    # Phase B: 黑天鹅时刻
    _subheader("Phase B: 黑天鹅注入 -- 同时极端利好 & 利空")

    SHARED_TS = "2026-06-15T09:30:00.000000Z"
    snap_a = manager.ingest_observation(
        id_a, BeliefObservation(value=0.90, confidence=0.99,
                                source=BeliefSource.MARKET_DATA, timestamp=SHARED_TS)
    )
    snap_b = manager.ingest_observation(
        id_b, BeliefObservation(value=0.10, confidence=0.99,
                                source=BeliefSource.MARKET_DATA, timestamp=SHARED_TS)
    )

    delta_after = abs(snap_a.expectation - snap_b.expectation)
    conflicts_after = manager.list_conflicts()

    print(f"  节点 A (注入后): E[t]={snap_a.expectation:.4f}, status={snap_a.status_label}")
    print(f"  节点 B (注入后): E[t]={snap_b.expectation:.4f}, status={snap_b.status_label}")
    print(f"  注入后 DE={delta_after:.4f}  (阈值=0.3)")
    print(f"  冲突记录数: {len(conflicts_after)}")

    conflict_triggered = len(conflicts_after) >= 1
    if conflict_triggered:
        c = conflicts_after[0]
        print(f"\n  冲突 #{c.conflict_id[:8]}...")
        print(f"    左: {c.left_id} | 右: {c.right_id}")
        print(f"    左置信: {c.left_confidence:.4f} | 右置信: {c.right_confidence:.4f}")
        print(f"    策略: {c.resolution.value}")

    # Phase C: 单节点盲区验证
    _subheader("Phase C: 单节点盲区验证")
    manager_2 = BeliefStateManager(BeliefManagerConfig(gamma=1.0))
    pid = manager_2.register_node("TSLA 走势", alpha=5.0, beta=3.0)
    manager_2.ingest_observation(
        pid, BeliefObservation(value=0.90, confidence=0.99,
                               source=BeliefSource.MARKET_DATA, timestamp=SHARED_TS),
    )
    manager_2.ingest_observation(
        pid, BeliefObservation(value=0.10, confidence=0.99,
                               source=BeliefSource.MARKET_DATA, timestamp=SHARED_TS),
    )
    single_conflicts = manager_2.list_conflicts()
    single_snap = manager_2.get_snapshot(pid)
    print(f"  单节点冲突数: {len(single_conflicts)} (预期: 0 -- 架构盲区)")
    print(f"  单节点 E[t]={single_snap.expectation:.4f} (两信号被平均)")

    assert len(single_conflicts) == 0

    result = {
        "scenario": "2 - 黑天鹅多空双杀",
        "delta_initial": round(delta_initial, 6),
        "delta_after": round(delta_after, 6),
        "conflict_threshold": 0.3,
        "conflict_triggered": conflict_triggered,
        "conflict_count": len(conflicts_after),
        "resolution": conflicts_after[0].resolution.value if conflict_triggered else "NONE",
        "single_node_blindspot_confirmed": len(single_conflicts) == 0,
        "status": "PASS" if conflict_triggered else "PARTIAL_FAIL",
    }

    print(f"\n  >>> 场景 2 战果: {result['status']}")
    return result


# ============================================================
# 场景 3: 高频噪音轰炸 (The Noise Bombardment)
# ============================================================

def run_scenario_3() -> Dict[str, Any]:
    _header("场景 3: 高频噪音轰炸 (The Noise Bombardment)")
    _subheader("Phase 8.4 对称修正公式的噪音免疫力验证")

    manager = BeliefStateManager(BeliefManagerConfig(gamma=1.0))
    pid = manager.register_node(
        "TSLA beats earnings",
        proposition_id="noise-target",
        alpha=5.0, beta=3.0,
        source=BeliefSource.SHADOW_PREDICTION,
    )

    snap_before = manager.get_snapshot(pid)
    alpha_before = snap_before.node.alpha
    beta_before = snap_before.node.beta
    expectation_before = snap_before.expectation
    score_before = snap_before.score

    print(f"  初始信念: alpha={alpha_before:.4f}, beta={beta_before:.4f}, "
          f"E[t]={expectation_before:.6f}, score={score_before:.6f}")

    NOISE_CONFIDENCE = 0.01
    NEUTRAL_VALUE = 0.5
    NOISE_COUNT = 100

    print()
    for i in range(NOISE_COUNT):
        snap = manager.ingest_observation(
            pid, _make_obs(NEUTRAL_VALUE, NOISE_CONFIDENCE,
                           ts=_get_ts((i // 24) + 1, (i % 24)))
        )
        if (i + 1) % 10 == 0 or i == 0:
            drift = abs(snap.expectation - expectation_before)
            print(f"  [{i+1:3d}] alpha={snap.node.alpha:.6f}, beta={snap.node.beta:.6f}, "
                  f"E[t]={snap.expectation:.6f}, drift={drift:.6f}")

    snap_after = manager.get_snapshot(pid)
    alpha_delta = abs(snap_after.node.alpha - alpha_before)
    beta_delta = abs(snap_after.node.beta - beta_before)
    expectation_delta = abs(snap_after.expectation - expectation_before)
    score_delta = abs(snap_after.score - score_before)
    mass_added = (snap_after.node.alpha + snap_after.node.beta - 2.0) \
                 - (alpha_before + beta_before - 2.0)

    # 核心指标: β/α 不对称比
    # 旧公式 = 199:1 (灾难性不对称)
    # 新公式 = 1:1 (完美对称)
    ba_ratio = beta_delta / alpha_delta if alpha_delta > 0 else 0

    # 旧公式理论对比
    alpha_old = alpha_before
    beta_old = beta_before
    for _ in range(NOISE_COUNT):
        eff = NEUTRAL_VALUE * NOISE_CONFIDENCE
        alpha_old += eff
        beta_old += 1.0 - eff
    e_old = alpha_old / (alpha_old + beta_old)

    print(f"\n  -- Phase 8.4 噪音免疫量化评估 --")
    print(f"  alpha 漂移: {alpha_delta:.6f}")
    print(f"  beta 漂移: {beta_delta:.6f}")
    print(f"  E[t] 漂移: {expectation_delta:.6f}")
    print(f"  Score 漂移: {score_delta:.6f}")
    print(f"  beta/alpha 漂移比: {ba_ratio:.4f}  (完美对称=1.0, 旧公式=199)")
    print(f"  注入总质量: {mass_added:.4f} (预期: {NOISE_COUNT * NOISE_CONFIDENCE:.2f})")
    print(f"  最终 E[t]: {snap_after.expectation:.6f} (初始: {expectation_before:.6f})")
    print()
    print(f"  -- 旧公式对比 --")
    print(f"  旧公式 E[t] 理论值: {e_old:.6f}")
    print(f"  旧公式 E[t] 漂移: {abs(e_old - expectation_before):.6f}")
    print(f"  <- 系统性熊市偏移! 新公式已修复此项。")

    # 通过标准: E[t] 漂移 < 2% (对称分布的自然漂移)
    PASS_THRESHOLD = 0.02
    expectation_stable = expectation_delta < PASS_THRESHOLD
    score_stable = score_delta < PASS_THRESHOLD
    symmetric = abs(ba_ratio - 1.0) < 0.01  # beta/alpha 比近似 1:1

    print(f"\n  噪音免疫阈值: E[t] 漂移 < {PASS_THRESHOLD}")
    print(f"  E[t] 稳定性: {'[PASS]' if expectation_stable else '[FAIL]'}")
    print(f"  Score 稳定性: {'[PASS]' if score_stable else '[FAIL]'}")
    print(f"  对称性(beta/alpha=1): {'[PASS]' if symmetric else '[FAIL]'}")

    all_pass = expectation_stable and score_stable and symmetric

    result = {
        "scenario": "3 - 高频噪音轰炸",
        "expected_mass_added": NOISE_COUNT * NOISE_CONFIDENCE,
        "actual_mass_added": round(mass_added, 6),
        "alpha_drift": round(alpha_delta, 6),
        "beta_drift": round(beta_delta, 6),
        "beta_alpha_ratio": round(ba_ratio, 4),
        "expectation_drift": round(expectation_delta, 6),
        "score_drift": round(score_delta, 6),
        "old_formula_theoretical_E": round(e_old, 6),
        "new_formula_noise_immune": all_pass,
        "status": "PASS" if all_pass else "FAIL",
    }

    print(f"\n  >>> 场景 3 战果: {result['status']}")
    return result


# ============================================================
# Main
# ============================================================

def main() -> None:
    print()
    print("Phase 8.4 红蓝对抗极限压测 (Adversarial Stress Test)")
    print("beta-Bernoulli Belief State Manager - 认知中枢极限压力测试")
    print()

    results: List[Dict[str, Any]] = []
    results.append(run_scenario_1())
    results.append(run_scenario_2())
    results.append(run_scenario_3())

    _header("Phase 8.4 红蓝对抗战报汇总 (Final Report)")

    all_pass = True
    for r in results:
        icon = "[PASS]" if r["status"] == "PASS" else "[FAIL]"
        if r["status"] != "PASS":
            all_pass = False
        print(f"  {icon} {r['scenario']}: {r['status']}")

    print()
    if all_pass:
        print("  >>> 所有场景通过! 信念核心认知中枢通过极限压力测试。")
    else:
        print("  >>> 部分场景未通过，需要进一步分析。")

    # 保存 JSON 报告
    report = {
        "phase": "8.4",
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "formula": "alpha + value*conf, beta + (1-value)*conf (symmetric)",
        "all_scenarios_passed": all_pass,
        "scenarios": results,
    }

    report_dir = os.path.join(_SCRIPT_DIR, "..", "memory-bank")
    os.makedirs(report_dir, exist_ok=True)
    report_path = os.path.join(report_dir, "phase8_4_stress_test_result.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print(f"\n  详细报告已保存至: {report_path}")


if __name__ == "__main__":
    main()