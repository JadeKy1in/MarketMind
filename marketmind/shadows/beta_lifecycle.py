"""Beta shadow lifecycle — creation, promotion, and isolation rules.

Beta shadows are sandboxed methodology testing variants. They are ISOLATED —
excluded from ranking, voting, and collusion detection. Promotion requires
20-day positive track record with Sharpe > 0.5.

Extracted from shadow_mother.py per workspace modular architecture rules.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from marketmind.shadows.shadow_state import ShadowStateDB, ShadowConfig
from marketmind.config.settings import ShadowSettings

logger = logging.getLogger("marketmind.shadows.beta_lifecycle")


async def create_beta_shadow(
    state_db: ShadowStateDB,
    template_shadow_id: str,
    methodology_variant: dict,
) -> str:
    """Create a beta shadow from an expert template with methodology tweaks.

    Beta shadows are ISOLATED — excluded from ranking, voting, collusion detection.

    Args:
        state_db: ShadowStateDB for persistence.
        template_shadow_id: Parent expert shadow to clone from.
        methodology_variant: Dict of methodology tweaks under test.

    Returns:
        The new beta shadow_id string.

    Raises:
        ValueError: If template shadow not found.
    """
    template = state_db.get_shadow(template_shadow_id)
    if not template:
        raise ValueError(f"Template shadow '{template_shadow_id}' not found")

    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    shadow_id = f"beta:{template.domain or 'general'}:{ts}"

    variant_text = " ".join(f"{k}: {v}" for k, v in methodology_variant.items())
    methodology = (
        f"{template.methodology_prompt}\n\n"
        f"[BETA METHODOLOGY VARIANT]\n"
        f"Methodology tweaks under test: {variant_text}\n"
        f"Status: sandboxed. This output is isolated from ranking and consensus."
    )

    config = ShadowConfig(
        shadow_id=shadow_id,
        shadow_type="beta",
        display_name=f"Beta {template.display_name}",
        methodology_prompt=methodology,
        virtual_capital=template.virtual_capital,
        max_positions=template.max_positions,
        model=template.model,
        temperature=template.temperature,
        domain=template.domain,
        parent_shadow_id=template_shadow_id,
        generation=template.generation + 1,
        status="beta",
    )
    state_db.create_shadow(config)
    logger.info("Created beta shadow %s from template %s", shadow_id, template_shadow_id)
    return shadow_id


async def promote_beta_shadow(
    state_db: ShadowStateDB,
    shadow_id: str,
) -> bool:
    """Promote beta to active after 20-day positive track record.

    Requires Sharpe > 0.5 over evaluation window.

    Args:
        state_db: ShadowStateDB for snapshot history and status update.
        shadow_id: Beta shadow to evaluate for promotion.

    Returns:
        True if promoted, False otherwise.
    """
    shadow = state_db.get_shadow(shadow_id)
    if not shadow:
        logger.warning("promote_beta_shadow: shadow %s not found", shadow_id)
        return False
    if shadow.status != "beta":
        logger.warning("promote_beta_shadow: shadow %s is not beta (status=%s)",
                       shadow_id, shadow.status)
        return False

    snapshots = state_db.get_snapshot_history(shadow_id, days=20)
    if len(snapshots) < 20:
        logger.info("promote_beta_shadow: %s has %d days (< 20 required)",
                    shadow_id, len(snapshots))
        return False

    avg_sharpe = sum(
        s.sharpe_ratio for s in snapshots if s.sharpe_ratio is not None
    ) / max(len(snapshots), 1)
    cumulative_return = snapshots[-1].cumulative_return_pct or 0.0

    if avg_sharpe <= 0.5:
        logger.info("promote_beta_shadow: %s Sharpe %.3f <= 0.5", shadow_id, avg_sharpe)
        return False

    state_db.update_shadow_status(shadow_id, "active")
    logger.info("Promoted beta shadow %s to active (Sharpe=%.3f, return=%.2f%%)",
                 shadow_id, avg_sharpe, cumulative_return * 100)
    return True
