"""
dashboard_panel.py — Sprint 5: 左侧数据面板（集成一键日报按钮 + 持仓表格 + 影子对比）
"""

from __future__ import annotations
import logging
import threading
from typing import Any, Callable, List, Optional
import customtkinter as ctk

from projects.command_center.models.position import Position
from projects.command_center.config.portfolio_loader import load_portfolio
from projects.command_center.config.settings_manager import SettingsManager

logger = logging.getLogger(__name__)

# 表格列数
_N_COLS = 8


class DashboardPanel(ctk.CTkFrame):
    """左侧 Dashboard 面板，包含三个选项卡 + 一键日报按钮。"""

    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self._pipeline_cb: Optional[Callable[[], None]] = None
        self._shadow_cb: Optional[Callable[[], None]] = None

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=0)  # 分隔线
        self.grid_rowconfigure(2, weight=1)  # Tabview

        # 标题栏 + 一键日报按钮
        title_bar = ctk.CTkFrame(self, fg_color="transparent")
        title_bar.grid(row=0, column=0, padx=12, pady=(12, 4), sticky="ew")
        title_bar.grid_columnconfigure(0, weight=1)  # 标题左对齐
        title_bar.grid_columnconfigure(1, weight=0)  # 按钮右对齐

        self._title = ctk.CTkLabel(title_bar, text="交易中枢",
            font=ctk.CTkFont(size=16, weight='bold'), anchor='w')
        self._title.grid(row=0, column=0, sticky='w')

        self._daily_report_btn = ctk.CTkButton(
            title_bar, text="执行: 每日归因战报",
            font=ctk.CTkFont(size=12),
            fg_color="#1a73e8", hover_color="#1557b0",
            width=150, height=30,
            command=self._on_daily_report,
        )
        self._daily_report_btn.grid(row=0, column=1, padx=(8, 0), sticky='e')

        # 影子复盘面板按钮
        self._macro_research_btn = ctk.CTkButton(
            title_bar, text="影子复盘面板",
            font=ctk.CTkFont(size=12),
            fg_color="#b05ce6", hover_color="#8e3dc9",
            width=160, height=30,
            command=self._on_macro_research,
        )
        self._macro_research_btn.grid(row=0, column=2, padx=(4, 0), sticky='e')

        # 状态标签
        self._status_label = ctk.CTkLabel(
            self, text="", font=ctk.CTkFont(size=11),
            text_color=("#fbbc04", "#ffb300"),
        )
        self._status_label.grid(row=1, column=0, padx=16, pady=(0, 4), sticky='w')

        # 分隔线
        self._sep = ctk.CTkFrame(self, height=2, fg_color=('#cccccc', '#333333'))
        self._sep.grid(row=2, column=0, padx=12, pady=(0, 8), sticky='ew')

        # Tabview
        self._tv = ctk.CTkTabview(self)
        self._tv.grid(row=3, column=0, padx=8, pady=(0, 8), sticky='nsew')
        self.grid_rowconfigure(3, weight=1)

        # 仓位管理 tab
        self._tab_positions = self._tv.add("仓位管理")
        self._tab_positions.grid_columnconfigure(0, weight=1)
        self._tab_positions.grid_rowconfigure(0, weight=1)
        self._build_positions_tab()

        # 影子对比 tab
        self._tab_shadows = self._tv.add("影子对比")
        self._tab_shadows.grid_columnconfigure(0, weight=1)
        self._tab_shadows.grid_rowconfigure(1, weight=1)
        self._build_shadow_tab()

    # ============================================================
    # Tab: 仓位管理 (Defect 4 修复: 弃用固定 width, 改用 uniform 列组)
    # ============================================================

    def _build_positions_tab(self) -> None:
        """构建仓位管理选项卡，使用 uniform 列组确保任何字体下严格对齐。"""
        self._pos_scroll = ctk.CTkScrollableFrame(self._tab_positions, fg_color="transparent")
        self._pos_scroll.grid(row=0, column=0, sticky="nsew")
        self._pos_scroll.grid_columnconfigure(0, weight=1)

        # 表头
        headers = ["标的", "名称", "股数", "成本价", "市价", "市值", "权重", "盈亏%"]
        header_frame = ctk.CTkFrame(self._pos_scroll, fg_color=("#e0e0e0", "#2a2a3e"))
        header_frame.grid(row=0, column=0, sticky="ew", pady=(0, 2))
        # 使用 uniform 列组 + minsize 确保所有列等宽且不会过窄
        header_frame.grid_columnconfigure(
            tuple(range(_N_COLS)), weight=1, uniform='pos_col', minsize=60
        )

        for col, h in enumerate(headers):
            ctk.CTkLabel(
                header_frame, text=h, font=ctk.CTkFont(size=11, weight="bold"),
                anchor='w',
            ).grid(row=0, column=col, padx=4, pady=4, sticky='ew')

        self._pos_rows: List[ctk.CTkFrame] = []

        # 从外部配置加载持仓（降级到 mock）
        self._load_positions()

        # 底部按钮栏 (Defect 3 修复)
        btn_frame = ctk.CTkFrame(self._tab_positions, fg_color="transparent")
        btn_frame.grid(row=1, column=0, padx=8, pady=(6, 8), sticky="ew")
        btn_frame.grid_columnconfigure(0, weight=1)
        btn_frame.grid_columnconfigure(1, weight=0)
        btn_frame.grid_columnconfigure(2, weight=0)

        ctk.CTkButton(
            btn_frame, text="手工编辑 JSON 配置文件",
            font=ctk.CTkFont(size=11),
            fg_color="#555555", hover_color="#666666",
            width=180, height=26,
            command=self._on_edit_json,
        ).grid(row=0, column=1, padx=(0, 6))

        ctk.CTkButton(
            btn_frame, text="重新加载仓位",
            font=ctk.CTkFont(size=11),
            fg_color="#1a73e8", hover_color="#1557b0",
            width=120, height=26,
            command=self._on_reload_positions,
        ).grid(row=0, column=2, padx=(0, 0))

    def _get_config_dir(self):
        """获取配置目录路径。"""
        sm = SettingsManager()
        return sm._path.parent  # projects/command_center/

    def _load_positions(self) -> None:
        """尝试从配置文件加载持仓，失败则回退到演示 Mock 数据。"""
        config_dir = self._get_config_dir()
        positions = load_portfolio(config_dir)
        self.populate_positions(positions)

    def _on_edit_json(self) -> None:
        """打开 portfolio.json 在默认文本编辑器中。"""
        import os
        config_dir = self._get_config_dir()
        json_path = config_dir / "portfolio.json"

        # 如果文件不存在，从当前加载的仓位创建一份
        if not json_path.exists():
            from projects.command_center.config.portfolio_loader import save_portfolio
            save_portfolio(config_dir, self._current_positions or [])

        try:
            os.startfile(str(json_path))
        except Exception as exc:
            logger.warning("Failed to open portfolio.json: %s", exc)

    def _on_reload_positions(self) -> None:
        """重新加载仓位并刷新表格。"""
        self._load_positions()
        self.set_status("状态: 仓位已重新加载")
        self.after(3000, lambda: self.set_status(""))

    def populate_positions(self, positions: List[Position]) -> None:
        """用 Position 数据填充仓位表格，使用 uniform 列组保证对齐。"""
        # 存储当前加载的仓位供外部操作引用
        self._current_positions = positions

        # 清除旧行 (从 row=1 开始, row=0 是表头)
        for old_row in self._pos_rows:
            old_row.destroy()
        self._pos_rows.clear()

        for idx, pos in enumerate(positions):
            row_frame = ctk.CTkFrame(self._pos_scroll, fg_color="transparent")
            row_frame.grid(row=idx + 1, column=0, sticky="ew", pady=1)
            # 与表头一致的 uniform 列组
            row_frame.grid_columnconfigure(
                tuple(range(_N_COLS)), weight=1, uniform='pos_col', minsize=60
            )

            pnl_pct = pos.pnl_pct
            pnl_color = "#34a853" if pnl_pct >= 0 else "#ea4335"
            pnl_text = f"{pnl_pct:+.2f}%"

            row_data = [
                pos.ticker,
                pos.asset_name[:18],
                f"{pos.shares:.1f}",
                f"${pos.avg_cost:.2f}",
                f"${pos.current_price:.2f}",
                f"${pos.market_value:,.0f}",
                f"{pos.current_weight*100:.1f}%",
            ]

            for col, val in enumerate(row_data):
                ctk.CTkLabel(
                    row_frame, text=val, font=ctk.CTkFont(size=11),
                    anchor='w',
                ).grid(row=0, column=col, padx=4, pady=2, sticky='ew')

            # 盈亏% 列带颜色
            ctk.CTkLabel(
                row_frame, text=pnl_text, font=ctk.CTkFont(size=11),
                text_color=pnl_color, anchor='w',
            ).grid(row=0, column=7, padx=4, pady=2, sticky='ew')

            self._pos_rows.append(row_frame)

    # ============================================================
    # Tab: 影子对比（含触发按钮）
    # ============================================================

    def _build_shadow_tab(self) -> None:
        """影子对比 tab：触发按钮 + 结果展示区。"""
        # 顶部工具栏
        toolbar = ctk.CTkFrame(self._tab_shadows, fg_color="transparent")
        toolbar.grid(row=0, column=0, padx=8, pady=(8, 4), sticky="ew")
        toolbar.grid_columnconfigure(0, weight=0)
        toolbar.grid_columnconfigure(1, weight=1)

        self._shadow_btn = ctk.CTkButton(
            toolbar, text="持仓风险分析 (Monte Carlo)",
            font=ctk.CTkFont(size=12),
            fg_color="#1557b0", hover_color="#0d47a1",
            width=200, height=30,
            command=self._on_shadow_replay,
        )
        self._shadow_btn.grid(row=0, column=0, padx=(0, 8), sticky="w")

        self._shadow_status = ctk.CTkLabel(
            toolbar, text="", font=ctk.CTkFont(size=11),
            text_color=("#fbbc04", "#ffb300"),
        )
        self._shadow_status.grid(row=0, column=1, sticky="w")

        # 结果展示区
        self._shadow_result = ctk.CTkTextbox(
            self._tab_shadows, font=ctk.CTkFont(size=12),
            wrap="word", state="disabled",
        )
        self._shadow_result.grid(row=1, column=0, padx=8, pady=(0, 8), sticky="nsew")

    # ============================================================
    # 一键日报
    # ============================================================

    def set_pipeline_callback(self, cb: Callable[[], None]) -> None:
        """设置全链路回调（由 MainWindow 注入）。"""
        self._pipeline_cb = cb

    def set_shadow_callback(self, cb: Callable[[], None]) -> None:
        """设置影子复盘回调（由 MainWindow 注入）。"""
        self._shadow_cb = cb

    def set_macro_research_callback(self, cb: Callable[[], None]) -> None:
        """设置深度宏观研报回调（由 MainWindow 注入）。"""
        self._macro_research_cb = cb

    def set_status(self, text: str) -> None:
        """更新状态标签文本。"""
        self._status_label.configure(text=text)

    def get_macro_research_button(self) -> ctk.CTkButton:
        """返回宏观研报按钮（用于主窗口控制启用/禁用状态）。"""
        return self._macro_research_btn

    def _on_daily_report(self) -> None:
        """一键日报按钮点击。"""
        if self._pipeline_cb:
            self.set_status("状态: 正在生成战报...")
            self._daily_report_btn.configure(state="disabled")
            try:
                self._pipeline_cb()
            except Exception as e:
                self.set_status(f"状态: 错误 - {e}")
            finally:
                self._daily_report_btn.configure(state="normal")
        else:
            self.set_status("状态: 请先注入管线回调")
            self.after(3000, lambda: self.set_status(""))

    def _on_macro_research(self) -> None:
        """深度宏观研报按钮点击。"""
        if hasattr(self, "_macro_research_cb") and self._macro_research_cb:
            self.set_status("状态: 正在生成深度宏观研报...")
            self._macro_research_btn.configure(state="disabled")
            try:
                self._macro_research_cb()
            except Exception as e:
                self.set_status(f"状态: 错误 - {e}")
            finally:
                self._macro_research_btn.configure(state="normal")
        else:
            self.set_status("状态: 请先注入宏观研报回调")
            self.after(3000, lambda: self.set_status(""))

    def _on_shadow_replay(self) -> None:
        """影子复盘按钮点击（后台线程执行）。"""
        if self._shadow_cb:
            self._shadow_status.configure(text="正在进行蒙特卡洛模拟...")
            self._shadow_btn.configure(state="disabled")
            try:
                self._shadow_cb()
            except Exception as e:
                self._shadow_status.configure(text=f"错误: {e}")
            finally:
                self._shadow_btn.configure(state="normal")
        else:
            self._shadow_status.configure(text="请先注入影子回调")

    def render_shadow_result(self, text: str) -> None:
        """渲染影子对比结果到文本区域。"""
        self._shadow_result.configure(state="normal")
        self._shadow_result.delete("1.0", "end")
        self._shadow_result.insert("1.0", text)
        self._shadow_result.see("1.0")
        self._shadow_result.configure(state="disabled")
        self._shadow_status.configure(text="影子复盘完成")

    # ============================================================
    # 属性
    # ============================================================

    @property
    def current_positions(self) -> List[Position]:
        """获取当前表格中加载的持仓列表。"""
        return getattr(self, "_current_positions", [])

    @property
    def macro_research_button(self) -> ctk.CTkButton:
        return self._macro_research_btn

    @property
    def tabview(self) -> ctk.CTkTabview:
        return self._tv

    @property
    def tab_positions(self) -> ctk.CTkFrame:
        return self._tab_positions

    @property
    def tab_beliefs(self) -> ctk.CTkFrame:
        return self._tab_beliefs

    @property
    def tab_shadows(self) -> ctk.CTkFrame:
        return self._tab_shadows