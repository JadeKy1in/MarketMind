"""
main_window.py — Sprint 5: 主窗口（集成 Settings Hub 热更新）
"""

from __future__ import annotations
import logging
from typing import Any, Dict, Optional
import customtkinter as ctk
from projects.command_center.config.settings_manager import SettingsManager
from projects.command_center.gateway.task_queue import TaskQueue
from projects.command_center.ui.dashboard_panel import DashboardPanel
from projects.command_center.ui.chat_panel import ChatPanel
from projects.command_center.ui.settings_modal import SettingsModal

logger = logging.getLogger(__name__)

TITLE = "Cline OS Command Center V2.0"
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

        # 注入一键日报回调
        self._dash.set_pipeline_callback(self._run_daily_report)

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
        """递归遍历 widget 树，更新所有 CTk 组件的字体。"""
        try:
            # 尝试多种可能的字体属性
            if hasattr(widget, "configure"):
                try:
                    widget.configure(font=font)
                except Exception:
                    pass  # 忽略不支持 font 的 widget
        except Exception:
            pass
        try:
            for child in widget.winfo_children():
                MainWindow._apply_font_recursive(child, font)
        except Exception:
            pass

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
        """一键生成每日归因战报（后台线程执行）。"""
        import threading

        def _do_report():
            import asyncio
            import time

            self._dash.set_status("状态: 正在拉取新闻...")
            try:
                # Step 1: 情报摄入
                from projects.command_center.intelligence.scraper import Scraper
                from projects.command_center.intelligence.intake_pipeline import IntakePipeline
                from projects.command_center.engine.optimizer import Optimizer
                from projects.command_center.engine.shadow_comparator import ShadowComparator
                from projects.command_center.engine.semantic_translator import SemanticTranslator
                from projects.command_center.engine.reporter import Reporter
                from projects.command_center.models.position import Position

                # 创建样本仓位（实际应从数据源注入）
                sample_positions = [
                    Position(ticker="SPY", weight=0.40, value=400000, shares=1000),
                    Position(ticker="QQQ", weight=0.25, value=250000, shares=800),
                    Position(ticker="TLT", weight=0.20, value=200000, shares=1800),
                    Position(ticker="XLF", weight=0.10, value=100000, shares=4000),
                    Position(ticker="CASH", weight=0.05, value=50000, shares=50000),
                ]

                # Step 2: 一键优化 → 影子对比 → 翻译 → 报告
                self._dash.set_status("状态: 正在优化调仓...")
                optimizer = Optimizer()
                opt_result = optimizer.optimize(sample_positions, belief_scores=None)

                self._dash.set_status("状态: 正在运行影子对比...")
                comparator = ShadowComparator()
                comp_result = comparator.compare(sample_positions, opt_result.suggestions)

                self._dash.set_status("状态: 正在生成报告...")
                translator = SemanticTranslator()
                translated = translator.translate_comparison(comp_result)
                suggestions_narrative = translator.translate_suggestions(
                    opt_result.suggestions, sample_positions
                )

                reporter = Reporter()
                report_data = reporter.build_data(
                    positions=sample_positions,
                    optimized_suggestions=opt_result,
                    comparison=comp_result,
                    translated_comparison=translated,
                    translated_suggestions=suggestions_narrative,
                )
                report_md = reporter.build_markdown(report_data)

                # Step 3: 通知 Dashboard
                self._dash.set_status("状态: 战报生成完成")
                self._chat.append_system_message(
                    report_md[-2000:],  # 显示最后 2000 字符
                    model="全链路战报",
                )

            except Exception as e:
                logger.error("Daily report failed: %s", e)
                self._dash.set_status(f"状态: 战报生成失败 - {e}")
            finally:
                self._dash._daily_report_btn.configure(state="normal")

        self._dash._daily_report_btn.configure(state="disabled")
        threading.Thread(target=_do_report, daemon=True).start()

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

    def _on_close(self):
        logger.info("Closing window")
        try:
            self._chat.shutdown()
        except Exception as e:
            logger.warning("shutdown err: %s", e)
        self.destroy()
