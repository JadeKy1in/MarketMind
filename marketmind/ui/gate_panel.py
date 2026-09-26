"""Gate 1/2/3 interaction panels with progressive disclosure."""
from __future__ import annotations
from typing import Any, Callable
import customtkinter as ctk


class GatePanel(ctk.CTkFrame):
    """Base gate panel with header, content area, and action button."""

    def __init__(self, master, gate_number: int, title: str, **kwargs):
        super().__init__(master, **kwargs)
        self.gate_number = gate_number
        self._on_action: Callable[[], None] | None = None

        self.header = ctk.CTkLabel(
            self, text=f"Gate {gate_number}: {title}",
            font=ctk.CTkFont(size=18, weight="bold"),
        )
        self.header.pack(pady=(10, 5), padx=10, anchor="w")

        self.content = ctk.CTkScrollableFrame(self, height=300)
        self.content.pack(fill="both", expand=True, padx=10, pady=5)

        self._status_label = ctk.CTkLabel(
            self, text="Pending...",
            font=ctk.CTkFont(size=12), text_color="gray",
        )
        self._status_label.pack(pady=(5, 5), padx=10)

        self.action_btn = ctk.CTkButton(
            self, text="Run Analysis", command=self._handle_action,
        )
        self.action_btn.pack(pady=(5, 10), padx=10)

    def set_action(self, callback: Callable[[], None]) -> None:
        self._on_action = callback

    def _handle_action(self) -> None:
        if self._on_action:
            self.action_btn.configure(state="disabled", text="Running...")
            self._on_action()

    def set_status(self, text: str, color: str = "gray") -> None:
        self._status_label.configure(text=text, text_color=color)

    def set_content_widgets(self, widgets: list[ctk.CTkBaseClass]) -> None:
        for w in self.content.winfo_children():
            w.destroy()
        for w in widgets:
            w.pack(fill="x", pady=2, padx=5)

    def unlock_action(self, text: str = "Proceed") -> None:
        self.action_btn.configure(state="normal", text=text)


class DirectionBriefCard(ctk.CTkFrame):
    """Compact 80-120 word direction brief for a single asset/sector."""

    def __init__(self, master, ticker: str, direction: str, brief: str, **kwargs):
        super().__init__(master, **kwargs)
        self.configure(fg_color=("gray90", "gray20"))

        self.header = ctk.CTkLabel(
            self, text=f"{ticker}  [{direction}]",
            font=ctk.CTkFont(size=14, weight="bold"),
        )
        self.header.pack(pady=(5, 2), padx=8, anchor="w")

        self.body = ctk.CTkLabel(
            self, text=brief, wraplength=400, justify="left",
            font=ctk.CTkFont(size=12),
        )
        self.body.pack(pady=(0, 5), padx=8, anchor="w")
