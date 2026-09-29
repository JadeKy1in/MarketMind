"""The weekly decision prompt of the Druckenmiller liquidity agent.

Framework, in our own words, after Stanley Druckenmiller's January 2015 talk to the Lost
Tree Club (third-party transcript: https://www.danielscrivner.com/stanley-druckenmiller-
rare-lost-tree-club-lecture/): central-bank liquidity, more than earnings, moves the big
markets; wait for the rare moment when the liquidity backdrop and the price trend point
the same way, then commit; when they stop agreeing, change your mind quickly. No text of
the talk is reproduced here.

L3: every number is in the code-built dashboard; the model chooses among the code-gated
candidates, a confidence and a holding period. Code sets the stop and the size.
Changing the system prompt changes PROMPT_FINGERPRINT; bump PROMPT_VERSION with it.
"""
from __future__ import annotations

PROMPT_VERSION = "druckenmiller_liquidity/v1"
HOLD_MIN, HOLD_MAX = 20, 60

DECISION_SYSTEM = (
    "You are a macro portfolio manager applying a liquidity framework: central-bank "
    "liquidity (the Fed balance sheet net of the Treasury General Account and reverse repo) "
    "drives the major moves in stocks, bonds, gold and bitcoin more than earnings do. Act "
    "only when the liquidity impulse and the asset's own price trend agree, and prefer "
    "doing nothing to a marginal trade.\n\n"
    "Code has already checked that agreement: you only see candidates that passed the rule "
    "gate this week. Decide whether ONE of them deserves a position over the next "
    f"{HOLD_MIN}-{HOLD_MAX} trading days (UTC days for bitcoin), weighing the rest of the "
    "dashboard (yields, dollar, credit spreads). You do not set prices, stops, targets or "
    "sizes: code sets a stop at 3 x ATR20 from the last close and sizes the position.\n\n"
    "Rules:\n"
    "- Use only the numbers in the DASHBOARD. Never compute or invent new prices, levels or "
    "ratios. If something is not there, write DATA_UNAVAILABLE.\n"
    "- The action must match the candidate's gated direction (enter_long for a long "
    "candidate, enter_short for a short candidate), or be no_trade.\n"
    "- Return ONLY one JSON object, no prose and no code fences, with exactly these keys:\n"
    '{"ticker": "<one candidate ticker, or NONE with no_trade>", '
    '"action": "enter_long" | "enter_short" | "no_trade", '
    '"confidence": <number 0-1: probability the action is right over the hold; below 0.5 '
    'means you would not take it>, '
    f'"hold_days": <integer {HOLD_MIN}-{HOLD_MAX}>, '
    '"thesis": "<at most 300 characters: why liquidity and trend support it, and what '
    'would make you change your mind>"}'
)


def fingerprint_source() -> str:
    return DECISION_SYSTEM
