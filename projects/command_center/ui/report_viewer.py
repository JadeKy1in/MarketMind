"""
report_viewer.py — Sprint 4: 报告查看器

在界面上提供"一键优化"按钮和"导出报告"按钮。
点击"一键优化"触发完整链路：
  Position → Belief → Optimizer → ShadowComparator → SemanticTranslator → Reporter

SPARC:
  Specification: V2.0 Sprint 4 — UI 报告查看器
  Pseudocode: trigger → full_pipeline → dict_report → Reporter.build_markdown
  Architecture: UI 层，通过 DashboardPanel 注入数据和回调
  Refinement: 异常安全，进度提示
  Completion: 测试覆盖率 ≥ 70%
"""

from __future__ import annotations

import datetime
import logging
import os
import tkinter.filedialog as filedialog
import tkinter.messagebox as messagebox
from dataclasses import asdict
from typing import Any, Callable, Dict, List, Optional

import customtkinter as ctk

logger = logging.getLogger(__name__)


class ReportViewer(ctk.CTkFrame):
    """报告查看器 — "一键优化" + "导出报告" + Markdown 预览。

    使用方式:
        viewer = ReportViewer(parent_frame)
        viewer.set_pipeline_callback(run_full_pipeline)
        viewer.set_data_provider(get_data)
    """

    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        # 回调
        self._pipeline_callback: Optional[Callable[[], Any]] = None
        self._data_provider: Optional[Callable[[], Dict[str, Any]]] = None

        # 状态
        self._last_report: Optional[str] = None
        self._last_report_data: Optional[Any] = None

        # ── 标题 ──
        self._title = ctk.CTkLabel(
            self, text="📄 报告中心",
            font=ctk.CTkFont(size=15, weight="bold"), anchor="w",
        )
        self._title.grid(row=0, column=0, padx=12, pady=(8, 4), sticky="ew")

        # ── 按钮行 ──
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.grid(row=1, column=0, padx=8, pady=(4, 4), sticky="ew")
        btn_frame.grid_columnconfigure(0, weight=0)
        btn_frame.grid_columnconfigure(1, weight=0)
        btn_frame.grid_columnconfigure(2, weight=0)
        btn_frame.grid_columnconfigure(3, weight=1)

        self._optimize_btn = ctk.CTkButton(
            btn_frame,
            text="⚡ 一键优化",
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color="#1a73e8",
            hover_color="#1557b0",
            command=self._on_optimize,
            width=120,
        )
        self._optimize_btn.grid(row=0, column=0, padx=(0, 6), pady=4)

        self._export_md_btn = ctk.CTkButton(
            btn_frame,
            text="📥 导出 Markdown",
            font=ctk.CTkFont(size=12),
            fg_color="#34a853",
            hover_color="#2d8f47",
            command=self._on_export_md,
            width=120,
        )
        self._export_md_btn.grid(row=0, column=1, padx=6, pady=4)

        self._export_pdf_btn = ctk.CTkButton(
            btn_frame,
            text="📕 导出 PDF",
            font=ctk.CTkFont(size=12),
            fg_color="#ea4335",
            hover_color="#c5221f",
            command=self._on_export_pdf,
            width=100,
        )
        self._export_pdf_btn.grid(row=0, column=2, padx=6, pady=4)

        # ── 报告预览（Markdown 文本区域） ──
        self._preview_text = ctk.CTkTextbox(
            self,
            font=ctk.CTkFont(size=12, family="Consolas"),
            wrap="word",
        )
        self._preview_text.grid(row=2, column=0, padx=8, pady=(4, 8), sticky="nsew")
        self._preview_text.configure(state="disabled")

        # ── 状态栏 ──
        self._status_label = ctk.CTkLabel(
            self, text="就绪 — 点击「一键优化」启动全链路分析",
            font=ctk.CTkFont(size=11),
            anchor="w",
            text_color=("#666666", "#888888"),
        )
        self._status_label.grid(row=3, column=0, padx=12, pady=(0, 6), sticky="ew")

        logger.info("ReportViewer initialized")

    # ============================================================
    # 回调注入
    # ============================================================

    def set_pipeline_callback(
        self,
        callback: Callable[[], Any],
    ) -> None:
        """设置全链路回调。

        Args:
            callback: 无参函数，返回 optimizer_result, comparison_result, report_data
        """
        self._pipeline_callback = callback

    def set_data_provider(
        self,
        provider: Callable[[], Dict[str, Any]],
    ) -> None:
        """设置数据提供者。

        Args:
            provider: 返回当前数据字典的函数
        """
        self._data_provider = provider

    # ============================================================
    # 事件处理器
    # ============================================================

    def _on_optimize(self) -> None:
        """点击"一键优化"按钮。"""
        if self._pipeline_callback is None:
            self._set_status("⚠️ 未设置优化回调，请先配置全链路管道", "#ea4335")
            return

        self._set_status("⏳ 正在执行全链路分析...", "#fbbc04")
        self._optimize_btn.configure(state="disabled")
        self._export_md_btn.configure(state="disabled")
        self._export_pdf_btn.configure(state="disabled")
        self.update_idletasks()

        try:
            result = self._pipeline_callback()

            # 结果解析
            if isinstance(result, tuple) and len(result) >= 2:
                optimizer_result = result[0]
                comparison_result = result[1]
                report_data = result[2] if len(result) >= 3 else None
            else:
                optimizer_result = result
                comparison_result = None
                report_data = None

            # 如果有 report_data，使用 Reporter 生成 Markdown
            if report_data is not None:
                from projects.command_center.engine.reporter import Reporter

                reporter = Reporter()
                md = reporter.build_markdown(report_data)
                self._last_report = md
                self._last_report_data = report_data
                self._display_markdown(md)
                self._set_status(
                    f"✅ 分析完成 — {len(report_data.rebalance_suggestions)} 条建议",
                    "#34a853",
                )
            else:
                self._set_status("✅ 分析完成，但无报告数据返回", "#34a853")

            logger.info(
                "Full pipeline executed: suggestions=%s",
                len(getattr(optimizer_result, "suggestions", [])),
            )

        except Exception as e:
            logger.error("Pipeline error: %s", e, exc_info=True)
            self._set_status(f"❌ 分析出错: {e}", "#ea4335")
            self._display_markdown(f"# 错误\n\n运行全链路分析时出错：\n\n```\n{e}\n```")

        finally:
            self._optimize_btn.configure(state="normal")
            self._export_md_btn.configure(state="normal")
            self._export_pdf_btn.configure(state="normal")

    def _on_export_md(self) -> None:
        """导出 Markdown 报告到文件。"""
        if not self._last_report:
            self._set_status("⚠️ 还没有可导出的报告，请先运行「一键优化」", "#ea4335")
            return

        file_path = filedialog.asksaveasfilename(
            defaultextension=".md",
            filetypes=[("Markdown files", "*.md"), ("All files", "*.*")],
            title="导出 Markdown 报告",
        )
        if not file_path:
            return

        try:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(self._last_report)
            self._set_status(f"✅ 报告已导出: {os.path.basename(file_path)}", "#34a853")
            logger.info("Report exported as Markdown: %s", file_path)
        except Exception as e:
            logger.error("Export MD failed: %s", e)
            messagebox.showerror("导出失败", f"写入文件出错：\n{e}")

    def _on_export_pdf(self) -> None:
        """尝试导出 PDF 报告。降级策略：失败时提示安装 weasyprint。"""
        if not self._last_report or not self._last_report_data:
            self._set_status("⚠️ 还没有可导出的报告，请先运行「一键优化」", "#ea4335")
            return

        file_path = filedialog.asksaveasfilename(
            defaultextension=".pdf",
            filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")],
            title="导出 PDF 报告",
        )
        if not file_path:
            return

        self._set_status("⏳ 正在生成 PDF...", "#fbbc04")
        self._export_pdf_btn.configure(state="disabled")
        self.update_idletasks()

        try:
            from projects.command_center.engine.reporter import Reporter

            reporter = Reporter()
            # Temporarily save to the requested path
            output_dir = os.path.dirname(file_path)
            result_path = reporter.build_pdf(self._last_report_data, output_dir=output_dir)

            if result_path and os.path.exists(result_path):
                # 如果路径不同，移动文件
                if result_path != file_path and os.path.exists(result_path):
                    import shutil
                    shutil.move(result_path, file_path)

                self._set_status(f"✅ PDF 已导出: {os.path.basename(file_path)}", "#34a853")
                logger.info("Report exported as PDF: %s", file_path)
            else:
                self._set_status(
                    "⚠️ PDF 导出失败（weasyprint 可能未安装）\n"
                    "请执行: pip install weasyprint",
                    "#ea4335",
                )
                messagebox.showinfo(
                    "PDF 导出提示",
                    "weasyprint 未安装或安装有误。\n\n"
                    "请执行以下命令安装：\n"
                    "  pip install weasyprint\n\n"
                    "Markdown 报告已就绪，可正常导出。",
                )

        except Exception as e:
            logger.error("Export PDF failed: %s", e)
            self._set_status(f"⚠️ PDF 导出失败: {e}", "#ea4335")

        finally:
            self._export_pdf_btn.configure(state="normal")

    # ============================================================
    # 显示
    # ============================================================

    def _display_markdown(self, md: str) -> None:
        """在预览框中显示 Markdown。"""
        self._preview_text.configure(state="normal")
        self._preview_text.delete("1.0", "end")
        self._preview_text.insert("1.0", md)
        self._preview_text.configure(state="disabled")

    def _set_status(self, text: str, color: str = "#888888") -> None:
        """设置状态栏文本。"""
        self._status_label.configure(text=text, text_color=color)
        self.update_idletasks()

    def display_report(self, md: str, report_data: Any = None) -> None:
        """外部注入报告内容。

        Args:
            md: Markdown 文本
            report_data: 可选的 ReportData 对象（用于导出）
        """
        self._last_report = md
        self._last_report_data = report_data
        self._display_markdown(md)
        self._set_status("✅ 报告加载完成", "#34a853")