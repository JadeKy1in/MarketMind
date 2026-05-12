"""
chat_panel.py — Sprint 5: 右侧对话面板（集成附件处理）

新增功能:
  - 接收 IntakeBar 扩展的 (text, files) 回调
  - 附件在后台线程通过 OCRReader 异步解析
  - 图片路由到 Flash Vision API
"""

from __future__ import annotations
import logging
import os
import threading
import time
from typing import List, Optional
import customtkinter as ctk
from projects.command_center.gateway.task_queue import TaskQueue, TaskResult
from projects.command_center.intelligence.ocr_reader import read_files, build_vision_messages
from projects.command_center.ui.intake_bar import IntakeBar

logger = logging.getLogger(__name__)
_TAG_U = "msg_user"
_TAG_S = "msg_system"
_TAG_E = "msg_error"
_TAG_T = "msg_ts"
_POLL_MS = 100


class ChatPanel(ctk.CTkFrame):
    """右侧对话面板 + 情报入口 + 附件处理。"""

    def __init__(self, master, task_queue: Optional[TaskQueue] = None, **kwargs):
        super().__init__(master, **kwargs)
        self._tq = task_queue
        self._owned = False
        if self._tq is None:
            self._tq = TaskQueue.create_default(auto_start=True)
            self._owned = True
        if not self._tq.is_running:
            self._tq.start()
        self._last_tid: Optional[str] = None

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=0)

        self._disp = ctk.CTkTextbox(
            self, font=ctk.CTkFont(size=14), wrap="word", state="disabled"
        )
        self._disp.grid(row=0, column=0, padx=8, pady=(8, 4), sticky="nsew")
        self._disp.tag_config(_TAG_U, foreground="#1a73e8", justify="right",
            lmargin2=60)
        self._disp.tag_config(_TAG_S, foreground="#34a853", justify="left",
            lmargin1=10)
        self._disp.tag_config(_TAG_E, foreground="#ea4335", justify="left")
        self._disp.tag_config(_TAG_T, foreground="#888888", justify="center")

        self._ibar = IntakeBar(self, on_submit=self._on_submit)
        self._ibar.grid(row=1, column=0, padx=0, pady=0, sticky="ew")

        self._welcome()
        self._polling = True
        self._schedule_poll()
        logger.info("ChatPanel ready (poll=%dms)", _POLL_MS)

    @property
    def intake_bar(self) -> IntakeBar:
        return self._ibar

    @property
    def task_queue(self) -> TaskQueue:
        return self._tq

    def shutdown(self):
        self._polling = False
        if self._owned and self._tq:
            self._tq.shutdown()
        logger.info("ChatPanel shutdown")

    def _welcome(self, adapter_status: str = "检测中..."):
        self._welcome_text = (
            "SignalFoundry Terminal\n宏观投资决策终端\n\n"
            "欢迎使用！在下方输入框发送消息即可开始对话。\n"
            "支持附件: 图片(Flash Vision)、PDF、MD、TXT\n"
            f"当前模式: {adapter_status}\n\n"
        )
        self._disp.configure(state="normal")
        self._disp.insert("end", self._welcome_text, _TAG_S)
        self._disp.see("end")
        self._disp.configure(state="disabled")

    def set_mode_status(self, status: str) -> None:
        """Update the mode display. Called after adapter detection."""
        self._welcome_text = self._welcome_text.replace(
            "当前模式: 检测中...", f"当前模式: {status}"
        )
        self._disp.configure(state="normal")
        self._disp.delete("1.0", "end")
        self._disp.insert("end", self._welcome_text, _TAG_S)
        self._disp.configure(state="disabled")

    def update_adapter_status(self, pro_label: str, flash_label: str) -> None:
        """更新适配器状态显示（由 MainWindow 在启动后调用）。"""
        status = f"Pro: {pro_label} / Flash: {flash_label}"
        self._disp.configure(state="normal")
        ts = time.strftime("%H:%M:%S")
        self._disp.insert("end", f"\n[{ts}] 适配器状态\n", _TAG_T)
        self._disp.insert("end", f"{status}\n\n", _TAG_S)
        self._disp.see("end")
        self._disp.configure(state="disabled")

    def append_user_message(self, text: str):
        self._disp.configure(state="normal")
        ts = time.strftime("%H:%M:%S")
        self._disp.insert("end", f"\n[{ts}] 你\n", _TAG_T)
        self._disp.insert("end", f"{text}\n\n", _TAG_U)
        self._disp.see("end")
        self._disp.configure(state="disabled")

    def append_system_message(self, text: str, model: str = ""):
        self._disp.configure(state="normal")
        ts = time.strftime("%H:%M:%S")
        tag = f" [{model}]" if model else ""
        self._disp.insert("end", f"\n[{ts}] 助手{tag}\n", _TAG_T)
        self._disp.insert("end", f"{text}\n\n", _TAG_S)
        self._disp.see("end")
        self._disp.configure(state="disabled")

    def append_error_message(self, text: str):
        self._disp.configure(state="normal")
        ts = time.strftime("%H:%M:%S")
        self._disp.insert("end", f"\n[{ts}] 错误\n", _TAG_T)
        self._disp.insert("end", f"{text}\n\n", _TAG_E)
        self._disp.see("end")
        self._disp.configure(state="disabled")

    def _schedule_poll(self):
        if self._polling:
            self.after(_POLL_MS, self._poll)

    def _poll(self):
        if not self._polling or not self._tq:
            return
        try:
            for r in self._tq.drain_callbacks(10):
                if r.error:
                    self.append_error_message(f"模型错误: {r.error}")
                else:
                    self.append_system_message(r.output, model=r.model_used)
        except Exception as e:
            logger.error("poll err: %s", e)
        finally:
            self._schedule_poll()

    # ============================================================
    # 提交处理（支持附件）
    # ============================================================

    def _on_submit(self, text: str, files: List[str]):
        """从 IntakeBar 接收文本 + 附件。"""
        if not text.strip() and not files:
            return

        # 显示用户消息
        if text.strip():
            self.append_user_message(text)
        if files:
            names = ", ".join(os.path.basename(f) for f in files)
            self.append_user_message(f"[附件] {names}")

        self._ibar.disable()

        if files:
            # 有附件时：后台读取文件，然后提交
            threading.Thread(
                target=self._handle_attachment_task,
                args=(text, files),
                daemon=True,
            ).start()
        else:
            # 纯文本：直接提交到 TaskQueue
            try:
                tid = self._tq.submit_from_text(
                    text=text,
                    callback=lambda tid, res, err: (
                        self._ibar.enable() or self._ibar.focus()
                    ),
                )
                self._last_tid = tid
            except Exception as e:
                self.append_error_message(f"提交失败: {e}")
                self._ibar.enable()

    def _handle_attachment_task(self, text: str, files: List[str]):
        """后台线程：读取文件 → 提交到 TaskQueue。"""
        try:
            # 读取附件（I/O 操作在后台线程执行）
            files_content = read_files(files)
            messages = build_vision_messages(files_content, user_text=text)

            # 安全地回到主线程提交
            self.after(0, lambda: self._submit_messages(messages))
        except Exception as e:
            logger.error("Attachment processing failed: %s", e)
            self.after(0, lambda: self.append_error_message(f"附件处理失败: {e}"))
            self.after(0, lambda: self._ibar.enable())

    def _submit_messages(self, messages):
        """在主线程提交消息到 TaskQueue。"""
        try:
            tid = self._tq.submit(
                messages=messages,
                callback=lambda tid, res, err: (
                    self._ibar.enable() or self._ibar.focus()
                ),
            )
            self._last_tid = tid
        except Exception as e:
            self.append_error_message(f"提交失败: {e}")
            self._ibar.enable()