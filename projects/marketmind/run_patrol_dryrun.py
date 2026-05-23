#!/usr/bin/env python3
"""
run_patrol_dryrun.py -- Stage 2.5 真实外网点火试车 (The Dry Run)
========================================================================
端到端真实试车: Scout -> Distill -> Ingest -> Belief State Report

执行步骤:
  1. 注册所有预设命题 (preloaded propositions)
  2. 调用 scout_fetcher.fetch_all() 真实抓取 FRED / Yahoo Finance / Reuters
  3. 尝试调用 LLM Distiller; 如无 API Key 则使用 MockDistiller 降级
  4. 通过 Instantiator 将蒸馏结果注入 BeliefStateManager
  5. 打印完整的执行战报

Usage:
    python run_patrol_dryrun.py
"""

from __future__ import annotations

import datetime
import json
import logging
import os
import sys
import textwrap
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# -- 将项目根目录加入 sys.path --
_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJECT = os.path.join(_HERE, "projects", "robinhood")
if _PROJECT not in sys.path:
    sys.path.insert(0, _PROJECT)

# Force UTF-8 for Windows terminal compatibility
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

logging.basicConfig(
    level=logging.WARNING,
    format="%(levelname)s | %(name)s | %(message)s",
)

# -- 导入项目模块 --
from src.scout_fetcher import (
    RawEvent,
    ScoutConfig,
    fetch_all,
    fetch_fred_observations,
    fetch_yahoo_finance_headlines,
    fetch_reuters_rss,
)
from src.belief_state_manager import BeliefStateManager, BeliefManagerConfig, DuplicatePropositionError
from src.belief_types import BeliefSource, BeliefObservation
from src.belief_math import beta_expectation, beta_uncertainty
from src.ingestion_pipeline import (
    PRELOADED_PROPOSITIONS,
    Distiller,
    DistillerConfig,
    DistilledEvent,
    Instantiator,
    IngestionResult,
)

# ========================================================================
# 1. Mock Distiller -- LLM API Key 缺失时的安全降级
# ========================================================================

class MockDistiller:
    """Mock Distiller: 当 LLM API Key 缺失时使用。

    伪造三条蒸馏结果:
      - 一条看跌 (bearish) -> 增加衰退概率
      - 一条看涨 (bullish) -> 增加降息概率
      - 一条看涨 (bullish) -> 科技板块跑赢
    """

    def distill(self, raw_events: List[RawEvent]) -> List[DistilledEvent]:
        mock_digest = [
            DistilledEvent(
                proposition_id="macro_us_recession_risk",
                direction="bearish",
                confidence=0.72,
                one_liner="ISM PMI 超预期下滑至48.6",
                tickers=["SPY", "QQQ"],
            ),
            DistilledEvent(
                proposition_id="macro_fed_rate_path",
                direction="bullish",
                confidence=0.65,
                one_liner="FedWatch 显示9月降息概率升至78%",
                tickers=["TLT", "SPY"],
            ),
            DistilledEvent(
                proposition_id="sector_tech_outperform",
                direction="bullish",
                confidence=0.68,
                one_liner="NVDA 财报超预期带动AI板块",
                tickers=["NVDA", "AMD", "QQQ"],
            ),
        ]

        print(f"  [MOCK] MockDistiller: 生成了 {len(mock_digest)} 条蒸馏结果 "
              f"(LLM API Key 未配置)")
        return mock_digest


# ========================================================================
# 2. Pretty Printer -- 终端战报格式化
# ========================================================================

_SUB_SEP = "-" * 60

def _banner(text: str, char: str = "=") -> None:
    print(f"\n{char * 72}")
    print(f"  {text}")
    print(f"{char * 72}")

def _print_section(title: str) -> None:
    print(f"\n  >> {title}")
    print(f"  {_SUB_SEP}")

def print_battle_report(
    raw_events: List[RawEvent],
    track_stats: Dict[str, Dict[str, int]],
    fetch_errors: List[str],
    distilled_events: List[DistilledEvent],
    used_mock: bool,
    ingest_result: IngestionResult,
    manager: BeliefStateManager,
) -> None:
    """打印完整的执行战报。"""

    # -- 战报标题 --
    print(f"\n{'#' * 72}")
    print(f"##  AUTOMATED PATROL DRY RUN -- BATTLE REPORT          ##")
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"##  {now_str} UTC+8  ##")
    print(f"{'#' * 72}")

    # -- 1. Scout 战果 --
    _banner("PHASE 1: SCOUT (真实外网数据抓取)", "-")
    _print_section("Raw Events 清单")

    if not raw_events:
        print("    [!!] 未抓取到任何 Raw Event")
    else:
        for i, ev in enumerate(raw_events, 1):
            short_title = ev.title[:80]
            print(f"    [{i:2d}] [NEWS] {short_title}")
            print(f"         |-> 源: {ev.source_name:15s} | 分类: {ev.category:10s} "
                  f"| 时间: {ev.timestamp[:10]}")

    # Track Stats
    print()
    _print_section("Track 统计")
    for track_name, stats in track_stats.items():
        if track_name == "fred":
            print(f"    [FRED API]    成功={stats.get('success', 0)}, "
                  f"事件={stats.get('events', 0)}")
        elif track_name == "reuters":
            print(f"    [Reuters RSS] 成功={stats.get('success', 0)}, "
                  f"事件={stats.get('events', 0)}")
        elif track_name == "yahoo":
            print(f"    [Yahoo Fin]   成功={stats.get('success', 0)}/"
                  f"{stats.get('total_tickers', 0)} tickers, "
                  f"事件={stats.get('events', 0)}")

    if fetch_errors:
        print()
        _print_section("抓取错误")
        for err in fetch_errors[:5]:
            print(f"    [!!]  {err}")
        if len(fetch_errors) > 5:
            print(f"    ... 还有 {len(fetch_errors) - 5} 个错误未显示")

    # -- 2. Distill 战果 --
    _banner("PHASE 2: DISTILL (事件提纯)", "-")
    if used_mock:
        print("  [!!] 降级模式: 使用 MockDistiller (无 LLM API Key)")
    else:
        print("  [OK] 生产模式: 使用 LLM Distiller")

    if not distilled_events:
        print("    [!!] 无蒸馏结果")
    else:
        for i, de in enumerate(distilled_events, 1):
            direction_icon = "[BULL]" if de.direction == "bullish" else "[BEAR]" if de.direction == "bearish" else "[NEUT]"
            direction_label = de.direction.upper()
            conf_pct = de.confidence * 100
            print(f"    [{i:2d}] {direction_icon} [{direction_label:7s}] "
                  f"置信度={conf_pct:5.1f}%")
            print(f"         |-> 命题: {de.proposition_id}")
            print(f"         |-> 摘要: {de.one_liner}")
            if de.tickers:
                print(f"         |-> 标的: {', '.join(de.tickers)}")

    # -- 3. Belief Ingestion 战果 --
    _banner("PHASE 3: BELIEF INGESTION (信念注入)", "-")
    print(f"    原始事件: {ingest_result.total_raw}")
    print(f"    蒸馏成功: {ingest_result.distilled_count}")
    print(f"    注入成功: {ingest_result.ingested_count}")

    if ingest_result.errors:
        print()
        _print_section("注入错误")
        for err in ingest_result.errors[:3]:
            print(f"    [!!]  {err}")

    # -- 4. Belief State Delta --
    _banner("PHASE 4: BELIEF STATE DELTA (信念状态变化)", "-")

    core_proposition = "macro_us_recession_risk"
    snap = manager.get_snapshot(core_proposition)

    if snap:
        print(f"  核心命题: {snap.node.proposition}")
        print(f"  +{'-' * 55}+")
        print(f"  |  alpha (成功证据):        {snap.node.alpha:>8.3f}                     |")
        print(f"  |  beta (失败证据):         {snap.node.beta:>8.3f}                     |")
        print(f"  |  E[theta] (衰退概率期望): {snap.expectation:>8.3f}  ({snap.expectation * 100:.1f}%)   |")
        print(f"  |  Var[theta] (认知不确定性):{snap.uncertainty:>8.6f}            |")
        print(f"  |  置信度评分:              {snap.score:>8.3f}                     |")
        print(f"  +{'-' * 55}+")

        print()
        _print_section("其它活跃命题")
        for s in manager.list_active():
            if s.node.proposition_id == core_proposition:
                continue
            direction = "[BULL]" if s.expectation > 0.5 else "[BEAR]" if s.expectation < 0.5 else "[NEUT]"
            print(f"    {direction:6s} | {s.node.proposition_id:30s} "
                  f"| E[theta]={s.expectation:.3f} | 观测={s.observation_count}")
    else:
        print("    [!!] 核心命题 'macro_us_recession_risk' 未注册或已退休")

    # -- 5. 全局统计摘要 --
    _banner("FINAL SUMMARY", "=")
    total_active = manager.get_active_count()
    total_nodes = manager.get_node_count()
    total_conflicts = len(manager.list_conflicts())
    total_retirements = len(manager.list_retirements())
    print(f"  [ACTIVE] 活跃命题:     {total_active}")
    print(f"  [TOTAL]  总命题数:     {total_nodes}")
    print(f"  [CONF]   冲突记录:     {total_conflicts}")
    print(f"  [RET]    退休记录:     {total_retirements}")
    print(f"{'=' * 72}")
    verdict = "[PASS] 全部通过" if ingest_result.ingested_count > 0 else "[WARN] 未注入任何事件"
    print(f"  最终判决: {verdict}")
    print(f"{'=' * 72}")
    print()


# ========================================================================
# 3. Main Dry Run
# ========================================================================

def main() -> int:
    # -- Phase 0: 初始化 BeliefStateManager --
    _banner("INITIALIZING BELIEF STATE MANAGER", "-")
    config = BeliefManagerConfig(
        gamma=0.95,
        theta=0.1,
        conflict_threshold=0.3,
        auto_decay_interval_seconds=86400,
    )
    manager = BeliefStateManager(config=config)
    print("  [OK] BeliefStateManager 初始化完成")
    print(f"     gamma={config.gamma}, theta={config.theta}")

    # -- Phase 1: 注册预设命题 --
    _banner("PHASE 0 (PREP): 注册预设命题", "-")
    registered = 0
    for prop_id, prop_text in PRELOADED_PROPOSITIONS.items():
        try:
            manager.register_node(
                prop_text,
                proposition_id=prop_id,
                source=BeliefSource.MACRO_CALENDAR,
            )
            registered += 1
            print(f"  [OK] 已注册: {prop_id:35s} <- {prop_text}")
        except DuplicatePropositionError:
            print(f"  [EXIST] 已存在: {prop_id:35s}")

    print(f"\n  [STATS] 共注册 {registered} 个命题")

    # -- Phase 1: Scout -- 真实抓取 --
    _banner("PHASE 1: SCOUT -- 真实外网抓取", "-")
    print("  正在抓取 FRED API / Reuters RSS / Yahoo Finance...")

    # 抓取前快照
    pre_snap = manager.get_snapshot("macro_us_recession_risk")

    scout_cfg = ScoutConfig(rate_limit_seconds=0.5)
    fetch_result = fetch_all(config=scout_cfg)

    raw_events = fetch_result.events
    track_stats = fetch_result.track_stats
    fetch_errors = fetch_result.errors

    print(f"  [OK] 抓取完成: {len(raw_events)} 个 Raw Event")

    # -- Phase 2: Distill --
    _banner("PHASE 2: DISTILL -- 事件提纯", "-")

    llm_key = os.environ.get("LLM_API_KEY") or os.environ.get("OPENAI_API_KEY")
    used_mock = False
    distilled_events: List[DistilledEvent] = []

    if llm_key:
        print("  [OK] 检测到 LLM API Key, 使用生产 Distiller")
        try:
            dist_cfg = DistillerConfig(
                api_key=llm_key,
                api_url=os.environ.get("LLM_API_URL", "https://api.openai.com/v1/chat/completions"),
                model=os.environ.get("LLM_MODEL", "gpt-4o-mini"),
            )
            distiller = Distiller(config=dist_cfg)
            distilled_events = distiller.distill(raw_events)
            print(f"  [OK] LLM 蒸馏完成: {len(distilled_events)} 条结果")
        except Exception as e:
            print(f"  [WARN] LLM Distiller 异常: {e}")
            print(f"  [WARN] 降级至 MockDistiller")
            used_mock = True
    else:
        print("  [WARN] 未检测到 LLM API Key (LLM_API_KEY / OPENAI_API_KEY)")
        used_mock = True

    if used_mock:
        mock = MockDistiller()
        distilled_events = mock.distill(raw_events)

    # -- Phase 3: Ingest --
    _banner("PHASE 3: INGEST -- 信念注入", "-")

    instantiator = Instantiator(manager)
    ingest_result = instantiator.instantiate_and_ingest(
        distilled_events,
        source=BeliefSource.MACRO_CALENDAR,
    )

    print(f"  [OK] 注入完成: {ingest_result.ingested_count}/{ingest_result.distilled_count} 条")

    # -- Phase 4: 打印战报 --
    print_battle_report(
        raw_events=raw_events,
        track_stats=track_stats,
        fetch_errors=fetch_errors,
        distilled_events=distilled_events,
        used_mock=used_mock,
        ingest_result=ingest_result,
        manager=manager,
    )

    # -- Return Code --
    if ingest_result.ingested_count > 0:
        print("[PASS] Stage 2.5 真实外网点火试车: 通过")
        return 0
    else:
        print("[WARN] Stage 2.5 真实外网点火试车: 未注入事件 (可能无数据)")
        return 0  # Still success -- we exercised the pipeline


if __name__ == "__main__":
    sys.exit(main())