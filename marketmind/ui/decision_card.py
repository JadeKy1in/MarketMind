"""Structured decision card display — trade and no-trade cards side by side."""
from __future__ import annotations
from typing import Any
import customtkinter as ctk


class DecisionCard(ctk.CTkFrame):
    def __init__(self, master, card_type: str = "trade", **kwargs):
        super().__init__(master, **kwargs)
        self.card_type = card_type
        colors = {"trade": ("#e8f5e9", "#1b5e20"), "no_trade": ("#fce4ec", "#b71c1c")}
        self._fg = colors.get(card_type, ("gray90", "gray20"))

        self.configure(fg_color=self._fg)

        self.header = ctk.CTkLabel(
            self, text="TRADE CARD" if card_type == "trade" else "NO-TRADE CARD",
            font=ctk.CTkFont(size=16, weight="bold"),
        )
        self.header.pack(pady=(8, 4), padx=10, anchor="w")

        self.body = ctk.CTkScrollableFrame(self, height=200)
        self.body.pack(fill="both", expand=True, padx=10, pady=5)

        self._fields: dict[str, ctk.CTkLabel] = {}

    def set_field(self, key: str, value: str) -> None:
        if key not in self._fields:
            frame = ctk.CTkFrame(self.body)
            frame.pack(fill="x", pady=1)
            k_label = ctk.CTkLabel(frame, text=f"{key}:", font=ctk.CTkFont(size=12, weight="bold"), width=120, anchor="w")
            k_label.pack(side="left", padx=(0, 5))
            v_label = ctk.CTkLabel(frame, text=value, font=ctk.CTkFont(size=12), justify="left", wraplength=300)
            v_label.pack(side="left", fill="x", expand=True)
            self._fields[key] = v_label
        else:
            self._fields[key].configure(text=value)

    def set_decision_data(self, data: dict[str, Any]) -> None:
        for w in self.body.winfo_children():
            w.destroy()
        self._fields.clear()
        for key in ["ticker", "direction", "confidence", "resonance_signal", "entry_zone", "stop_loss", "target", "max_hold_days"]:
            if key in data:
                self.set_field(key, str(data[key]))
        if "thesis" in data:
            thesis = data["thesis"]
            self.set_field("thesis", thesis[:150] + "..." if len(str(thesis)) > 150 else str(thesis))
