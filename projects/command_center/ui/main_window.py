"""
main_window.py — Sprint 5: 主窗口（集成 Settings Hub 热更新 + 影子复盘）
"""

from __future__ import annotations
import json
import logging
import sys
from typing import Any, Dict, List, Optional
import customtkinter as ctk
from projects.command_center.config.settings_manager import SettingsManager
from projects.command_center.gateway.task_queue import TaskQueue
from projects.command_center.ui.dashboard_panel import DashboardPanel
from projects.command_center.ui.chat_panel import ChatPanel
from projects.command_center.ui.settings_modal import SettingsModal

logger = logging.getLogger(__name__)

TITLE = "SignalFoundry Terminal"
W, H = 1400, 900
MW, MH = 1000, 700
DW, CW = 4, 6


class MainWindow(ctk.CTk):
    """Command Center V2.0 主窗口——四象限布局 + 设置中心。"""

    def __init__(self, task_queue: Optional[TaskQueue] = None,
                 settings: Optional[SettingsManager] = None):
        super().__init__()
        self._settings = settings or SettingsManager()

        self.title(TITLE)
        self.geometry(f"{W}x{H}")
        self.minsize(MW, MH)

        # 从 SettingsManager 加载外观
        self._apply_appearance(self._settings.get_all())

        self.grid_columnconfigure(0, weight=DW)
        self.grid_columnconfigure(1, weight=CW)
        self.grid_rowconfigure(0, weight=1)

        self._dash = DashboardPanel(self, fg_color=("#f0f0f0", "#1a1a2e"))
        self._dash.grid(row=0, column=0, padx=(6, 3), pady=6, sticky="nsew")

        self._chat = ChatPanel(self, task_queue=task_queue,
            fg_color=("#f0f0f0", "#1a1a2e"))
        self._chat.grid(row=0, column=1, padx=(3, 6), pady=6, sticky="nsew")

        # Detect adapter mode and update display
        self.after(200, self._detect_pipeline_mode)

        # 注入一键日报回调 + 影子复盘回调 + 深度宏观研报回调
        self._dash.set_pipeline_callback(self._run_daily_report)
        self._dash.set_shadow_callback(self._run_shadow_replay)
        self._dash.set_macro_research_callback(self._run_shadow_results)

        # 标题栏右侧齿轮按钮
        self._settings_btn = ctk.CTkButton(
            self, text="设置", width=60, height=28,
            font=ctk.CTkFont(size=12),
            command=self._open_settings,
        )
        # 通过 place 放在标题栏区域（相对于父窗口坐标系）
        self._settings_btn.place(relx=0.94, rely=0.02, anchor="ne")

        # 注册热更新订阅
        self._settings.subscribe(self._on_settings_changed)

        # 强制触发一次冷启动字体加载（Defect 3A 修复）
        self._on_settings_changed(self._settings.get_all())

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        logger.info("MainWindow %dx%d", W, H)

    # ============================================================
    # 热更新
    # ============================================================

    def _apply_appearance(self, settings: Dict[str, Any]) -> None:
        """立即应用外观设置。"""
        appearance = settings.get("appearance", {})
        mode = appearance.get("appearance_mode", "dark")
        theme = appearance.get("color_theme", "blue")
        ctk.set_appearance_mode(mode)
        ctk.set_default_color_theme(theme)

    def _on_settings_changed(self, settings: Dict[str, Any]) -> None:
        """SettingsManager 通知设置变更时的热更新回调。"""
        try:
            self._apply_appearance(settings)

            # 字体热更新
            appearance = settings.get("appearance", {})
            family = appearance.get("font_family", "Microsoft YaHei")
            size = appearance.get("font_size_base", 14)
            font = ctk.CTkFont(family=family, size=size)
            self._apply_font_recursive(self, font)

            self.update_idletasks()
            logger.info("Settings hot-applied: font=%s, size=%d, mode=%s",
                        family, size, settings.get("appearance", {}).get("appearance_mode"))
        except Exception as exc:
            logger.error("Error applying settings: %s", exc)

    @staticmethod
    def _apply_font_recursive(widget: Any, font: ctk.CTkFont) -> None:
        """递归遍历 widget 树，更新所有 CTk 组件的字体。

        特殊穿透 CTkTabview 的 _segmented_button 内部标签按钮，
        以确保 Tab 标题字体同步更新（Defect 3B 修复）。
        """
        try:
            if hasattr(widget, "configure"):
                try:
                    widget.configure(font=font)
                except Exception as exc:
                    logger.debug("_apply_font_recursive skip %s: %s",
                                 widget.winfo_class(), exc)
        except Exception as exc:
            logger.debug("_apply_font_recursive error on %s: %s",
                         widget.winfo_class() if hasattr(widget, 'winfo_class') else '?', exc)

        # 特殊穿透: CTkTabview 的 SegmentedButton 内部按钮
        if isinstance(widget, ctk.CTkTabview):
            try:
                seg = getattr(widget, "_segmented_button", None)
                if seg is not None:
                    try:
                        seg.configure(font=font)
                    except Exception:
                        pass
                    # 穿透到每个内部 segment 按钮
                    buttons_dict = getattr(seg, "_buttons_dict", None)
                    if buttons_dict is not None:
                        for btn in buttons_dict.values():
                            try:
                                btn.configure(font=font)
                            except Exception:
                                pass
            except Exception:
                pass

        try:
            for child in widget.winfo_children():
                MainWindow._apply_font_recursive(child, font)
        except Exception as exc:
            logger.debug("_apply_font_recursive children iteration: %s", exc)

    # ============================================================
    # 设置弹窗
    # ============================================================

    def _open_settings(self) -> None:
        """打开全局设置弹窗。"""
        logger.info("Opening settings modal")
        SettingsModal(self, settings=self._settings, on_saved=None)

    # ============================================================
    # 一键日报
    # ============================================================

    def _run_daily_report(self) -> None:
        """一键生成每日归因战报（后台线程执行）。

        四阶段管线:
          Phase 1: Scout — 情报摄入（Scraper + IntakePipeline）
          Phase 2: Reason — LLM 推理与信念更新
          Phase 3: Optimize — 真实信念权重注入调仓优化
          Phase 4: Report — 影子对比 + LLM 解读 + Markdown 生成

        防御性编程:
          - 每阶段独立 try-except，单阶段失败不影响后续
          - 无 API Key 时自动 Mock 降级，管线永不卡死
          - asyncio.new_event_loop() 管理异步生命周期
        """
        import threading

        def _do_report():
            import asyncio
            import time

            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                self._run_daily_report_impl(loop)
            except Exception as e:
                logger.error("Daily report fatal: %s", e, exc_info=True)
                self._dash.set_status(f"状态: 战报生成失败 - {e}")
                self._chat.append_error_message(f"战报生成链路崩溃: {e}")
            finally:
                loop.close()
                # 恢复按钮状态（通过 after 回到主线程）
                try:
                    self.after(0, lambda: (
                        self._dash._daily_report_btn.configure(state="normal")
                    ))
                except Exception:
                    pass

        self._dash._daily_report_btn.configure(state="disabled")
        threading.Thread(target=_do_report, daemon=True).start()

    def _run_daily_report_impl(self, loop: asyncio.AbstractEventLoop) -> None:
        """四阶段管线实现体（在后台线程的 asyncio 事件循环中执行）。

        优先使用 SignalFoundry Phase B 管线 (projects/robinhood/src/main.py)。
        若导入失败则降级到 SignalFoundry 原生管线。
        """
        import time

        # ---- 优先路径: SignalFoundry Phase B 管线 ----
        try:
            import sys
            from pathlib import Path
            robinhood_root = str(Path(__file__).resolve().parent.parent.parent / "robinhood")
            if robinhood_root not in sys.path:
                sys.path.insert(0, robinhood_root)

            from src.main import run_daily_mode

            # Progress stages with estimated timing
            stages = [
                (0, "S1: 新闻采集 (57个信源)..."),
                (3000, "S2: 四维分析引擎运行..."),
                (6000, "S2.5: 认知回顾对比昨日..."),
                (9000, "S3: 共振聚合计算..."),
                (12000, "S4: 持仓决策生成..."),
                (15000, "S5: Pro 深度分析 (1-2分钟)..."),
                (30000, "S6: 报告生成中..."),
            ]
            for delay, msg in stages:
                self.after(delay, lambda m=msg: self._dash.set_status(f"状态: {m}"))

            report = run_daily_mode(mock=False, verbose=True)
            self._show_report(report)
            return
        except ImportError:
            logger.debug("SignalFoundry Phase B not available, using Command Center native pipeline")
        except Exception as exc:
            logger.warning("SignalFoundry pipeline failed, falling back to native: %s", exc)

        # ---- 降级路径: SignalFoundry 原生管线 ----

        # ─────────────────────────────────────────────────────
        # 初始化默认回退数据
        # ─────────────────────────────────────────────────────
        from projects.command_center.models.position import Position
        from projects.command_center.engine.optimizer import Optimizer
        from projects.command_center.engine.shadow_comparator import ShadowComparator
        from projects.command_center.engine.reporter import Reporter, ReportData
        from projects.command_center.engine.semantic_translator import SemanticTranslator
        from projects.command_center.engine.llm_interpreter import LLMInterpreter
        from projects.command_center.gateway.flash_adapter import FlashAdapter

        # 从 Dashboard 获取真实持仓（降级到 Mock）
        positions = self._dash.current_positions
        if not positions:
            positions = self._fallback_positions()

        # 初始化各引擎实例
        optimizer = Optimizer()
        comparator = ShadowComparator()
        translator = SemanticTranslator()
        reporter = Reporter()

        # ─────────────────────────────────────────────────────
        # Phase 1: Scout — 情报摄入 (try-except 隔离)
        # ─────────────────────────────────────────────────────
        self._dash.set_status("状态: 正在拉取新闻...")
        scraped_contents = []
        pipeline_result = None
        try:
            # 创建 IntakePipeline
            from projects.command_center.intelligence.intake_pipeline import (
                IntakePipeline, IntakePipelineConfig,
            )
            from projects.command_center.intelligence.scraper import Scraper, ScraperConfig
            from projects.command_center.intelligence.belief_modifier import BeliefModifier

            # 尝试创建 FlashAdapter（无 API Key 时自动 Mock）
            flash_adapter: Any = None
            try:
                from projects.command_center.config.settings_manager import SettingsManager
                sm = SettingsManager()
                api_key = sm.get_api_key()
                if api_key:
                    from projects.command_center.gateway.flash_adapter import (
                        FlashAdapter, FlashAdapterConfig,
                    )
                    fc = FlashAdapterConfig(api_key=api_key)
                    flash_adapter = FlashAdapter(config=fc)
            except Exception as exc:
                logger.debug("FlashAdapter init skipped: %s", exc)

            # 创建 Scraper + FactChecker + BeliefModifier
            scraper = Scraper(flash_adapter=flash_adapter)
            from projects.command_center.intelligence.fact_checker import (
                FactChecker, FactCheckerConfig,
            )
            fact_checker = FactChecker(flash_adapter=flash_adapter)

            belief_modifier = BeliefModifier()

            pipeline_cfg = IntakePipelineConfig(
                skip_fact_check=False,
                skip_belief_modify=False,
                timeout_seconds=60.0,
            )
            pipeline = IntakePipeline(
                scraper=scraper,
                fact_checker=fact_checker,
                belief_modifier=belief_modifier,
                config=pipeline_cfg,
            )

            # 默认新闻源列表（如果全部失败，自动 Mock 降级）
            news_urls = [
                "https://finance.yahoo.com/news/",
                "https://www.reuters.com/markets/",
                "https://www.cnbc.com/markets/",
            ]

            # 并发执行 IntakePipeline
            self._dash.set_status("状态: 正在分析市场资讯...")
            pipeline_results = loop.run_until_complete(
                pipeline.run_batch(news_urls, max_concurrent=2)
            )

            # 聚合结果
            for pr in pipeline_results:
                if pr.scraped and not pr.scraped.error:
                    scraped_contents.append(pr.scraped)
                if pr.plan and pr.plan.suggestions:
                    # 取最后一条有信念建议的结果作为宏观上下文
                    pipeline_result = pr

            logger.info(
                "Phase 1 Scout: %d/%d urls scraped, %d belief suggestions",
                len(scraped_contents), len(news_urls),
                len(pipeline_result.plan.suggestions) if pipeline_result and pipeline_result.plan else 0,
            )

        except Exception as exc:
            logger.warning("Phase 1 Scout failed (non-fatal): %s", exc)
            self._dash.set_status("状态: 新闻源不可用，使用模拟数据...")

        # 构建宏观上下文摘要（用于 LLMInterpreter）
        macro_context = ""
        if pipeline_result and pipeline_result.plan:
            for sug in pipeline_result.plan.suggestions:
                if sug.reason:
                    macro_context += sug.reason + "\n"
        if not macro_context:
            macro_context = (
                "Mock macro context: Market showing mixed signals. "
                "Fed policy uncertainty persists. Tech sector momentum strong. "
                "Bond yields stabilizing."
            )

        # ─────────────────────────────────────────────────────
        # Phase 2: Optimize — 真实信念权重注入调仓优化
        # ─────────────────────────────────────────────────────
        self._dash.set_status("状态: 正在优化调仓...")

        # 构建信念快照（从 IntakePipeline 结果提取）
        belief_snapshots = []
        if pipeline_result and pipeline_result.plan:
            for sug in pipeline_result.plan.suggestions:
                belief_snapshots.append({
                    "proposition_id": sug.proposition_id,
                    "score": sug.observation_value,
                    "expectation": sug.observation_value,
                })

        opt_result = optimizer.optimize(
            positions,
            belief_snapshots=belief_snapshots if belief_snapshots else None,
        )
        suggestions = opt_result.suggestions

        # ─────────────────────────────────────────────────────
        # Phase 3: Shadow — 影子对比 + LLM 解读
        # ─────────────────────────────────────────────────────
        self._dash.set_status("状态: 正在运行影子对比...")
        comp_result = comparator.compare(positions, suggestions)

        self._dash.set_status("状态: 正在生成 AI 解读...")
        llm_interpreter = LLMInterpreter(flash_adapter=flash_adapter)
        llm_result = loop.run_until_complete(
            llm_interpreter.interpret(
                comparison=comp_result,
                improvement=comp_result.improvement,
                risk_reduction=comp_result.risk_reduction,
                win_probability=comp_result.win_probability,
                suggested_preferred=comp_result.suggested_is_preferred,
                n_simulations=comp_result.n_simulations,
                macro_context=macro_context,
            )
        )

        # ─────────────────────────────────────────────────────
        # Phase 4: Report — 语义翻译 + 报告生成
        # ─────────────────────────────────────────────────────
        self._dash.set_status("状态: 正在生成报告...")

        # 语义翻译
        translated = translator.translate_full_comparison(comp_result)
        suggestions_narrative = {}

        # 构建信念摘要
        belief_summary = []
        for bs in belief_snapshots:
            belief_summary.append({
                "proposition_id": bs.get("proposition_id", ""),
                "score": bs.get("score", 0.5),
                "expectation": bs.get("expectation", 0.5),
            })

        # 将 LLM 解读嵌入翻译结果用于报告展示
        if isinstance(translated, dict) and llm_result.verdict_text:
            translated["verdict"] = llm_result.verdict_text
            translated["recommended_action"] = (
                "执行调仓建议" if comp_result.suggested_is_preferred
                else "维持当前仓位"
            )

        total_value = sum(p.market_value for p in positions)

        report_data = ReportData(
            positions=positions,
            belief_summary=belief_summary,
            rebalance_suggestions=suggestions,
            comparison=comp_result,
            comparison_interpretation=translated,
            interpretation_map=suggestions_narrative,
            total_portfolio_value=total_value,
            n_simulations=comp_result.n_simulations,
        )

        report_md = reporter.build_markdown(report_data)

        # 在报告末尾追加 LLM 蒙特卡洛解读段落
        if llm_result.verdict_text:
            llm_section = (
                "\n\n## 6. Monte Carlo AI 解读\n\n"
                f"{llm_result.verdict_text}\n\n---\n"
            )
            report_md += llm_section

        self._dash.set_status("状态: 战报生成完成")
        self._chat.append_system_message(report_md[-3000:], model="全链路战报")
        logger.info("Daily report completed: %d positions, %d suggestions, MC=%s",
                     len(positions), len(suggestions), llm_result.source)


    @staticmethod
    def _fallback_positions() -> List[Any]:
        """当 UI 中没有加载任何持仓时的 Mock 回退。"""
        from projects.command_center.models.position import Position
        return [
            Position(ticker="SPY", asset_name="SPDR S&P 500 ETF",
                shares=120.0, avg_cost=478.50, current_price=512.30,
                target_weight=0.40, current_weight=0.42),
            Position(ticker="QQQ", asset_name="Invesco QQQ Trust",
                shares=85.0, avg_cost=398.20, current_price=435.60,
                target_weight=0.25, current_weight=0.27),
            Position(ticker="TLT", asset_name="iShares 20+ Year Treasury Bond ETF",
                shares=2000.0, avg_cost=92.80, current_price=95.40,
                target_weight=0.20, current_weight=0.18),
            Position(ticker="XLF", asset_name="Financial Select Sector SPDR Fund",
                shares=4500.0, avg_cost=34.20, current_price=36.80,
                target_weight=0.10, current_weight=0.09),
            Position(ticker="CASH", asset_name="Cash Reserve",
                shares=50000.0, avg_cost=1.00, current_price=1.00,
                target_weight=0.05, current_weight=0.04),
        ]

    # ============================================================
    # Track B: 深度宏观研报
    # ============================================================

    def _run_macro_research(self) -> None:
        """生成深度宏观研报（后台线程执行）。

        新管线（零 Monte Carlo):
          Phase 0: 定义研究议程（6个定向问题）
          Phase 1: ResearchAgent 并发多源搜索
          Phase 2: MacroResearchEngine CoT 推理 + 范式注入
          Phase 3: 保存 Markdown 到 reports/ + 通知 UI

        防御性编程:
          - 每阶段独立 try-except，网络异常静默 Mock 降级
          - asyncio.new_event_loop() 管理异步生命周期
        """
        import threading

        def _do_research():
            import asyncio

            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                self._run_macro_research_impl(loop)
            except Exception as e:
                logger.error("Macro research fatal: %s", e, exc_info=True)
                self._dash.set_status("状态: 宏观研报生成失败 - %s" % e)
                self._chat.append_error_message("深度宏观研报生成链路崩溃: %s" % e)
            finally:
                loop.close()
                try:
                    self.after(0, lambda: (
                        self._dash._macro_research_btn.configure(state="normal")
                    ))
                except Exception:
                    pass

        self._dash._macro_research_btn.configure(state="disabled")
        threading.Thread(target=_do_research, daemon=True).start()

    def _run_macro_research_impl(self, loop: asyncio.AbstractEventLoop) -> None:
        """宏观研报管线实现体（在后台线程的 asyncio 事件循环中执行）。"""
        import time
        from projects.command_center.intelligence.research_agent import (
            ResearchAgent, get_default_agenda,
        )
        from projects.command_center.engine.macro_research import (
            MacroResearchEngine, MacroResearchReport,
        )
        from projects.command_center.gateway.pro_adapter import (
            ProAdapter, ProAdapterConfig,
        )

        # 尝试创建 ProAdapter（无 API Key 时自动 Mock）
        pro_adapter: Any = None
        try:
            from projects.command_center.config.settings_manager import SettingsManager
            sm = SettingsManager()
            api_key = sm.get_api_key()
            if api_key:
                pc = ProAdapterConfig(api_key=api_key)
                pro_adapter = ProAdapter(config=pc)
        except Exception as exc:
            logger.debug("ProAdapter init skipped for macro research: %s", exc)

        # 初始化引擎
        research_agent = ResearchAgent()
        macro_engine = MacroResearchEngine(pro_adapter=pro_adapter)

        # -------------------------------------------------------
        # Phase 0: 获取研究议程
        # -------------------------------------------------------
        self._dash.set_status("状态: 正在构建研究议程...")
        self._chat.append_system_message(
            "启动深度宏观研报管线\n研究议程: 6 个定向问题",
            model="Track B",
        )

        agenda = get_default_agenda()
        agenda_text = "\n".join(f"  {i+1}. {q}" for i, q in enumerate(agenda))
        self._chat.append_system_message(
            f"研究议程:\n{agenda_text}", model="Track B"
        )

        # -------------------------------------------------------
        # Phase 1: 并发多源搜索
        # -------------------------------------------------------
        self._dash.set_status("状态: 正在多源检索情报 (6/6 并发)...")

        async def _run_phase1():
            tasks = [research_agent.research(q) for q in agenda]
            return await asyncio.gather(*tasks)

        try:
            research_results = loop.run_until_complete(_run_phase1())

            success_count = sum(1 for r in research_results if r.source != "mock" or r.items)
            self._chat.append_system_message(
                f"情报检索完成: {success_count}/{len(agenda)} 议题获取到数据\n"
                f"来源: {', '.join(set(r.source for r in research_results))}",
                model="Track B",
            )
        except Exception as exc:
            logger.warning("Phase 1 research failed, using fallback: %s", exc)
            # 降级：使用默认议程创建 Mock 结果
            from projects.command_center.intelligence.research_agent import ResearchResult
            research_results = [
                ResearchResult(query=q, raw_text=f"(DuckDuckGo 不可用，使用本地预设数据)")
                for q in agenda
            ]
            self._chat.append_system_message(
                "网络搜索不可用，已降级至本地预设热点数据", model="Track B"
            )

        # -------------------------------------------------------
        # Phase 2: CoT 推理 + 研报生成
        # -------------------------------------------------------
        self._dash.set_status("状态: 正在生成深度宏观研报（CoT 推理中）...")
        self._chat.append_system_message(
            "正在调用 DeepSeek Pro 进行多跳因果推理...", model="Track B"
        )

        report = loop.run_until_complete(
            macro_engine.generate(research_results, title="全球宏观流动性全景分析")
        )

        # -------------------------------------------------------
        # Phase 3: 保存研报到磁盘
        # -------------------------------------------------------
        filepath = MacroResearchEngine.save_report(report)

        # -------------------------------------------------------
        # Final: 通知 UI
        # -------------------------------------------------------
        # 提取报告前 600 字符作为预览
        preview = report.content[:600] + "\n\n...(完整内容已保存至文件)"

        report_summary = (
            f"深度宏观研报生成完成\n"
            f"标题: {report.title}\n"
            f"模型: {report.model_used}\n"
            f"章节: {len(report.sections)} 个\n"
            f"预估 token: {report.token_estimate:,}\n"
            f"来源: {len(report.source_info)} 条\n"
        )
        if filepath:
            report_summary += f"\n已保存至: {filepath}"

        self._dash.set_status("状态: 深度宏观研报生成完成")
        self._chat.append_system_message(
            report_summary, model="Track B"
        )

        # 在 ChatPanel 显示完整报告（截断至 4000 字符）
        self._chat.append_system_message(
            preview, model="宏观研报预览"
        )

        logger.info(
            "Macro research completed: title=%s, tokens=%d, file=%s",
            report.title, report.token_estimate, filepath,
        )

    # ============================================================
    # 影子复盘
    # ============================================================

    def _run_shadow_replay(self) -> None:
        """执行蒙特卡洛影子复盘（后台线程执行，不卡 UI）。"""
        import threading

        def _do_shadow():
            try:
                from projects.command_center.models.position import Position
                from projects.command_center.engine.optimizer import Optimizer
                from projects.command_center.engine.shadow_comparator import ShadowComparator
                from projects.command_center.engine.semantic_translator import SemanticTranslator
                from projects.command_center.engine.reporter import Reporter, ReportData

                # 使用与一键日报相同的持仓数据
                sample_positions = [
                    Position(ticker="SPY", asset_name="SPDR S&P 500 ETF",
                        shares=120.0, avg_cost=478.50, current_price=512.30,
                        target_weight=0.40, current_weight=0.42),
                    Position(ticker="QQQ", asset_name="Invesco QQQ Trust",
                        shares=85.0, avg_cost=398.20, current_price=435.60,
                        target_weight=0.25, current_weight=0.27),
                    Position(ticker="TLT", asset_name="iShares 20+ Year Treasury Bond ETF",
                        shares=2000.0, avg_cost=92.80, current_price=95.40,
                        target_weight=0.20, current_weight=0.18),
                    Position(ticker="XLF", asset_name="Financial Select Sector SPDR Fund",
                        shares=4500.0, avg_cost=34.20, current_price=36.80,
                        target_weight=0.10, current_weight=0.09),
                    Position(ticker="CASH", asset_name="Cash Reserve",
                        shares=50000.0, avg_cost=1.00, current_price=1.00,
                        target_weight=0.05, current_weight=0.04),
                ]

                optimizer = Optimizer()
                opt_result = optimizer.optimize(sample_positions, belief_snapshots=None)
                suggestions = opt_result.suggestions

                comparator = ShadowComparator()
                comp_result = comparator.compare(sample_positions, suggestions)

                translator = SemanticTranslator()
                translated = translator.translate_full_comparison(comp_result)
                suggestions_narrative = {}

                report_data = ReportData(
                    positions=sample_positions,
                    rebalance_suggestions=suggestions,
                    comparison=comp_result,
                    comparison_interpretation=translated,
                    interpretation_map=suggestions_narrative,
                    total_portfolio_value=sum(p.market_value for p in sample_positions),
                    n_simulations=10000,
                )

                reporter = Reporter()
                report_md = reporter.build_markdown(report_data)

                # 提取影子对比相关部分（第5章）
                shadow_section = ""
                for line in report_md.split("\n"):
                    if "## 5." in line or shadow_section:
                        shadow_section += line + "\n"
                    if "---" in line and shadow_section:
                        break

                display_text = shadow_section or "蒙特卡洛影子复盘完成，但未提取到对比数据。"
                self._dash.render_shadow_result(display_text)

            except Exception as e:
                logger.error("Shadow replay failed: %s", e, exc_info=True)
                self._dash._shadow_status.configure(text=f"影子复盘失败: {e}")

        threading.Thread(target=_do_shadow, daemon=True).start()

    # ============================================================
    # 属性
    # ============================================================

    @property
    def dashboard(self) -> DashboardPanel:
        return self._dash

    @property
    def chat_panel(self) -> ChatPanel:
        return self._chat

    @property
    def settings_manager(self) -> SettingsManager:
        return self._settings

    def _detect_pipeline_mode(self) -> None:
        """Detect which pipeline is available and update the mode display."""
        try:
            import sys
            from pathlib import Path
            robinhood_root = str(Path(__file__).resolve().parent.parent.parent / "robinhood")
            if robinhood_root not in sys.path:
                sys.path.insert(0, robinhood_root)
            from src.main import run_daily_mode
            self._chat.set_mode_status("DeepSeek Flash + Pro 全管线")
        except ImportError:
            self._chat.set_mode_status("SignalFoundry 原生管线")
        except Exception:
            self._chat.set_mode_status("SignalFoundry 原生管线")

    def _run_shadow_results(self) -> None:
        """影子复盘面板：显示影子交易胜率、收益率、结算结果。"""
        import threading, json
        def _do_shadow():
            self._dash.set_status("状态: 加载影子复盘数据...")
            try:
                from pathlib import Path
                robinhood_root = str(Path(__file__).resolve().parent.parent.parent / "robinhood")
                sys.path.insert(0, robinhood_root)
                from src.shadow_personalities import run_daily_shadow_cycles, format_shadow_report
                from src.methodology_evolver import evolve_methodology, format_evolution_report

                cycles = run_daily_shadow_cycles()
                report = format_shadow_report(cycles)
                method_report = evolve_methodology()
                method_text = format_evolution_report(method_report)

                full = f"{report}\n\n{method_text}"
                self._show_report(full)
            except Exception as e:
                self._dash.set_status(f"状态: 影子复盘失败 - {e}")
                self._chat.append_error_message(f"影子复盘失败: {e}")
        threading.Thread(target=_do_shadow, daemon=True).start()

    def _show_report(self, report: str) -> None:
        """Display a Markdown report in the chat panel and update status."""
        self._dash.set_status("状态: 战报生成完成")
        # Show truncated preview in chat, save full report to file
        preview = report[:4000]
        if len(report) > 4000:
            preview += f"\n\n... (全文 {len(report)} 字符，已保存至 output/reports/)"
        self._chat.append_system_message(preview, model="SignalFoundry Phase B")
        # Save full report
        from pathlib import Path
        from datetime import datetime
        out_dir = Path(__file__).resolve().parent.parent.parent / "robinhood" / "output" / "reports"
        out_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_path = out_dir / f"daily_report_{ts}.md"
        report_path.write_text(report, encoding="utf-8")
        logger.info("Report saved to %s", report_path)

    def _on_close(self):
        logger.info("Closing window")
        try:
            self._chat.shutdown()
        except Exception as e:
            logger.warning("shutdown err: %s", e)
        self.destroy()