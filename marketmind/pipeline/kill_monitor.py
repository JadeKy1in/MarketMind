"""Kill-criteria monitor for Gate 1 hypothesis pre-mortem conditions.

Pure heuristics + data comparison — no LLM calls. The extraction helper
uses regex to parse Chinese/English pre-mortem text into structured
KillCriterion objects.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone

logger = logging.getLogger("marketmind.pipeline.kill_monitor")


# ── Dataclasses ───────────────────────────────────────────────────────────────────

@dataclass
class KillCriterion:
    criterion_id: str
    description: str
    observable: str
    data_source: str  # "FRED:XXX" | "market_data:XXX" | "news_search:XXX"
    threshold_value: float | None = None
    threshold_direction: str = "below"  # "below" | "above" | "equals"
    deadline: str | None = None  # ISO date YYYY-MM-DD
    consequence: str = "KILL"  # "KILL" | "REDUCE_50" | "REVIEW"
    status: str = "MONITORING"  # "MONITORING" | "TRIGGERED" | "EXPIRED" | "DATA_UNAVAILABLE"
    last_checked: str = ""
    last_value: float | None = None


@dataclass
class KillMonitorReport:
    monitored: list[KillCriterion]
    triggered: list[KillCriterion]
    expired: list[KillCriterion]
    requires_attention: bool
    summary: str


# ── Regex patterns for extraction ─────────────────────────────────────────────────

_THRESHOLD_RE = re.compile(r"(\d+\.?\d*)\s*(%|元|美元|点)?")
_DIRECTION_BELOW_RE = re.compile(r"(跌破|跌至|低于|下破)")
_DIRECTION_ABOVE_RE = re.compile(r"(突破|超过|高于|升至|上破)")
_DIRECTION_EQUALS_RE = re.compile(r"(达到)")
_CONSEQUENCE_RE = re.compile(r"(终止|减仓|退出|审查|平仓|离场|清仓)")
_DATE_CN_RE = re.compile(r"(\d{1,2})\s*月\s*(\d{1,2})\s*日")
_DATE_ISO_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")
_FOREX_RE = re.compile(r"([A-Z]{3}/[A-Z]{3})")
_ARROW_RE = re.compile(r"\s*[→>]\s*")

_ECON_KEYWORDS = ("CPI", "GDP", "PMI", "PPI", "失业", "就业", "通胀", "利率", "零售", "工业产出")
_EVENT_KEYWORDS = ("会议", "声明", "发布", "报告", "讲话", "政策", "纪要", "决议")


# ── Extraction helper ─────────────────────────────────────────────────────────────

def extract_kill_criteria(hypothesis_result) -> list[KillCriterion]:
    """Parse pre_mortem text from HypothesisResult into structured KillCriteria.

    Looks for patterns like:
      - 'ECB下次会议明确鸽派 → EUR可能继续走弱'
      - '德国CPI < 2.2% → 减仓50%'
      - 'EUR/USD跌破1.05 → 退出'

    Uses regex heuristics — no LLM calls.
    """
    criteria: list[KillCriterion] = []
    texts = [
        getattr(hypothesis_result, "bear_case", ""),
        getattr(hypothesis_result, "hypothesis", ""),
        getattr(hypothesis_result, "refined_hypothesis", ""),
    ]
    combined = "\n".join(t for t in texts if t)
    if not combined.strip():
        return criteria

    lines = re.split(r"[。\n;；]", combined)

    for i, line in enumerate(lines):
        line = line.strip()
        if len(line) < 10:
            continue

        has_arrow = bool(_ARROW_RE.search(line))
        has_dir = (
            bool(_DIRECTION_BELOW_RE.search(line))
            or bool(_DIRECTION_ABOVE_RE.search(line))
            or bool(_DIRECTION_EQUALS_RE.search(line))
        )
        has_cons = bool(_CONSEQUENCE_RE.search(line))

        if not (has_arrow or (has_dir and has_cons)):
            continue

        parts = _ARROW_RE.split(line, maxsplit=1)
        condition = parts[0].strip()
        consequence_text = parts[1].strip() if len(parts) > 1 else line

        # ── Direction ──
        dir_below = _DIRECTION_BELOW_RE.search(condition)
        dir_above = _DIRECTION_ABOVE_RE.search(condition)
        dir_equals = _DIRECTION_EQUALS_RE.search(condition)
        dir_match = dir_below or dir_above or dir_equals

        if dir_below:
            direction = "below"
        elif dir_above:
            direction = "above"
        elif dir_equals:
            direction = "equals"
        else:
            direction = "below"

        # ── Threshold (search near the directional keyword, not whole string) ──
        threshold_value = None
        search_region = condition
        if dir_match:
            search_region = condition[dir_match.end():]
        thresh_match = _THRESHOLD_RE.search(search_region)
        if thresh_match:
            threshold_value = float(thresh_match.group(1))

        # ── Consequence ──
        cons_match = _CONSEQUENCE_RE.search(consequence_text)
        if cons_match:
            kw = cons_match.group(1)
            if kw in ("终止", "清仓", "离场", "退出", "平仓"):
                consequence = "KILL"
            elif kw == "减仓":
                consequence = "REDUCE_50"
            elif kw == "审查":
                consequence = "REVIEW"
            else:
                consequence = "REVIEW"
        else:
            consequence = "REVIEW"

        # ── Deadline ──
        deadline: str | None = None
        date_cn = _DATE_CN_RE.search(line)
        date_iso = _DATE_ISO_RE.search(line)
        if date_iso:
            deadline = date_iso.group(1)
        elif date_cn:
            month = int(date_cn.group(1))
            day = int(date_cn.group(2))
            year = datetime.now(timezone.utc).year
            deadline = f"{year}-{month:02d}-{day:02d}"

        # ── Data source ──
        forex_match = _FOREX_RE.search(condition)
        if forex_match:
            data_source = f"market_data:{forex_match.group(1)}"
        elif any(kw in condition for kw in _ECON_KEYWORDS):
            data_source = "FRED:GENERIC"
        elif any(kw in condition for kw in _EVENT_KEYWORDS):
            data_source = "news_search:GENERIC"
        else:
            data_source = "news_search:GENERIC"

        criteria.append(KillCriterion(
            criterion_id=f"KC-{i:03d}",
            description=line[:120],
            observable=condition[:200],
            data_source=data_source,
            threshold_value=threshold_value,
            threshold_direction=direction,
            deadline=deadline,
            consequence=consequence,
        ))

    return criteria


# ── Monitor function ──────────────────────────────────────────────────────────────

async def monitor_kill_criteria(
    criteria: list[KillCriterion],
    market_data: dict | None = None,
) -> KillMonitorReport:
    """Check all criteria against current data and deadlines.

    Args:
        criteria: List of KillCriterion to evaluate.
        market_data: Optional dict mapping data-source keys to current values,
                     e.g. {"EUR/USD": 1.0480, "AAPL": 195.50}.

    Returns:
        KillMonitorReport with categorized criteria and summary.
    """
    now = datetime.now(timezone.utc)
    now_str = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    today = now.date()

    triggered: list[KillCriterion] = []
    expired: list[KillCriterion] = []

    for c in criteria:
        c.last_checked = now_str

        # ── Deadline check ──
        if c.deadline and c.status == "MONITORING":
            try:
                deadline_dt = datetime.strptime(c.deadline, "%Y-%m-%d").date()
                if today > deadline_dt:
                    c.status = "EXPIRED"
                    expired.append(c)
                    continue
            except ValueError:
                pass

        # ── Market data threshold check ──
        if (
            c.data_source.startswith("market_data:")
            and market_data
            and c.threshold_value is not None
        ):
            key = c.data_source.split(":", 1)[1]
            value = market_data.get(key)
            if value is not None:
                c.last_value = float(value)
                triggered_flag = False
                if c.threshold_direction == "below" and value < c.threshold_value:
                    triggered_flag = True
                elif c.threshold_direction == "above" and value > c.threshold_value:
                    triggered_flag = True
                elif c.threshold_direction == "equals" and value == c.threshold_value:
                    triggered_flag = True

                if triggered_flag:
                    c.status = "TRIGGERED"
                    triggered.append(c)
                    logger.warning(
                        "Kill criterion TRIGGERED: %s — %s", c.criterion_id, c.description
                    )

    # ── Categorize ──
    all_monitored = [c for c in criteria if c.status == "MONITORING"]
    all_triggered = [c for c in criteria if c.status == "TRIGGERED"]
    all_expired = [c for c in criteria if c.status == "EXPIRED"]

    requires_attention = len(all_triggered) > 0

    if all_triggered:
        summary = f"ALERT: {len(all_triggered)} kill criteria triggered — review immediately"
    elif all_expired:
        summary = f"OK: {len(all_expired)} criteria expired without trigger"
    else:
        summary = f"INFO: {len(all_monitored)} criteria under monitoring, no triggers"

    return KillMonitorReport(
        monitored=all_monitored,
        triggered=all_triggered,
        expired=all_expired,
        requires_attention=requires_attention,
        summary=summary,
    )
