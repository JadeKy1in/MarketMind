"""
intake_bar.py — Sprint 5: 返回对话输入栏 (IntakeBar)

新增功能:
  - 附件按钮 [+]（零 Emoji）— 选择图片/PDF/MD/TXT 文件
  - 已选文件状态标签
  - 回调签名扩展: on_submit(text, files)

红线:
  - 零 Emoji: 使用纯文本按钮 [+] 或 [添加附件]
  - 文件 I/O 仅在点击按钮时在主线程进行（仅选择对话框）
  - 异步读取在 ChatPanel 层处理
"""

from __future__ import annotations

import logging
import os
from tkinter import filedialog
from typing import Callable, List, Optional

import customtkinter as ctk

logger = logging.getLogger(__name__)


class IntakeBar(ctk.CTkFrame):
    """对话输入栏——文本输入 + 附件选择 + 发送。"""

    def __init__(self, master,
                 on_submit: Optional[Callable[[str, List[str]], None]] = None,
                 placeholder: str = "输入消息、URL 或交易指令...",
                 **kwargs):
        super().__init__(master, **kwargs)
        self._on_submit = on_submit
        self._pending_files: List[str] = []

        self.grid_columnconfigure(0, weight=0)   # 附件按钮
        self.grid_columnconfigure(1, weight=1)   # 输入框
        self.grid_columnconfigure(2, weight=0)   # 发送按钮

        # 附件按钮
        self._attach_btn = ctk.CTkButton(
            self, text="+", width=36, height=40,
            font=ctk.CTkFont(size=18, weight="bold"),
            fg_color=("#cccccc", "#333333"),
            hover_color=("#aaaaaa", "#555555"),
            command=self._on_attach_click,
        )
        self._attach_btn.grid(row=0, column=0, padx=(12, 2), pady=10)

        # 输入框
        self._entry = ctk.CTkEntry(self, placeholder_text=placeholder,
            font=ctk.CTkFont(size=14), height=40)
        self._entry.grid(row=0, column=1, padx=2, pady=10, sticky="ew")
        self._entry.bind("<Return>", lambda e: self._do_submit())

        # 发送按钮
        self._send = ctk.CTkButton(self, text="发送",
            font=ctk.CTkFont(size=14, weight="bold"),
            width=80, height=40, command=self._do_submit)
        self._send.grid(row=0, column=2, padx=(2, 12), pady=10)

        # 文件标签（仅在有附件时显示）
        self._file_label = ctk.CTkLabel(
            self, text="", anchor="w",
            font=ctk.CTkFont(size=11),
            text_color=("#1a73e8", "#4fc3f7"),
        )

        logger.info("IntakeBar initialized (attachment enabled)")

    @property
    def entry(self) -> ctk.CTkEntry:
        return self._entry

    @property
    def send_button(self) -> ctk.CTkButton:
        return self._send

    @property
    def pending_files(self) -> List[str]:
        """当前待发送的文件路径列表（副本）。"""
        return list(self._pending_files)

    def set_on_submit(self, cb):
        self._on_submit = cb

    def clear(self):
        self._entry.delete(0, "end")
        self._pending_files.clear()
        self._update_file_label()

    def focus(self):
        self._entry.focus()

    def disable(self):
        self._entry.configure(state="disabled")
        self._send.configure(state="disabled")
        self._attach_btn.configure(state="disabled")

    def enable(self):
        self._entry.configure(state="normal")
        self._send.configure(state="normal")
        self._attach_btn.configure(state="normal")

    # ============================================================
    # 附件
    # ============================================================

    def _on_attach_click(self):
        """打开文件选择对话框，支持图片/PDF/MD/TXT。"""
        files = filedialog.askopenfilenames(
            title="选择附件",
            filetypes=[
                ("All Supported", "*.png *.jpg *.jpeg *.pdf *.md *.txt *.csv"),
                ("Images", "*.png *.jpg *.jpeg"),
                ("Documents", "*.pdf *.md *.txt"),
                ("Spreadsheets", "*.csv"),
            ],
        )
        if files:
            self._pending_files = list(files)
            self._update_file_label()
            logger.info("Attached %d files: %s", len(files),
                        [os.path.basename(f) for f in files])

    def _update_file_label(self):
        """更新文件状态标签。"""
        if self._pending_files:
            names = ", ".join(os.path.basename(f) for f in self._pending_files)
            self._file_label.configure(text=f"[附件] {names}")
            self._file_label.grid(
                row=1, column=0, columnspan=3,
                padx=16, pady=(0, 4), sticky="w",
            )
        else:
            self._file_label.grid_forget()

    # ============================================================
    # 提交
    # ============================================================

    def _do_submit(self):
        text = self._entry.get().strip()
        files = self._pending_files.copy()
        self._pending_files.clear()
        self._update_file_label()

        if not text and not files:
            return

        if self._on_submit:
            self._on_submit(text, files)

        self._entry.delete(0, "end")