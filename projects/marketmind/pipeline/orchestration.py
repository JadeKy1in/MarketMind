"""Pipeline orchestration — run_daily, run_full, run_gate1_mode, run_interactive.

Thin coordinator: calls pre_gate1 and post_gate1 modules.
"""
from __future__ import annotations
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
                    shadow_count: int | None = None) -> int:
    """Execute full daily analysis pipeline (stages 0-10, no Gate 1)."""
    state = await run_pre_gate1(config, mock, verbose, shadow_count)
    return await run_post_gate1(config, state, mock, verbose)


async def run_full(config: "MarketMindConfig", mock: bool = False, verbose: bool = False,
                   shadow_count: int | None = None, session_mode: str = "full") -> int:
    """Complete pipeline with Gate 1 interaction in the middle.

    Flow: Stage 0-3 → Gate 1 → Stage 4-10 → Archive
    """
    state = await run_pre_gate1(config, mock, verbose, shadow_count)

    # Gate 1: Human direction confirmation
    hypotheses = state["hypotheses"]
    if hypotheses:
        from marketmind.pipeline.gate1_interaction import run_gate1
        from marketmind.storage.session import SessionManager, SessionState, GateCheckpoint

        session_id = f"gate1-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M')}"
        print("\n" + "=" * 60)
        print("  Gate 1 — Investment Direction Confirmation")
        print("=" * 60)

        gate1_session = await run_gate1(
            hypotheses=hypotheses,
            session_id=session_id,
            mode=session_mode,
            io_handler=_cli_input_handler,
            status_handler=_cli_status_handler,
        )

        # Save Gate 1 checkpoint
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

    # Continue to stages 4-10
    return await run_post_gate1(config, state, mock, verbose)


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
