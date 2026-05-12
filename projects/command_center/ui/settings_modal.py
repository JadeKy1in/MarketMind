"""settings_modal.py — Sprint 5: 全局设置弹窗 (SettingsModal)

通过齿轮按钮从 MainWindow 唤起。提供 5 个标签页:
  1. 外观 — 字体选择（动态读取系统字体）、字号、主题、色彩
  2. API — DeepSeek API Key 输入（密码框隐藏）
  3. 算法超参数 — Optimizer 核心参数滑块
  4. 影子对比 — ShadowComparator 参数选择
  5. 高级 — 情报管线、信念系统等（折叠区）

零 Emoji 策略: 所有按钮使用纯文本。
字体选择器使用 tkinter.font.families() 动态读取系统已安装字体。
"""

from __future__ import annotations

import logging
import tkinter.font as tkfont
from tkinter import messagebox
from typing import Any, Callable, Dict, List, Optional

import customtkinter as ctk

from projects.command_center.config.settings_manager import SettingsManager
from projects.command_center.config.defaults import DEFAULT_SETTINGS

logger = logging.getLogger(__name__)


def _get_system_fonts() -> List[str]:
    """读取系统已安装字体列表。"""
    try:
        return sorted(set(tkfont.families()))
    except Exception as exc:
        logger.warning("Failed to list system fonts: %s", exc)
        return ["Microsoft YaHei", "SimHei", "PingFang SC", "Arial", "Helvetica"]


class SettingsModal(ctk.CTkToplevel):
    """全局设置弹窗（模态）。

    用法:
        modal = SettingsModal(parent)
        modal.wait_window()  # 模态阻塞
    """

    def __init__(
        self,
        master: Any,
        settings: Optional[SettingsManager] = None,
        on_saved: Optional[Callable[[], None]] = None,
    ) -> None:
        super().__init__(master)
        self._settings = settings or SettingsManager()
        self._on_saved = on_saved
        self._font_list = _get_system_fonts()

        self.title("全局设置")
        self.geometry("680x520")
        self.resizable(True, True)
        self.minsize(600, 420)

        # 模态设置
        self.transient(master)
        self.grab_set()

        # 布局
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # Tabview
        self._tabs = ctk.CTkTabview(self)
        self._tabs.grid(row=0, column=0, padx=12, pady=(12, 4), sticky="nsew")

        # 创建各标签页
        self._tab_appearance = self._tabs.add("外观")
        self._tab_api = self._tabs.add("API")

        # 构建标签页 UI
        self._build_appearance_tab()
        self._build_api_tab()

        # 底部按钮栏
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.grid(row=1, column=0, padx=12, pady=(4, 12), sticky="ew")
        btn_frame.grid_columnconfigure(0, weight=1)
        btn_frame.grid_columnconfigure(1, weight=0)
        btn_frame.grid_columnconfigure(2, weight=0)
        btn_frame.grid_columnconfigure(3, weight=1)

        ctk.CTkButton(
            btn_frame, text="恢复默认",
            fg_color="#555555", hover_color="#666666",
            command=self._on_reset,
        ).grid(row=0, column=1, padx=(0, 6))

        ctk.CTkButton(
            btn_frame, text="保存设置",
            fg_color="#1a73e8", hover_color="#1557b0",
            command=self._on_save,
        ).grid(row=0, column=2, padx=(6, 0))

        # 居中显示
        self.after(50, self._center_on_parent)

        # 强制应用全局字体配置 (Defect 4 修复: 子窗口继承主窗口字体)
        try:
            appearance = self._settings.get("appearance", {})
            family = appearance.get("font_family", "Microsoft YaHei")
            size = appearance.get("font_size_base", 14)
            font = ctk.CTkFont(family=family, size=size)
            from projects.command_center.ui.main_window import MainWindow
            MainWindow._apply_font_recursive(self, font)
        except Exception as exc:
            logger.debug("SettingsModal font inheritance skipped: %s", exc)

        logger.info("SettingsModal opened with %d fonts available", len(self._font_list))

    # ============================================================
    # 居中
    # ============================================================

    def _center_on_parent(self) -> None:
        """将弹窗放置在主窗口中央。"""
        try:
            parent = self.master
            px = parent.winfo_x()
            py = parent.winfo_y()
            pw = parent.winfo_width()
            ph = parent.winfo_height()
            sw = self.winfo_reqwidth()
            sh = self.winfo_reqheight()
            self.geometry(f"+{px + (pw - sw) // 2}+{py + (ph - py) // 2}")
        except Exception:
            pass

    # ============================================================
    # Tab: 外观
    # ============================================================

    def _build_appearance_tab(self) -> None:
        tab = self._tab_appearance
        tab.grid_columnconfigure(0, weight=0)
        tab.grid_columnconfigure(1, weight=1)
        tab.grid_rowconfigure(10, weight=1)  # 底部弹性空间

        row = 0

        # 字体家族
        ctk.CTkLabel(tab, text="字体家族:", anchor="w").grid(
            row=row, column=0, padx=(12, 8), pady=(16, 6), sticky="w")
        current_font = self._settings.get("appearance.font_family", "Microsoft YaHei")
        self._font_var = ctk.StringVar(value=current_font)
        self._font_cb = ctk.CTkComboBox(
            tab, values=self._font_list, variable=self._font_var,
            width=300, state="readonly",
        )
        self._font_cb.grid(row=row, column=1, padx=(0, 12), pady=(16, 6), sticky="ew")
        row += 1

        # 基础字号
        ctk.CTkLabel(tab, text="基础字号:", anchor="w").grid(
            row=row, column=0, padx=(12, 8), pady=6, sticky="w")
        current_size = self._settings.get("appearance.font_size_base", 14)
        self._size_var = ctk.IntVar(value=current_size)
        self._size_slider = ctk.CTkSlider(
            tab, from_=10, to=24, number_of_steps=14,
            variable=self._size_var, command=self._on_size_slider,
        )
        self._size_slider.grid(row=row, column=1, padx=(0, 12), pady=6, sticky="ew")
        self._size_label = ctk.CTkLabel(tab, text=f"{current_size}pt", width=40)
        self._size_label.grid(row=row, column=2, padx=(0, 12), pady=6, sticky="w")
        row += 1

        # 外观模式
        ctk.CTkLabel(tab, text="外观模式:", anchor="w").grid(
            row=row, column=0, padx=(12, 8), pady=6, sticky="w")
        current_mode = self._settings.get("appearance.appearance_mode", "dark")
        self._mode_var = ctk.StringVar(value=current_mode)
        mode_cb = ctk.CTkComboBox(
            tab, values=["dark", "light", "system"],
            variable=self._mode_var, state="readonly", width=200,
        )
        mode_cb.grid(row=row, column=1, padx=(0, 12), pady=6, sticky="w")
        row += 1

        # 色彩主题
        ctk.CTkLabel(tab, text="色彩主题:", anchor="w").grid(
            row=row, column=0, padx=(12, 8), pady=6, sticky="w")
        current_theme = self._settings.get("appearance.color_theme", "blue")
        self._theme_var = ctk.StringVar(value=current_theme)
        theme_cb = ctk.CTkComboBox(
            tab, values=["blue", "dark-blue", "green"],
            variable=self._theme_var, state="readonly", width=200,
        )
        theme_cb.grid(row=row, column=1, padx=(0, 12), pady=6, sticky="w")

    def _on_size_slider(self, val: float) -> None:
        self._size_label.configure(text=f"{int(val)}pt")

    # ============================================================
    # Tab: API
    # ============================================================

    def _build_api_tab(self) -> None:
        tab = self._tab_api
        tab.grid_columnconfigure(0, weight=0)
        tab.grid_columnconfigure(1, weight=1)
        tab.grid_rowconfigure(10, weight=1)

        row = 0

        # DeepSeek API Key
        ctk.CTkLabel(tab, text="DeepSeek API Key:", anchor="w").grid(
            row=row, column=0, padx=(12, 8), pady=(16, 6), sticky="w")
        self._api_key_var = ctk.StringVar(value=self._settings.get_api_key())
        api_entry = ctk.CTkEntry(
            tab, textvariable=self._api_key_var,
            placeholder_text="输入 DeepSeek API Key...",
            show="*", width=400,
        )
        api_entry.grid(row=row, column=1, padx=(0, 12), pady=(16, 6), sticky="ew")
        row += 1

        ctk.CTkLabel(tab, text="", anchor="w").grid(
            row=row, column=1, padx=(0, 12), pady=(0, 6), sticky="w")
        ctk.CTkLabel(
            tab, text="Pro 模型: deepseek-v4-pro | Flash 模型: deepseek-v4-flash（已锁定）",
            text_color=("#666666", "#999999"),
            anchor="w",
        ).grid(row=row, column=1, padx=(0, 12), pady=(0, 6), sticky="w")

    # ============================================================
    # Tab: 算法超参数
    # ============================================================

    def _build_optimizer_tab(self) -> None:
        tab = self._tab_optimizer
        tab.grid_columnconfigure(0, weight=0)
        tab.grid_columnconfigure(1, weight=1)
        tab.grid_rowconfigure(10, weight=1)

        # 顶部说明文字
        note = ctk.CTkLabel(
            tab,
            text="以下参数控制优化算法行为，不直接操作持仓。",
            text_color=("#888888", "#aaaaaa"),
            anchor="w",
            font=ctk.CTkFont(size=11),
        )
        note.grid(row=0, column=0, columnspan=3, padx=12, pady=(12, 4), sticky="w")

        params = [
            ("漂移阈值", "optimizer.drift_threshold", 0.01, 0.10, 0.01, "{:.2f}"),
            ("单仓位权重上限", "optimizer.max_single_position_weight", 0.10, 0.50, 0.05, "{:.2f}"),
            ("现金仓位地板", "optimizer.cash_weight_floor", 0.01, 0.20, 0.01, "{:.2f}"),
            ("最小信念权重", "optimizer.min_belief_weight", 0.05, 0.50, 0.05, "{:.2f}"),
            ("波动率缓冲", "optimizer.volatility_buffer", 0.0, 0.10, 0.01, "{:.2f}"),
        ]
        self._optimizer_sliders: Dict[str, ctk.CTkSlider] = {}
        self._optimizer_labels: Dict[str, ctk.CTkLabel] = {}

        for i, (label, path, lo, hi, step, fmt) in enumerate(params):
            row = i + 1  # +1 因为第0行是说明文字
            ctk.CTkLabel(tab, text=f"{label}:", anchor="w").grid(
                row=row, column=0, padx=(12, 8), pady=6, sticky="w")
            current_val = self._settings.get(path, (lo + hi) / 2)
            n_steps = int((hi - lo) / step)
            var = ctk.DoubleVar(value=current_val)
            slider = ctk.CTkSlider(
                tab, from_=lo, to=hi, number_of_steps=n_steps,
                variable=var,
                command=lambda v, p=path, f=fmt, r=row: self._on_opt_slider(p, f, v),
            )
            slider.grid(row=row, column=1, padx=(0, 8), pady=6, sticky="ew")
            val_label = ctk.CTkLabel(tab, text=fmt.format(current_val), width=50)
            val_label.grid(row=row, column=2, padx=(0, 12), pady=6, sticky="w")
            self._optimizer_sliders[path] = slider
            self._optimizer_labels[path] = val_label

        # 最大建议数
        row = len(params) + 1
        ctk.CTkLabel(tab, text="最大建议数:", anchor="w").grid(
            row=row, column=0, padx=(12, 8), pady=6, sticky="w")
        self._max_sug_var = ctk.IntVar(
            value=self._settings.get("optimizer.max_suggestions", 10))
        sug_spin = ctk.CTkEntry(tab, textvariable=self._max_sug_var, width=80)
        sug_spin.grid(row=row, column=1, padx=(0, 12), pady=6, sticky="w")

    def _on_opt_slider(self, path: str, fmt: str, val: float) -> None:
        self._optimizer_labels[path].configure(text=fmt.format(val))

    # ============================================================
    # Tab: 影子对比
    # ============================================================

    def _build_shadow_tab(self) -> None:
        tab = self._tab_shadow
        tab.grid_columnconfigure(0, weight=0)
        tab.grid_columnconfigure(1, weight=1)
        tab.grid_rowconfigure(10, weight=1)

        row = 0

        # MC 模拟次数
        ctk.CTkLabel(tab, text="MC 模拟次数:", anchor="w").grid(
            row=row, column=0, padx=(12, 8), pady=(16, 6), sticky="w")
        self._n_sim_var = ctk.StringVar(
            value=str(self._settings.get("shadow_comparator.n_simulations", 10000)))
        sim_cb = ctk.CTkComboBox(
            tab, values=["5000", "10000", "20000", "50000"],
            variable=self._n_sim_var, state="readonly", width=150,
        )
        sim_cb.grid(row=row, column=1, padx=(0, 12), pady=(16, 6), sticky="w")
        row += 1

        # 模拟天数
        ctk.CTkLabel(tab, text="模拟天数:", anchor="w").grid(
            row=row, column=0, padx=(12, 8), pady=6, sticky="w")
        self._n_days_var = ctk.StringVar(
            value=str(self._settings.get("shadow_comparator.n_days", 30)))
        days_cb = ctk.CTkComboBox(
            tab, values=["7", "14", "30", "60", "90"],
            variable=self._n_days_var, state="readonly", width=150,
        )
        days_cb.grid(row=row, column=1, padx=(0, 12), pady=6, sticky="w")
        row += 1

        # VaR 置信水平
        ctk.CTkLabel(tab, text="VaR 置信水平:", anchor="w").grid(
            row=row, column=0, padx=(12, 8), pady=6, sticky="w")
        self._conf_var = ctk.StringVar(
            value=f"{self._settings.get('shadow_comparator.confidence_level', 0.95):.2f}")
        conf_cb = ctk.CTkComboBox(
            tab, values=["0.90", "0.95", "0.99"],
            variable=self._conf_var, state="readonly", width=150,
        )
        conf_cb.grid(row=row, column=1, padx=(0, 12), pady=6, sticky="w")

    # ============================================================
    # Tab: 高级
    # ============================================================

    def _build_advanced_tab(self) -> None:
        tab = self._tab_advanced
        tab.grid_columnconfigure(0, weight=0)
        tab.grid_columnconfigure(1, weight=1)
        tab.grid_rowconfigure(10, weight=1)

        # 情报管线温度
        row = 0
        ctk.CTkLabel(tab, text="Pro 温度:", anchor="w").grid(
            row=row, column=0, padx=(12, 8), pady=(16, 6), sticky="w")
        self._temp_pro_var = ctk.DoubleVar(
            value=self._settings.get("chat.temperature_pro", 0.7))
        temp_pro_slider = ctk.CTkSlider(
            tab, from_=0.0, to=2.0, number_of_steps=20,
            variable=self._temp_pro_var, command=self._on_temp_pro,
        )
        temp_pro_slider.grid(row=row, column=1, padx=(0, 8), pady=(16, 6), sticky="ew")
        self._temp_pro_label = ctk.CTkLabel(
            tab, text=f"{self._temp_pro_var.get():.1f}", width=40)
        self._temp_pro_label.grid(row=row, column=2, padx=(0, 12), pady=(16, 6), sticky="w")
        row += 1

        ctk.CTkLabel(tab, text="Flash 温度:", anchor="w").grid(
            row=row, column=0, padx=(12, 8), pady=6, sticky="w")
        self._temp_flash_var = ctk.DoubleVar(
            value=self._settings.get("chat.temperature_flash", 0.3))
        temp_flash_slider = ctk.CTkSlider(
            tab, from_=0.0, to=2.0, number_of_steps=20,
            variable=self._temp_flash_var, command=self._on_temp_flash,
        )
        temp_flash_slider.grid(row=row, column=1, padx=(0, 8), pady=6, sticky="ew")
        self._temp_flash_label = ctk.CTkLabel(
            tab, text=f"{self._temp_flash_var.get():.1f}", width=40)
        self._temp_flash_label.grid(row=row, column=2, padx=(0, 12), pady=6, sticky="w")
        row += 1

        # 信念衰减阈值
        ctk.CTkLabel(tab, text="信念衰减阈值:", anchor="w").grid(
            row=row, column=0, padx=(12, 8), pady=6, sticky="w")
        self._decay_var = ctk.DoubleVar(
            value=self._settings.get("belief.decay_rate_threshold", 0.85))
        decay_slider = ctk.CTkSlider(
            tab, from_=0.5, to=1.0, number_of_steps=50,
            variable=self._decay_var,
        )
        decay_slider.grid(row=row, column=1, padx=(0, 8), pady=6, sticky="ew")
        ctk.CTkLabel(tab, textvariable=self._decay_var, width=40).grid(
            row=row, column=2, padx=(0, 12), pady=6, sticky="w")
        row += 1

        # 反思间隔（小时）
        ctk.CTkLabel(tab, text="反思间隔 (小时):", anchor="w").grid(
            row=row, column=0, padx=(12, 8), pady=6, sticky="w")
        self._reflect_var = ctk.IntVar(
            value=self._settings.get("belief.reflection_interval_hours", 24))
        reflect_entry = ctk.CTkEntry(tab, textvariable=self._reflect_var, width=80)
        reflect_entry.grid(row=row, column=1, padx=(0, 12), pady=6, sticky="w")

    def _on_temp_pro(self, val: float) -> None:
        self._temp_pro_label.configure(text=f"{val:.1f}")

    def _on_temp_flash(self, val: float) -> None:
        self._temp_flash_label.configure(text=f"{val:.1f}")

    # ============================================================
    # 保存 / 重置
    # ============================================================

    def _collect_values(self) -> Dict[str, Any]:
        """收集所有 UI 控件的值。"""
        sm = self._settings

        # 外观
        sm.set("appearance.font_family", self._font_var.get())
        sm.set("appearance.font_size_base", int(self._size_var.get()))
        sm.set("appearance.appearance_mode", self._mode_var.get())
        sm.set("appearance.color_theme", self._theme_var.get())

        # API Key
        sm.set_api_key(self._api_key_var.get())
        sm.set("api.deepseek_pro_model", self._pro_model_var.get())
        sm.set("api.deepseek_flash_model", self._flash_model_var.get())

        # 调仓参数
        for path, in [
            ("optimizer.drift_threshold",),
            ("optimizer.max_single_position_weight",),
            ("optimizer.cash_weight_floor",),
            ("optimizer.min_belief_weight",),
            ("optimizer.volatility_buffer",),
        ]:
            if path in self._optimizer_sliders:
                sm.set(path, round(self._optimizer_sliders[path].get(), 4))

        sm.set("optimizer.max_suggestions", int(self._max_sug_var.get()))

        # 影子对比
        sm.set("shadow_comparator.n_simulations", int(self._n_sim_var.get()))
        sm.set("shadow_comparator.n_days", int(self._n_days_var.get()))
        sm.set("shadow_comparator.confidence_level", float(self._conf_var.get()))

        # 高级
        sm.set("chat.temperature_pro", round(self._temp_pro_var.get(), 1))
        sm.set("chat.temperature_flash", round(self._temp_flash_var.get(), 1))
        sm.set("belief.decay_rate_threshold", round(self._decay_var.get(), 2))
        sm.set("belief.reflection_interval_hours", int(self._reflect_var.get()))

        return sm.get_all()

    def _on_save(self) -> None:
        """保存并关闭弹窗，成功后显示确认提示。"""
        try:
            self._collect_values()
            self._settings.save_and_notify()
            logger.info("Settings saved from modal")
            messagebox.showinfo(
                "设置已保存",
                "所有设置已成功保存并应用。"
            )
            if self._on_saved:
                self._on_saved()
            self.destroy()
        except Exception as exc:
            logger.error("Failed to save settings: %s", exc)
            messagebox.showerror(
                "保存失败",
                f"保存设置时出错: {exc}"
            )

    def _on_reset(self) -> None:
        """重置为默认值并关闭。"""
        self._settings.reset_to_defaults()
        self._settings.save_and_notify()
        logger.info("Settings reset to defaults")
        messagebox.showinfo(
            "设置已重置",
            "所有设置已恢复为默认值。"
        )
        if self._on_saved:
            self._on_saved()
        self.destroy()