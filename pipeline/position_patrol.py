"""Position patrol: daily health check, buy archive comparison, cash reframing."""
from __future__ import annotations
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from marketmind.gateway.async_client import chat_pro
from marketmind.config.settings import MarketMindConfig

logger = logging.getLogger("marketmind.pipeline.position_patrol")


@dataclass
class PositionStatus:
    # Ground-truth fields from INPUT (never from LLM)
    ticker: str
    entry_price: float
    current_price: float
    pnl_pct: float
    days_held: int
    protection_active: bool = False

    # Analytical fields from LLM output
    status: str = "yellow"
    logic_valid: bool = True
    technical_breach: bool = False
    time_expiry_reached: bool = False
    opportunity_cost_signal: bool = False
    cash_reframing_answer: str = "hesitate"
    recommendation: str = "hold"
    exit_conditions_met: list[str] = field(default_factory=list)
    alternative_use: str = ""

    # Code-enforced override fields (never from LLM)
    recommendation_override: str | None = None
    override_reason: str | None = None


PATROL_SYSTEM_PROMPT = """You are a disciplined position manager. For each position, perform a cold-eyed review.

Checklist:
1. Buy Archive Check: Is the original thesis still valid? What's changed since entry?
2. Cash Reframing: If you had cash equal to this position's market value right now, would you buy this today over today's best opportunity?
3. Layer 3 Exit Review: Stop-loss triggered? Daily structure broken? Time limit reached?
4. Opportunity Cost: Is there a higher-conviction use for this capital today?

Output JSON array (ANALYTICAL FIELDS ONLY — do NOT repeat entry_price/current_price/pnl_pct/days_held):
[{
  "ticker": "TICKER",
  "status": "green|yellow|red",
  "logic_valid": true|false,
  "technical_breach": true|false,
  "time_expiry_reached": true|false,
  "opportunity_cost_signal": true|false,
  "cash_reframing_answer": "yes|no|hesitate",
  "recommendation": "hold|reduce|exit",
  "exit_conditions_met": ["condition1"],
  "alternative_use": "If exiting, suggest: ..."
}]

Rules:
- Green: all conditions clean, thesis intact
- Yellow: 1-2 warning signs, needs attention
- Red: thesis broken OR technical breached OR time expired -> recommend exit
- Sell recommendations MUST include alternative use for freed capital
- During first 60 days: only recommend sell if BOTH logic falsified AND technical breached (磨合期保护)"""


async def patrol_positions(positions: list[dict], config: MarketMindConfig | None = None) -> tuple[list[PositionStatus], str | None]:
    """Run daily position patrol across all active positions.

    Returns (results, error_message). error_message is None on success.
    """
    if not positions:
        return [], None
    if config is None:
        config = MarketMindConfig.from_env()
    positions_text = json.dumps(positions, indent=2, ensure_ascii=False)
    user_prompt = f"Review these positions for today's health check:\n\n{positions_text}"
    try:
        result = await chat_pro(
            system_prompt=PATROL_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            temperature=0.2,
            max_tokens=4096,
        )
        parsed = _parse_patrol_response(result["content"], positions, config)
        validated = _apply_protection_veto(parsed, config.position_protection_days)
        return validated, None
    except Exception as e:
        logger.error("Position patrol failed: %s", e)
        return [], str(e)


def _parse_patrol_response(content: str, positions: list[dict], config: MarketMindConfig) -> list[PositionStatus]:
    """Parse LLM response and join with input positions for ground-truth fields."""
    from marketmind.gateway.response_parser import extract_json

    # Build lookup from input positions
    pos_lookup: dict[str, dict] = {}
    for p in positions:
        ticker = str(p.get("ticker", "")).upper()
        if ticker:
            pos_lookup[ticker] = p

    try:
        data = extract_json(content)
    except ValueError:
        logger.warning("Failed to extract JSON from patrol response")
        return []

    if isinstance(data, dict):
        data = [data]

    results = []
    seen_tickers: set[str] = set()
    for d in data:
        ticker = str(d.get("ticker", "")).upper()
        if not ticker:
            continue
        seen_tickers.add(ticker)
        input_pos = pos_lookup.get(ticker, {})

        # Ground-truth from input (never from LLM)
        entry_price = float(input_pos.get("entry_price", 0))
        current_price = float(input_pos.get("current_price", 0))
        if entry_price > 0:
            pnl_pct = round((current_price - entry_price) / entry_price * 100, 2)
        else:
            pnl_pct = 0.0
        entry_date = input_pos.get("entry_date", "")
        if entry_date:
            try:
                days_held = (datetime.now().date() - datetime.fromisoformat(entry_date).date()).days
            except (ValueError, TypeError):
                days_held = 0
        else:
            days_held = 0
        protection_active = days_held < config.position_protection_days

        results.append(PositionStatus(
            ticker=ticker,
            entry_price=entry_price,
            current_price=current_price,
            pnl_pct=pnl_pct,
            days_held=days_held,
            protection_active=protection_active,
            # Analytical fields from LLM
            status=d.get("status", "yellow"),
            logic_valid=bool(d.get("logic_valid", True)),
            technical_breach=bool(d.get("technical_breach", False)),
            time_expiry_reached=bool(d.get("time_expiry_reached", False)),
            opportunity_cost_signal=bool(d.get("opportunity_cost_signal", False)),
            cash_reframing_answer=d.get("cash_reframing_answer", "hesitate"),
            recommendation=d.get("recommendation", "hold"),
            exit_conditions_met=d.get("exit_conditions_met", []),
            alternative_use=d.get("alternative_use", ""),
        ))

    # Warn about input positions missing LLM analysis
    for ticker in pos_lookup:
        if ticker not in seen_tickers:
            logger.warning("Position '%s' in input but missing from LLM patrol analysis", ticker)

    return results


def _apply_protection_veto(results: list[PositionStatus], protection_days: int) -> list[PositionStatus]:
    """Enforce 60-day protection period: override exit recommendation if conditions not fully met."""
    for ps in results:
        if not ps.protection_active:
            continue

        if ps.recommendation == "exit":
            exit_conditions_count = sum([
                1 if not ps.logic_valid else 0,
                1 if ps.technical_breach else 0,
            ])
            if exit_conditions_count < 2:
                ps.recommendation_override = "hold"
                ps.override_reason = (
                    f"60-day protection: only {exit_conditions_count}/2 exit conditions met "
                    f"(need both logic_falsified AND technical_breach). "
                    f"LLM recommended 'exit' but protection period active (day {ps.days_held}/{protection_days})."
                )
                logger.info(
                    "Protection veto: %s (day %d) — LLM exit overridden to hold (%d/2 conditions)",
                    ps.ticker, ps.days_held, exit_conditions_count,
                )
    return results
