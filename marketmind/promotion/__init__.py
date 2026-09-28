"""Promotion ladder (docs/S7_DESIGN.md §一, SPEC_v3 §8): probation -> formal -> advisor -> monitored.

Pure code, no LLM. `metrics` holds the statistics, `ladder.evaluate` the stage
machine, `runner.run_promotion` the daily file I/O.
"""
