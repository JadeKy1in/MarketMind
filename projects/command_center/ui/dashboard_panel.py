"""
dashboard_panel.py — Sprint 5: 左侧数据面板（集成一键日报按钮）
"""

from __future__ import annotations
from typing import Any, Callable, Optional
import customtkinter as ctk


class DashboardPanel(ctk.CTkFrame):
    """左侧 Dashboard 面板，包含三个选项卡 + 一键日报按钮。"""

    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self._pipeline_cb: Optional[Callable[[], None]] = None

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=0)  # 分隔线
        self.grid_rowconfigure(2, weight=1)  # Tabview

        # 标题栏 + 一键日报按钮
        title_bar = ctk.CTkFrame(self, fg_color="transparent")
        title_bar.grid(row=0, column=0, padx=12, pady=(12, 4), sticky="ew")
        title_bar.grid_columnconfigure(0, weight=1)  # 标题左对齐
        title_bar.grid_columnconfigure(1, weight=0)  # 按钮右对齐

        self._title = ctk.CTkLabel(title_bar, text="Command Center Dashboard",
            font=ctk.CTkFont(size=16, weight='bold'), anchor='w')
        self._title.grid(row=0, column=0, sticky='w')

        self._daily_report_btn = ctk.CTkButton(
            title_bar, text="执行: 一键生成每日归因战报",
            font=ctk.CTkFont(size=12),
            fg_color="#1a73e8", hover_color="#1557b0",
            width=220, height=30,
            command=self._on_daily_report,
        )
        self._daily_report_btn.grid(row=0, column=1, padx=(8, 0), sticky='e')

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

        for name, hint in [
            ('仓位管理', '持仓比例 / 浮盈浮亏 / 风险评估'),
            ('信念图谱', '信念节点 / 置信度评分 / 冲突检测'),
            ('影子对比', '多模型决策差异 / 分歧分析 / 共识度'),
        ]:
            tab = self._tv.add(name)
            tab.grid_columnconfigure(0, weight=1)
            tab.grid_rowconfigure(0, weight=1)
            lbl = ctk.CTkLabel(tab, text=f'{name}\n\n{hint}',
                font=ctk.CTkFont(size=13),
                text_color=('#666666', '#999999'))
            lbl.grid(row=0, column=0, padx=20, pady=40, sticky='nsew')

    # ============================================================
    # 一键日报
    # ============================================================

    def set_pipeline_callback(self, cb: Callable[[], None]) -> None:
        """设置全链路回调（由 MainWindow 注入）。"""
        self._pipeline_cb = cb

    def set_status(self, text: str) -> None:
        """更新状态标签文本。"""
        self._status_label.configure(text=text)

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

    # ============================================================
    # 属性
    # ============================================================

    @property
    def tabview(self) -> ctk.CTkTabview:
        return self._tv

    @property
    def tab_positions(self) -> ctk.CTkFrame:
        return self._tv.tab('仓位管理')

    @property
    def tab_beliefs(self) -> ctk.CTkFrame:
        return self._tv.tab('信念图谱')

    @property
    def tab_shadows(self) -> ctk.CTkFrame:
        return self._tv.tab('影子对比')