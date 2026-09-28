"""System fragility threshold library. Versioned, with staleness tracking."""

from dataclasses import dataclass
from datetime import datetime, timezone

# Threshold values come from the 2026-05-18 methodology research
# (docs/archive/project-docs/dev/research/pipeline-methodology-gap.md).
THRESHOLDS_RESEARCHED_ON = "2026-05-18T00:00:00+00:00"
# Thresholds (re)sourced against live data on 2026-09-28 (owner decision: fill the
# remaining gaps and add financial-stress inputs). Each carries its basis inline.
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
    data_source: str         # "FRED:WRBWFRBL"
    source_document: str     # "Fed H.4.1", "BIS Quarterly Review", etc.
    current_value: float | None = None
    # Date the threshold value was last researched. It used to default to "now",
    # which meant the 90-day staleness check could never fire.
    last_validated: str = THRESHOLDS_RESEARCHED_ON
    is_active: bool = True
    # False = MONITOR-only: the value is shown but the threshold has no defensible
    # calibration, so it can never be "crossed" and does not enter the score.
    crossable: bool = True


THRESHOLD_LIBRARY: list[FragilityThreshold] = [
    # ── Liquidity / reserve thresholds ──
    FragilityThreshold(
        metric="bank_reserves", name_zh="银行准备金",
        threshold_value=2.7, unit="USD_trillion", direction="below",
        mechanism="SOFR spikes above IORB → repo market freeze → broad asset selloff",
        cascade=["repo_spike", "dealer_stress", "equity_correlation_1"],
        data_source="FRED:WRBWFRBL", source_document="Fed H.4.1",
    ),
    FragilityThreshold(
        metric="on_rrp", name_zh="隔夜逆回购余额",
        threshold_value=50, unit="USD_billion", direction="below",
        mechanism="ON RRP near zero → last liquidity buffer exhausted → funding stress emerges",
        cascade=["repo_spike", "sofr_iorb_spread", "bank_reserves_pressure"],
        data_source="FRED:RRPONTSYD", source_document="Fed H.4.1",
    ),
    FragilityThreshold(
        metric="tga", name_zh="财政部TGA账户",
        threshold_value=100, unit="USD_billion", direction="below",
        mechanism="TGA rapid drawdown → Treasury injecting liquidity → debt ceiling maneuvering → uncertainty spike",
        cascade=["bill_issuance_surge", "repo_volatility", "debt_ceiling_risk"],
        data_source="FRED:WTREGEN", source_document="Treasury Daily Statement",
    ),
    FragilityThreshold(
        metric="sofr_iorb_spread", name_zh="SOFR-IORB利差",
        threshold_value=25, unit="basis_points", direction="above",
        mechanism="SOFR-IORB spread >25bp → repo market stress → echoes Sep 2019 liquidity crisis",
        cascade=["repo_freeze", "dealer_balance_sheet", "equity_selloff"],
        data_source="FRED:SOFR, IORB", source_document="Fed H.4.1",
    ),

    # ── Rate / yield thresholds ──
    FragilityThreshold(
        metric="us10y_yield", name_zh="10年期美债收益率",
        threshold_value=4.5, unit="percent", direction="above",
        mechanism="10Y >4.5% → political pain threshold breached → policy intervention likely; sustained breach → higher discount rates crush growth equities",
        cascade=["mortgage_rate_spike", "growth_stock_repricing", "em_debt_stress"],
        data_source="FRED:DGS10", source_document="Treasury yield curve",
    ),
    FragilityThreshold(
        metric="ccc_treasury_spread", name_zh="CCC级信用利差",
        threshold_value=1000, unit="basis_points", direction="above",
        mechanism="CCC-Treasury spread >1000bp → deeply distressed credit → default cycle imminent → risk-off cascade",
        cascade=["hy_outflows", "bank_lending_freeze", "small_cap_credit_crunch"],
        data_source="FRED:BAMLH0A3HYC", source_document="ICE BofA High Yield Index",
    ),

    # ── Volatility / stress thresholds ──
    FragilityThreshold(
        metric="vix", name_zh="VIX波动率指数",
        threshold_value=35, unit="index", direction="above",
        mechanism="VIX >35 → systemic fear pricing → vol-targeting funds delever → forced selling accelerates drawdown",
        cascade=["vol_fund_delever", "option_hedging_surge", "liquidity_evaporation"],
        data_source="CBOE:VIX", source_document="CBOE VIX methodology",
    ),
    FragilityThreshold(
        metric="hyg_lqd_spread", name_zh="HYG-LQD信用价差",
        threshold_value=200, unit="basis_points", direction="above",
        mechanism="HY vs IG spread >200bp → credit differentiation breaking down → risk-off rotation accelerating",
        cascade=["etf_redemption_surge", "dealer_inventory_buildup", "corporate_bond_illiquidity"],
        # Read as ICE BofA US HY OAS minus US Corporate (IG) OAS, in bp. Note: this
        # differential has rarely been far below ~200bp (it was ~201bp in Sep 2026),
        # so the 200bp line flags "not tight", not acute stress. Unrevised since 2026-05-18.
        data_source="FRED:BAMLH0A0HYM2 - BAMLC0A0CM", source_document="ICE BofA OAS data",
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
        threshold_value=200, unit="basis_points", direction="above",
        mechanism="BBB OAS >200bp → lowest-IG tier repricing → fallen-angel risk → IG fund outflows",
        cascade=["fallen_angel_downgrades", "ig_outflows", "corporate_refinancing_stress"],
        # FRED BAMLC0A4CBBB is in percent (x100 -> bp). FRED only exposes the last 3
        # years of ICE data (2023-09..2026-09: median 107bp, max 163bp; 2026-09-24 97bp),
        # so a long-history percentile cannot be re-verified here. Basis (inference from
        # recalled history, NOT re-verified): BBB OAS reached ~200bp+ in the 2015-16
        # energy selloff and the 2022 rate shock, ~400bp+ in March 2020 and ~700bp+ in
        # 2008; 200bp therefore marks "episode-level" BBB stress.
        data_source="FRED:BAMLC0A4CBBB", source_document="ICE BofA BBB US Corporate Index OAS",
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
