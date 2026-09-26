"""Zombie shadow detector — startup integrity check.

Every ecosystem init compares DB-stored shadows against the canonical list
from current creation code. Any shadow in the DB not created by current code
is a zombie — it was registered by code that has since been removed/replaced.

Mechanical check, zero cost, runs once at startup. No human discipline required.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from marketmind.shadows.shadow_state import ShadowStateDB

logger = logging.getLogger("marketmind.shadows.zombie_detector")


def _canonical_shadow_ids() -> set[str]:
    """Extract all shadow_ids from current factory code.

    SINGLE SOURCE OF TRUTH. Code is authoritative, not DB.
    """
    from marketmind.shadows.expert_shadows import EXPERT_SHADOW_CONFIGS
    from marketmind.shadows.daredevil_shadows import DAREDEVIL_SHADOW_CONFIGS

    ids: set[str] = set()
    for cfg in EXPERT_SHADOW_CONFIGS:
        ids.add(cfg.shadow_id)
    for cfg in DAREDEVIL_SHADOW_CONFIGS:
        ids.add(cfg.shadow_id)
    return ids


def detect_zombies(state_db: "ShadowStateDB") -> list[str]:
    """Compare DB shadows against canonical code list. Auto-retire zombies.

    Returns list of zombie shadow_ids that were found and retired.
    """
    canonical = _canonical_shadow_ids()
    db_shadows = state_db.get_visible_shadows()
    db_ids = {s.shadow_id for s in db_shadows}

    zombies = db_ids - canonical
    missing = canonical - db_ids

    retired: list[str] = []
    for zid in sorted(zombies):
        logger.warning(
            "ZOMBIE DETECTED: '%s' exists in DB but is no longer created by current code. "
            "It was likely registered by code that has been removed or replaced. "
            "Auto-retiring.",
            zid,
        )
        try:
            state_db.eliminate_shadow(
                zid, "Zombie: shadow removed from code — auto-retired by zombie_detector"
            )
            retired.append(zid)
        except Exception:
            logger.debug("Could not auto-retire zombie '%s' (may already be eliminated)", zid)

    if missing:
        logger.info(
            "New shadows in code but not yet in DB (%d): %s. Will be created on init.",
            len(missing), sorted(missing),
        )

    if retired:
        logger.info("Zombie cleanup: auto-retired %d shadows: %s", len(retired), retired)

    return retired
