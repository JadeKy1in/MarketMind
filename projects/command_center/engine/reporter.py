"""
reporter.py — Sprint 4: 报告生成引擎

组装所有数据源（Positions, Beliefs, Rebalance Suggestions, Shadow Comparisons），
生成结构化 Markdown 报告。PDF 导出作为可选（try-except）附加功能。

设计原则：
  - 降级策略：Markdown 是核心输出，PDF 是 try-except 包装
  - 纯文本管道：report_data → markdown → (optional) PDF
  - 模板化：预定义的报告模板，可自定义节标题

SPARC:
  Specification: V2.0 Sprint 4 — 报告生成
  Pseudocode: data → template → markdown_string → (try PDF)
  Architecture: 纯函数式组装，无文件系统副作用的报告构建
  Refinement: 异常安全，PDF 失败不阻塞 Markdown
  Completion: 测试覆盖率 ≥ 80%
"""

from __future__ import annotations

import datetime
import logging
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ============================================================
# 报告数据组装
# ============================================================


@dataclass
class ReportData:
    """报告所需的所有数据源组装体。

    Attributes:
        title: 报告标题
        generated_at: 生成时间（ISO-8601）
        positions: 仓位列表（dict 或 Position 对象）
        belief_summary: 信念摘要（dict 列表）
        rebalance_suggestions: 调仓建议（dict 或 RebalanceSuggestion 对象）
        optimizer_summary: 优化器摘要文本
        comparison: 影子对比结果（dict 或 ComparisonResult 对象）
        comparison_interpretation: 语义翻译的对比解读（ShadowComparisonInterpretation 或 dict）
        interpretation_map: ticker → TranslationResult 映射
        total_portfolio_value: 总市值
        n_simulations: Monte Carlo 模拟路径数
    """
    title: str = "Cline OS Command Center — 投资决策报告"
    generated_at: str = field(default_factory=lambda: (
        datetime.datetime.now(datetime.timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%S.%f"
        ) + "Z"
    ))
    positions: List[Any] = field(default_factory=list)
    belief_summary: List[Dict[str, Any]] = field(default_factory=list)
    rebalance_suggestions: List[Any] = field(default_factory=list)
    optimizer_summary: str = ""
    comparison: Optional[Any] = None
    comparison_interpretation: Optional[Any] = None
    interpretation_map: Dict[str, Any] = field(default_factory=dict)
    total_portfolio_value: float = 0.0
    n_simulations: int = 0


# ============================================================
# Reporter — 报告生成器
# ============================================================


class Reporter:
    """报告生成引擎 — 组装数据源 → 结构化 Markdown → 可选 PDF。

    用法:
        reporter = Reporter()
        md = reporter.build_markdown(report_data)
        with open("report.md", "w") as f:
            f.write(md)

        # 带 PDF 尝试
        pdf_path = reporter.build_pdf(report_data, output_dir="./reports")
        if pdf_path:
            print(f"PDF saved: {pdf_path}")
    """

    # 风险等级 → 表情映射
    _RISK_EMOJI = {
        "低": "🟢",
        "中等": "🟡",
        "高": "🔴",
        "极高": "⛔",
        "未知": "⚪",
    }

    # 紧急程度 → 表情映射
    _URGENCY_EMOJI = {
        "HIGH": "🔴",
        "MEDIUM": "🟡",
        "LOW": "🟢",
    }

    # 信心等级颜色（ANSI 用于终端，Markdown 用文字符号）
    _CONFIDENCE_SYMBOL = {
        "极强": "🟢",
        "很强": "🟢",
        "较强": "🟡",
        "一般": "🟡",
        "较弱": "🔴",
        "极弱": "🔴",
    }

    def build_markdown(self, data: ReportData) -> str:
        """构建完整结构化 Markdown 报告。

        Args:
            data: 报告数据

        Returns:
            str: 格式化的 Markdown 文本
        """
        sections: List[str] = []

        # ── 页眉 ──
        sections.append(self._build_header(data))

        # ── 执行摘要 ──
        sections.append(self._build_executive_summary(data))

        # ── 仓位一览 ──
        sections.append(self._build_positions_section(data))

        # ── 信念摘要 ──
        sections.append(self._build_belief_section(data))

        # ── 调仓建议 ──
        sections.append(self._build_rebalance_section(data))

        # ── 影子对比分析 ──
        sections.append(self._build_comparison_section(data))

        # ── 详细翻译 ──
        sections.append(self._build_translations_section(data))

        # ── 免责声明 ──
        sections.append(self._build_disclaimer())

        return "\n\n".join(sections)

    def build_pdf(
        self,
        data: ReportData,
        output_dir: str = ".",
    ) -> Optional[str]:
        """尝试生成 PDF 报告。降级策略：失败则返回 None。

        Args:
            data: 报告数据
            output_dir: 输出目录

        Returns:
            Optional[str]: 成功时返回 PDF 文件路径，失败返回 None
        """
        try:
            from weasyprint import HTML
            md = self.build_markdown(data)
            html = self._markdown_to_html(md)

            import os
            os.makedirs(output_dir, exist_ok=True)

            timestamp = datetime.datetime.now(datetime.timezone.utc).strftime(
                "%Y%m%d_%H%M%S"
            )
            pdf_path = os.path.join(output_dir, f"report_{timestamp}.pdf")

            HTML(string=html).write_pdf(pdf_path)
            logger.info("PDF report generated: %s", pdf_path)
            return pdf_path

        except ImportError:
            logger.warning(
                "weasyprint not installed. Install with: pip install weasyprint"
            )
        except Exception as e:
            logger.warning("PDF generation failed (non-fatal): %s", e)

        return None

    # ============================================================
    # 内部构建方法
    # ============================================================

    @staticmethod
    def _safe_get(obj: Any, key: str, default: Any = None) -> Any:
        if obj is None:
            return default
        if isinstance(obj, dict):
            return obj.get(key, default)
        return getattr(obj, key, default)

    @staticmethod
    def _format_weight(w: float) -> str:
        return f"{w * 100:.1f}%"

    @staticmethod
    def _format_dollar(v: float) -> str:
        return f"${v:,.2f}"

    # ── 页眉 ──

    def _build_header(self, data: ReportData) -> str:
        lines = [
            f"# {data.title}",
            "",
            f"**生成时间**: {data.generated_at}",
            f"**总市值**: {self._format_dollar(data.total_portfolio_value)}",
            f"**Monte Carlo 模拟**: {data.n_simulations:,} 条路径" if data.n_simulations > 0 else "",
            "",
            "---",
        ]
        return "\n".join(line for line in lines if line)

    # ── 执行摘要 ──

    def _build_executive_summary(self, data: ReportData) -> str:
        lines = [
            "## 1. 执行摘要",
            "",
        ]

        # 仓位统计
        n_active = sum(
            1 for p in data.positions
            if self._safe_get(p, "status") == "ACTIVE"
        )
        n_total = len(data.positions)
        lines.append(f"- **仓位**: {n_active} 个活跃仓位 / {n_total} 个总仓位")

        # 调仓建议统计
        n_suggestions = len(data.rebalance_suggestions)
        n_high = sum(
            1 for s in data.rebalance_suggestions
            if self._safe_get(s, "urgency") == "HIGH"
        )
        n_med = sum(
            1 for s in data.rebalance_suggestions
            if self._safe_get(s, "urgency") == "MEDIUM"
        )
        lines.append(
            f"- **调仓信号**: {n_suggestions} 条建议"
            f"（{n_high} 条紧急 / {n_med} 条中等）"
        )

        # 影子对比裁决
        comp_interp = data.comparison_interpretation
        if comp_interp:
            verdict = self._safe_get(comp_interp, "verdict", "")
            if verdict:
                lines.append(f"- **Monte Carlo 裁决**: {verdict}")
            action = self._safe_get(comp_interp, "recommended_action", "")
            if action:
                lines.append(f"- **建议操作**: {action}")

        # 信念统计
        n_beliefs = len(data.belief_summary)
        if n_beliefs > 0:
            lines.append(f"- **活跃信念**: {n_beliefs} 个命题")

        lines.append("")
        lines.append("---")
        return "\n".join(lines)

    # ── 仓位一览 ──

    def _build_positions_section(self, data: ReportData) -> str:
        lines = [
            "## 2. 仓位一览",
            "",
            "| 标的 | 名称 | 股数 | 市价 | 市值 | 权重 | 盈亏 |",
            "|------|------|------|------|------|------|------|",
        ]

        for p in data.positions:
            ticker = self._safe_get(p, "ticker", "?")
            name = self._safe_get(p, "asset_name", "")
            shares = self._safe_get(p, "shares", 0.0)
            price = self._safe_get(p, "current_price", 0.0)
            mkt_val = self._safe_get(p, "market_value", shares * price)
            weight = self._safe_get(p, "current_weight", 0.0)

            # 盈亏
            avg_cost = self._safe_get(p, "avg_cost", 0.0)
            if avg_cost > 0 and price > 0:
                pnl = (price - avg_cost) * shares
                pnl_str = f"{pnl:+,.0f}"
            else:
                pnl_str = "-"

            lines.append(
                f"| {ticker} | {name} | {shares:.1f} | "
                f"{self._format_dollar(price)} | {self._format_dollar(mkt_val)} | "
                f"{self._format_weight(weight)} | {pnl_str} |"
            )

        lines.extend(["", "---"])
        return "\n".join(lines)

    # ── 信念摘要 ──

    def _build_belief_section(self, data: ReportData) -> str:
        if not data.belief_summary:
            return "## 3. 信念图谱\n\n*暂无活跃信念数据。*\n\n---"

        lines = [
            "## 3. 信念图谱",
            "",
            "| 命题 | 评分 | 信心等级 | 预期值 |",
            "|------|------|----------|--------|",
        ]

        for b in data.belief_summary:
            prop_id = self._safe_get(b, "proposition_id", "?")
            score = float(self._safe_get(b, "score", 0.5))

            # 信心等级
            if score >= 0.75:
                level = "🟢 很强"
            elif score >= 0.5:
                level = "🟡 较强"
            elif score >= 0.25:
                level = "🔴 较弱"
            else:
                level = "⛔ 极弱"

            expectation = float(self._safe_get(b, "expectation", 0.0))

            lines.append(
                f"| {prop_id} | {score:.2f} | {level} | {expectation:.2f} |"
            )

        lines.extend(["", "---"])
        return "\n".join(lines)

    # ── 调仓建议 ──

    def _build_rebalance_section(self, data: ReportData) -> str:
        if not data.rebalance_suggestions:
            return "## 4. 调仓建议\n\n*当前无需调整仓位。*\n\n---"

        lines = [
            "## 4. 调仓建议",
            "",
            "| 标的 | 方向 | 当前权重 | 目标权重 | 股数变动 | 紧急程度 | 信念评分 |",
            "|------|------|----------|----------|----------|----------|----------|",
        ]

        for s in data.rebalance_suggestions:
            ticker = self._safe_get(s, "ticker", "?")
            delta = float(self._safe_get(s, "delta_shares", 0.0))
            direction = "🔺 买入" if delta > 0 else "🔻 卖出"
            from_w = float(self._safe_get(s, "from_weight", 0.0))
            to_w = float(self._safe_get(s, "to_weight", 0.0))
            urgency = self._safe_get(s, "urgency", "LOW")
            urg_emoji = self._URGENCY_EMOJI.get(urgency, "⚪")
            belief_w = float(self._safe_get(s, "belief_weight", 0.5))

            lines.append(
                f"| {ticker} | {direction} | {self._format_weight(from_w)} | "
                f"{self._format_weight(to_w)} | {delta:+.1f} | "
                f"{urg_emoji} {urgency} | {belief_w:.2f} |"
            )

        # 如果有语义翻译结果，添加自然语言描述
        if data.interpretation_map:
            lines.extend(["", "### 详细解读", ""])
            for ticker, tr in sorted(data.interpretation_map.items()):
                narrative = self._safe_get(tr, "action_narrative", "")
                if narrative:
                    lines.extend([
                        f"**{ticker}**:",
                        "",
                        f"> {narrative}",
                        "",
                    ])
                belief_n = self._safe_get(tr, "belief_narrative", "")
                if belief_n:
                    lines.append(f"> *信念支撑：{belief_n}*")
                    lines.append("")

        lines.append("---")
        return "\n".join(lines)

    # ── 影子对比分析 ──

    def _build_comparison_section(self, data: ReportData) -> str:
        if not data.comparison:
            return "## 5. Monte Carlo 影子对比分析\n\n*未执行影子对比分析。*\n\n---"

        lines = [
            "## 5. Monte Carlo 影子对比分析",
            "",
            f"基于 **{data.n_simulations:,}** 条模拟路径的统计分析：",
            "",
        ]

        # 统计对比表
        comp = data.comparison
        cs = self._safe_get(comp, "current_stats")
        ss = self._safe_get(comp, "suggested_stats")

        if cs and ss:
            lines.extend([
                "| 指标 | 当前方案 | 建议方案 | 变化 |",
                "|------|----------|----------|------|",
            ])

            # 获取原始数值（非字符串）
            c_mean = self._safe_get(cs, "mean", 0.0)
            s_mean = self._safe_get(ss, "mean", 0.0)
            c_std = self._safe_get(cs, "std", 0.0)
            s_std = self._safe_get(ss, "std", 0.0)
            c_sharpe = self._safe_get(cs, "sharpe", 0.0)
            s_sharpe = self._safe_get(ss, "sharpe", 0.0)
            c_win = self._safe_get(cs, "win_rate", 0.0)
            s_win = self._safe_get(ss, "win_rate", 0.0)
            c_var = self._safe_get(cs, "var", 0.0)
            s_var = self._safe_get(ss, "var", 0.0)

            def delta_str(c: float, s: float) -> str:
                d = s - c
                return f"{d:+.4f}" if abs(d) > 0.0001 else "持平"

            # 用原始浮点数计算 delta
            for label, c_raw, s_raw, fmt in [
                ("预期收益", c_mean, s_mean, lambda v: f"{v*100:.2f}%"),
                ("波动率", c_std, s_std, lambda v: f"{v*100:.2f}%"),
                ("夏普比率", c_sharpe, s_sharpe, lambda v: f"{v:.2f}"),
                ("胜率", c_win, s_win, lambda v: f"{v*100:.1f}%"),
                ("VaR (95%)", c_var, s_var, lambda v: f"{v*100:.2f}%"),
            ]:
                c_val = fmt(c_raw)
                s_val = fmt(s_raw)
                d_val = delta_str(c_raw, s_raw)
                lines.append(
                    f"| {label} | {c_val} | {s_val} | {d_val} |"
                )

        # 裁决和推荐
        interp = data.comparison_interpretation
        if interp:
            lines.extend(["", "### 综合评估", ""])

            verdict = self._safe_get(interp, "verdict", "")
            if verdict:
                lines.append(f"**结论**: {verdict}")
                lines.append("")

            summary = self._safe_get(interp, "summary_paragraph", "")
            if summary:
                lines.append(f"> {summary}")
                lines.append("")

            action = self._safe_get(interp, "recommended_action", "")
            if action:
                lines.append(f"**推荐操作**: {action}")

        lines.append("")
        lines.append("---")
        return "\n".join(lines)

    # ── 详细翻译 ──

    def _build_translations_section(self, data: ReportData) -> str:
        """可选：当有翻译结果时，生成详细翻译节。"""
        if not data.interpretation_map:
            return ""

        lines = [
            "## 6. 深度分析",
            "",
            "每条调仓建议的详细语义翻译和不确定性分析：",
            "",
        ]

        for ticker in sorted(data.interpretation_map.keys()):
            tr = data.interpretation_map[ticker]
            lines.append(f"### {ticker} — {self._safe_get(tr, 'asset_name', '')}")
            lines.append("")

            # 行动叙事
            narrative = self._safe_get(tr, "action_narrative", "")
            if narrative:
                lines.extend(["> **操作分析**:", f"> {narrative}", ""])

            # 信心等级
            conf = self._safe_get(tr, "confidence")
            if conf:
                level = self._safe_get(conf, "level_name", "")
                desc = self._safe_get(conf, "description", "")
                lines.append(f"- **信心等级**: {self._CONFIDENCE_SYMBOL.get(level, '')} {level} — {desc}")

            # 不确定性
            uncert = self._safe_get(tr, "uncertainty")
            if uncert:
                vol = self._safe_get(uncert, "volatility_desc", "")
                risk = self._safe_get(uncert, "risk_level", "")
                risk_emoji = self._RISK_EMOJI.get(risk, "")
                if vol:
                    lines.append(f"- **波动分析**: {risk_emoji} {vol}")
                tail = self._safe_get(uncert, "tail_risk_desc", "")
                if tail:
                    lines.append(f"- **尾部风险**: {tail}")
                max_loss = self._safe_get(uncert, "max_loss_desc", "")
                if max_loss:
                    lines.append(f"- **最大回撤**: {max_loss}")

            # 信念叙事
            belief_n = self._safe_get(tr, "belief_narrative", "")
            if belief_n:
                lines.append(f"- **信念支撑**: {belief_n}")

            # 影子对比解读
            shadow = self._safe_get(tr, "shadow_interpretation")
            if shadow:
                summary = self._safe_get(shadow, "summary_paragraph", "")
                if summary:
                    lines.append(f"- **Monte Carlo 分析**: {summary}")

            lines.append("")

        lines.append("---")
        return "\n".join(lines)

    # ── 免责声明 ──

    @staticmethod
    def _build_disclaimer() -> str:
        return (
            "## 免责声明\n\n"
            "*本报告由 Cline OS Command Center V2.0 自动生成，仅供决策参考，"
            "不构成投资建议。投资有风险，入市需谨慎。*\n\n"
            "---\n\n"
            "*© Cline OS Command Center V2.0 — 报告引擎 v1.0*"
        )

    # ============================================================
    # Markdown → HTML 转换（用于 PDF 导出）
    # ============================================================

    @staticmethod
    def _markdown_to_html(md: str) -> str:
        """将 Markdown 转换为基本 HTML。"""
        import html as html_lib

        lines = md.split("\n")
        html_parts: List[str] = [
            "<!DOCTYPE html>",
            "<html lang='zh-CN'>",
            "<head><meta charset='utf-8'>",
            "<style>",
            "  body { font-family: 'Noto Sans SC', 'Microsoft YaHei', sans-serif; "
            "padding: 2em; max-width: 900px; margin: auto; }",
            "  h1 { color: #1a73e8; border-bottom: 2px solid #1a73e8; }",
            "  h2 { color: #333; margin-top: 1.5em; }",
            "  h3 { color: #555; }",
            "  table { border-collapse: collapse; width: 100%; margin: 1em 0; }",
            "  th, td { border: 1px solid #ccc; padding: 8px; text-align: left; }",
            "  th { background-color: #f5f5f5; }",
            "  blockquote { border-left: 4px solid #1a73e8; margin: 1em 0; "
            "padding: 0.5em 1em; background: #f9f9f9; }",
            "</style>",
            "</head><body>",
        ]

        in_table = False
        for line in lines:
            stripped = line.strip()

            # 标题
            if stripped.startswith("### "):
                html_parts.append(f"<h3>{html_lib.escape(stripped[4:])}</h3>")
            elif stripped.startswith("## "):
                html_parts.append(f"<h2>{html_lib.escape(stripped[3:])}</h2>")
            elif stripped.startswith("# "):
                html_parts.append(f"<h1>{html_lib.escape(stripped[2:])}</h1>")
            # 表格
            elif stripped.startswith("|") and stripped.endswith("|"):
                cells = [
                    c.strip() for c in stripped.split("|")[1:-1]
                ]
                if "---" in stripped:
                    continue  # 分隔线
                if not in_table:
                    html_parts.append("<table>")
                    in_table = True
                # 检测表头（如果上一行是表头，这行还是表头模式）
                # 简单处理：所有行都作为 <tr>
                is_header = any(
                    c in ("标的", "名称", "指标", "命题", "方向", "ticker")
                    for c in cells
                )
                tag = "th" if is_header else "td"
                html_parts.append(
                    "<tr>" + "".join(f"<{tag}>{html_lib.escape(c)}</{tag}>" for c in cells) + "</tr>"
                )
            else:
                if in_table:
                    html_parts.append("</table>")
                    in_table = False

                # 其他元素
                if not stripped:
                    html_parts.append("<br>")
                elif stripped.startswith("> "):
                    html_parts.append(
                        f"<blockquote>{html_lib.escape(stripped[2:])}</blockquote>"
                    )
                elif stripped.startswith("- **"):
                    # 列表项
                    html_parts.append(f"<li>{stripped[2:]}</li>")
                elif stripped.startswith("**"):
                    strong = stripped.strip("*")
                    html_parts.append(f"<p><strong>{html_lib.escape(strong)}</strong></p>")
                else:
                    html_parts.append(f"<p>{html_lib.escape(stripped)}</p>")

        if in_table:
            html_parts.append("</table>")

        html_parts.extend(["</body></html>"])
        return "\n".join(html_parts)