"""Shadow Panel — ranking dashboard showing all visible shadows sorted by rank."""
from __future__ import annotations
from typing import Any, Callable
import customtkinter as ctk


class ShadowPanel(ctk.CTkFrame):
    """Ranking dashboard panel with sortable table of shadow performance.

    Rows are color-coded by achievement tier:
      ELITE=gold, EXCELLENT=green, NORMAL=gray, WATCH=orange, ENDANGERED=red
    """

    TIER_COLORS = {
        "elite": "#DAA520",
        "excellent": "#2E8B57",
        "normal": "#808080",
        "watch": "#FF8C00",
        "endangered": "#DC143C",
    }

    def __init__(self, master, async_bridge, **kwargs):
        super().__init__(master, **kwargs)
        self._bridge = async_bridge
        self._rankings: list[dict] = []
        self._on_shadow_click: Callable[[str], None] | None = None

        # Header
        self.header = ctk.CTkLabel(
            self, text="Shadows",
            font=ctk.CTkFont(size=18, weight="bold"),
        )
        self.header.pack(pady=(10, 5), padx=10, anchor="w")

        # Stats bar
        stats_text = "0 active"
        self._stats_label = ctk.CTkLabel(
            self, text=stats_text,
            font=ctk.CTkFont(size=12), text_color="gray",
        )
        self._stats_label.pack(pady=(0, 5), padx=10, anchor="w")

        # Column headers in a frame
        col_frame = ctk.CTkFrame(self, fg_color="transparent")
        col_frame.pack(fill="x", padx=10, pady=(0, 2))

        col_headers = [
            ("#", 30), ("Shadow", 180), ("Tier", 100),
            ("Score", 70), ("Trend", 70),
        ]
        for text, width in col_headers:
            lbl = ctk.CTkLabel(
                col_frame, text=text, width=width,
                font=ctk.CTkFont(size=11, weight="bold"),
                anchor="w",
            )
            lbl.pack(side="left", padx=2)

        # Scrollable ranking table
        self.scroll = ctk.CTkScrollableFrame(self, height=350)
        self.scroll.pack(fill="both", expand=True, padx=10, pady=5)

        self._row_widgets: list[ctk.CTkFrame] = []

    def load_rankings(self, rankings: list[dict]) -> None:
        """Populate the ranking table from a list of shadow ranking dicts.

        Each dict must have: rank, shadow_id, display_name, tier,
        composite_score, deflated_score, percentile_rank, trend.
        """
        self._rankings = rankings

        # Update stats
        active_count = len(rankings)
        tier_counts = {}
        for r in rankings:
            t = r.get("tier", "normal")
            tier_counts[t] = tier_counts.get(t, 0) + 1
        stats_parts = [f"{active_count} active"]
        for tier in ["elite", "excellent", "normal", "watch", "endangered"]:
            if tier in tier_counts:
                stats_parts.append(f"{tier.title()}: {tier_counts[tier]}")
        self._stats_label.configure(text="  |  ".join(stats_parts))

        # Clear existing rows
        for row in self._row_widgets:
            row.destroy()
        self._row_widgets.clear()

        # Build rows
        for r in rankings:
            row_frame = ctk.CTkFrame(self.scroll, fg_color="transparent")
            row_frame.pack(fill="x", pady=1, padx=2)
            self._row_widgets.append(row_frame)

            columns = [
                (str(r.get("rank", "?")), 30),
                (r.get("display_name", r.get("shadow_id", "Unknown")), 180),
                (r.get("tier", "normal").upper(), 100),
                (f"{r.get('composite_score', 0):.2f}", 70),
                (self._format_trend(r.get("trend", 0)), 70),
            ]

            tier = r.get("tier", "normal")
            tier_color = self.TIER_COLORS.get(tier, "#808080")

            for idx, (text, width) in enumerate(columns):
                text_color = tier_color if idx == 2 else None
                lbl = ctk.CTkLabel(
                    row_frame, text=text, width=width, anchor="w",
                    font=ctk.CTkFont(size=12),
                    text_color=text_color if text_color else ("white", "black"),
                )
                lbl.pack(side="left", padx=2)

                # Make the row clickable — bind to all labels in the row
                sid = r.get("shadow_id", "")
                lbl.bind("<Button-1>", lambda e, s=sid: self._handle_row_click(s))

            # Also make the row frame itself clickable
            sid = r.get("shadow_id", "")
            row_frame.bind("<Button-1>", lambda e, s=sid: self._handle_row_click(s))

    def refresh(self) -> None:
        """Async load rankings via the bridge (placeholder for backend integration)."""
        async def _fetch():
            # TODO: wire to ranking engine
            return self._rankings if self._rankings else []

        def _on_done(result):
            if result:
                self.load_rankings(result)

        self._bridge.submit("shadow_rankings_refresh", _fetch(), _on_done)

    def set_on_click_callback(self, callback: Callable[[str], None]) -> None:
        """Register a callback to fire when a shadow row is clicked.

        The callback receives the shadow_id string.
        """
        self._on_shadow_click = callback

    def clear(self) -> None:
        """Remove all ranking data and clear the display."""
        self._rankings = []
        self._stats_label.configure(text="0 active")
        for row in self._row_widgets:
            row.destroy()
        self._row_widgets.clear()

    def _handle_row_click(self, shadow_id: str) -> None:
        """Internal click handler — delegates to registered callback."""
        if self._on_shadow_click and shadow_id:
            self._on_shadow_click(shadow_id)

    @staticmethod
    def _format_trend(trend: float) -> str:
        """Format trend as up/down arrow with change value."""
        if trend > 0:
            return f"↑ +{trend:.0f}" if trend == int(trend) else f"↑ +{trend:.1f}"
        elif trend < 0:
            return f"↓ {trend:.0f}" if trend == int(trend) else f"↓ {trend:.1f}"
        return "↔ 0"
