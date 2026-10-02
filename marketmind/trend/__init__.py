"""Pure-code trend state machine ("big-move detector") - docs/TREND_DESIGN.md.

Wired into the daily and weekend runs as a state file (data/trend/) and the big-move
alerts; ledger records carry its state as an annotation only (ledger/trend_tag.py,
docs/S7_DESIGN.md §六) - it never blocks a trade.
"""
