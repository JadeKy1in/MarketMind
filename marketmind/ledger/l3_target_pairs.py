"""Identifiers of the closed L3 target v1 / v2 ledger counterfactual.

Owner decision 2026-10-22: the daily run recorded, for each green / yellow L3 ticker
whose alternative target_v2 (pipeline.l3_indicators.alt_target) differed from the live
target, two ledger-only rows with the same entry zone, stop, hold and size:

  source_id "baseline:l3_target_v1"  live target (target_price)
  source_id "baseline:l3_target_v2"  target_v2

Owner decision 2026-11-20 (docs/S7_DESIGN.md §六): experiment closed, v1 stays the live
rule, no new pairs are written. Rows already in the ledger are source_type "baseline":
they keep settling through settlement.settle_all (store.unsettled() includes baselines),
stay hidden from list() by default, and are read with ledger.l3_target_compare.
"""
from __future__ import annotations

SOURCE_TYPE = "baseline"
VERSIONS = ("v1", "v2")
KIND = {"v1": "l3_target_v1", "v2": "l3_target_v2"}
SOURCE_IDS = {v: f"baseline:{k}" for v, k in KIND.items()}
