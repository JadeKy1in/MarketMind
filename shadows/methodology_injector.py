"""MethodologyInjector — Write improvement signals back to shadow prompts.

This is the MISSING PRIMITIVE identified by the Architect review. All
feedback loops (crystallization, AEL, challenger verdicts, method
breeding, reset candidates) detect issues but cannot write changes
back to shadow prompts. This class bridges that gap.

All injections are logged to the methodology_changes audit table.

Extracted from methodology_evolver.py to comply with 500-line hard ceiling.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Optional

logger = logging.getLogger("marketmind.shadows.methodology_injector")

_METHOD_DIR = Path(__file__).resolve().parent.parent / "data" / "methodology"
_METHOD_DIR.mkdir(parents=True, exist_ok=True)
_AUDIT_FILE = _METHOD_DIR / "evolution_audit.jsonl"


class MethodologyInjector:
    """Writes improvement signals back to ShadowConfig.methodology_prompt.

    This is the MISSING PRIMITIVE identified by the Architect review. All
    feedback loops (crystallization, AEL, challenger verdicts, method
    breeding, reset candidates) detect issues but cannot write changes
    back to shadow prompts. This class bridges that gap.

    All injections are logged to the methodology_changes audit table.
    """

    def __init__(self, state_db):
        self._state_db = state_db

    def inject_lessons(self, shadow_id: str, lessons: list[str]) -> bool:
        """Append [LESSONS LEARNED] block to a shadow's methodology prompt.

        Used by AEL slow layer (Phase 7) to persist monthly debrief findings.
        """
        config = self._state_db.get_shadow(shadow_id)
        if config is None:
            return False

        # Remove any previous [LESSONS LEARNED] section
        old_prompt = config.methodology_prompt
        base_prompt = old_prompt.split("[LESSONS LEARNED")[0].strip()

        lessons_text = "\n".join(f"- {l}" for l in lessons)
        new_prompt = f"{base_prompt}\n\n[LESSONS LEARNED — apply these in your analysis]\n{lessons_text}"

        return self._state_db.update_methodology_prompt(
            shadow_id, new_prompt,
            reason=f"Injected {len(lessons)} AEL lessons"
        )

    def inject_validated_insight(self, shadow_id: str, insight: str) -> bool:
        """Add a [VALIDATED INSIGHT] block from crystallization (P1-2)."""
        config = self._state_db.get_shadow(shadow_id)
        if config is None:
            return False

        old_prompt = config.methodology_prompt
        # Remove any previous injected insight with same content
        cleaned = re.sub(
            r'\n\[VALIDATED INSIGHT\].*?\n(?=\n|\[|$)', '', old_prompt, flags=re.DOTALL
        )
        new_prompt = f"{cleaned.strip()}\n\n[VALIDATED INSIGHT] {insight}"

        return self._state_db.update_methodology_prompt(
            shadow_id, new_prompt,
            reason=f"Promoted crystallized insight: {insight[:100]}"
        )

    def inject_retired_insight(self, shadow_id: str, insight: str) -> bool:
        """Add a [RETIRED] note when a previously-validated insight is invalidated."""
        config = self._state_db.get_shadow(shadow_id)
        if config is None:
            return False

        old_prompt = config.methodology_prompt
        retired_block = f"\n[RETIRED: This insight was invalidated — do NOT use]\n{insight}"
        new_prompt = old_prompt + retired_block

        return self._state_db.update_methodology_prompt(
            shadow_id, new_prompt,
            reason=f"Retired invalidated insight: {insight[:100]}"
        )

    def inject_failure_patterns(self, shadow_id: str, failures: list[str]) -> bool:
        """Prepend [FAILURE PATTERNS TO AVOID] for challengers (P3-1).

        Used when a challenger replaces a target — the challenger learns
        from the predecessor's documented failures.
        """
        config = self._state_db.get_shadow(shadow_id)
        if config is None:
            return False

        old_prompt = config.methodology_prompt
        # Remove any previous [FAILURE PATTERNS] section
        base = old_prompt.split("[FAILURE PATTERNS TO AVOID]")[0].strip()

        failures_text = "\n".join(f"- {f}" for f in failures)
        new_prompt = (
            f"[FAILURE PATTERNS TO AVOID — learned from predecessor]\n"
            f"{failures_text}\n\n{base}"
        )

        return self._state_db.update_methodology_prompt(
            shadow_id, new_prompt,
            reason=f"Injected {len(failures)} predecessor failure patterns"
        )

    def reset_to_baseline(self, shadow_id: str) -> bool:
        """Restore a shadow's methodology to its original template.

        Used when a reset candidate is flagged (stagnation detected).
        The original methodology is recovered from the first entry in
        the methodology_changes audit table, or from config_json.
        """
        original = self._state_db.get_original_methodology(shadow_id)
        if original is None:
            config = self._state_db.get_shadow(shadow_id)
            if config is None:
                return False
            original = config.methodology_prompt
            if not original:
                return False

        return self._state_db.update_methodology_prompt(
            shadow_id, original,
            reason="Reset to baseline (stagnation detected)"
        )

    def get_audit_trail(
        self, method_id: str | None = None, limit: int = 50
    ) -> list[dict]:
        """Get the methodology audit trail, optionally filtered by method_id.

        Args:
            method_id: Optional filter for a specific method.
            limit: Maximum number of entries to return.

        Returns:
            List of audit entry dicts, most recent first.
        """
        if not _AUDIT_FILE.exists():
            return []
        entries = []
        with open(_AUDIT_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    if method_id is None or entry.get("method_id") == method_id:
                        entries.append(entry)
                except json.JSONDecodeError:
                    continue
        # Return most recent first, limited
        entries.reverse()
        return entries[:limit]
