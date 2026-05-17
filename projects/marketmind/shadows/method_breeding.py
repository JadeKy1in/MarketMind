"""Method Breeding — Auto-generate new methods when old ones retire.

Uses technique inspired by AlphaCrafter's Miner Agent and
QuantEvolve's island model: when methods retire, breed new ones
from the remaining best performers.

Extracted from methodology_evolver.py to comply with 500-line hard ceiling.
"""
from __future__ import annotations

import json
import logging
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from marketmind.shadows.methodology_evolver import (
    load_tracker, save_tracker, MethodRecord,
)

logger = logging.getLogger("marketmind.shadows.method_breeding")

_METHOD_DIR = Path(__file__).resolve().parent.parent / "data" / "methodology"
_METHOD_DIR.mkdir(parents=True, exist_ok=True)
_AUDIT_FILE = _METHOD_DIR / "evolution_audit.jsonl"


def _auto_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# Breeding templates: combine two existing methods to create a new one
BREED_TEMPLATES = [
    "Hybrid of {parent1} and {parent2}: apply {parent1} logic "
    "with {parent2} timing filters",
    "{parent1} with {parent2}'s risk management overlays",
    "Ensemble: {parent1} for entry, {parent2} for exit decisions",
    "Regime-switched: {parent1} in bull markets, {parent2} in bear markets",
    "Reversed {parent1}: flip the signal direction and validate",
    "Scaled {parent1}: apply position sizing from {parent2}",
]


def breed_new_method() -> Optional[str]:
    """Generate a new method by combining two existing active methods.

    Uses technique inspired by AlphaCrafter's Miner Agent and
    QuantEvolve's island model: when methods retire, breed new ones
    from the remaining best performers.

    Returns:
        New method_id if breeding was successful, None otherwise.
    """
    tracker = load_tracker()
    active = [m for m in tracker.values() if m.active and m.total_predictions >= 3]

    if len(active) < 2:
        logger.warning("Breeder: need at least 2 active methods, have %d", len(active))
        return None

    # Select best performers as parents
    ranked = sorted(
        active,
        key=lambda m: m.correct_predictions / max(m.total_predictions, 1),
        reverse=True,
    )
    parent1 = ranked[0]
    parent2 = ranked[1] if len(ranked) > 1 else parent1

    template = random.choice(BREED_TEMPLATES)
    description = template.format(
        parent1=parent1.method_id,
        parent2=parent2.method_id,
    )

    # Generate unique ID
    base_id = f"bred-{parent1.method_id[:8]}-{parent2.method_id[:8]}"
    new_id = base_id
    counter = 1
    while new_id in tracker:
        new_id = f"{base_id}-v{counter}"
        counter += 1

    new_method = MethodRecord(
        method_id=new_id,
        description=description,
        category="bred",
        active=True,
        decay_factor=0.6,  # Start with moderate confidence
    )

    tracker[new_id] = new_method
    save_tracker(tracker)

    # Write audit entry
    entry = {
        "timestamp": _auto_iso(),
        "event": "method_bred",
        "new_method": new_id,
        "parent1": parent1.method_id,
        "parent2": parent2.method_id,
        "description": description,
    }
    with open(_AUDIT_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    logger.info(
        "Breeder: created %s from %s + %s",
        new_id, parent1.method_id, parent2.method_id,
    )
    return new_id


def maintain_population(min_active: int = 6, max_active: int = 15) -> dict[str, Any]:
    """Maintain a healthy population of analysis methods.

    If too few active methods remain (< min_active), breed new ones.
    If too many (> max_active), retire the worst performers.

    Args:
        min_active: Minimum number of active methods to maintain.
        max_active: Maximum before forced retirement.

    Returns:
        Dict with actions taken and population stats.
    """
    tracker = load_tracker()
    active = [m for m in tracker.values() if m.active]
    retired = [m for m in tracker.values() if not m.active]

    result: dict[str, Any] = {
        "before_active": len(active),
        "before_retired": len(retired),
        "actions": [],
    }

    # Retire excess
    if len(active) > max_active:
        ranked = sorted(
            active,
            key=lambda m: m.correct_predictions / max(m.total_predictions, 1),
        )
        to_retire = ranked[:(len(active) - max_active)]
        for m in to_retire:
            m.active = False
            result["actions"].append(f"Retired (excess): {m.method_id}")

    # Breed if too few
    while len([m for m in tracker.values() if m.active]) < min_active:
        new_id = breed_new_method()
        if new_id:
            result["actions"].append(f"Bred: {new_id}")
        else:
            break  # Can't breed

    save_tracker(tracker)

    active_after = len([m for m in tracker.values() if m.active])
    result["after_active"] = active_after
    result["methods_created"] = len(result["actions"])

    # Auto-reactivate retired methods as last resort
    if active_after < min_active and retired:
        best_retired = sorted(
            retired,
            key=lambda m: m.correct_predictions / max(m.total_predictions, 1),
            reverse=True,
        )
        for m in best_retired[:(min_active - active_after)]:
            m.active = True
            m.decay_factor = 0.3  # Low confidence restart
            result["actions"].append(f"Reactivated: {m.method_id} (low confidence)")

    save_tracker(tracker)
    return result
