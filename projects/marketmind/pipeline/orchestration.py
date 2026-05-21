"""Pipeline orchestration — run_daily, run_full, run_gate1_mode, run_interactive.

Thin coordinator: calls pre_gate1 and post_gate1 modules, wires Gate 1→2→3 in run_full().
"""
from __future__ import annotations
from dataclasses import asdict
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from marketmind.config.settings import MarketMindConfig

from marketmind.gateway.async_client import init_gateway
from marketmind.pipeline.pre_gate1 import run_pre_gate1
from marketmind.pipeline.post_gate1 import run_post_gate1


# ── CLI IO handlers for Gate 1 ─────────────────────────────────────────────────

async def _cli_input_handler(prompt: str) -> str:
    """Async wrapper around stdin for Gate 1 interaction."""
    print(prompt, end="")
    return input()


async def _cli_status_handler(message: str) -> None:
    """Async wrapper around print for Gate 1 status display."""
    print(message)


# ── Run modes ──────────────────────────────────────────────────────────────────

async def run_daily(config: "MarketMindConfig", mock: bool = False, verbose: bool = False,
                    shadow_count: int | None = None,
                    inject_result=None) -> int:
    """Execute full daily analysis pipeline (stages 0-10, no Gate 1)."""
    state = await run_pre_gate1(config, mock, verbose, shadow_count,
                                inject_result=inject_result)
    return await run_post_gate1(config, state, mock, verbose)


async def run_full(config: "MarketMindConfig", mock: bool = False, verbose: bool = False,
                   shadow_count: int | None = None, session_mode: str = "full") -> int:
    """Complete pipeline with Gate 1→2→3 user interaction.

    Flow: Stage 0-3 → Gate 1 → Stage 4-10 → Gate 2 → Gate 3 → Archive
    """
    from marketmind.storage.session import SessionManager, SessionState, GateCheckpoint

    state = await run_pre_gate1(config, mock, verbose, shadow_count)

    gate1_session = None

    # ── Gate 1: Human direction confirmation ──────────────────────────────
    hypotheses = state["hypotheses"]
    if hypotheses:
        from marketmind.pipeline.gate1_interaction import run_gate1

        gate1_id = f"gate1-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M')}"
        print("\n" + "=" * 60)
        print("  Gate 1 — Investment Direction Confirmation")
        print("=" * 60)

        gate1_session = await run_gate1(
            hypotheses=hypotheses,
            session_id=gate1_id,
            mode=session_mode,
            io_handler=_cli_input_handler,
            status_handler=_cli_status_handler,
        )

        session_mgr = SessionManager()
        session_mgr.save(SessionState(
            session_id=gate1_session.session_id,
            mode=session_mode,
            current_gate=1,
            gate1=GateCheckpoint(1, True, data={
                "selected_direction": gate1_session.selected_direction,
                "rejected": gate1_session.rejected_directions,
            }),
        ))
        if verbose:
            print(f"Gate 1 checkpoint saved: {gate1_session.session_id}")

    # ── Stages 4-10: Full analysis pipeline ───────────────────────────────
    exit_code = await run_post_gate1(config, state, mock, verbose)
    if exit_code != 0:
        return exit_code

    # ── Gate 2: Signal Confirmation ───────────────────────────────────────
    if gate1_session is None or not gate1_session.selected_direction:
        print("\nNo direction selected at Gate 1. Pipeline complete.")
        return 0

    post_hypotheses = state.get("hypotheses", [])
    fragility_report = state.get("fragility_report")
    regime_mapping = state.get("regime_mapping")

    from marketmind.pipeline.gate2_interaction import run_gate2

    gate2_id = f"gate2-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M')}"
    print("\n" + "=" * 60)
    print("  Gate 2 — Signal Confirmation")
    print("=" * 60)

    try:
        gate2_session = await run_gate2(
            direction=gate1_session.selected_direction,
            hypotheses=post_hypotheses,
            fragility_report=fragility_report,
            regime_mapping=regime_mapping,
            session_id=gate2_id,
            io_handler=_cli_input_handler,
            status_handler=_cli_status_handler,
        )
    except Exception as e:
        print(f"\n[Gate 2 failed: {e}] Partial state saved. Pipeline stopped gracefully.")
        session_mgr = SessionManager()
        session_mgr.save(SessionState(
            session_id=gate2_id,
            mode=session_mode,
            current_gate=2,
            gate1=GateCheckpoint(1, True, data={
                "selected_direction": gate1_session.selected_direction,
            }),
            gate2=GateCheckpoint(2, False, data={
                "error": str(e)[:200],
            }),
        ))
        return 1

    # Save cross-gate checkpoint after Gate 2
    session_mgr = SessionManager()
    session_mgr.save(SessionState(
        session_id=gate2_id,
        mode=session_mode,
        current_gate=2,
        gate1=GateCheckpoint(1, True, data={
            "selected_direction": gate1_session.selected_direction,
        }),
        gate2=GateCheckpoint(2, True, data={
            "conviction": gate2_session.final_conviction,
            "outcome": gate2_session.outcome,
        }),
    ))

    if gate2_session.outcome != "CONTINUE":
        print(f"\nGate 2 outcome: {gate2_session.outcome}. Pipeline stopped.")
        return 0

    # ── Gate 3: Position Decision ─────────────────────────────────────────
    from marketmind.pipeline.gate3_interaction import run_gate3

    gate3_id = f"gate3-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M')}"
    print("\n" + "=" * 60)
    print("  Gate 3 — Position Decision")
    print("=" * 60)

    try:
        gate3_session = await run_gate3(
            gate2_session=gate2_session,
            hypotheses=post_hypotheses,
            session_id=gate3_id,
            io_handler=_cli_input_handler,
            status_handler=_cli_status_handler,
        )
    except Exception as e:
        print(f"\n[Gate 3 failed: {e}] Partial state saved. Pipeline stopped gracefully.")
        session_mgr = SessionManager()
        session_mgr.save(SessionState(
            session_id=gate3_id,
            mode=session_mode,
            current_gate=3,
            gate2=GateCheckpoint(2, True, data={
                "conviction": gate2_session.final_conviction,
                "outcome": gate2_session.outcome,
            }),
            gate3=GateCheckpoint(3, False, data={
                "error": str(e)[:200],
            }),
        ))
        return 1

    # Save Gate 3 checkpoint with full ticket data
    if gate3_session.ticket:
        session_mgr = SessionManager()
        session_mgr.save(SessionState(
            session_id=gate3_id,
            mode=session_mode,
            current_gate=3,
            gate1=GateCheckpoint(1, True, data={
                "selected_direction": gate1_session.selected_direction,
            }),
            gate2=GateCheckpoint(2, True, data={
                "conviction": gate2_session.final_conviction,
                "outcome": gate2_session.outcome,
            }),
            gate3=GateCheckpoint(3, gate3_session.outcome == "EXECUTED", data={
                "ticket": asdict(gate3_session.ticket),
            }),
        ))

    if gate3_session.outcome == "EXECUTED":
        # Archive the decision ticket to the session archivist
        archivist = state.get("archivist")
        if archivist and gate3_session.ticket:
            try:
                archivist.save_json("decisions", f"ticket_{gate3_id}",
                                    asdict(gate3_session.ticket))
                if verbose:
                    print(f"Decision ticket archived: {gate3_id}")
            except Exception as e:
                if verbose:
                    print(f"Archive warning: {e}")
        print(f"\nDecision executed: {gate3_session.ticket.direction}")
    else:
        print(f"\nGate 3 outcome: {gate3_session.outcome}. Pipeline complete.")

    return 0


async def run_gate1_mode(config: "MarketMindConfig", mock: bool = False,
                         verbose: bool = False,
                         shadow_count: int | None = None) -> int:
    """Run Stage 0-3 then Gate 1 interaction, save checkpoint, and exit.

    Does NOT run stages 4-10. Use --mode gate1 for direction-only sessions.
    """
    state = await run_pre_gate1(config, mock, verbose, shadow_count)

    hypotheses = state["hypotheses"]
    if not hypotheses:
        print("No hypotheses to present. Pipeline stopped early.")
        return 0

    from marketmind.pipeline.gate1_interaction import run_gate1
    from marketmind.storage.session import SessionManager, SessionState, GateCheckpoint

    session_id = f"gate1-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M')}"
    print("\n" + "=" * 60)
    print("  Gate 1 — Investment Direction Confirmation")
    print("=" * 60)

    gate1_session = await run_gate1(
        hypotheses=hypotheses,
        session_id=session_id,
        mode="full",
        io_handler=_cli_input_handler,
        status_handler=_cli_status_handler,
    )

    # Save Gate 1 checkpoint
    session_mgr = SessionManager()
    session_mgr.save(SessionState(
        session_id=gate1_session.session_id,
        mode="full",
        current_gate=1,
        gate1=GateCheckpoint(1, True, data={
            "selected_direction": gate1_session.selected_direction,
            "rejected": gate1_session.rejected_directions,
        }),
    ))

    if verbose:
        print(f"Gate 1 complete. Session: {gate1_session.session_id}")
        print(f"  Selected: {gate1_session.selected_direction}")
        print(f"  Rejected: {gate1_session.rejected_directions}")

    print("\nGate 1 finished. Use --mode full to continue with stages 4-10.")
    return 0


async def run_interactive(config: "MarketMindConfig", mock: bool = False,
                          verbose: bool = False, shadow_count: int | None = None) -> int:
    """Run the full interactive pipeline with CLI prompts at each stage."""
    from marketmind.pipeline.session_context import SessionContext
    from marketmind.pipeline.layer1_interactive import run_l1_interactive
    from marketmind.pipeline.l2_interactive import run_l2_interactive
    from marketmind.pipeline.l3_interactive import run_l3_interactive
    from marketmind.pipeline.decision_interactive import run_decision_interactive

    init_gateway(config.deepseek_api_key, config.deepseek_base_url)
    ctx = SessionContext(config=config)

    async def cli_handler(prompt: str) -> str:
        if mock:
            return "好"
        print(prompt, end="")
        return input()

    # Stage 1: L1 narrative
    l1_result, skip, _ = await run_l1_interactive(config, mock=mock, verbose=verbose,
                                                   shadow_count=shadow_count)
    ctx.l1_result = l1_result
    if skip:
        return 0

    # Stage 2: L2 fundamental
    if not await run_l2_interactive(ctx, cli_handler):
        return 0

    # Stage 3: L3 technical
    if not await run_l3_interactive(ctx, cli_handler):
        return 0

    # Stage 4: Decision
    if not await run_decision_interactive(ctx, cli_handler):
        return 0

    return 0
