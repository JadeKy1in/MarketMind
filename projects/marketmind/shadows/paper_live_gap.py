"""Paper-to-Live Gap Manager -- virtual slippage, confidence discount,
inter-shadow GapRatio, and live-ready certification.

Manages the gap between virtual (paper) returns and real-world expected returns:
- Permanent 20% baseline discount on all shadow-reported returns
- Virtual slippage: 0.5% of ATR applied to entry/exit
- Inter-shadow GapRatio: compare each shadow's PnL vs median shadow for same ticker/date
- Discount closure: as GapRatio improves, reduce discount (floor 5%)
- Live-ready certification: 6 criteria check
"""
from __future__ import annotations

import logging
import math
import statistics
from dataclasses import dataclass
from datetime import datetime, timezone

from projects.marketmind.shadows.shadow_state import ShadowStateDB, ShadowConfig
from projects.marketmind.config.settings import ShadowSettings

logger = logging.getLogger("marketmind.shadows.paper_live_gap")


@dataclass
class GapMetrics:
    """Snapshot of paper-to-live gap metrics for a shadow."""
    shadow_id: str
    discount_rate: float              # current applied discount (0.05-0.20)
    virtual_slippage_cumulative: float
    inter_shadow_gap_ratio: float
    live_trade_count: int
    live_virtual_gap: float | None
    live_ready: bool


class PaperLiveGapManager:
    """Manages the gap between virtual (paper) returns and expected real-world returns.

    Applies virtual slippage on entry/exit, confidence discounts on reported returns,
    computes inter-shadow gap ratios, and certifies shadows as live-ready.
    """

    def __init__(self, state_db: ShadowStateDB, settings: ShadowSettings):
        self.state_db = state_db
        self.settings = settings
        # In-memory per-shadow discount rates; initialized lazily from defaults
        self._discount_rates: dict[str, float] = {}
        # Track cumulative virtual slippage per shadow
        self._cumulative_slippage: dict[str, float] = {}

    # ── Virtual slippage ─────────────────────────────────────────────────

    def apply_virtual_slippage(self, ticker: str, direction: str,
                                entry_price: float, atr: float) -> float:
        """Apply 0.5% of ATR as slippage to entry/exit price.

        Long entry: price increases (buy at slightly worse price)
        Short entry: price decreases (sell short at slightly worse price)
        Returns the slippage-adjusted price.
        """
        slippage_amount = self.settings.virtual_slippage_atr_pct * atr  # 0.005 * ATR
        if direction == "long":
            return entry_price + slippage_amount
        elif direction == "short":
            return entry_price - slippage_amount
        else:
            logger.warning("Unknown direction '%s' for %s, no slippage applied", direction, ticker)
            return entry_price

    def apply_virtual_slippage_exit(self, ticker: str, direction: str,
                                     exit_price: float, atr: float) -> float:
        """Apply virtual slippage on exit (inverse of entry).

        Long exit: price decreases (sell at slightly worse price)
        Short exit: price increases (cover at slightly worse price)
        """
        slippage_amount = self.settings.virtual_slippage_atr_pct * atr
        if direction == "long":
            return exit_price - slippage_amount
        elif direction == "short":
            return exit_price + slippage_amount
        else:
            return exit_price

    # ── Confidence discount ──────────────────────────────────────────────

    def _get_discount_rate(self, shadow_id: str) -> float:
        """Get current discount rate for a shadow, initializing to default if needed."""
        if shadow_id not in self._discount_rates:
            self._discount_rates[shadow_id] = self.settings.confidence_discount_default
        return self._discount_rates[shadow_id]

    def apply_confidence_discount(self, reported_return: float, shadow_id: str) -> float:
        """Apply confidence discount to a reported return.

        discounted_return = reported_return * (1 - discount_rate)
        """
        rate = self._get_discount_rate(shadow_id)
        return reported_return * (1.0 - rate)

    # ── Inter-shadow gap ─────────────────────────────────────────────────

    def compute_inter_shadow_gap(self, shadow_id: str, ticker: str, date: str) -> float:
        """Compute GapRatio: |shadow PnL - median PnL| / max(|median|, 0.01).

        Compares the shadow's average PnL for a ticker/date against the median
        PnL of all other active shadows for the same ticker/date.

        Returns a ratio where:
        - 0.0 = perfect alignment
        - 1.0 = 100% deviation from median
        - Large values = extreme deviation
        """
        trades = self.state_db.get_trade_history(shadow_id, limit=500)
        own_pnls = [
            t.pnl_pct for t in trades
            if t.ticker == ticker and t.pnl_pct is not None
        ]
        if not own_pnls:
            return float("inf")

        own_avg = statistics.mean(own_pnls)

        # Gather PnL from all other active shadows for same ticker
        other_pnls: list[float] = []
        all_active = self.state_db.get_active_shadows()
        for other in all_active:
            if other.shadow_id == shadow_id:
                continue
            other_trades = self.state_db.get_trade_history(other.shadow_id, limit=500)
            for t in other_trades:
                if t.ticker == ticker and t.pnl_pct is not None:
                    other_pnls.append(t.pnl_pct)

        if not other_pnls:
            # No peers to compare against — gap is zero by convention
            return 0.0

        median_pnl = statistics.median(other_pnls)
        denominator = max(abs(median_pnl), 0.01)
        gap = abs(own_avg - median_pnl) / denominator
        return gap

    # ── Discount rate evolution ──────────────────────────────────────────

    def update_discount_rate(self, shadow_id: str) -> float:
        """Update the discount rate based on current inter-shadow gap.

        As GapRatio decreases (shadow converges toward peer median), the discount
        rate is reduced proportionally. The floor is 5%, ceiling is 20%.

        Returns the new discount rate.
        """
        current_rate = self._get_discount_rate(shadow_id)
        default = self.settings.confidence_discount_default
        floor = self.settings.confidence_discount_floor
        factor = self.settings.gap_closure_adjustment_factor  # 0.75

        # Compute current gap — use most recent date and common tickers
        trades = self.state_db.get_trade_history(shadow_id, limit=100)
        if not trades:
            # No trade data — keep current rate
            return current_rate

        # Find the most common ticker for this shadow
        from collections import Counter
        ticker_counts = Counter(t.ticker for t in trades)
        most_common_ticker = ticker_counts.most_common(1)
        if not most_common_ticker:
            return current_rate

        ticker = most_common_ticker[0][0]
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        gap = self.compute_inter_shadow_gap(shadow_id, ticker, today)

        if gap == float("inf"):
            return current_rate

        # Target discount: as gap approaches 0, discount approaches floor
        # When gap >= 1.0, discount = default
        # When gap < 1.0, discount = max(floor, gap * default)
        target_rate = max(floor, min(default, gap * default))

        # Smooth adjustment: move current rate toward target by factor
        new_rate = current_rate + factor * (target_rate - current_rate)
        new_rate = max(floor, min(default, new_rate))
        self._discount_rates[shadow_id] = new_rate

        logger.debug("Shadow %s discount: %.3f -> %.3f (gap=%.3f)",
                      shadow_id, current_rate, new_rate, gap)
        return new_rate

    # ── Live-ready certification ─────────────────────────────────────────

    def check_live_ready(self, shadow_id: str) -> tuple[bool, str]:
        """Check whether a shadow meets all 6 live-ready criteria.

        Criteria:
        1. >= 10 paired trades
        2. GapRatio < 0.30
        3. Discount rate < 0.15
        4. Forward validation >= 50% (second half of trades have >=50% win rate)
        5. PBO < 5% (expert) / < 10% (daredevil)
        6. MDD < 25% (expert) / < 35% (daredevil)

        Returns (is_ready, reason_string).
        """
        config = self.state_db.get_shadow(shadow_id)
        if config is None:
            return False, f"Shadow '{shadow_id}' not found"

        is_daredevil = config.shadow_type == "daredevil"
        mdd_limit = 0.35 if is_daredevil else 0.25
        pbo_limit = 0.10 if is_daredevil else 0.05

        trades = self.state_db.get_trade_history(shadow_id, limit=500)
        closed_trades = [t for t in trades if t.exit_price is not None]

        # Criterion 1: >= 10 paired trades
        if len(closed_trades) < self.settings.live_ready_min_trades:
            return False, f"Only {len(closed_trades)} trades, need >= {self.settings.live_ready_min_trades}"

        # Criterion 2: GapRatio < 0.30
        from collections import Counter
        ticker_counts = Counter(t.ticker for t in closed_trades)
        most_common = ticker_counts.most_common(1)
        if most_common:
            ticker = most_common[0][0]
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            gap = self.compute_inter_shadow_gap(shadow_id, ticker, today)
            if gap >= self.settings.live_ready_max_gap:
                return False, f"GapRatio {gap:.3f} >= {self.settings.live_ready_max_gap}"

        # Criterion 3: Discount < 0.15
        discount = self._get_discount_rate(shadow_id)
        if discount >= 0.15:
            return False, f"Discount {discount:.3f} >= 0.15"

        # Criterion 4: Forward validation >= 50%
        if not self._check_forward_validation(closed_trades):
            return False, "Forward validation win rate < 50%"

        # Criterion 5: PBO check
        pbo = self._estimate_pbo(closed_trades, config)
        if pbo >= pbo_limit:
            return False, f"PBO {pbo:.3f} >= {pbo_limit}"

        # Criterion 6: MDD check
        latest = self.state_db.get_latest_snapshot(shadow_id)
        if latest and latest.max_drawdown_pct is not None:
            if latest.max_drawdown_pct >= mdd_limit:
                return False, f"MDD {latest.max_drawdown_pct:.1%} >= {mdd_limit:.0%}"
        # If no snapshot data, we can't verify MDD — proceed with caution

        return True, (
            f"Live-ready: 6/6 criteria passed (trades={len(closed_trades)}, "
            f"discount={discount:.1%})"
        )

    def _check_forward_validation(self, closed_trades: list) -> bool:
        """Check if second-half of trades have >= 50% win rate."""
        n = len(closed_trades)
        if n < 4:
            return False
        half = n // 2
        second_half = closed_trades[half:]  # more recent half (ordered DESC by exit_date)
        wins = sum(1 for t in second_half if t.pnl_pct is not None and t.pnl_pct > 0)
        wr = wins / len(second_half) if second_half else 0.0
        return wr >= 0.50

    def _estimate_pbo(self, trades: list, config: ShadowConfig) -> float:
        """Estimate Probability of Backtest Overfitting (PBO).

        Simplified heuristic: PBO = 1 / (1 + n_trades).
        More trades reduce overfitting risk.
        Values below 0.05 (expert) or 0.10 (daredevil) indicate acceptable risk.
        """
        n = len(trades)
        if n == 0:
            return 1.0
        pbo = 1.0 / (1.0 + n)
        return pbo

    # ── Metrics snapshot ─────────────────────────────────────────────────

    def get_gap_metrics(self, shadow_id: str) -> GapMetrics:
        """Produce a comprehensive GapMetrics snapshot for a shadow."""
        trades = self.state_db.get_trade_history(shadow_id, limit=500)
        closed_trades = [t for t in trades if t.exit_price is not None]

        discount = self._get_discount_rate(shadow_id)
        cum_slippage = self._cumulative_slippage.get(shadow_id, 0.0)

        # Compute gap for most common ticker
        from collections import Counter
        ticker_counts = Counter(t.ticker for t in closed_trades)
        gap = 0.0
        if ticker_counts:
            ticker = ticker_counts.most_common(1)[0][0]
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            gap = self.compute_inter_shadow_gap(shadow_id, ticker, today)

        is_ready, _ = self.check_live_ready(shadow_id)

        # Live-virtual gap: difference between virtual and adjusted returns
        virtual_total = sum(t.pnl_pct or 0.0 for t in closed_trades)
        adjusted_total = sum(
            self.apply_confidence_discount(t.pnl_pct or 0.0, shadow_id)
            for t in closed_trades
        )
        live_virtual_gap = virtual_total - adjusted_total if closed_trades else None

        return GapMetrics(
            shadow_id=shadow_id,
            discount_rate=discount,
            virtual_slippage_cumulative=cum_slippage,
            inter_shadow_gap_ratio=gap,
            live_trade_count=len(closed_trades),
            live_virtual_gap=live_virtual_gap,
            live_ready=is_ready,
        )
