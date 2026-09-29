"""System fragility threshold library. Versioned, with staleness tracking."""

from dataclasses import dataclass
from datetime import datetime, timezone

# Threshold values come from the 2026-05-18 methodology research
# (docs/archive/project-docs/dev/research/pipeline-methodology-gap.md).
THRESHOLDS_RESEARCHED_ON = "2026-05-18T00:00:00+00:00"
# Thresholds (re)sourced against live data on 2026-09-28 (owner decision: fill the
# remaining gaps and add financial-stress inputs). Each carries its basis inline.
# 2026-09-28 revision (owner decision; research accessed 2026-09-28, URLs in each
# entry's source_document): HY-IG 200->450bp; CCC 1000->1300bp; SOFR-IORB 25bp ->
# 10bp persisting 3 observations; bank reserves $2.7T -> reserves/GDP 9% warning / 8%
# stress; BBB OAS 200bp warning + 300bp stress; ON RRP, US 10Y and CEX reserves ->
# MONITOR-only (shown, never crossed, not scored). 2026-09-29 (red-team fix): TGA
# (<$100B), VIX (>35) and dollar index (>110) had no cited source either -> MONITOR-only
# under the same policy.
THRESHOLDS_REVIEWED_2026_09_28 = "2026-09-28T00:00:00+00:00"


@dataclass
class FragilityThreshold:
    metric: str              # "bank_reserves"
    name_zh: str             # "银行准备金"
    threshold_value: float
    unit: str                # "USD_trillion" | "percent" | "basis_points" | "index"
    direction: str           # "below" (crossed when value drops below threshold) | "above"
    mechanism: str           # what happens when crossed
    cascade: list[str]       # second-order effects
    data_source: str         # "FRED:WRESBAL"
    source_document: str     # "Fed H.4.1", "BIS Quarterly Review", etc.
    current_value: float | None = None
    # Date the threshold value was last researched. It used to default to "now",
    # which meant the 90-day staleness check could never fire.
    last_validated: str = THRESHOLDS_RESEARCHED_ON
    is_active: bool = True
    # False = MONITOR-only: the value is shown but the threshold has no defensible
    # calibration, so it can never be "crossed" and does not enter the score.
    crossable: bool = True
    # Optional earlier "warning" line for two-tier thresholds (same unit and direction).
    # When set, threshold_value is the stress line (crossed -> CRITICAL) and passing
    # warning_value only raises the alert to WARNING (not crossed).
    warning_value: float | None = None


THRESHOLD_LIBRARY: list[FragilityThreshold] = [
    # ── Liquidity / reserve thresholds ──
    FragilityThreshold(
        metric="bank_reserves", name_zh="银行准备金/名义GDP",
        # Two tiers (owner decision 2026-09-28): < 9% of nominal GDP = warning,
        # < 8% = stress (crossed). Replaces the absolute < $2.7T line, which does not
        # scale with the economy or the banking system.
        threshold_value=8.0, warning_value=9.0, unit="percent_of_GDP", direction="below",
        mechanism="Reserves/GDP falling toward the edge of 'ample' → banks hoard reserves → SOFR trades above IORB → repo market strain → broad asset selloff",
        cascade=["repo_spike", "dealer_stress", "equity_correlation_1"],
        # Input: FRED WRESBAL (reserve balances, millions USD, weekly) / FRED GDP (nominal,
        # billions USD SAAR, latest quarter): pct = M / (B*1000) * 100. Data source was
        # listed as WRBWFRBL while the inputs fetched WRESBAL; both now say WRESBAL.
        # Basis (owner decision 2026-09-28 from research accessed 2026-09-28): the
        # reserves-to-GDP framing of the "ample reserves" boundary in Gov. Waller's
        # 2025-07-10 speech and Cleveland Fed Economic Commentary 2025-05; 9% = warning,
        # 8% = stress.
        data_source="FRED:WRESBAL / FRED:GDP",
        source_document=("Fed H.4.1; BEA NIPA GDP; "
                         "https://www.federalreserve.gov/newsevents/speech/waller20250710a.htm ; "
                         "https://www.clevelandfed.org/publications/economic-commentary/2025/"
                         "ec-202505-qt-ample-reserves-changing-fed-balance-sheet "
                         "(accessed 2026-09-28)"),
        last_validated=THRESHOLDS_REVIEWED_2026_09_28,
    ),
    FragilityThreshold(
        metric="on_rrp", name_zh="隔夜逆回购余额",
        threshold_value=50, unit="USD_billion", direction="below",
        mechanism="ON RRP near zero → last liquidity buffer exhausted → funding stress emerges",
        cascade=["repo_spike", "sofr_iorb_spread", "bank_reserves_pressure"],
        # MONITOR-only (owner decision 2026-09-28): ON RRP has been ~$0.58B since late
        # 2025, so "< $50B" is permanently crossed and carries no signal. Value is shown;
        # the 50 is kept for reference only. Source: FRED RRPONTSYD (accessed 2026-09-28).
        crossable=False,
        data_source="FRED:RRPONTSYD",
        source_document=("Fed H.4.1; https://fred.stlouisfed.org/series/RRPONTSYD "
                         "(accessed 2026-09-28)"),
        last_validated=THRESHOLDS_REVIEWED_2026_09_28,
    ),
    FragilityThreshold(
        metric="tga", name_zh="财政部TGA账户",
        threshold_value=100, unit="USD_billion", direction="below",
        # A TGA drawdown ADDS reserves (Treasury spends down its Fed balance); it is the
        # later rebuild, funded by bill issuance, that drains reserves. A very low TGA
        # signals debt-ceiling maneuvering and a large rebuild still to come.
        mechanism="TGA < $100B → debt-ceiling drawdown (the drawdown itself adds reserves) → X-date uncertainty spike; after resolution the TGA rebuild via bill issuance drains reserves → repo volatility",
        cascade=["bill_issuance_surge", "repo_volatility", "debt_ceiling_risk"],
        # MONITOR-only (red-team fix 2026-09-29): the $100B level has no cited source, so
        # under the 2026-09-28 policy (unsourced -> monitor only, as for us10y / on_rrp /
        # CEX reserves) the value is shown, never crossed, kept out of the score. $100B
        # kept for reference only.
        crossable=False,
        data_source="FRED:WTREGEN", source_document="Treasury Daily Statement",
    ),
    FragilityThreshold(
        metric="sofr_iorb_spread", name_zh="SOFR-IORB利差(连续3期最小值)",
        threshold_value=10, unit="basis_points", direction="above",
        mechanism="SOFR above IORB by >10bp for 3+ consecutive observations → SOFR above the Standing Repo Facility rate → persistent repo market stress (echoes Sep 2019 / Oct 2025)",
        cascade=["repo_freeze", "dealer_balance_sheet", "equity_selloff"],
        # Input value = the MINIMUM of (SOFR - IORB) in bp over the 3 most recent SOFR
        # observations (IORB on the same dates), so "> 10bp" means every one of the last
        # 3 observations exceeded 10bp (persistence rule; owner decision 2026-09-28).
        # Basis (owner decision 2026-09-28 from research accessed 2026-09-28): a spread
        # above 10bp puts SOFR above the Standing Repo Facility rate; the Oct-2025 repo
        # strain peaked at ~14-16bp, which the old 25bp line missed.
        data_source="FRED:SOFR - FRED:IORB (last 3 observations)",
        source_document=("Fed H.4.1; https://www.federalreserve.gov/econres/notes/feds-notes/"
                         "market-based-indicators-on-the-road-to-ample-reserves-20250131.html ; "
                         "https://www.dallasfed.org/news/speeches/logan/2025/lkl251031 "
                         "(accessed 2026-09-28)"),
        last_validated=THRESHOLDS_REVIEWED_2026_09_28,
    ),

    # ── Rate / yield thresholds ──
    FragilityThreshold(
        metric="us10y_yield", name_zh="10年期美债收益率",
        threshold_value=4.5, unit="percent", direction="above",
        mechanism="10Y >4.5% → political pain threshold breached → policy intervention likely; sustained breach → higher discount rates crush growth equities",
        cascade=["mortgage_rate_spike", "growth_stock_repricing", "em_debt_stress"],
        # MONITOR-only (owner decision 2026-09-28): no sourced level for 4.5%; value is
        # shown, never crossed, kept out of the score. 4.5 kept for reference only.
        crossable=False,
        data_source="FRED:DGS10", source_document="Treasury yield curve",
        last_validated=THRESHOLDS_REVIEWED_2026_09_28,
    ),
    FragilityThreshold(
        metric="ccc_treasury_spread", name_zh="CCC级信用利差",
        threshold_value=1300, unit="basis_points", direction="above",
        mechanism="CCC-Treasury spread >1300bp → deeply distressed credit → default cycle imminent → risk-off cascade",
        cascade=["hy_outflows", "bank_lending_freeze", "small_cap_credit_crunch"],
        # Raised 1000 -> 1300bp (owner decision 2026-09-28): ~1000bp is roughly CCC's
        # normal level in 2026. SECONDARY source, medium-low confidence (accessed
        # 2026-09-28): Lead-Lag Report "The credit-equity divergence".
        data_source="FRED:BAMLH0A3HYC",
        source_document=("ICE BofA High Yield Index; "
                         "https://www.leadlagreport.com/the-credit-equity-divergence-what/ "
                         "(secondary, medium-low confidence; accessed 2026-09-28)"),
        last_validated=THRESHOLDS_REVIEWED_2026_09_28,
    ),

    # ── Volatility / stress thresholds ──
    FragilityThreshold(
        metric="vix", name_zh="VIX波动率指数",
        threshold_value=35, unit="index", direction="above",
        mechanism="VIX >35 → systemic fear pricing → vol-targeting funds delever → forced selling accelerates drawdown",
        cascade=["vol_fund_delever", "option_hedging_surge", "liquidity_evaporation"],
        # MONITOR-only (red-team fix 2026-09-29): the 35 level has no cited source, so
        # under the 2026-09-28 policy (unsourced -> monitor only, as for us10y / on_rrp /
        # CEX reserves) the value is shown, never crossed, kept out of the score. 35
        # kept for reference only.
        crossable=False,
        data_source="CBOE:VIX", source_document="CBOE VIX methodology",
    ),
    FragilityThreshold(
        metric="hyg_lqd_spread", name_zh="HYG-LQD信用价差",
        threshold_value=450, unit="basis_points", direction="above",
        mechanism="HY vs IG spread >450bp → credit differentiation breaking down → risk-off rotation accelerating",
        cascade=["etf_redemption_surge", "dealer_inventory_buildup", "corporate_bond_illiquidity"],
        # Read as ICE BofA US HY OAS minus US Corporate (IG) OAS, in bp.
        # Raised 200 -> 450bp (owner decision 2026-09-28): 200bp is a tight-market level
        # (~201bp in Sep 2026) and fired falsely; 450bp ~ the 25-year average (research
        # accessed 2026-09-28, sources below).
        data_source="FRED:BAMLH0A0HYM2 - BAMLC0A0CM",
        source_document=("ICE BofA OAS data; "
                         "https://investmentgrade.com/investment-grade-bond-statistics-2026/ ; "
                         "https://recessionpulse.com/indicators/credit-spreads "
                         "(accessed 2026-09-28)"),
        last_validated=THRESHOLDS_REVIEWED_2026_09_28,
    ),

    # ── Macro / structural thresholds ──
    FragilityThreshold(
        metric="margin_debt_gdp", name_zh="保证金债务/GDP比率",
        threshold_value=2.5, unit="percent_of_GDP", direction="above",
        mechanism="Margin debt >2.5% GDP → systemic leverage at historical extremes → forced deleveraging risk on any drawdown",
        cascade=["margin_call_cascade", "retail_liquidation", "broker_liquidity_stress"],
        # Source (2026-09-28): Fed Z.1 broker-dealer "margin loans and other receivables"
        # (FRED BOGZ1FL663067003Q, millions USD, quarter-end) / nominal GDP (FRED GDP,
        # billions USD SAAR), same quarter: pct = M / (B*1000) * 100. Includes "other
        # receivables", so it is a broader measure than FINRA debit balances.
        # Basis for 2.5%: on this series' own FRED history the ratio has exceeded 2.5%
        # only once, at the 2000Q1 dot-com peak (max 2.64%); 2008Q3 peaked 2.38%,
        # 2021 ~2.14%. 2026Q2 = 2.29%. The 2.5% line therefore marks "near the
        # historical extreme" on the series actually fed.
        data_source="FRED:BOGZ1FL663067003Q / FRED:GDP",
        source_document="Fed Z.1 Financial Accounts; BEA NIPA GDP",
        last_validated=THRESHOLDS_REVIEWED_2026_09_28,
    ),
    FragilityThreshold(
        metric="dollar_index", name_zh="美元指数",
        threshold_value=110, unit="index", direction="above",
        mechanism="DXY rapid rise >110 → global dollar shortage → EM FX crisis → cross-border lending freeze",
        cascade=["em_fx_devaluation", "dollar_debt_crisis", "commodity_price_collapse"],
        # MONITOR-only (red-team fix 2026-09-29): the 110 level has no cited source, so
        # under the 2026-09-28 policy (unsourced -> monitor only, as for us10y / on_rrp /
        # CEX reserves) the value is shown, never crossed, kept out of the score. 110
        # kept for reference only.
        crossable=False,
        data_source="ICE:DXY", source_document="ICE Dollar Index",
    ),
    FragilityThreshold(
        metric="copper_gold_ratio", name_zh="铜金比",
        threshold_value=3.5, unit="ratio", direction="below",
        mechanism="Copper/gold ratio <3.5 → industrial demand pessimism vs safe-haven demand → recession pricing",
        cascade=["commodity_selloff", "industrial_production_contraction", "risk_asset_rotation"],
        # Fed as the market convention: copper USD/lb divided by gold USD/troy oz, x1000
        # (copper = FRED PCOPPUSDM USD/metric ton / 2204.62262; gold = GC=F closes averaged
        # over the same month). July 2026 = 6.14 / 4079 x1000 = 1.51.
        # MONITOR-only: the 3.5 level has no source and fits no convention. On the x1000
        # convention the ratio has been far below 3.5 for over a decade (secular gold
        # outperformance), so "below 3.5" would be permanently crossed; on x100 it would
        # never be near 3.5. Kept for reference; not crossable until re-researched.
        crossable=False,
        data_source="FRED:PCOPPUSDM; yfinance:GC=F",
        source_document="IMF primary commodity prices (via FRED); COMEX gold futures",
        last_validated=THRESHOLDS_REVIEWED_2026_09_28,
    ),

    # ── International / EM thresholds ──
    FragilityThreshold(
        metric="em_import_cover", name_zh="新兴市场外汇储备进口覆盖",
        threshold_value=3, unit="months_import_cover", direction="below",
        mechanism="EM FX reserves <3 months import cover → balance of payments crisis → capital flight → sovereign default risk",
        cascade=["capital_controls", "imf_bailout", "contagion_to_other_em"],
        # Source (2026-09-28): World Bank WDI FI.RES.TOTL.MO (total reserves incl. gold,
        # in months of imports; annual) for the "Low & middle income" aggregate (LMY).
        # 2025 = 9.9 months. Basis for 3 months: the traditional IMF import-cover
        # adequacy rule of thumb (IMF, "Assessing Reserve Adequacy", 2011). Caveat: the
        # aggregate is dominated by China and large reserve holders, so it cannot show
        # stress in individual EMs; a cross only occurs in a broad EM reserve crisis.
        data_source="WorldBank:FI.RES.TOTL.MO (LMY aggregate)",
        source_document="World Bank WDI; IMF Assessing Reserve Adequacy (2011)",
        last_validated=THRESHOLDS_REVIEWED_2026_09_28,
    ),

    # ── Crypto / digital asset threshold ──
    FragilityThreshold(
        metric="crypto_exchange_reserves", name_zh="交易所加密资产储备月变动",
        threshold_value=-10, unit="percent_7d_change", direction="below",
        mechanism="CEX-held assets falling >10% in a week → exchange run risk → withdrawal freezes → cascading trust failure",
        cascade=["stablecoin_depeg", "defi_liquidity_crunch", "contagion_to_tradfi"],
        # Proxy (2026-09-28): aggregate 7-day % change of USD TVL over DefiLlama category
        # "CEX" (/protocols; ~$318B across 80 exchanges). DefiLlama's free API has no
        # monthly field and per-exchange history is ~30MB+ per call, so the original
        # -20%/month rule (CryptoQuant, coin units) cannot be computed. Drawdown rule
        # (inference, not a cited level): -10% in 7 days = half the old monthly
        # threshold compressed into one week. Caveat: USD-valued, so a broad crypto price
        # fall also moves it; it measures exchange-held value, not coin outflows alone.
        # MONITOR-only (owner decision 2026-09-28): the -10%/7d level has no source;
        # value is shown, never crossed, kept out of the score.
        crossable=False,
        data_source="DefiLlama:/protocols category=CEX change_7d",
        source_document="DefiLlama CEX transparency dashboard",
        last_validated=THRESHOLDS_REVIEWED_2026_09_28,
    ),

    # ── Financial-stress indices (added 2026-09-28) ──
    FragilityThreshold(
        metric="stlfsi", name_zh="圣路易斯联储金融压力指数",
        threshold_value=1.0, unit="index", direction="above",
        mechanism="STLFSI >1 → financial stress one standard deviation above average → funding and credit markets tightening",
        cascade=["credit_spread_widening", "risk_off", "dealer_stress"],
        # Basis: the index is constructed with mean 0 ("normal" stress) and unit standard
        # deviation (verified on FRED 1993-2026: mean 0.00, sd 1.00). 1.0 = +1 sd (~p92);
        # crossed in 2008 (9.7), 2011 (1.39), 2016 (1.27), 2020 (5.6), SVB 2023 (1.13).
        # 2026-09-18 = -0.91.
        data_source="FRED:STLFSI4", source_document="St. Louis Fed Financial Stress Index",
        last_validated=THRESHOLDS_REVIEWED_2026_09_28,
    ),
    FragilityThreshold(
        metric="ofr_fsi", name_zh="OFR金融压力指数",
        threshold_value=4.1, unit="index", direction="above",
        mechanism="OFR FSI >4.1 → global market stress one standard deviation above average → cross-asset deleveraging",
        cascade=["volatility_spike", "funding_stress", "safe_asset_bid"],
        # Basis: 0 = average stress by construction, but not unit-variance. Verified on
        # the OFR CSV 2000-2026: mean -0.04, sd 4.10 -> threshold +1 sd = 4.1 (~p89).
        # Crossed in 2008 (29.3), 2011 (6.9), 2020 (10.3); not in 2022 (3.5) or SVB (2.4).
        # 2026-09-23 = -2.66.
        data_source="OFR:financial-stress-index/data/fsi.csv",
        source_document="OFR Financial Stress Index",
        last_validated=THRESHOLDS_REVIEWED_2026_09_28,
    ),
    FragilityThreshold(
        metric="bbb_oas", name_zh="BBB级公司债利差",
        # Two tiers (owner decision 2026-09-28): > 200bp = warning, > 300bp = stress
        # (event-level, crossed).
        threshold_value=300, warning_value=200, unit="basis_points", direction="above",
        mechanism="BBB OAS >200bp (warning) / >300bp (stress) → lowest-IG tier repricing → fallen-angel risk → IG fund outflows",
        cascade=["fallen_angel_downgrades", "ig_outflows", "corporate_refinancing_stress"],
        # FRED BAMLC0A4CBBB is in percent (x100 -> bp). FRED only exposes the last 3
        # years of ICE data (2023-09..2026-09: median 107bp, max 163bp; 2026-09-24 97bp).
        # Basis (research accessed 2026-09-28): FRED BAMLC0A4CBBB history plus a
        # secondary source (eco3min, BBB IG composition) support 200bp as the warning
        # level and 300bp as the event-level stress line.
        data_source="FRED:BAMLC0A4CBBB",
        source_document=("ICE BofA BBB US Corporate Index OAS; "
                         "https://fred.stlouisfed.org/series/BAMLC0A4CBBB ; "
                         "https://eco3min.fr/en/bbb-investment-grade-composition-2/ "
                         "(secondary; accessed 2026-09-28)"),
        last_validated=THRESHOLDS_REVIEWED_2026_09_28,
    ),
]


def validate_thresholds() -> list[str]:
    """Check for stale thresholds (>90 days since last_validated). Returns warnings."""
    warnings = []
    now = datetime.now(timezone.utc)
    for t in THRESHOLD_LIBRARY:
        try:
            validated = datetime.fromisoformat(t.last_validated)
            if (now - validated).days > 90:
                warnings.append(
                    f"STALE: {t.metric} last validated {(now - validated).days}d ago"
                )
        except (ValueError, TypeError):
            warnings.append(
                f"INVALID_DATE: {t.metric} has unparseable last_validated"
            )
    if len(warnings) == len(THRESHOLD_LIBRARY):
        warnings.append(
            "CRITICAL: ALL thresholds are STALE — fragility library may be abandoned"
        )
    return warnings


__all__ = ["FragilityThreshold", "THRESHOLD_LIBRARY", "validate_thresholds"]
