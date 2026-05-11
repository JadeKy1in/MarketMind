"""Shadow Status Card — individual shadow detail view shown on row click."""
from __future__ import annotations
from typing import Any
import customtkinter as ctk


class ShadowStatusCard(ctk.CTkFrame):
    """Individual shadow detail card with performance metrics and positions.

    Displayed when a row in the ShadowPanel ranking table is clicked.
    Shows tier badge, composite/deflated scores, component metrics,
    virtual capital, max drawdown, positions, and integrity score.
    """

    TIER_COLORS = {
        "elite": "#DAA520",
        "excellent": "#2E8B57",
        "normal": "#808080",
        "watch": "#FF8C00",
        "endangered": "#DC143C",
    }

    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self._shadow_data: dict | None = None
        self._widgets: list[ctk.CTkLabel] = []

        # Title line
        self._title_label = ctk.CTkLabel(
            self, text="Select a shadow to view details",
            font=ctk.CTkFont(size=16, weight="bold"),
        )
        self._title_label.pack(pady=(10, 5), padx=10, anchor="w")
        self._widgets.append(self._title_label)

        # Section container — built dynamically on display_shadow()
        self._sections_frame = ctk.CTkFrame(self, fg_color="transparent")
        self._sections_frame.pack(fill="both", expand=True, padx=10, pady=5)
        self._widgets.append(self._sections_frame)

    def display_shadow(self, shadow_data: dict) -> None:
        """Populate the status card with shadow performance data.

        Expected keys: shadow_id, display_name, shadow_type, tier, rank,
        total_shadows, percentile, composite_score, deflated_score, mppm,
        calmar, omega, win_rate, virtual_capital, capital_change_90d,
        max_drawdown, positions (list of str), integrity_score.
        """
        self._shadow_data = shadow_data

        # Clear previous content
        for w in self._sections_frame.winfo_children():
            w.destroy()
        self._widgets = [self._title_label, self._sections_frame]

        data = shadow_data
        display_name = data.get("display_name", data.get("shadow_id", "Unknown"))
        shadow_type = data.get("shadow_type", "unknown")
        tier = data.get("tier", "normal")
        rank = data.get("rank", "?")
        total = data.get("total_shadows", "?")
        percentile = data.get("percentile", 0)
        composite = data.get("composite_score", 0)
        deflated = data.get("deflated_score", 0)
        mppm = data.get("mppm", 0)
        calmar = data.get("calmar", 0)
        omega = data.get("omega", 0)
        wr = data.get("win_rate", 0)
        capital = data.get("virtual_capital", 0)
        cap_change = data.get("capital_change_90d", 0)
        mdd = data.get("max_drawdown", 0)
        positions = data.get("positions", [])
        integrity = data.get("integrity_score", 0)
        tier_color = self.TIER_COLORS.get(tier, "#808080")

        # ── Title row: display_name (type:domain) | TIER badge ──────────
        title_text = f"{display_name} ({shadow_type})"
        self._title_label.configure(text=title_text)

        tier_label = ctk.CTkLabel(
            self._sections_frame,
            text=f"TIER: {tier.upper()}",
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color=tier_color,
        )
        tier_label.pack(pady=(5, 2), padx=10, anchor="w")
        self._widgets.append(tier_label)

        # ── Rank / Percentile ────────────────────────────────────────────
        rank_text = f"Rank: {rank}/{total}  |  Percentile: p{int(percentile)}"
        rank_label = ctk.CTkLabel(
            self._sections_frame, text=rank_text,
            font=ctk.CTkFont(size=12), text_color="gray",
        )
        rank_label.pack(pady=(0, 5), padx=10, anchor="w")
        self._widgets.append(rank_label)

        # ── Separator ────────────────────────────────────────────────────
        sep1 = ctk.CTkFrame(self._sections_frame, height=1, fg_color="gray50")
        sep1.pack(fill="x", padx=10, pady=5)
        self._widgets.append(sep1)

        # ── Composite Score line ─────────────────────────────────────────
        score_text = f"Composite Score: {composite:.2f}  (deflated: {deflated:.2f})"
        score_label = ctk.CTkLabel(
            self._sections_frame, text=score_text,
            font=ctk.CTkFont(size=13, weight="bold"),
        )
        score_label.pack(pady=(2, 5), padx=10, anchor="w")
        self._widgets.append(score_label)

        # ── Component metrics row ────────────────────────────────────────
        metrics_text = (
            f"MPPM: {mppm:.2f}  |  Calmar: {calmar:.2f}  "
            f"|  Omega: {omega:.1f}  |  WR: {wr:.0%}"
        )
        metrics_label = ctk.CTkLabel(
            self._sections_frame, text=metrics_text,
            font=ctk.CTkFont(size=12),
        )
        metrics_label.pack(pady=(0, 5), padx=10, anchor="w")
        self._widgets.append(metrics_label)

        # ── Virtual Capital ──────────────────────────────────────────────
        cap_direction = "↑" if cap_change >= 0 else "↓"
        cap_text = f"Virtual Capital: ${capital:,.0f}  ({cap_direction} {abs(cap_change):.1f}% 90d)"
        cap_label = ctk.CTkLabel(
            self._sections_frame, text=cap_text,
            font=ctk.CTkFont(size=12),
        )
        cap_label.pack(pady=(0, 2), padx=10, anchor="w")
        self._widgets.append(cap_label)

        # ── Max Drawdown ─────────────────────────────────────────────────
        mdd_text = f"Max Drawdown: {mdd:.1f}%"
        mdd_label = ctk.CTkLabel(
            self._sections_frame, text=mdd_text,
            font=ctk.CTkFont(size=12),
        )
        mdd_label.pack(pady=(0, 5), padx=10, anchor="w")
        self._widgets.append(mdd_label)

        # ── Positions ────────────────────────────────────────────────────
        pos_text = f"Positions: {', '.join(positions)}" if positions else "Positions: (none)"
        pos_label = ctk.CTkLabel(
            self._sections_frame, text=pos_text,
            font=ctk.CTkFont(size=12), wraplength=500,
        )
        pos_label.pack(pady=(0, 5), padx=10, anchor="w")
        self._widgets.append(pos_label)

        # ── Separator ────────────────────────────────────────────────────
        sep2 = ctk.CTkFrame(self._sections_frame, height=1, fg_color="gray50")
        sep2.pack(fill="x", padx=10, pady=2)
        self._widgets.append(sep2)

        # ── Integrity Score ──────────────────────────────────────────────
        integrity_text = f"Integrity Score: {integrity}/100"
        integrity_color = "green" if integrity >= 80 else ("orange" if integrity >= 60 else "red")
        integrity_label = ctk.CTkLabel(
            self._sections_frame, text=integrity_text,
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=integrity_color,
        )
        integrity_label.pack(pady=(2, 10), padx=10, anchor="w")
        self._widgets.append(integrity_label)

    def clear(self) -> None:
        """Reset the card to its empty/placeholder state."""
        self._shadow_data = None
        self._title_label.configure(text="Select a shadow to view details")
        for w in self._sections_frame.winfo_children():
            w.destroy()

    @staticmethod
    def _get_tier_color(tier: str) -> str:
        """Map achievement tier string to display color name."""
        return ShadowStatusCard.TIER_COLORS.get(tier, "gray")
