"""Daily briefing generator for shadow startup protocol.

Each shadow receives a personalized Daily Briefing at startup with structured
sections that mitigate Lost-in-the-Middle: critical info at start and end,
data-dense content in the middle.

Phase E Module 2 — Integration layer.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from marketmind.shadows.briefing_sections import (
    BriefingSectionFormatter,
    MAX_BRIEFING_TOKENS,
    SECTION_SEP,
)

logger = logging.getLogger("marketmind.shadows.daily_briefing")


class DailyBriefingGenerator:
    """Generate per-shadow personalized daily briefings.

    The briefing is structured to mitigate Lost-in-the-Middle:
    - Sections 1 (Persona) and 5 (Instruction) contain critical decision-making info.
    - Sections 2-4 contain data-dense but lower-priority content in the middle.

    Usage:
        gen = DailyBriefingGenerator(state_db)
        briefing = await gen.generate("expert:gold:bullion_broker", market_ctx)
    """

    def __init__(self, state_db):
        """Initialize with a ShadowStateDB for persistence queries.

        Args:
            state_db: ShadowStateDB instance for accessing shadow config,
                      episodic memory, and pending signals.
        """
        self.state_db = state_db
        self._formatter = BriefingSectionFormatter(state_db)

    # ── Public API ──────────────────────────────────────────────────────────

    async def generate(
        self,
        shadow_id: str,
        market_context: dict,
        max_tokens: int = MAX_BRIEFING_TOKENS,
        figure_activity: list[dict] | None = None,
    ) -> str:
        """Generate structured Daily Briefing for one shadow.

        Sections:
            [1] PERSONA (~150 tokens) — who the shadow is, strategy, constraints
            [2] EXPERIENCE (~600 tokens) — episodic memory with Ebbinghaus decay weighting
            [3] PENDING SIGNALS (~400 tokens) — registry entries, priority-sorted
            [4] TODAY'S MARKET (~800 tokens) — domain-filtered market data
            [5] FIGURE ACTIVITY (~150 tokens) — today's market figure signals (NEW)
            [6] INSTRUCTION (~200 tokens) — key requirements repeated at end

        Lost-in-the-Middle mitigation: critical info at start ([1]) and end ([6]).
        Data-dense middle sections ([2]-[5]) are lower priority for retention.

        Args:
            shadow_id: Unique shadow identifier (e.g. "expert:gold:bullion_broker").
            market_context: Dict with market data (indices, volatility, rates, etc.).
            max_tokens: Maximum token budget for the entire briefing (default 3200).
            figure_activity: Optional list of figure activity dicts (from
                FigureNewsPusher.push_to_shadows). Only CRITICAL tier shown.
                Shadows do NOT receive AWA scores — only raw content.

        Returns:
            Structured briefing string with section markers, suitable for
            injection into the shadow's LLM context window.
        """
        formatter = self._formatter

        persona = formatter.load_persona(shadow_id)
        experience = formatter.load_experience(shadow_id)
        pending_signals = formatter.load_pending_signals(shadow_id)
        market_section = formatter.format_market_section(shadow_id, market_context)
        figure_section = formatter.format_figure_activity(figure_activity)

        # Assemble briefing with section separators
        sections = [
            f"[1] PERSONA & STRATEGY\n{persona}",
            f"[2] CUMULATIVE EXPERIENCE\n{experience}",
            f"[3] PENDING SIGNALS\n{pending_signals}",
            f"[4] TODAY'S MARKET\n{market_section}",
        ]

        # Figure activity section (only included if there are CRITICAL signals)
        if figure_section:
            sections.append(f"[5] TODAY'S FIGURE ACTIVITY\n{figure_section}")
            sections.append(f"[6] INSTRUCTION\n{formatter.format_instruction()}")
        else:
            sections.append(f"[5] INSTRUCTION\n{formatter.format_instruction()}")

        briefing = SECTION_SEP.join(sections)

        # Rough token estimation: ~0.75 tokens per character for English text
        estimated_tokens = int(len(briefing) * 0.75)
        if estimated_tokens > max_tokens:
            logger.warning(
                "Briefing for %s exceeds token budget: estimated %d > %d max. "
                "Truncating market section.",
                shadow_id, estimated_tokens, max_tokens,
            )
            # Build non-market sections for budget calculation
            non_market_sections = [sections[0], sections[1], sections[2]]
            if figure_section:
                non_market_sections.append(sections[-2])  # figure section
            non_market_sections.append(sections[-1])  # instruction
            current_no_market = len(SECTION_SEP.join(non_market_sections)) * 0.75
            available = max_tokens - int(current_no_market) - 50
            if available > 0:
                truncated_market = formatter.truncate_text(
                    formatter.format_market_section(shadow_id, market_context),
                    max_chars=int(available / 0.75),
                )
                sections[3] = f"[4] TODAY'S MARKET\n{truncated_market}"
                briefing = SECTION_SEP.join(sections)

        logger.info("Generated briefing for %s: ~%d tokens, %d chars",
                     shadow_id, estimated_tokens, len(briefing))
        return briefing

    # ── Backward-compat delegation wrappers ──────────────────────────────────

    def _load_persona(self, shadow_id: str) -> str:
        """[Deprecated] Delegate to BriefingSectionFormatter.load_persona."""
        return self._formatter.load_persona(shadow_id)

    def _load_experience(self, shadow_id: str) -> str:
        """[Deprecated] Delegate to BriefingSectionFormatter.load_experience."""
        return self._formatter.load_experience(shadow_id)

    def _load_pending_signals(self, shadow_id: str) -> str:
        """[Deprecated] Delegate to BriefingSectionFormatter.load_pending_signals."""
        return self._formatter.load_pending_signals(shadow_id)

    def _format_market_section(self, shadow_id: str, market_context: dict) -> str:
        """[Deprecated] Delegate to BriefingSectionFormatter.format_market_section."""
        return self._formatter.format_market_section(shadow_id, market_context)

    def _format_instruction(self) -> str:
        """[Deprecated] Delegate to BriefingSectionFormatter.format_instruction."""
        return self._formatter.format_instruction()

    def _format_figure_activity(
        self, figure_activity: list[dict] | None
    ) -> str:
        """[Deprecated] Delegate to BriefingSectionFormatter.format_figure_activity."""
        return self._formatter.format_figure_activity(figure_activity)

    @staticmethod
    def _truncate_text(text: str, max_chars: int = 200) -> str:
        """[Deprecated] Delegate to BriefingSectionFormatter.truncate_text."""
        return BriefingSectionFormatter.truncate_text(text, max_chars)

    @staticmethod
    def _derive_persona_from_id(shadow_id: str) -> str:
        """[Deprecated] Delegate to BriefingSectionFormatter.derive_persona_from_id."""
        return BriefingSectionFormatter.derive_persona_from_id(shadow_id)
