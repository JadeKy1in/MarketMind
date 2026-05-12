"""Multi-day backtest runner — validates shadow consensus signal quality."""
from __future__ import annotations
import json
import logging
import statistics
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from marketmind.shadows.shadow_state import ShadowStateDB

logger = logging.getLogger("marketmind.backtest_runner")


class BacktestRunner:
    """Batch replay mode: validate shadow consensus predictive quality across dates."""

    def __init__(self, state_db: ShadowStateDB):
        self.state_db = state_db

    def run(self, start_date: str, end_date: str, output_path: str | None = None) -> dict:
        """Run backtest across date range. Returns metrics dict and optionally writes JSON."""
        try:
            start = datetime.strptime(start_date, "%Y-%m-%d").date()
            end = datetime.strptime(end_date, "%Y-%m-%d").date()
        except (ValueError, TypeError) as e:
            raise ValueError(f"Invalid date format. Use YYYY-MM-DD. start={start_date}, end={end_date}") from e
        if start > end:
            raise ValueError(f"start_date ({start_date}) must be <= end_date ({end_date})")

        hits = 0
        total = 0
        by_ticker: dict[str, dict] = defaultdict(lambda: {"hits": 0, "total": 0})
        confusion = {"long_correct": 0, "long_wrong": 0,
                      "short_correct": 0, "short_wrong": 0}
        consensus_returns: list[float] = []

        current = start
        while current <= end:
            date_str = current.strftime("%Y-%m-%d")
            next_str = (current + timedelta(days=1)).strftime("%Y-%m-%d")

            day_result = self._evaluate_day(date_str, next_str)
            hits += day_result["hits"]
            total += day_result["total"]
            for tkr, counts in day_result["by_ticker"].items():
                by_ticker[tkr]["hits"] += counts["hits"]
                by_ticker[tkr]["total"] += counts["total"]
            confusion["long_correct"] += day_result["confusion"]["long_correct"]
            confusion["long_wrong"] += day_result["confusion"]["long_wrong"]
            confusion["short_correct"] += day_result["confusion"]["short_correct"]
            confusion["short_wrong"] += day_result["confusion"]["short_wrong"]
            if day_result.get("consensus_return") is not None:
                consensus_returns.append(day_result["consensus_return"])

            current += timedelta(days=1)

        hit_rate = hits / total if total > 0 else 0.0
        sharpe = self._compute_sharpe(consensus_returns)

        # Per-ticker hit rates
        ticker_rates = {}
        for tkr, counts in sorted(by_ticker.items()):
            if counts["total"] > 0:
                ticker_rates[tkr] = {
                    "hit_rate": round(counts["hits"] / counts["total"], 3),
                    "n": counts["total"],
                }

        # Confusion matrix metrics
        long_total = confusion["long_correct"] + confusion["long_wrong"]
        short_total = confusion["short_correct"] + confusion["short_wrong"]
        long_precision = confusion["long_correct"] / long_total if long_total > 0 else 0.0
        short_precision = confusion["short_correct"] / short_total if short_total > 0 else 0.0

        report = {
            "start_date": start_date,
            "end_date": end_date,
            "days_evaluated": (end - start).days + 1,
            "total_predictions": total,
            "hit_rate": round(hit_rate, 4),
            "sharpe_of_consensus": round(sharpe, 4),
            "by_ticker": ticker_rates,
            "confusion_matrix": {
                "long_precision": round(long_precision, 4),
                "short_precision": round(short_precision, 4),
                "long_predictions": long_total,
                "short_predictions": short_total,
            },
        }

        if output_path:
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2)
            logger.info("Backtest report written to %s", output_path)

        return report

    def _evaluate_day(self, date_str: str, next_date_str: str) -> dict:
        """Evaluate consensus signal quality for a single day."""
        result = {
            "hits": 0, "total": 0,
            "by_ticker": defaultdict(lambda: {"hits": 0, "total": 0}),
            "confusion": {"long_correct": 0, "long_wrong": 0,
                           "short_correct": 0, "short_wrong": 0},
            "consensus_return": None,
        }

        votes = self.state_db.get_votes_by_date_range(date_str, date_str)
        if not votes:
            return result  # No vote data for this date — skip

        # Group votes by ticker
        ticker_votes: dict[str, list[dict]] = defaultdict(list)
        for v in votes:
            ticker_votes[v["ticker"]].append(v)

        for ticker, tvotes in ticker_votes.items():
            longs = sum(1 for v in tvotes if v["direction"] == "long")
            shorts = sum(1 for v in tvotes if v["direction"] == "short")
            if longs + shorts == 0:
                continue
            consensus = "long" if longs >= shorts else "short"

            # Check next-day return from virtual_trades for this ticker
            next_return_sign = self._get_next_day_return_sign(ticker, next_date_str)
            if next_return_sign is None:
                continue

            result["total"] += 1
            result["by_ticker"][ticker]["total"] += 1
            correct = (consensus == "long" and next_return_sign > 0) or \
                       (consensus == "short" and next_return_sign < 0)
            if correct:
                result["hits"] += 1
                result["by_ticker"][ticker]["hits"] += 1
                if consensus == "long":
                    result["confusion"]["long_correct"] += 1
                else:
                    result["confusion"]["short_correct"] += 1
            else:
                if consensus == "long":
                    result["confusion"]["long_wrong"] += 1
                else:
                    result["confusion"]["short_wrong"] += 1

        # Consensus return proxy: net correct - net wrong (scaled)
        if result["total"] > 0:
            result["consensus_return"] = (result["hits"] * 2 - result["total"]) / result["total"]

        return result

    def _get_next_day_return_sign(self, ticker_or_shadow: str, next_date: str) -> int | None:
        """Get next-day return sign. Returns 1 (positive), -1 (negative), or None."""
        return self.state_db.get_next_day_return_sign(ticker_or_shadow, next_date)

    @staticmethod
    def _compute_sharpe(returns: list[float]) -> float:
        if len(returns) < 2:
            return 0.0
        mu = statistics.mean(returns)
        sigma = statistics.stdev(returns)
        return mu / sigma if sigma > 0 else 0.0
