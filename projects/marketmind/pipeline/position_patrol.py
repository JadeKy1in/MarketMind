"""Position patrol: daily health check, buy archive comparison, cash reframing."""
from __future__ import annotations
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from projects.marketmind.gateway.async_client import chat_pro


@dataclass
class PositionStatus:
    ticker: str
    status: str                    # green | yellow | red
    entry_price: float
    current_price: float
    pnl_pct: float
    days_held: int
    logic_valid: bool              # buy thesis still intact?
    technical_breach: bool         # below stop or key support broken?
    time_expiry_reached: bool
    opportunity_cost_signal: bool  # better opportunity available?
    cash_reframing_answer: str     # "yes" | "no" | "hesitate"
    recommendation: str            # hold | reduce | exit
    exit_conditions_met: list[str]
    alternative_use: str           # if exiting, what to do with freed capital


PATROL_SYSTEM_PROMPT = """You are a disciplined position manager. For each position, perform a cold-eyed review.

Checklist:
1. Buy Archive Check: Is the original thesis still valid? What's changed since entry?
2. Cash Reframing: If you had cash equal to this position's market value right now, would you buy this today over today's best opportunity?
3. Layer 3 Exit Review: Stop-loss triggered? Daily structure broken? Time limit reached?
4. Opportunity Cost: Is there a higher-conviction use for this capital today?

Output JSON array:
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
- Red: thesis broken OR technical breached OR time expired → recommend exit
- Sell recommendations MUST include alternative use for freed capital
- During first 60 days: only recommend sell if BOTH logic falsified AND technical breached (磨合期保护)"""


async def patrol_positions(positions: list[dict]) -> list[PositionStatus]:
    """Run daily position patrol across all active positions."""
    if not positions:
        return []
    positions_text = json.dumps(positions, indent=2, ensure_ascii=False)
    user_prompt = f"Review these positions for today's health check:\n\n{positions_text}"
    try:
        result = await chat_pro(
            system_prompt=PATROL_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            temperature=0.2,
            max_tokens=4096,
        )
        return _parse_patrol_response(result["content"])
    except Exception:
        return []


def _parse_patrol_response(content: str) -> list[PositionStatus]:
    content = content.strip()
    if content.startswith("```"):
        lines = content.split("\n")
        content = "\n".join(lines[1:])
        if content.endswith("```"):
            content = content[:-3]
    try:
        data = json.loads(content)
        if isinstance(data, dict):
            data = [data]
    except json.JSONDecodeError:
        start = content.find("[")
        end = content.rfind("]")
        if start != -1 and end != -1:
            data = json.loads(content[start:end + 1])
        else:
            return []
    results = []
    for d in data:
        results.append(PositionStatus(
            ticker=d.get("ticker", ""),
            status=d.get("status", "yellow"),
            entry_price=float(d.get("entry_price", 0)),
            current_price=float(d.get("current_price", 0)),
            pnl_pct=float(d.get("pnl_pct", 0)),
            days_held=int(d.get("days_held", 0)),
            logic_valid=bool(d.get("logic_valid", True)),
            technical_breach=bool(d.get("technical_breach", False)),
            time_expiry_reached=bool(d.get("time_expiry_reached", False)),
            opportunity_cost_signal=bool(d.get("opportunity_cost_signal", False)),
            cash_reframing_answer=d.get("cash_reframing_answer", "hesitate"),
            recommendation=d.get("recommendation", "hold"),
            exit_conditions_met=d.get("exit_conditions_met", []),
            alternative_use=d.get("alternative_use", ""),
        ))
    return results
