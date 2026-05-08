"""
shadow_comparison_panel.py — Sprint 3: 影子对比面板

渲染 Optimizer 和 ShadowComparator 的对比结果。
嵌入在 DashboardPanel 的"影子对比"选项卡内。

SPARC:
  Specification: V2.0 Sprint 3 — 影子对比 UI 渲染
  Pseudocode: OptimizerResult + ComparisonResult → CTkFrame 表格
  Architecture: 纯 UI 渲染层，通过 DashboardPanel 注入数据
  Refinement: Mock 数据模式，无需真实引擎也可预览
  Completion: 测试覆盖率 ≥ 70%
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import customtkinter as ctk

logger = logging.getLogger(__name__)


class ShadowComparisonPanel(ctk.CTkFrame):
    """影子对比面板 — 渲染调仓建议 + Monte Carlo 对比结果。

    使用方式:
        panel = ShadowComparisonPanel(parent_tab)
        panel.render(optimizer_result, comparison_result)
    """

    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # ── 标题 ──
        self._title = ctk.CTkLabel(
            self, text="📊 影子对比引擎",
            font=ctk.CTkFont(size=15, weight="bold"), anchor="w",
        )
        self._title.grid(row=0, column=0, padx=12, pady=(8, 4), sticky="ew")

        # ── 滚动区域（放置建议表格和对比结果） ──
        self._scroll = ctk.CTkScrollableFrame(self)
        self._scroll.grid_columnconfigure(0, weight=1)
        self._scroll.grid(row=1, column=0, padx=8, pady=4, sticky="nsew")

        # ── 空状态 ──
        self._empty_label = ctk.CTkLabel(
            self._scroll, text="暂无对比数据。\n运行调仓优化后将在此处显示结果。",
            font=ctk.CTkFont(size=13),
            text_color=("#666666", "#888888"),
        )
        self._empty_label.grid(row=0, column=0, padx=20, pady=60)

        # 缓存用于渲染的控件引用
        self._suggestion_frames: List[ctk.CTkFrame] = []
        self._comparison_frame: Optional[ctk.CTkFrame] = None

        logger.info("ShadowComparisonPanel initialized")

    # ============================================================
    # 渲染入口
    # ============================================================

    def render(
        self,
        optimizer_result: Any = None,  # OptimizerResult or dict
        comparison_result: Any = None,  # ComparisonResult or dict
    ) -> None:
        """渲染优化结果和对比结果。

        Args:
            optimizer_result: OptimizerResult 实例或 dict
            comparison_result: ComparisonResult 实例或 dict
        """
        # 清空现有内容
        self._clear()

        if optimizer_result is None and comparison_result is None:
            self._empty_label = ctk.CTkLabel(
                self._scroll, text="暂无对比数据。",
                font=ctk.CTkFont(size=13),
                text_color=("#666666", "#888888"),
            )
            self._empty_label.grid(row=0, column=0, padx=20, pady=60)
            return

        row_idx = 0

        # ── 调仓建议表格 ──
        if optimizer_result is not None:
            suggestions = self._safe_get(optimizer_result, "suggestions", [])
            belief_scores = self._safe_get(optimizer_result, "belief_scores", {})
            total_value = self._safe_get(optimizer_result, "total_portfolio_value", 0.0)
            high_count = self._safe_get(optimizer_result, "high_urgency_count", 0)

            # 摘要行
            summary_label = ctk.CTkLabel(
                self._scroll,
                text=(
                    f"📋 调仓建议 | "
                    f"{len(suggestions)} 条建议 ({high_count} 条高优先级) | "
                    f"总市值 ${total_value:,.0f}"
                ),
                font=ctk.CTkFont(size=13),
                anchor="w",
            )
            summary_label.grid(row=row_idx, column=0, padx=8, pady=(4, 2), sticky="ew")
            row_idx += 1

            if suggestions:
                for s in suggestions:
                    s_frame = self._build_suggestion_row(s)
                    s_frame.grid(row=row_idx, column=0, padx=4, pady=2, sticky="ew")
                    self._suggestion_frames.append(s_frame)
                    row_idx += 1
            else:
                no_sug = ctk.CTkLabel(
                    self._scroll, text="⚠️ 未检测到需要调仓的信号",
                    font=ctk.CTkFont(size=12),
                    text_color=("#999999", "#777777"),
                )
                no_sug.grid(row=row_idx, column=0, padx=8, pady=8, sticky="w")
                row_idx += 1

        # 分隔线
        sep = ctk.CTkFrame(self._scroll, height=1, fg_color=("#cccccc", "#444444"))
        sep.grid(row=row_idx, column=0, padx=8, pady=8, sticky="ew")
        row_idx += 1

        # ── 影子对比结果 ──
        if comparison_result is not None:
            self._comparison_frame = self._build_comparison_section(comparison_result)
            self._comparison_frame.grid(
                row=row_idx, column=0, padx=8, pady=(4, 8), sticky="ew",
            )
            row_idx += 1

        logger.info(
            "ShadowComparisonPanel rendered: %d suggestions, comparison=%s",
            len(self._suggestion_frames),
            comparison_result is not None,
        )

    # ============================================================
    # 内部构建
    # ============================================================

    def _build_suggestion_row(self, s: Any) -> ctk.CTkFrame:
        """构建单条调仓建议的行控件。"""
        ticker = self._safe_get(s, "ticker", "?")
        action = self._safe_get(s, "reason_short", "")
        urgency = self._safe_get(s, "urgency", "LOW")
        belief_w = float(self._safe_get(s, "belief_weight", 0.5))
        delta = float(self._safe_get(s, "delta_shares", 0.0))
        from_w = float(self._safe_get(s, "from_weight", 0.0))
        to_w = float(self._safe_get(s, "to_weight", 0.0))

        # 颜色编码
        if urgency == "HIGH":
            urgency_color = "#ea4335"
            bg_color = "#2d1b1b"
        elif urgency == "MEDIUM":
            urgency_color = "#fbbc04"
            bg_color = "#2d2b1b"
        else:
            urgency_color = "#34a853"
            bg_color = "#1b2d1b"

        frame = ctk.CTkFrame(self._scroll, fg_color=bg_color, corner_radius=6)
        frame.grid_columnconfigure(0, weight=0)
        frame.grid_columnconfigure(1, weight=1)
        frame.grid_columnconfigure(2, weight=0)

        # Tick + 方向
        direction = "🔺" if delta > 0 else "🔻"
        tick_lbl = ctk.CTkLabel(
            frame,
            text=f"{direction} {ticker}",
            font=ctk.CTkFont(size=14, weight="bold"),
            anchor="w",
        )
        tick_lbl.grid(row=0, column=0, padx=(8, 4), pady=4, sticky="w")

        # 原因
        reason_lbl = ctk.CTkLabel(
            frame,
            text=action,
            font=ctk.CTkFont(size=11),
            anchor="w",
            text_color=("#cccccc", "#bbbbbb"),
        )
        reason_lbl.grid(row=0, column=1, padx=4, pady=4, sticky="ew")

        # 权重变化
        weight_text = f"☑ {from_w*100:.1f}% → {to_w*100:.1f}%"
        if abs(delta) > 0.01:
            weight_text += f" ({delta:+.1f} 股)"
        weight_lbl = ctk.CTkLabel(
            frame,
            text=weight_text,
            font=ctk.CTkFont(size=11),
            anchor="e",
        )
        weight_lbl.grid(row=0, column=2, padx=(4, 8), pady=4, sticky="e")

        # 信念权重条
        belief_frame = ctk.CTkFrame(frame, height=4, fg_color="#333333")
        belief_frame.grid(row=1, column=0, columnspan=3, padx=8, pady=(0, 4), sticky="ew")
        belief_bar = ctk.CTkFrame(
            belief_frame, height=4,
            fg_color=urgency_color,
            width=int(belief_w * 200),
        )
        belief_bar.place(x=0, y=0)

        return frame

    def _build_comparison_section(
        self,
        comp_result: Any,
    ) -> ctk.CTkFrame:
        """构建影子对比结果控件。"""
        current_mean = float(self._safe_get(
            self._safe_get(comp_result, "current_stats", {}), "mean", 0.0
        ))
        suggested_mean = float(self._safe_get(
            self._safe_get(comp_result, "suggested_stats", {}), "mean", 0.0
        ))
        improvement = float(self._safe_get(comp_result, "improvement", 0.0))
        risk_reduction = float(self._safe_get(comp_result, "risk_reduction", 0.0))
        win_prob = float(self._safe_get(comp_result, "win_probability", 0.0))
        suggested_preferred = bool(self._safe_get(comp_result, "suggested_is_preferred", False))
        convergence = float(self._safe_get(comp_result, "convergence_score", 0.0))
        n_sims = int(self._safe_get(comp_result, "n_simulations", 0))

        frame = ctk.CTkFrame(self._scroll)
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_columnconfigure(1, weight=1)

        # 标题
        title_color = "#34a853" if suggested_preferred else "#ea4335"
        title_text = "✅ 建议方案优于当前方案" if suggested_preferred else "⚠️ 当前方案更优"
        title_lbl = ctk.CTkLabel(
            frame,
            text=f"📈 Monte Carlo 分析 ({n_sims:,} 条路径)",
            font=ctk.CTkFont(size=13, weight="bold"),
            anchor="w",
        )
        title_lbl.grid(row=0, column=0, columnspan=2, padx=8, pady=(4, 2), sticky="ew")

        # 优劣标签
        verdict_lbl = ctk.CTkLabel(
            frame, text=title_text,
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=title_color, anchor="w",
        )
        verdict_lbl.grid(row=1, column=0, columnspan=2, padx=8, pady=(0, 4), sticky="w")

        # 对比指标（2列布局）
        metrics = [
            ("预期收益改进", f"{improvement:+.2%}",
             "#34a853" if improvement > 0 else "#ea4335"),
            ("风险（标准差）降低", f"{risk_reduction:+.2%}",
             "#34a853" if risk_reduction > 0 else "#ea4335"),
            ("胜率变化", f"{win_prob:+.2%}",
             "#34a853" if win_prob > 0 else "#ea4335"),
            ("收敛度", f"{convergence:.2f}",
             "#34a853" if convergence > 0.5 else "#fbbc04"),
            ("当前预期收益", f"{current_mean:+.4%}", "#ffffff"),
            ("建议预期收益", f"{suggested_mean:+.4%}", "#ffffff"),
        ]

        for i, (label, value, color) in enumerate(metrics):
            lbl = ctk.CTkLabel(
                frame, text=label,
                font=ctk.CTkFont(size=12),
                anchor="w",
            )
            lbl.grid(row=2 + i, column=0, padx=(8, 4), pady=2, sticky="w")

            val = ctk.CTkLabel(
                frame, text=value,
                font=ctk.CTkFont(size=12, weight="bold"),
                text_color=color, anchor="e",
            )
            val.grid(row=2 + i, column=1, padx=(4, 8), pady=2, sticky="e")

        return frame

    # ============================================================
    # 辅助
    # ============================================================

    def _clear(self) -> None:
        """清空所有已有控件。"""
        for widget in self._scroll.winfo_children():
            widget.destroy()
        self._suggestion_frames.clear()
        self._comparison_frame = None

    @staticmethod
    def _safe_get(obj: Any, key: str, default: Any = None) -> Any:
        if obj is None:
            return default
        if isinstance(obj, dict):
            return obj.get(key, default)
        return getattr(obj, key, default)