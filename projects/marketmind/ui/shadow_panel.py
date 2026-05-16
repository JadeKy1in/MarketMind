"""Shadow Panel — ranking dashboard showing all visible shadows sorted by rank."""
from __future__ import annotations
from typing import Any, Callable
import customtkinter as ctk

from marketmind.ui.shadow_charts import RankingTrendChart, DiscountRateChart


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

    def __init__(self, master, async_bridge, state_db=None, **kwargs):
        super().__init__(master, **kwargs)
        self._bridge = async_bridge
        self._state_db = state_db
        self._rankings: list[dict] = []
        self._on_shadow_click: Callable[[str], None] | None = None
        self._selected_shadow_id: str | None = None

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
        self.scroll = ctk.CTkScrollableFrame(self, height=250)
        self.scroll.pack(fill="x", padx=10, pady=5)

        self._row_widgets: list[ctk.CTkFrame] = []

        # Chart area
        self._chart_container = ctk.CTkFrame(self, fg_color="transparent")
        self._chart_container.pack(fill="both", expand=True, padx=10, pady=5)

        self._ranking_chart = RankingTrendChart(self._chart_container)
        self._ranking_chart.pack(fill="both", expand=True, pady=(0, 5))

        self._discount_chart = DiscountRateChart(self._chart_container)
        self._discount_chart.pack(fill="both", expand=True)

    def load_rankings(self, rankings: list[dict]) -> None:
        """Populate the ranking table from a list of shadow ranking dicts."""
        self._rankings = rankings

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

        for row in self._row_widgets:
            row.destroy()
        self._row_widgets.clear()

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

                sid = r.get("shadow_id", "")
                lbl.bind("<Button-1>", lambda e, s=sid: self._handle_row_click(s))

            sid = r.get("shadow_id", "")
            row_frame.bind("<Button-1>", lambda e, s=sid: self._handle_row_click(s))

        # Auto-load first shadow's charts
        if rankings and not self._selected_shadow_id:
            first_id = rankings[0].get("shadow_id", "")
            if first_id:
                self._load_charts_for_shadow(first_id)

    def _load_charts_for_shadow(self, shadow_id: str) -> None:
        """Load ranking trend + discount rate chart data for a shadow."""
        self._selected_shadow_id = shadow_id
        if self._state_db is None:
            return
        try:
            snapshots = self._state_db.get_snapshot_history(shadow_id, days=90)
            self._ranking_chart.clear()
            self._ranking_chart.load_data(shadow_id, snapshots)
            self._discount_chart.clear()
            self._discount_chart.load_data(snapshots)
        except Exception:
            pass  # Charts are best-effort, don't crash the panel

    def refresh(self) -> None:
        """Async load rankings via the bridge."""
        async def _fetch():
            return self._rankings if self._rankings else []

        def _on_done(result):
            if result:
                self.load_rankings(result)

        self._bridge.submit("shadow_rankings_refresh", _fetch(), _on_done)

    def set_on_click_callback(self, callback: Callable[[str], None]) -> None:
        self._on_shadow_click = callback

    def clear(self) -> None:
        self._rankings = []
        self._stats_label.configure(text="0 active")
        for row in self._row_widgets:
            row.destroy()
        self._row_widgets.clear()
        self._ranking_chart.clear()
        self._discount_chart.clear()

    def _handle_row_click(self, shadow_id: str) -> None:
        self._load_charts_for_shadow(shadow_id)
        if self._on_shadow_click and shadow_id:
            self._on_shadow_click(shadow_id)

    @staticmethod
    def _format_trend(trend: float) -> str:
        if trend > 0:
            return f"↑ +{trend:.0f}" if trend == int(trend) else f"↑ +{trend:.1f}"
        elif trend < 0:
            return f"↓ {trend:.0f}" if trend == int(trend) else f"↓ {trend:.1f}"
        return "↔ 0"
