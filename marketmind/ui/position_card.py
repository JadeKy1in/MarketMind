"""Position status card display — green/yellow/red health indicators."""
from __future__ import annotations
from typing import Any
import customtkinter as ctk


class PositionCard(ctk.CTkFrame):
    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self.configure(fg_color=("gray95", "gray17"))

        self.ticker_label = ctk.CTkLabel(self, text="---", font=ctk.CTkFont(size=16, weight="bold"))
        self.ticker_label.pack(pady=(8, 2), padx=10, anchor="w")

        self.status_indicator = ctk.CTkFrame(self, width=20, height=20, corner_radius=10)
        self.status_indicator.pack(pady=(0, 5), padx=10, anchor="w")

        self._fields: dict[str, ctk.CTkLabel] = {}

    def set_position(self, data: dict[str, Any]) -> None:
        ticker = str(data.get("ticker", "---"))
        status = str(data.get("status", "yellow"))
        self.ticker_label.configure(text=ticker)

        colors = {"green": "#4caf50", "yellow": "#ff9800", "red": "#f44336"}
        self.status_indicator.configure(fg_color=colors.get(status, colors["yellow"]))

        for w in self.ticker_label.master.winfo_children():
            if isinstance(w, ctk.CTkFrame) and w != self.status_indicator:
                pass

        for key in ["entry", "current", "pnl_pct", "days_held", "thesis_valid", "recommendation"]:
            if key in data:
                self._set_field(key, str(data[key]))

    def _set_field(self, key: str, value: str) -> None:
        if key not in self._fields:
            frame = ctk.CTkFrame(self)
            frame.pack(fill="x", pady=1, padx=10)
            k_label = ctk.CTkLabel(frame, text=f"{key}:", font=ctk.CTkFont(size=11, weight="bold"), width=80, anchor="w")
            k_label.pack(side="left")
            v_label = ctk.CTkLabel(frame, text=value, font=ctk.CTkFont(size=11))
            v_label.pack(side="left", fill="x", expand=True)
            self._fields[key] = (frame, v_label)
        else:
            self._fields[key][1].configure(text=value)
