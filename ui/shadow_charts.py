"""Shadow performance charts — ranking trend and discount rate evolution.

Lightweight Canvas-based charting — no matplotlib dependency.
"""
from __future__ import annotations
from datetime import datetime
import customtkinter as ctk


class RankingTrendChart(ctk.CTkFrame):
    """Line chart of composite_score over time for selected shadows."""

    COLORS = ["#DAA520", "#2E8B57", "#4682B4", "#FF8C00", "#DC143C",
              "#8B4513", "#6A5ACD", "#20B2AA", "#FF69B4", "#708090"]

    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self._series: dict[str, list[tuple[str, float]]] = {}
        self._canvas = None
        self._legend_frame = None
        self._title_label = ctk.CTkLabel(
            self, text="Ranking Trend", font=ctk.CTkFont(size=13, weight="bold"))
        self._title_label.pack(pady=(5, 0), padx=10, anchor="w")

    def _ensure_canvas(self):
        if self._canvas is None:
            self._canvas = ctk.CTkCanvas(self, height=200, bg="#2B2B2B", highlightthickness=0)
            self._canvas.pack(fill="both", expand=True, padx=10, pady=5)
            self._legend_frame = ctk.CTkFrame(self, fg_color="transparent")
            self._legend_frame.pack(fill="x", padx=10, pady=(0, 5))

    def load_data(self, shadow_id: str, snapshots: list) -> None:
        """Load snapshot history for a shadow and add to chart."""
        if not snapshots:
            return
        points = []
        for s in reversed(snapshots):  # oldest first for chart
            date = getattr(s, 'date', '')
            score = getattr(s, 'composite_score', None)
            if date and score is not None:
                points.append((date, score))
        if points:
            self._series[shadow_id] = points
        self.redraw()

    def clear(self) -> None:
        self._series.clear()
        if self._canvas is not None:
            self._canvas.delete("all")
        if self._legend_frame is not None:
            for w in self._legend_frame.winfo_children():
                w.destroy()

    def redraw(self) -> None:
        self._ensure_canvas()
        canvas = self._canvas
        canvas.delete("all")
        if not self._series:
            canvas.create_text(200, 100, text="No data", fill="gray", font=("", 11))
            return

        w = canvas.winfo_width() or 400
        h = canvas.winfo_height() or 200
        margin = {"left": 45, "right": 15, "top": 15, "bottom": 30}

        # Collect all dates and values
        all_dates = set()
        all_vals = []
        for pts in self._series.values():
            for d, v in pts:
                all_dates.add(d)
                all_vals.append(v)
        if not all_vals:
            return
        dates_sorted = sorted(all_dates)
        vmin, vmax = min(all_vals), max(all_vals)
        vrange = vmax - vmin or 0.01

        plot_w = w - margin["left"] - margin["right"]
        plot_h = h - margin["top"] - margin["bottom"]

        def _x(date_str):
            i = dates_sorted.index(date_str) if date_str in dates_sorted else 0
            n = len(dates_sorted) - 1 or 1
            return margin["left"] + (i / n) * plot_w

        def _y(val):
            return margin["top"] + plot_h - ((val - vmin) / vrange) * plot_h

        # Grid lines
        for i in range(5):
            y = margin["top"] + (i / 4) * plot_h
            canvas.create_line(margin["left"], y, w - margin["right"], y,
                               fill="#444444", dash=(2, 4))
            val = vmin + (1 - i / 4) * vrange
            canvas.create_text(margin["left"] - 5, y, text=f"{val:.2f}",
                               fill="gray", anchor="e", font=("", 8))

        # X-axis labels (first + every Nth date)
        step = max(1, len(dates_sorted) // 6)
        for i, d in enumerate(dates_sorted):
            if i % step == 0:
                x = _x(d)
                label = d[-5:]  # MM-DD
                canvas.create_text(x, h - margin["bottom"] + 12, text=label,
                                   fill="gray", font=("", 7), angle=45)

        # Plot each series
        color_idx = 0
        for sid, pts in self._series.items():
            color = self.COLORS[color_idx % len(self.COLORS)]
            color_idx += 1
            pts_sorted = sorted(pts, key=lambda p: p[0])
            coords = []
            for d, v in pts_sorted:
                coords.extend([_x(d), _y(v)])
            if len(coords) >= 4:
                canvas.create_line(*coords, fill=color, width=2, smooth=True)

            # Last point marker
            if pts_sorted:
                lx, ly = _x(pts_sorted[-1][0]), _y(pts_sorted[-1][1])
                canvas.create_oval(lx - 3, ly - 3, lx + 3, ly + 3,
                                   fill=color, outline="")

        # Update legend
        for w in self._legend_frame.winfo_children():
            w.destroy()
        color_idx = 0
        for sid in self._series:
            color = self.COLORS[color_idx % len(self.COLORS)]
            color_idx += 1
            name = sid.split(":")[-1][:12] if ":" in sid else sid[:12]
            item = ctk.CTkFrame(self._legend_frame, fg_color="transparent")
            item.pack(side="left", padx=5)
            dot = ctk.CTkLabel(item, text="●", text_color=color, font=("", 10))
            dot.pack(side="left")
            lbl = ctk.CTkLabel(item, text=name, font=("", 9))
            lbl.pack(side="left")


class DiscountRateChart(ctk.CTkFrame):
    """Line chart of discount_rate over time for a single shadow."""

    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self._data: list[tuple[str, float]] = []
        self._canvas = None
        self._title_label = ctk.CTkLabel(
            self, text="Discount Rate Evolution", font=ctk.CTkFont(size=13, weight="bold"))
        self._title_label.pack(pady=(5, 0), padx=10, anchor="w")

    def _ensure_canvas(self):
        if self._canvas is None:
            self._canvas = ctk.CTkCanvas(self, height=150, bg="#2B2B2B", highlightthickness=0)
            self._canvas.pack(fill="both", expand=True, padx=10, pady=5)

    def load_data(self, snapshots: list) -> None:
        """Extract discount_rate from DailySnapshot objects."""
        points = []
        for s in reversed(snapshots):
            date = getattr(s, 'date', '')
            rate = getattr(s, 'discount_rate', None)
            if date and rate is not None:
                points.append((date, rate))
        self._data = points
        self.redraw()

    def clear(self) -> None:
        self._data.clear()
        if self._canvas is not None:
            self._canvas.delete("all")

    def redraw(self) -> None:
        self._ensure_canvas()
        canvas = self._canvas
        canvas.delete("all")
        if not self._data:
            canvas.create_text(200, 75, text="No discount data", fill="gray", font=("", 11))
            return

        w = canvas.winfo_width() or 400
        h = canvas.winfo_height() or 150
        margin = {"left": 45, "right": 15, "top": 10, "bottom": 25}

        # Fixed Y range: 0.05-0.20 (discount floor to ceiling)
        vmin, vmax = 0.03, 0.22

        plot_w = w - margin["left"] - margin["right"]
        plot_h = h - margin["top"] - margin["bottom"]

        def _y(val):
            return margin["top"] + plot_h - ((val - vmin) / (vmax - vmin)) * plot_h

        # Reference lines
        for rate, label, dash_color in [
            (0.20, "20% (default)", "#666666"),
            (0.15, "15% (live-ready)", "#FF8C00"),
            (0.05, "5% (floor)", "#2E8B57"),
        ]:
            y = _y(rate)
            canvas.create_line(margin["left"], y, w - margin["right"], y,
                               fill=dash_color, dash=(4, 4))
            canvas.create_text(w - margin["right"] + 2, y, text=label,
                               fill=dash_color, anchor="w", font=("", 7))

        # Y-axis labels
        for rate in [0.05, 0.10, 0.15, 0.20]:
            y = _y(rate)
            canvas.create_text(margin["left"] - 5, y, text=f"{rate:.0%}",
                               fill="gray", anchor="e", font=("", 8))

        # Plot data
        pts_sorted = sorted(self._data, key=lambda p: p[0])
        coords = []
        for d, v in pts_sorted:
            i = pts_sorted.index((d, v))
            x = margin["left"] + (i / max(len(pts_sorted) - 1, 1)) * plot_w
            coords.extend([x, _y(v)])
        if len(coords) >= 4:
            canvas.create_line(*coords, fill="#4682B4", width=2, smooth=True)

        # Current rate label
        if pts_sorted:
            last = pts_sorted[-1]
            i_last = len(pts_sorted) - 1
            lx = margin["left"] + (i_last / max(len(pts_sorted) - 1, 1)) * plot_w
            ly = _y(last[1])
            canvas.create_text(lx, ly - 10, text=f"{last[1]:.1%}",
                               fill="#4682B4", font=("", 9, "bold"))
