"""Analysis signal dashboard — multi-section scrollable overview."""
from __future__ import annotations
from typing import Any
import customtkinter as ctk


class DashboardPanel(ctk.CTkFrame):
    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)

        self.header = ctk.CTkLabel(
            self, text="Signal Dashboard",
            font=ctk.CTkFont(size=18, weight="bold"),
        )
        self.header.pack(pady=(10, 5), padx=10, anchor="w")

        self.scroll = ctk.CTkScrollableFrame(self, height=400)
        self.scroll.pack(fill="both", expand=True, padx=10, pady=5)

        self._sections: dict[str, ctk.CTkFrame] = {}

    def add_section(self, title: str) -> ctk.CTkFrame:
        frame = ctk.CTkFrame(self.scroll)
        frame.pack(fill="x", pady=4, padx=2)

        label = ctk.CTkLabel(frame, text=title, font=ctk.CTkFont(size=14, weight="bold"))
        label.pack(pady=(5, 2), padx=8, anchor="w")

        content = ctk.CTkFrame(frame)
        content.pack(fill="x", padx=8, pady=(0, 5))

        self._sections[title] = content
        return content

    def set_section_text(self, section: str, text: str) -> None:
        if section not in self._sections:
            self.add_section(section)
        content = self._sections[section]
        for w in content.winfo_children():
            w.destroy()
        label = ctk.CTkLabel(content, text=text, justify="left", wraplength=500, font=ctk.CTkFont(size=12))
        label.pack(fill="x", pady=2)

    def clear(self) -> None:
        for section in self._sections.values():
            for w in section.winfo_children():
                w.destroy()
        self._sections.clear()
