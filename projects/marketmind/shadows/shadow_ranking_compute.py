"""Shadow ranking computation — market anchor, ranking, plateau + reset detection."""
from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime, timezone, timedelta

from marketmind.shadows.shadow_state import ShadowStateDB, ShadowConfig
from marketmind.config.settings import ShadowSettings
from marketmind.shadows.shadow_agent import ShadowAgent
from marketmind.shadows.ranking_engine import RankingEngine, ShadowPerformance

logger = logging.getLogger("marketmind.shadows.shadow_ranking_compute")


def compute_market_anchor(
    state_db: ShadowStateDB,
    config: ShadowSettings,
    visible: list[ShadowConfig],
    all_votes: list,
    today: str,
) -> dict[str, float]:
    """Compute market accuracy anchor for each shadow.

    Fetches OHLCV data for tickers referenced in votes, saves market prices
    to state_db, and computes per-shadow market accuracy by comparing vote
    directions against realized price moves.
    """
    market_accuracy: dict[str, float] = {}
    try:
        from marketmind.shadows.market_data_fetcher import MarketDataFetcher
        mdf = MarketDataFetcher()
        all_tickers: set[str] = set()
        for vote in all_votes:
            ticker = getattr(vote, "ticker", None) or vote.get("ticker", "")
            if ticker:
                all_tickers.add(ticker)
        if all_tickers:
            lookback_start = (datetime.now(timezone.utc) -
                             timedelta(days=config.evaluation_window_days + 5)
                             ).strftime("%Y-%m-%d")
            for ticker in list(all_tickers)[:10]:
                prices = mdf.fetch_ohlcv(ticker, lookback_start)
                if prices:
                    for date_str, ohlcv in prices.items():
                        try:
                            state_db.insert_market_price(
                                ticker, date_str,
                                float(ohlcv.get("open", 0)),
                                float(ohlcv.get("high", 0)),
                                float(ohlcv.get("low", 0)),
                                float(ohlcv.get("close", 0)),
                                int(ohlcv.get("volume", 0)),
                            )
                        except Exception:
                            pass
            all_saved_votes = state_db.get_votes_by_date_range(
                lookback_start, today
            )
            votes_by_shadow: dict[str, list[dict]] = {}
            for v in all_saved_votes:
                sid_v = v.get("shadow_id", "")
                if sid_v:
                    votes_by_shadow.setdefault(sid_v, []).append(v)

            for cfg in visible:
                shadow_votes = votes_by_shadow.get(cfg.shadow_id, [])
                if not shadow_votes:
                    continue
                ticker_counts = Counter(
                    v.get("ticker", "") for v in shadow_votes
                )
                primary_ticker = ticker_counts.most_common(1)[0][0] if ticker_counts else ""
                if not primary_ticker:
                    continue
                acc = mdf.compute_market_accuracy(
                    shadow_votes, primary_ticker, lookback_start, today
                )
                market_accuracy[cfg.shadow_id] = acc
                logger.debug(
                    "Market accuracy for %s on %s: %.3f",
                    cfg.shadow_id, primary_ticker, acc
                )
    except Exception as e:
        logger.error("Market anchor computation failed: %s", e)

    return market_accuracy


def compute_rankings(
    state_db: ShadowStateDB,
    config: ShadowSettings,
    visible: list[ShadowConfig],
    all_votes: list,
    today: str,
    market_accuracy: dict[str, float],
) -> dict:
    """Compute rankings, detect plateaus, identify reset candidates, run WFE validation.

    Returns a dict with keys:
        rankings, plateau_flags, reset_candidates, ecosystem_alerts, performances
    """
    result: dict = {
        "rankings": [],
        "plateau_flags": [],
        "reset_candidates": [],
        "ecosystem_alerts": [],
        "performances": {},
    }

    try:
        engine = RankingEngine(config)
        performances: dict[str, ShadowPerformance] = {}
        for cfg in visible:
            snapshots = state_db.get_snapshot_history(
                cfg.shadow_id, days=config.evaluation_window_days
            )
            if snapshots:
                returns = [s.daily_return_pct or 0.0 for s in snapshots
                          if s.daily_return_pct is not None]
                cum = sum(returns)
                peak = 0.0; running = 0.0; mdd = 0.0
                for r in returns:
                    running += r
                    if running > peak: peak = running
                    dd = running - peak
                    if dd < mdd: mdd = dd
                abst_days = sum(1 for s in snapshots
                                if getattr(s, 'votes_produced', 0) == 0)
                perf = ShadowPerformance(
                    shadow_id=cfg.shadow_id,
                    daily_returns=returns,
                    cumulative_return=cum,
                    max_drawdown=abs(mdd) if mdd < 0 else 0.01,
                    max_drawdown_duration_days=0,
                    win_rate=sum(1 for r in returns if r > 0) / len(returns) if returns else 0.5,
                    total_trades=len(returns),
                    profitable_trades=sum(1 for r in returns if r > 0),
                    losing_trades=sum(1 for r in returns if r <= 0),
                    abstention_days=abst_days,
                    cagr=cum * 252 / len(returns) if len(returns) > 0 else 0.0,
                    domain=cfg.domain,
                    shadow_type=cfg.shadow_type,
                    career_days=len(snapshots),
                )
                performances[cfg.shadow_id] = perf

        result["performances"] = performances

        if performances:
            rankings = engine.rank_shadows(performances, {}, today,
                                            market_accuracy=market_accuracy if market_accuracy else None,
                                            wfe_results=None)
            result["rankings"] = rankings
            for rr in rankings:
                agent_config = state_db.get_shadow(rr.shadow_id)
                if agent_config:
                    agent = ShadowAgent(agent_config, state_db, config)
                    agent.apply_ranking_to_snapshot(rr)

            for cfg in visible:
                try:
                    tier_hist = state_db.get_tier_history(
                        cfg.shadow_id, days=config.plateau_no_elite_days * 2
                    )
                    wr_hist = state_db.get_wr_history(
                        cfg.shadow_id, days=config.plateau_no_elite_days * 2
                    )
                    insight_dates = state_db.get_insight_dates(
                        cfg.shadow_id, days=config.plateau_no_insight_days * 2
                    )

                    is_plateau, plateau_score = engine.detect_plateau(
                        cfg.shadow_id, tier_hist, wr_hist, insight_dates
                    )
                    if is_plateau:
                        logger.info("Plateau detected: %s (score=%.2f)", cfg.shadow_id, plateau_score)
                        result["plateau_flags"].append({
                            "shadow_id": cfg.shadow_id,
                            "plateau_score": plateau_score,
                            "date": today,
                        })

                    should_reset, reset_reason = engine.check_reset_eligibility(
                        tier_hist, wr_hist, insight_dates
                    )
                    if should_reset:
                        logger.info("Reset eligible: %s -- %s", cfg.shadow_id, reset_reason)
                        result["reset_candidates"].append({
                            "shadow_id": cfg.shadow_id,
                            "reason": reset_reason,
                            "date": today,
                        })
                except Exception as e:
                    logger.debug("Plateau/reset check failed for %s: %s", cfg.shadow_id, e)

            wfe_ratios: dict[str, float] = {}
            try:
                from marketmind.shadows.ranking_engine import WalkForwardValidator
                wf_validator = WalkForwardValidator()
                for cfg in visible:
                    snapshots = state_db.get_snapshot_history(
                        cfg.shadow_id, days=max(365, wf_validator.min_career_days)
                    )
                    if not snapshots:
                        continue
                    wf_result = wf_validator.validate(cfg.shadow_id, snapshots)
                    if not wf_result.skipped:
                        wfe_ratios[cfg.shadow_id] = wf_result.wfe_ratio
                    if wf_result.skipped:
                        logger.debug(
                            "WFE skipped for %s: %s", cfg.shadow_id, wf_result.skip_reason
                        )
                        continue
                    if wf_result.is_overfit:
                        logger.warning(
                            "WFE overfit detected: %s (WFE=%.3f, IS=%.4f, OOS=%.4f, "
                            "OOS_acc=%.2f, windows=%d, binomial_p=%.4f)",
                            cfg.shadow_id, wf_result.wfe_ratio,
                            wf_result.mean_is_deflated, wf_result.mean_oos_deflated,
                            wf_result.oos_directional_accuracy, wf_result.total_windows,
                            wf_result.binomial_p_value
                        )
                        result["ecosystem_alerts"].append({
                            "type": "wfe_overfit",
                            "shadow_id": cfg.shadow_id,
                            "wfe_ratio": wf_result.wfe_ratio,
                            "date": today,
                        })
            except Exception as e:
                logger.error("Walk-forward validation failed: %s", e)

    except Exception as e:
        logger.error("Ranking computation failed: %s", e)

    return result
