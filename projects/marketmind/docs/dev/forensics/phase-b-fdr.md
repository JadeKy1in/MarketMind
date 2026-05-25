# Forensic Design Reconstruction — Phase B (Shadow Ecosystem Core)

**Date reconstructed**: 2026-05-12
**Evidence sources**: 20 git commits, Red Team audit (B_full_phase_b.md), methodology docs, code structure

## What the Evidence Says Phase B Built

### Intended System
A multi-agent shadow ecosystem that runs adversarial validation on investment signals. 20+ independent "shadow" agents (each with different expertise/bias) analyze the same market data and news, produce votes, get ranked by performance, and the aggregate informs the final investment decision.

### Subsystems (B.0 through B.10)

| Subsystem | What It Does | Files |
|-----------|-------------|-------|
| B.0 ShadowConfig | Quotas, ranking params, challenger rules, collusion thresholds | `shadow_state.py` |
| B.1 Ranking Engine | MPPM/Calmar/Omega/WinRate composite, Bayesian haircut, percentile ranking, plateau detection | `ranking_engine.py` |
| B.2 Shadow Mother | Daily cycle orchestration: event scan → temp shadow lifecycle → counterfactual tracking | `shadow_mother.py`, `missed_path.py` |
| B.3 Expert Shadows | 15 domain-specific analysts (gold, oil, tech, crypto, etc.) | `expert_shadows.py` |
| B.4 Daredevil Shadows | 5 contrarian types + Catfish agent (minority-opinion enforcer) | `daredevil_shadows.py`, `catfish_agent.py` |
| B.5 Knowledge Filter | Learngenes selective inheritance, ACE risk detection | `knowledge_filter.py` |
| B.5 Challenger Engine | 3-stage elimination buffer, secret creation, paired t-test comparison | `challenger_engine.py` |
| B.6 Collusion Detector | Agreement stats, convergence vs herding discrimination, escalation | `collusion_detector.py` |
| B.6 Emergency Quota | Confidence-based extra calls, audit trail, reward/penalty | `emergency_quota.py` |
| B.7 Cash Reframing | A/B test with treatment/control cohorts, Mann-Whitney, non-inferiority TOST | `cash_reframing.py` |
| B.7 Paper-to-Live Gap | Virtual slippage, confidence discount, inter-shadow GapRatio | `paper_live_gap.py` |
| B.8 Shadow UI | Ranking dashboard, status cards, sidebar integration | UI widget files |
| B.9 Gateway Integration | Shadow priority in token budget, shadow votes in decision pipeline | `gateway/` |
| B.10 Full Orchestration | All subsystems wired into daily cycle, E2E tests (21-shadow setup) | `shadow_mother.py` |

### Phase B Completion State
- Red Team audit: 3 CRITICAL found, all fixed (Priority enum, emergency quota guard, snapshot metrics)
- Architect approval: obtained
- Tests: 299 passed (later expanded to 339 in Phase C)
- Gate: PASSED

## What I Need You to Confirm

1. **Was the core goal**: "20+ independent shadow analysts that compete, get ranked, and their votes inform decisions" — correct?

2. **Catfish agent**: Designed to enforce minority opinions when consensus >= 80% — was this your idea or something the implementation drifted into?

3. **Cash Reframing A/B test**: Was this supposed to be a permanent feature or an experimental validation tool?

4. **Shadow UI**: The ranking dashboard and status cards — were these meant for daily use or for development debugging?

5. **Anything missing**: Is there functionality you expected Phase B to deliver that you don't see above?
