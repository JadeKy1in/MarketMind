"""Mandatory 2-minute pause screen between Gate 2→3 — "走开。喝水。" """
from __future__ import annotations
from typing import Callable
import customtkinter as ctk


class PauseScreen(ctk.CTkFrame):
    def __init__(self, master, duration_seconds: int = 120, on_complete: Callable[[], None] | None = None, **kwargs):
        super().__init__(master, **kwargs)
        self._duration = duration_seconds
        self._remaining = duration_seconds
        self._on_complete = on_complete
        self._running = False

        self.message = ctk.CTkLabel(
            self, text="走开。喝水。",
            font=ctk.CTkFont(size=28, weight="bold"),
        )
        self.message.pack(pady=(40, 10))

        self.subtitle = ctk.CTkLabel(
            self, text="Step away from the screen. Get water.\nGate 3 will unlock after the pause.",
            font=ctk.CTkFont(size=14), text_color="gray",
        )
        self.subtitle.pack(pady=(0, 20))

        self.timer = ctk.CTkLabel(
            self, text=self._format_time(self._remaining),
            font=ctk.CTkFont(size=48, weight="bold"),
        )
        self.timer.pack(pady=20)

        self.skip_btn = ctk.CTkButton(
            self, text="Skip (not recommended)", command=self._skip,
            fg_color="transparent", text_color="gray",
        )
        self.skip_btn.pack(pady=(20, 10))

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._tick()

    def _tick(self) -> None:
        if not self._running:
            return
        self._remaining -= 1
        self.timer.configure(text=self._format_time(self._remaining))
        if self._remaining <= 0:
            self._running = False
            if self._on_complete:
                self._on_complete()
        else:
            self.after(1000, self._tick)

    def _skip(self) -> None:
        self._running = False
        if self._on_complete:
            self._on_complete()

    def reset(self) -> None:
        self._running = False
        self._remaining = self._duration
        self.timer.configure(text=self._format_time(self._remaining))

    @staticmethod
    def _format_time(seconds: int) -> str:
        m, s = divmod(max(seconds, 0), 60)
        return f"{m:02d}:{s:02d}"
