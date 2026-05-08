"""
intake_pipeline.py — Sprint 3: 情报摄入全链路管线（Orchestrator）

将 Scraper → FactChecker → BeliefModifier 三级管道序列化，
从 URL 输入到信念修改建议的完整端到端管线。

设计模式（Pipeline Orchestrator）:
  - 每级管道独立可 Mock
  - 级间降级（FactChecker 可跳过，BeliefModifier 永不跳）
  - 异步安全，线程安全
  - 完整的执行日志和性能追踪

SPARC:
  Specification: V2.0 Sprint 3 — 从 URL 到 Belief 建议的完整编排
  Pseudocode: URL → Scraper.scrape → FactChecker.check → BeliefModifier.build_plan
  Architecture: Pipeline Orchestrator — 每级独立，级间降级
  Refinement: 全部异步 + Mock 兼容
  Completion: 测试覆盖率 ≥ 85%
"""

from __future__ import annotations

import datetime
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .scraper import Scraper, ScraperConfig, ScrapedContent
from .fact_checker import FactChecker, FactCheckerConfig, FactCheckReport
from .belief_modifier import BeliefModifier, BeliefModifierConfig, BeliefModificationPlan

logger = logging.getLogger(__name__)


# ============================================================
# Pipeline 配置
# ============================================================


@dataclass
class IntakePipelineConfig:
    """情报摄入管线全局配置。

    Attributes:
        skip_fact_check: 跳过事实核查阶段（默认 False）
        skip_belief_modify: 跳过信念修改阶段（默认 False）
        parallel_extraction: 并行执行抓取和核查（默认 False，暂不支持）
        timeout_seconds: 整条管线的超时秒数（默认 120）
    """
    skip_fact_check: bool = False
    skip_belief_modify: bool = False
    parallel_extraction: bool = False
    timeout_seconds: float = 120.0


# ============================================================
# Pipeline Result
# ============================================================


@dataclass
class IntakePipelineResult:
    """管线执行结果。

    Attributes:
        url: 输入 URL
        scraped: 抓取结果
        report: 事实核查报告（None 表示跳过）
        plan: 信念修改计划（None 表示跳过）
        latency_ms: 执行耗时（毫秒）
        stages: 各阶段的耗时统计
        successes: 成功阶段数
        errors: 各阶段的错误
        completed: 管线是否完整执行
        timestamp: ISO-8601 完成时间
    """
    url: str = ""
    scraped: Optional[ScrapedContent] = None
    report: Optional[FactCheckReport] = None
    plan: Optional[BeliefModificationPlan] = None
    latency_ms: float = 0.0
    stages: Dict[str, float] = field(default_factory=dict)
    successes: int = 0
    errors: Dict[str, str] = field(default_factory=dict)
    completed: bool = False
    timestamp: str = field(default_factory=lambda: (
        datetime.datetime.now(datetime.timezone.utc).isoformat()
    ))

    @property
    def has_errors(self) -> bool:
        return len(self.errors) > 0

    @property
    def summary(self) -> str:
        """生成人类可读的管线执行摘要。"""
        parts = [f"IntakePipeline: {self.url}"]
        if self.successes == 3:
            parts.append("✅ FULL SUCCESS")
        elif self.successes > 0:
            parts.append(f"⚠️ Partial ({self.successes}/3 stages)")
            for stage, err in self.errors.items():
                parts.append(f"   ❌ {stage}: {err}")
        else:
            parts.append("❌ FAILED")
            for stage, err in self.errors.items():
                parts.append(f"   ❌ {stage}: {err}")
        parts.append(f"   ⏱ {self.latency_ms:.0f}ms")
        return "\n".join(parts)


# ============================================================
# IntakePipeline — Orchestrator
# ============================================================


class IntakePipeline:
    """情报摄入全链路编排器。

    从 URL 到信念修改建议的三级管线：
      1. Scraper:        URL → ScrapedContent（抓取 + 结构化提取）
      2. FactChecker:    ScrapedContent → FactCheckReport（核查）
      3. BeliefModifier: ScrapedContent + FactCheckReport → BeliefModificationPlan

    用法:
        pipeline = IntakePipeline(scraper, fact_checker, belief_modifier)
        result = await pipeline.run("https://example.com/news")
        print(result.plan.suggestions)
    """

    def __init__(
        self,
        scraper: Optional[Scraper] = None,
        fact_checker: Optional[FactChecker] = None,
        belief_modifier: Optional[BeliefModifier] = None,
        config: Optional[IntakePipelineConfig] = None,
        scraper_config: Optional[ScraperConfig] = None,
        fact_checker_config: Optional[FactCheckerConfig] = None,
        belief_modifier_config: Optional[BeliefModifierConfig] = None,
    ) -> None:
        """初始化全链路管线。

        Args:
            scraper: Scraper 实例（可选，自动创建 Mock）
            fact_checker: FactChecker 实例（可选，自动创建 Mock）
            belief_modifier: BeliefModifier 实例（可选，自动创建）
            config: 管线全局配置
            scraper_config: Scraper 配置
            fact_checker_config: FactChecker 配置
            belief_modifier_config: BeliefModifier 配置
        """
        self._config = config or IntakePipelineConfig()

        # 如果没有提供任何适配器，默认使用 Mock 模式
        self._scraper = scraper or Scraper(
            flash_adapter=None,
            config=scraper_config or ScraperConfig(mock_mode=True),
        )
        self._fact_checker = fact_checker or FactChecker(
            flash_adapter=None,
            config=fact_checker_config or FactCheckerConfig(mock_mode=True),
        )
        self._belief_modifier = belief_modifier or BeliefModifier(
            config=belief_modifier_config or BeliefModifierConfig(),
        )

        logger.info(
            "IntakePipeline initialized: scrape=%s, fact_check=%s, modify=%s",
            "real" if not getattr(self._scraper, "_mock_mode", True) else "mock",
            "real" if not getattr(self._fact_checker, "_mock_mode", True) else "mock",
            "enabled",
        )

    # ============================================================
    # 公共 API
    # ============================================================

    async def run(self, url: str) -> IntakePipelineResult:
        """执行单次全链路情报摄入。

        Args:
            url: 目标 URL

        Returns:
            IntakePipelineResult: 包含所有阶段的结果
        """
        start_time = time.time()
        result = IntakePipelineResult(url=url)

        # ─────────────────────────────────────────────────────
        # Stage 1: Scraper
        # ─────────────────────────────────────────────────────
        stage_start = time.time()
        stage_name = "scraper"
        try:
            scraped = await self._scraper.scrape(url)
            result.scraped = scraped
            result.stages[stage_name] = (time.time() - stage_start) * 1000

            if scraped and scraped.error:
                result.errors[stage_name] = scraped.error
                logger.warning("Scraper returned error for %s: %s", url, scraped.error)
            else:
                result.successes += 1
                logger.debug("Scraper OK for %s", url)

        except Exception as e:
            result.errors[stage_name] = str(e)
            result.stages[stage_name] = (time.time() - stage_start) * 1000
            logger.error("Scraper failed for %s: %s", url, e)

        # ─────────────────────────────────────────────────────
        # Stage 2: FactChecker
        # ─────────────────────────────────────────────────────
        stage_start = time.time()
        stage_name = "fact_checker"
        if self._config.skip_fact_check or result.errors.get("scraper"):
            if self._config.skip_fact_check:
                logger.debug("FactChecker skipped (config.skip_fact_check=True)")
            result.stages[stage_name] = 0.0
        else:
            try:
                report = await self._fact_checker.check(result.scraped)
                result.report = report
                result.stages[stage_name] = (time.time() - stage_start) * 1000

                if report and report.error:
                    result.errors[stage_name] = report.error
                    logger.warning("FactChecker error for %s: %s", url, report.error)
                else:
                    result.successes += 1
                    logger.debug("FactChecker OK for %s", url)

            except Exception as e:
                result.errors[stage_name] = str(e)
                result.stages[stage_name] = (time.time() - stage_start) * 1000
                logger.error("FactChecker failed for %s: %s", url, e)

        # ─────────────────────────────────────────────────────
        # Stage 3: BeliefModifier
        # ─────────────────────────────────────────────────────
        stage_start = time.time()
        stage_name = "belief_modifier"
        if self._config.skip_belief_modify:
            logger.debug("BeliefModifier skipped (config.skip_belief_modify=True)")
            result.stages[stage_name] = 0.0
        else:
            try:
                # 需要 scraped 数据才能继续
                if result.scraped is None:
                    result.errors[stage_name] = "No scraped content available"
                else:
                    plan = self._belief_modifier.build_plan(
                        result.scraped,
                        result.report,  # None 是允许的（skip_fact_check 模式）
                    )
                    result.plan = plan
                    result.stages[stage_name] = (time.time() - stage_start) * 1000

                    if plan and plan.error:
                        result.errors[stage_name] = plan.error
                    else:
                        result.successes += 1
                        logger.debug(
                            "BeliefModifier OK for %s: %d suggestions",
                            url,
                            len(plan.suggestions) if plan else 0,
                        )

            except Exception as e:
                result.errors[stage_name] = str(e)
                result.stages[stage_name] = (time.time() - stage_start) * 1000
                logger.error("BeliefModifier failed for %s: %s", url, e)

        # ─────────────────────────────────────────────────────
        # Final: 统计 & 完成
        # ─────────────────────────────────────────────────────
        result.latency_ms = (time.time() - start_time) * 1000
        result.completed = result.successes >= 2  # 至少 scraper + modifier

        logger.info(
            "IntakePipeline %s: %d/3 stages in %.0fms",
            url,
            result.successes,
            result.latency_ms,
        )
        return result

    # ============================================================
    # 批量执行
    # ============================================================

    async def run_batch(
        self,
        urls: List[str],
        max_concurrent: int = 3,
    ) -> List[IntakePipelineResult]:
        """批量执行 URL 情报摄入。

        Args:
            urls: URL 列表
            max_concurrent: 最大并发数（默认 3）

        Returns:
            List[IntakePipelineResult]: 结果列表（顺序与输入一致）
        """
        import asyncio

        semaphore = asyncio.Semaphore(max_concurrent)

        async def _run_one(url: str) -> IntakePipelineResult:
            async with semaphore:
                return await self.run(url)

        tasks = [_run_one(url) for url in urls]
        return await asyncio.gather(*tasks)