"""AEL Evolution Engine — controlled slow-layer experiment (Phase 7).

Implements AEL (Agent Evolving Learning) slow layer: monthly Pro debrief
→ diagnostic reflection → "lessons learned" injection into shadow prompts.

Key constraints (Red Team mandated):
- SLOW LAYER ONLY (monthly, not weekly). Fast layer deferred.
- MUST have control group (replica shadows receive no evolution).
- Challengers inherit ORIGINAL prompts, not evolved ones.
- Pro-quality debriefs require Item 10 (Pro default) already done.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

logger = logging.getLogger("marketmind.shadows.ael_evolution")


# ── Data classes ────────────────────────────────────────────────────────────

@dataclass
class AELDebriefResult:
    """Output from one monthly AEL debrief session."""
    shadow_id: str
    month: str
    win_rate: float
    cumulative_return: float
    total_trades: int
    failure_patterns: list[str]       # LLM-identified failure causes
    success_patterns: list[str]       # LLM-identified success causes
    lessons_learned: str              # concise Pro-generated lesson text
    prompt_injected: bool = False     # was the lesson injected into prompt?


@dataclass
class ReplicaPair:
    """A treatment/control pair for AEL experiment."""
    treatment_id: str    # gets AEL slow layer
    control_id: str      # replica, no AEL
    base_shadow_id: str  # original shadow being replicated
    created_at: str = ""
    months_active: int = 0


@dataclass
class ExperimentResult:
    """Statistical comparison of treatment vs control after N months."""
    treatment_id: str
    control_id: str
    months: int
    treatment_wr: float
    control_wr: float
    treatment_cum_return: float
    control_cum_return: float
    wr_difference: float
    p_value: float | None = None
    significant: bool = False
    recommendation: str = ""  # "EXPAND" | "CONTINUE" | "STOP"


# ── AEL Engine ───────────────────────────────────────────────────────────────

class AELEvolutionEngine:
    """Manages AEL slow-layer evolution with controlled experiments."""

    MAX_ACTIVE_LESSONS = 5   # per shadow cap on injected lessons

    # Shadow pairs for initial AEL experiment (Phase 7)
    EXPERIMENT_PAIRS = [
        # Daredevils: range-bound and momentum
        ("daredevil:range_bound:sideways_scout", "daredevil:momentum:trend_chaser"),
        # Experts: tech and macro
        ("expert:tech:silicon_oracle", "expert:macro:cycle_reader"),
    ]

    def __init__(self, state_db=None):
        self._state_db = state_db
        self._replica_pairs: dict[str, ReplicaPair] = {}
        self._debrief_history: dict[str, list[AELDebriefResult]] = {}
        self._active_lessons: dict[str, list[str]] = {}  # shadow_id -> [lesson_texts]
        # P1-5: Load persisted lessons from DB on init
        if state_db:
            self._load_persisted_lessons()

    def _load_persisted_lessons(self) -> None:
        """Load AEL lessons from DB to survive process restart (P1-5)."""
        conn = None
        try:
            conn = self._state_db._connect()
            rows = conn.execute(
                """SELECT shadow_id, reason FROM methodology_changes
                   WHERE change_type = 'ael_lesson' AND changed_at > date('now', '-90 days')
                   ORDER BY changed_at DESC"""
            ).fetchall()
            for row in rows:
                sid = row["shadow_id"]
                lesson = row["reason"].replace("AEL lesson: ", "")
                if sid not in self._active_lessons:
                    self._active_lessons[sid] = []
                if len(self._active_lessons[sid]) < self.MAX_ACTIVE_LESSONS:
                    self._active_lessons[sid].append(lesson)
        except Exception:
            pass
        finally:
            if conn:
                conn.close()

    def create_replica(self, base_shadow_id: str) -> ReplicaPair:
        """Create a replica of a shadow for controlled A/B testing.

        The replica has identical methodology but no AEL treatment.
        """
        ts = datetime.now(timezone.utc).strftime("%Y%m%d")
        treatment_id = base_shadow_id
        control_id = f"{base_shadow_id}:replica:{ts}"

        pair = ReplicaPair(
            treatment_id=treatment_id,
            control_id=control_id,
            base_shadow_id=base_shadow_id,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        self._replica_pairs[treatment_id] = pair
        logger.info("AEL replica pair created: %s / %s", treatment_id, control_id)
        return pair

    async def run_monthly_debrief(
        self, shadow_id: str, performances: dict, market_context: str = ""
    ) -> AELDebriefResult:
        """Run one monthly Pro debrief for a shadow.

        Analyzes last 30 days of decisions, identifies failure/success
        patterns, and generates concise lessons learned.

        Args:
            shadow_id: The shadow to debrief
            performances: Dict with keys: win_rate, cumulative_return,
                          total_trades, daily_returns, profitable_trades,
                          losing_trades
            market_context: Brief market summary for the month
        """
        from marketmind.gateway.async_client import chat_with_integrity

        month = datetime.now(timezone.utc).strftime("%Y-%m")
        wr = performances.get("win_rate", 0.0)
        cum_ret = performances.get("cumulative_return", 0.0)
        total = performances.get("total_trades", 0)
        profitable = performances.get("profitable_trades", 0)
        losing = performances.get("losing_trades", 0)

        system_prompt = (
            "You are a diagnostic analyst reviewing a shadow agent's monthly trading "
            "performance. Your job: identify the TOP 1-2 failure patterns and TOP 1-2 "
            "success patterns from this month's data. Be specific and data-driven. "
            "Output: FAILURE_PATTERNS: (bullet list), SUCCESS_PATTERNS: (bullet list), "
            "LESSON: (1-2 sentence actionable lesson for the shadow to improve next month). "
            "Keep LESSON under 80 words. Focus on PATTERNS, not individual trades."
        )

        user_prompt = (
            f"Shadow: {shadow_id}\n"
            f"Month: {month}\n"
            f"Win Rate: {wr:.1%}\n"
            f"Cumulative Return: {cum_ret:+.2%}\n"
            f"Total Trades: {total} ({profitable} profitable, {losing} losing)\n"
            f"Market Context: {market_context or 'Normal conditions'}\n\n"
            f"Analyze failure patterns, success patterns, and produce ONE concise lesson."
        )

        try:
            result = await chat_with_integrity(
                model="pro",
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                caller_agent=f"ael_debrief:{shadow_id}",
                temperature=0.3,
                reasoning_effort="low",
            )
            content = result.get("content", "")
        except Exception as e:
            logger.error("AEL debrief failed for %s: %s", shadow_id, e)
            content = ""

        # Parse LLM output
        failures, successes, lesson = self._parse_debrief(content)
        if not lesson:
            lesson = f"Continue current strategy. WR={wr:.1%} with {total} trades."

        debrief = AELDebriefResult(
            shadow_id=shadow_id,
            month=month,
            win_rate=wr,
            cumulative_return=cum_ret,
            total_trades=total,
            failure_patterns=failures,
            success_patterns=successes,
            lessons_learned=lesson,
        )
        self._debrief_history.setdefault(shadow_id, []).append(debrief)
        return debrief

    @staticmethod
    def _parse_debrief(text: str) -> tuple[list[str], list[str], str]:
        """Parse structured output from Pro debrief."""
        import re
        failures, successes, lesson = [], [], ""

        # Extract FAILURE_PATTERNS section
        fp_match = re.search(
            r'FAILURE_PATTERNS?:?\s*\n(.*?)(?=SUCCESS_PATTERNS|LESSON|$)', text, re.DOTALL
        )
        if fp_match:
            failures = [l.strip("-• ").strip() for l in fp_match.group(1).strip().split("\n") if l.strip()]

        # Extract SUCCESS_PATTERNS section
        sp_match = re.search(
            r'SUCCESS_PATTERNS?:?\s*\n(.*?)(?=FAILURE_PATTERNS|LESSON|$)', text, re.DOTALL
        )
        if sp_match:
            successes = [l.strip("-• ").strip() for l in sp_match.group(1).strip().split("\n") if l.strip()]

        # Extract LESSON
        l_match = re.search(r'LESSON:?\s*\n?(.*?)$', text, re.DOTALL)
        if l_match:
            lesson = l_match.group(1).strip()[:300]

        return failures[:3], successes[:3], lesson

    def inject_lesson(self, shadow_id: str, lesson: str) -> bool:
        """Inject a lesson into a shadow's active lesson list.

        Returns True if injected, False if cap reached and lesson rejected.
        """
        if shadow_id not in self._active_lessons:
            self._active_lessons[shadow_id] = []

        lessons = self._active_lessons[shadow_id]

        # Check for duplicates
        if lesson in lessons:
            return False

        if len(lessons) < self.MAX_ACTIVE_LESSONS:
            lessons.append(lesson)
            # P1-5: Persist lesson via state_db (uses proper connection handling)
            if self._state_db:
                try:
                    self._state_db.update_methodology_prompt(
                        shadow_id,
                        f"[AEL LESSON] {lesson}",
                        reason=f"AEL lesson: {lesson[:100]}"
                    )
                except Exception:
                    pass
            return True

        # Cap reached: reject silently (no head-to-head test infrastructure yet)
        logger.info("AEL lesson cap reached for %s (%d lessons)", shadow_id, len(lessons))
        return False

    def get_active_lessons(self, shadow_id: str) -> list[str]:
        """Get currently active lessons for a shadow."""
        return self._active_lessons.get(shadow_id, [])

    def get_augmented_prompt(self, shadow_id: str, base_prompt: str) -> str:
        """Get the augmented methodology prompt with active lessons appended.

        Used by the orchestrator to inject lessons before sending to LLM.
        Lessons are appended as '[LESSONS LEARNED]' section at the end.
        """
        lessons = self.get_active_lessons(shadow_id)
        if not lessons:
            return base_prompt

        lessons_text = "\n".join(f"- {l}" for l in lessons)
        return (
            f"{base_prompt}\n\n"
            f"[LESSONS LEARNED — apply these in your analysis]\n"
            f"{lessons_text}"
        )

    def compare_pair(self, pair: ReplicaPair,
                     treatment_perf: dict,
                     control_perf: dict) -> ExperimentResult:
        """Compare treatment vs control after experiment period."""
        import math

        t_wr = treatment_perf.get("win_rate", 0.0)
        c_wr = control_perf.get("win_rate", 0.0)
        t_ret = treatment_perf.get("cumulative_return", 0.0)
        c_ret = control_perf.get("cumulative_return", 0.0)
        t_n = treatment_perf.get("total_trades", 0)
        c_n = control_perf.get("total_trades", 0)

        diff = t_wr - c_wr

        # Simple z-test for proportions
        p_value = None
        significant = False
        if t_n >= 10 and c_n >= 10:
            p_pool = (t_wr * t_n + c_wr * c_n) / (t_n + c_n)
            se = math.sqrt(p_pool * (1 - p_pool) * (1/t_n + 1/c_n))
            if se > 0:
                z = diff / se
                # Approximate p-value from z-score
                p_value = 2 * (1 - 0.5 * (1 + math.erf(abs(z) / math.sqrt(2))))
                significant = p_value < 0.10  # alpha=0.10 per design spec

        recommendation = "CONTINUE"
        if significant and diff > 0:
            recommendation = "EXPAND"
        elif pair.months_active >= 3 and diff <= 0:
            recommendation = "STOP"

        return ExperimentResult(
            treatment_id=pair.treatment_id,
            control_id=pair.control_id,
            months=pair.months_active,
            treatment_wr=t_wr,
            control_wr=c_wr,
            treatment_cum_return=t_ret,
            control_cum_return=c_ret,
            wr_difference=diff,
            p_value=p_value,
            significant=significant,
            recommendation=recommendation,
        )
