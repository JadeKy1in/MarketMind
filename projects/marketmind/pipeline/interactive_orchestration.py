"""Interactive CLI pipeline orchestration — extracted from orchestration.py.

Provides the interactive (step-by-step) execution mode with user prompts
at L1, L2, L3, and Decision stages.
"""
from __future__ import annotations


async def run_interactive(config: "MarketMindConfig", mock: bool = False,
                          verbose: bool = False, shadow_count: int | None = None) -> int:
    """Run the full interactive pipeline with CLI prompts at each stage."""
    from marketmind.gateway.async_client import init_gateway
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

    l1_result, skip, _ = await run_l1_interactive(config, mock=mock, verbose=verbose,
                                                   shadow_count=shadow_count)
    ctx.l1_result = l1_result
    if skip:
        return 0

    if not await run_l2_interactive(ctx, cli_handler):
        return 0

    if not await run_l3_interactive(ctx, cli_handler):
        return 0

    if not await run_decision_interactive(ctx, cli_handler):
        return 0

    return 0
