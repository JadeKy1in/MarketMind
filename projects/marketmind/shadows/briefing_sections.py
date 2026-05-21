"""Briefing section formatters for DailyBriefingGenerator.

Extracted from daily_briefing.py to stay under the 500-line hard ceiling.
Provides persona loading, experience retrieval (with Ebbinghaus decay),
pending signals formatting, market data rendering, and figure activity display.

Pure formatting/loading logic — takes data dicts or shadow_id as input,
queries the DB via state_db passed at construction time.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("marketmind.shadows.briefing_sections")

# ── Section token budgets (cumulative max = 3200) ─────────────────────────
PERSONA_BUDGET = 150      # tokens
EXPERIENCE_BUDGET = 600   # tokens
PENDING_SIGNALS_BUDGET = 400   # tokens
MARKET_BUDGET = 800       # tokens
INSTRUCTION_BUDGET = 200  # tokens
MAX_BRIEFING_TOKENS = 3200

# ── Section markers for structured parsing ───────────────────────────────
SECTION_SEP = "\n---\n"


class BriefingSectionFormatter:
    """Format individual sections of a shadow's Daily Briefing.

    Handles persona loading, experience retrieval (with Ebbinghaus decay),
    pending signals, market data formatting, instruction footers, and
    figure activity rendering.

    Usage:
        formatter = BriefingSectionFormatter(state_db)
        persona = formatter.load_persona(shadow_id)
    """

    def __init__(self, state_db):
        """Initialize with a ShadowStateDB for persistence queries.

        Args:
            state_db: ShadowStateDB instance for accessing shadow config,
                      episodic memory, and pending signals.
        """
        self.state_db = state_db

    # ── Section loaders ──────────────────────────────────────────────────────

    def load_persona(self, shadow_id: str) -> str:
        """Load shadow persona from config.

        Extracts the fixed persona definition including strategy archetype,
        temperature, capital constraints, and behavioral traits.

        Args:
            shadow_id: Unique shadow identifier.

        Returns:
            Persona description string (~150 tokens).
        """
        try:
            conn = self.state_db._connect()
            try:
                row = conn.execute(
                    "SELECT config_json FROM shadow_configs WHERE shadow_id = ?",
                    (shadow_id,),
                ).fetchone()
                if row:
                    config = json.loads(row["config_json"] or "{}")
                    persona_text = config.get("persona") or config.get("description", "")
                    if persona_text:
                        return self.truncate_text(persona_text, max_chars=200)
            finally:
                conn.close()
        except Exception as e:
            logger.warning("Failed to load persona for %s: %s", shadow_id, e)

        # Fallback: derive persona from shadow_id structure
        return self.derive_persona_from_id(shadow_id)

    def load_experience(self, shadow_id: str) -> str:
        """Load episodic memory with Ebbinghaus decay weighting.

        Retrieves recent episodic observations and weights them by recency
        using an Ebbinghaus forgetting curve: weight = e^(-age_days / decay_days).

        More recent experiences get higher weight; older experiences fade.
        This prevents the shadow from being anchored to stale observations
        while preserving pattern recognition capability.

        Args:
            shadow_id: Unique shadow identifier.

        Returns:
            Formatted experience summary string (~600 tokens).
        """
        import math

        lines: list[str] = []
        decay_days = 30.0  # Half-life of episodic memory in days
        now = datetime.now(timezone.utc)

        try:
            conn = self.state_db._connect()
            try:
                rows = conn.execute(
                    """SELECT o.shadow_id, o.value, o.confidence, o.source_type,
                              o.extracted_text, o.created_at, n.proposition
                       FROM belief_observations o
                       JOIN belief_nodes n ON o.node_id = n.node_id
                       WHERE o.shadow_id = ? AND n.tier = 'episodic'
                       ORDER BY o.created_at DESC
                       LIMIT 30""",
                    (shadow_id,),
                ).fetchall()

                for row in rows:
                    try:
                        created_dt = datetime.fromisoformat(
                            (row["created_at"] or "").replace("Z", "+00:00")
                        )
                        age_hours = (now - created_dt.replace(tzinfo=now.tzinfo)).total_seconds() / 3600.0
                        age_days = max(0.0, age_hours / 24.0)
                        ebbinghaus_weight = math.exp(-age_days / decay_days)
                    except (ValueError, TypeError):
                        ebbinghaus_weight = 0.1

                    weight_label = ""
                    if ebbinghaus_weight > 0.7:
                        weight_label = " [HIGH-RELEVANCE]"
                    elif ebbinghaus_weight > 0.3:
                        weight_label = " [MODERATE]"
                    else:
                        weight_label = " [LOW]"

                    text = (row["extracted_text"] or "").strip()
                    if text:
                        truncated = self.truncate_text(text, max_chars=150)
                        lines.append(
                            f"- {truncated} "
                            f"(confidence: {row['confidence']:.2f}, "
                            f"decay_weight: {ebbinghaus_weight:.2f}){weight_label}"
                        )
            finally:
                conn.close()
        except Exception as e:
            logger.warning("Failed to load experience for %s: %s", shadow_id, e)

        if not lines:
            return "No prior episodic memories available (first session or cold start)."

        return "\n".join(lines)

    def load_pending_signals(self, shadow_id: str) -> str:
        """Load pending signals from registry, priority-sorted.

        Applies the truncation rules from final plan (§7.4):
        1. Pre-filter: exclude expired and cancelled
        2. Priority sort: signal_importance / (days_until_expected + 1)
        3. Truncate to fit 400 token budget
        4. Warn if expected_date <= 3 days and signal is truncated

        Args:
            shadow_id: Unique shadow identifier (or 'system' for orphaned signals).

        Returns:
            Formatted pending signals table string (~400 tokens).
        """
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        signals: list[dict] = []

        try:
            conn = self.state_db._connect()
            try:
                rows = conn.execute(
                    """SELECT id, signal_type, signal_description, trigger_condition,
                              related_ticker, expected_date, status, created_date
                       FROM pending_signals
                       WHERE (shadow_id = ? OR (shadow_id = 'system' AND status = 'orphaned'))
                         AND status NOT IN ('expired', 'cancelled')
                       ORDER BY expected_date ASC""",
                    (shadow_id,),
                ).fetchall()

                # Priority scoring: higher importance / closer date = higher priority
                for row in rows:
                    importance = 3  # default importance weight
                    try:
                        expected_dt = datetime.strptime(
                            row["expected_date"] or "2099-01-01", "%Y-%m-%d"
                        ).replace(tzinfo=timezone.utc)
                        days_until = max(0, (expected_dt - datetime.now(timezone.utc)).days)
                    except (ValueError, TypeError):
                        days_until = 99

                    priority = importance / (days_until + 1)
                    entry = {
                        "signal_type": row["signal_type"],
                        "description": (row["signal_description"] or "")[:120],
                        "ticker": row["related_ticker"] or "N/A",
                        "expected_date": row["expected_date"] or "unknown",
                        "status": row["status"],
                        "days_until": days_until,
                        "priority": round(priority, 4),
                    }
                    signals.append(entry)
            finally:
                conn.close()
        except Exception as e:
            logger.warning("Failed to load pending signals for %s: %s", shadow_id, e)

        if not signals:
            return "No pending signals. All previously registered signals have been resolved or expired."

        # Sort by priority descending
        signals.sort(key=lambda s: s["priority"], reverse=True)

        # Warn for imminent signals that might be truncated
        imminent = [s for s in signals if s["days_until"] <= 3]

        # Format output
        lines = [
            "| Status | Ticker | Expected | Signal Description |",
            "|--------|--------|----------|-------------------|",
        ]

        token_est = len("\n".join(lines)) * 0.75
        kept_count = 0
        truncated_imminent = False

        for sig in signals:
            line = (
                f"| {sig['status']:<7} | {sig['ticker']:<6} | "
                f"{sig['expected_date']:<8} | {sig['description']} |"
            )
            estimated_new = token_est + len(line) * 0.75
            if estimated_new > PENDING_SIGNALS_BUDGET:
                if sig["days_until"] <= 3:
                    truncated_imminent = True
                break
            lines.append(line)
            token_est = estimated_new
            kept_count += 1

        result = "\n".join(lines)

        if truncated_imminent:
            result = (
                "⚠ WARNING: Imminent signals (≤3 days) were truncated due to token budget.\n"
                + result
            )

        result += f"\n\nShowing {kept_count}/{len(signals)} pending signals."
        if len(signals) > kept_count:
            result += f" {len(signals) - kept_count} truncated."

        return result

    # ── Section formatting helpers ───────────────────────────────────────────

    def format_market_section(self, shadow_id: str, market_context: dict) -> str:
        """Format today's market data, domain-filtered for the shadow.

        Extracts relevant data from the market context based on shadow domain.
        Falls back to a compact summary of all available indices.

        Args:
            shadow_id: Shadow ID for domain filtering.
            market_context: Dict with market data (may contain keys like
                           'indices', 'volatility', 'rates', 'commodities', 'fx').

        Returns:
            Formatted market data string (~800 tokens).
        """
        lines: list[str] = []

        # Extract domain from shadow_id (e.g., "gold" from "expert:gold:bullion_broker")
        parts = shadow_id.split(":")
        domain = parts[1] if len(parts) >= 2 else "general"

        # Domain-specific data
        domain_map = {
            "gold": ["commodities", "rates"],
            "crypto": ["crypto"],
            "energy": ["commodities", "energy"],
            "bonds": ["rates", "yield_curve"],
            "vol": ["volatility"],
            "em": ["emerging_markets", "fx"],
            "tech": ["indices", "sector_tech"],
            "financials": ["rates", "sector_financials"],
            "healthcare": ["sector_healthcare"],
            "consumer": ["indices", "sector_consumer"],
            "industrials": ["indices", "sector_industrials"],
            "metals": ["commodities", "industrial_metals"],
            "agriculture": ["commodities", "agriculture"],
            "realestate": ["rates", "sector_realestate"],
            "fx": ["fx", "rates"],
            "macro": ["indices", "rates", "volatility", "commodities", "fx"],
            "intraday": ["indices", "volatility"],
            "weekly": ["indices", "volatility"],
            "event": ["volatility", "indices"],
            "sector": ["indices", "sector_all"],
            "consensus": ["sentiment", "indices"],
            "range_bound": ["volatility", "indices"],
            "panic": ["volatility", "credit"],
            "crash": ["indices", "valuation", "credit"],
        }

        relevant_keys = domain_map.get(domain, ["indices", "volatility"])

        for key in relevant_keys:
            data = market_context.get(key)
            if data is not None:
                if isinstance(data, dict):
                    lines.append(f"**{key.replace('_', ' ').title()}**:")
                    for k, v in data.items():
                        if isinstance(v, float):
                            lines.append(f"  - {k}: {v:,.2f}")
                        else:
                            lines.append(f"  - {k}: {v}")
                elif isinstance(data, list):
                    lines.append(f"**{key.replace('_', ' ').title()}**: {', '.join(str(x) for x in data[:10])}")
                else:
                    lines.append(f"**{key.replace('_', ' ').title()}**: {data}")

        if not lines:
            # Fallback: compact summary of all available data
            lines.append("**Market Summary**:")
            for k, v in market_context.items():
                if isinstance(v, dict):
                    lines.append(f"  - {k}: {len(v)} entries")
                elif isinstance(v, (int, float)):
                    lines.append(f"  - {k}: {v:,.2f}")
                else:
                    lines.append(f"  - {k}: {v}")

        return "\n".join(lines)

    def format_instruction(self) -> str:
        """Return the standardized instruction footer.

        Repeated at the end of every briefing to combat recency bias
        and ensure critical requirements are not lost in the middle.

        Returns:
            Instruction string (~200 tokens).
        """
        return (
            "You are an independent investment analyst. Your decisions are your own.\n\n"
            "KEY CONSTRAINTS:\n"
            "- Produce exactly ONE ShadowDecision today (no pooling, no abstention without "
            "MIN_POSITION fallback).\n"
            "- Min position size: $100 or 0.2% of virtual capital, whichever is larger.\n"
            "- Mark uncertain decisions with 'MIN_POSITION:UNCERTAIN' in thesis.\n"
            "- Do not reference other shadows' analyses — operate independently.\n"
            "- All tickers must be tradable; cite your data sources.\n"
            "- Your output feeds internal ranking only. It does NOT affect the main pipeline."
        )

    def format_figure_activity(
        self,
        figure_activity: list[dict] | None,
    ) -> str:
        """Format the 'Today's Figure Activity' section from CRITICAL-tier signals.

        Rules per design doc §8.1:
        - Only CRITICAL tier signals (AWA >= 0.80) are shown
        - Display: person_name, event_type, category (NOT AWA score!)
        - Max 3 entries to avoid clutter
        - Shadows receive raw content only — no scoring data

        Args:
            figure_activity: List of sanitized figure activity dicts (from
                FigureNewsPusher.push_to_shadows output). Each dict has:
                person_name, text, timestamp, event_type.

        Returns:
            Formatted figure activity string, or empty string if none.
        """
        if not figure_activity:
            return ""

        # Max 3 entries
        entries = figure_activity[:3]
        lines: list[str] = [
            "Key market figures were active today:",
        ]

        for entry in entries:
            name = entry.get("person_name", "Unknown")
            event = entry.get("event_type", "activity")
            text = (entry.get("text", "") or "")[:100]  # Truncate for brevity
            timestamp = entry.get("timestamp", "")

            ts_short = ""
            if timestamp:
                try:
                    dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                    ts_short = dt.strftime("%H:%M UTC")
                except (ValueError, TypeError):
                    ts_short = timestamp[:16] if len(timestamp) >= 16 else timestamp

            line = f"- {name} [{event}]"
            if ts_short:
                line += f" ({ts_short})"
            if text:
                line += f": {text}"
            lines.append(line)

        return "\n".join(lines)

    # ── Utilities ────────────────────────────────────────────────────────────

    @staticmethod
    def truncate_text(text: str, max_chars: int = 200) -> str:
        """Truncate text to max_chars, adding ellipsis if truncated.

        Args:
            text: Text to truncate.
            max_chars: Maximum character count.

        Returns:
            Truncated text with "..." suffix if truncated.
        """
        text = text.strip()
        if len(text) <= max_chars:
            return text
        return text[: max_chars - 3].rstrip() + "..."

    @staticmethod
    def derive_persona_from_id(shadow_id: str) -> str:
        """Derive a minimal persona description from the shadow_id structure.

        Used as fallback when shadow_configs table has no entry.

        Args:
            shadow_id: Shadow identifier (e.g. "expert:gold:bullion_broker").

        Returns:
            Derived persona string.
        """
        parts = shadow_id.split(":")
        if len(parts) >= 3:
            strategy, domain, name = parts[0], parts[1], parts[2]
        elif len(parts) == 2:
            strategy, domain, name = parts[0], parts[1], parts[1]
        else:
            return f"Shadow {shadow_id}: Independent investment analyst."

        strategy_labels = {
            "expert": "Domain expert (fundamental analysis, long-term horizon)",
            "momentum": "Momentum trader (trend-following, high turnover)",
            "contrarian": "Contrarian strategist (mean-reversion, anti-consensus)",
        }

        strategy_desc = strategy_labels.get(strategy, f"{strategy} strategy")
        return (
            f"Shadow ID: {shadow_id}\n"
            f"Strategy: {strategy_desc}\n"
            f"Domain: {domain.replace('_', ' ').title()}\n"
            f"Name: {name.replace('_', ' ').title()}"
        )
