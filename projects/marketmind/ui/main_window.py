"""Main MarketMind GUI — multi-panel layout with sidebar navigation and 3-gate flow."""
from __future__ import annotations
from typing import Any
import customtkinter as ctk

from projects.marketmind.ui.async_bridge import AsyncBridge
from projects.marketmind.ui.gate_panel import GatePanel, DirectionBriefCard
from projects.marketmind.ui.dashboard_panel import DashboardPanel
from projects.marketmind.ui.decision_card import DecisionCard
from projects.marketmind.ui.position_card import PositionCard
from projects.marketmind.ui.pause_screen import PauseScreen
from projects.marketmind.ui.progress import ProgressTracker
from projects.marketmind.ui.shadow_panel import ShadowPanel
from projects.marketmind.ui.shadow_status_card import ShadowStatusCard


class MainWindow(ctk.CTk):
    def __init__(self, config, **kwargs):
        super().__init__(**kwargs)
        self.config = config
        self.title("MarketMind — AI Investment Analysis Workstation")
        self.geometry("1200x800")
        ctk.set_appearance_mode("system")

        self.bridge = AsyncBridge(self)
        self.bridge.start()

        self._current_gate = 1
        self._session_data: dict[str, Any] = {}
        self._build_ui()

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self) -> None:
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # Sidebar
        self.sidebar = ctk.CTkFrame(self, width=180, corner_radius=0)
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        self.sidebar.grid_propagate(False)

        ctk.CTkLabel(self.sidebar, text="MarketMind", font=ctk.CTkFont(size=16, weight="bold")).pack(pady=(15, 10))

        nav_buttons = [
            ("Gate 1: Direction", self._show_gate1),
            ("Gate 2: Signal", self._show_gate2),
            ("Gate 3: Decision", self._show_gate3),
            ("Dashboard", self._show_dashboard),
            ("Positions", self._show_positions),
            ("Shadows", self._show_shadows),
        ]
        self._nav_buttons: dict[str, ctk.CTkButton] = {}
        for label, cmd in nav_buttons:
            btn = ctk.CTkButton(self.sidebar, text=label, command=cmd, fg_color="transparent")
            btn.pack(fill="x", padx=10, pady=2)
            self._nav_buttons[label] = btn

        # Content area
        self.content = ctk.CTkFrame(self)
        self.content.grid(row=0, column=1, sticky="nsew", padx=5, pady=5)
        self.content.grid_columnconfigure(0, weight=1)
        self.content.grid_rowconfigure(0, weight=1)

        # Progress bar at bottom
        self.progress_frame = ctk.CTkFrame(self)
        self.progress_frame.grid(row=1, column=0, columnspan=2, sticky="ew", padx=5, pady=5)

        self.progress_bar = ctk.CTkProgressBar(self.progress_frame, width=800)
        self.progress_bar.pack(side="left", fill="x", expand=True, padx=10, pady=5)
        self.progress_bar.set(0)

        self.status_label = ctk.CTkLabel(self.progress_frame, text="Ready", font=ctk.CTkFont(size=11), text_color="gray")
        self.status_label.pack(side="right", padx=10)

        # Initialize all panels
        self._panels: dict[str, ctk.CTkFrame] = {}
        self._init_panels()
        self._show_gate1()

    def _init_panels(self) -> None:
        # Gate 1: Direction Selection
        self.gate1 = GatePanel(self.content, 1, "Direction Briefs")
        self.gate1.set_action(self._run_gate1)
        self._panels["gate1"] = self.gate1

        # Gate 2: Signal Resonance + Red Team
        self.gate2 = GatePanel(self.content, 2, "Signal Resonance")
        self.gate2.set_action(self._run_gate2)
        self._panels["gate2"] = self.gate2

        # Gate 3: Decision Cards
        self.gate3 = GatePanel(self.content, 3, "Decision")
        self.gate3.set_action(self._run_gate3)
        self._panels["gate3"] = self.gate3

        # Pause screen (overlay)
        self.pause = PauseScreen(
            self.content, duration_seconds=120,
            on_complete=self._on_pause_complete,
        )
        self._panels["pause"] = self.pause

        # Dashboard
        self.dashboard = DashboardPanel(self.content)
        self._panels["dashboard"] = self.dashboard

        # Position cards container
        self.positions_frame = ctk.CTkScrollableFrame(self.content)
        self._panels["positions"] = self.positions_frame

        # Shadow ranking panel
        self.shadow_panel = ShadowPanel(self.content, self.bridge)
        self.shadow_panel.set_on_click_callback(self._show_shadow_status)
        self._panels["shadows"] = self.shadow_panel

        # Shadow status card (shown on row click)
        self.shadow_status_card = ShadowStatusCard(self.content)
        self._panels["shadow_status"] = self.shadow_status_card

        # Decision cards display
        self.decision_frame = ctk.CTkFrame(self.content)
        self.decision_frame.grid_columnconfigure((0, 1), weight=1)
        self._panels["decisions"] = self.decision_frame

    def _hide_all(self) -> None:
        for p in self._panels.values():
            p.grid_remove()

    def _show_panel(self, name: str) -> None:
        self._hide_all()
        panel = self._panels.get(name)
        if panel:
            panel.grid(row=0, column=0, sticky="nsew")

    def _show_gate1(self) -> None: self._show_panel("gate1")
    def _show_gate2(self) -> None: self._show_panel("gate2")
    def _show_gate3(self) -> None: self._show_panel("gate3")
    def _show_dashboard(self) -> None: self._show_panel("dashboard")
    def _show_positions(self) -> None: self._show_panel("positions")
    def _show_shadows(self) -> None:
        self._show_panel("shadows")
        # Auto-refresh rankings when panel is shown
        self.shadow_panel.refresh()

    def _show_shadow_status(self, shadow_id: str) -> None:
        """Show the status card for a shadow clicked in the ranking panel.
        Displays card below or beside the ranking panel.
        """
        self._show_panel("shadow_status")
        # Load shadow detail data via async bridge
        async def _fetch():
            # TODO: wire to shadow agent's receive_status_card()
            # For now, show placeholder with the shadow_id
            return {
                "shadow_id": shadow_id,
                "display_name": shadow_id,
                "shadow_type": "unknown",
                "tier": "normal",
                "rank": "?",
                "total_shadows": "?",
                "percentile": 0,
                "composite_score": 0,
                "deflated_score": 0,
                "mppm": 0,
                "calmar": 0,
                "omega": 0,
                "win_rate": 0,
                "virtual_capital": 0,
                "capital_change_90d": 0,
                "max_drawdown": 0,
                "positions": [],
                "integrity_score": 0,
            }

        def _on_done(result):
            self.shadow_status_card.display_shadow(result)

        self.bridge.submit(f"shadow_status_{shadow_id}", _fetch(), _on_done)

    # Pipeline stages
    def _run_gate1(self) -> None:
        self.gate1.set_status("Running direction analysis...", "orange")
        self._set_progress(0.15, "Gate 1: Direction analysis")

        async def _pipeline():
            from projects.marketmind.gateway.async_client import init_gateway, chat_pro
            init_gateway(self.config.deepseek_api_key, self.config.deepseek_base_url)

            # TODO: wire full pipeline — Scout → Flash → Layer1 → Gate 1 briefs
            # For now, produce placeholder briefs to demonstrate UI flow
            briefs = [
                ("Tech/Growth", "risk_on", "Tech earnings momentum with AI capex expansion driving semiconductor demand."),
                ("Gold/PM", "risk_on", "Real rate divergence and central bank buying support gold above $2,400."),
            ]
            return briefs

        def _on_done(result):
            widgets = []
            for ticker, direction, brief in result:
                widgets.append(DirectionBriefCard(self.gate1.content, ticker, direction, brief))
            self.gate1.set_content_widgets(widgets)
            self.gate1.set_status("Direction briefs ready. 2 directions selected.", "green")
            self.gate1.unlock_action("Lock Selection & Proceed to Gate 2")
            self.gate1.set_action(self._on_gate1_confirmed)
            self._set_progress(0.30, "Gate 1: Complete")
            self._session_data["gate1_briefs"] = result

        self.bridge.submit("gate1", _pipeline(), _on_done)

    def _on_gate1_confirmed(self) -> None:
        self._session_data["gate1_confirmed"] = True
        self._current_gate = 2
        self._show_gate2()

    def _run_gate2(self) -> None:
        self.gate2.set_status("Running signal resonance + Red Team challenge...", "orange")
        self._set_progress(0.40, "Gate 2: Signal resonance")

        async def _pipeline():
            # TODO: wire Layer 1-2-3 + Red Team + Resonance
            await __import__("asyncio").sleep(0.5)
            return {
                "resonance_signal": "strong",
                "dimensions": 3,
                "pbo": 0.04,
                "red_team_objections": 1,
            }

        def _on_done(result):
            self._session_data["gate2_result"] = result
            self.gate2.set_status(
                f"Signal: {result['resonance_signal']} | {result['dimensions']}/4 dims | PBO: {result['pbo']:.1%}",
                "green",
            )
            self._set_progress(0.55, "Gate 2: Complete — Pause required")
            self._show_pause()

        self.bridge.submit("gate2", _pipeline(), _on_done)

    def _show_pause(self) -> None:
        self._show_panel("pause")
        self.pause.reset()
        self.pause.start()

    def _on_pause_complete(self) -> None:
        self._session_data["pause_completed"] = True
        self._current_gate = 3
        self._show_gate3()
        self.gate3.set_status("Pause complete. Ready for final decision.", "green")
        self.gate3.unlock_action("Generate Decision Cards")

    def _run_gate3(self) -> None:
        self.gate3.set_status("Generating decision cards...", "orange")
        self._set_progress(0.70, "Gate 3: Decision synthesis")

        async def _pipeline():
            await __import__("asyncio").sleep(0.5)
            return {
                "trade": {"ticker": "AAPL", "direction": "long", "confidence": 0.75,
                           "resonance_signal": "strong", "entry_zone": "185-190",
                           "stop_loss": "178", "target": "210", "max_hold_days": 30,
                           "thesis": "AI capex cycle + services margin expansion"},
                "no_trade": {"ticker": "---", "direction": "cash", "confidence": 0.60,
                              "resonance_signal": "none", "entry_zone": "---",
                              "stop_loss": "---", "target": "---", "max_hold_days": 0,
                              "thesis": "Cash preserves optionality. No signal meets >=3/4 dim threshold."},
            }

        def _on_done(result):
            for w in self.decision_frame.winfo_children():
                w.destroy()
            trade_card = DecisionCard(self.decision_frame, card_type="trade")
            trade_card.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)
            trade_card.set_decision_data(result["trade"])

            no_trade_card = DecisionCard(self.decision_frame, card_type="no_trade")
            no_trade_card.grid(row=0, column=1, sticky="nsew", padx=5, pady=5)
            no_trade_card.set_decision_data(result["no_trade"])

            self._show_panel("decisions")
            self.gate3.set_status("Decision cards ready. Review and confirm.", "green")
            self.gate3.unlock_action("Confirm & Archive Session")
            self.gate3.set_action(self._on_session_complete)
            self._set_progress(1.0, "Complete")

        self.bridge.submit("gate3", _pipeline(), _on_done)

    def _on_session_complete(self) -> None:
        self._session_data["session_complete"] = True
        self._show_dashboard()
        self.dashboard.add_section("Session Complete")
        self.dashboard.set_section_text("Session Complete", "All 3 gates passed. Session archived.")
        self.status_label.configure(text="Session complete", text_color="green")

    def _set_progress(self, fraction: float, status: str) -> None:
        self.progress_bar.set(fraction)
        self.status_label.configure(text=status)

    def _on_close(self) -> None:
        self.bridge.stop()
        self.destroy()
