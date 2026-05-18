# ANALYSIS_METHODOLOGY_B — Shadow Ecosystem Quantitative Framework

**Author**: Quant Analyst (Sonnet 1M)
**Date**: 2026-05-11
**Status**: COMPLETE — Ready for Architect handoff

## 1. Ranking Engine

### Composite Score Formula
- 4 metrics converted to within-cohort percentile ranks (0-1)
- C_raw = 0.35 * P_MPPM + 0.25 * P_Calmar + 0.20 * P_Omega + 0.20 * P_WR
- MPPM uses gamma=3 risk aversion parameter
- Calmar = CAGR / max(|MDD|, 0.001)
- Omega(L=0) capped at 10
- Win Rate excludes abstention days

### Bayesian Overfitting Haircut (Witzany 2021)
- h(N,T) = T / (T + 8 + 24 * ln(N))
- N=15, T=60 → h=0.451 (matches spec example: SR 1.2 → 0.4-0.6)
- Haircut naturally decreases as shadows accumulate more history

### Achievement Ladder
- Percentile boundaries: p15, p30, p70, p85 of C_deflated distribution
- Elite: p85 for 30 days + deflated Sharpe > 0.8
- Excellent: p70 for 10 days + deflated Sharpe > 0.6
- Normal: default
- Watch: p30 for 10 days or MDD > 30%
- Endangered: p15 for 20 days

### Plateau Detection
- 3 conditions simultaneously: never elite/excellent in 126 days, win rate range < 10pp over 90 days, no insights in 63 days
- PlateauScore weighted for reset prioritization
- Max 2 resets/month

## 2. Challenger Mechanism

### Creation: rank_pct < 0.20 for K=3 consecutive evaluation periods
### Comparison: 2-week paired t-test (one-sided, alpha=0.10) + Calmar gate
### Anti-gaming: opacity, fixed evaluation window, budget parity, knowledge isolation, consecutive failure guard

## 3. Shadow Mother

### Event Detection
- E1: Central bank shock: |actual - expected| >= 50bp
- E2: Geopolitical: VIX ratio >= 1.5 AND delta >= 5 points
- E3: Volatility shock: single-asset 24h |r| >= 5 * sigma_60d
- E4: Key personnel change (keyword detection)

### Event Prioritization (when >10 simultaneous)
- ImpactScore = 0.40 * VIX_norm + 0.30 * max_zscore + 0.30 * NewsVolume_norm
- Top 5 get shadows

### Destruction: catalyst resolved, volatility decay (5 days < 2σ), inactivity (5 days), 30-day cap, degradation

## 4. Collusion Detection

### Flag: agreement >= 80% for 3 consecutive days
### Statistical gate: P ~4.4e-5 under random null (binomial test)
### Discrimination: market_signal_strength > 0.70 → convergence; ≤ 0.70 → herding

## 5. Paper-to-Live Gap

### Discount: starts at 20%, adjusts via gap_closure * 0.75, floor at 5%
### Live-ready: 10+ paired trades, GapRatio < 0.30, discount < 0.15, forward validation >= 50%, PBO < 5%/10%, MDD < 25%/35%

## 6. Cash Reframing Validation

### Design: 6 treatment + 6 control expert shadows, 90-day A/B test
### Primary: one-sided Mann-Whitney on DE, alpha=0.10
### Non-inferiority: TOST on cumulative return, margin delta=2.0% (90-day)
### Success: DE reduction (p<0.10) AND non-inferior returns (90% CI lower > -0.02)

## 7. Open Questions for Architect (10 items)
See full methodology in agent output for Q1-Q10 covering state persistence, percentile computation, challenger visibility, catfish methodology, and more.
