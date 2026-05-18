"""System fragility threshold library. Versioned, with staleness tracking."""

from dataclasses import dataclass, field
from datetime import datetime, timezone


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
    last_validated: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    is_active: bool = True


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
        data_source="Bloomberg:HYG, LQD OAS", source_document="ICE BofA OAS data",
    ),

    # ── Macro / structural thresholds ──
    FragilityThreshold(
        metric="margin_debt_gdp", name_zh="保证金债务/GDP比率",
        threshold_value=2.5, unit="percent_of_GDP", direction="above",
        mechanism="Margin debt >2.5% GDP → systemic leverage at historical extremes → forced deleveraging risk on any drawdown",
        cascade=["margin_call_cascade", "retail_liquidation", "broker_liquidity_stress"],
        data_source="FINRA margin statistics; BEA GDP", source_document="FINRA Monthly Margin",
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
        data_source="LME:Copper; COMEX:Gold", source_document="LME / CME futures",
    ),

    # ── International / EM thresholds ──
    FragilityThreshold(
        metric="em_import_cover", name_zh="新兴市场外汇储备进口覆盖",
        threshold_value=3, unit="months_import_cover", direction="below",
        mechanism="EM FX reserves <3 months import cover → balance of payments crisis → capital flight → sovereign default risk",
        cascade=["capital_controls", "imf_bailout", "contagion_to_other_em"],
        data_source="IMF IFS; national central banks", source_document="IMF International Financial Statistics",
    ),

    # ── Crypto / digital asset threshold ──
    FragilityThreshold(
        metric="crypto_exchange_reserves", name_zh="交易所加密资产储备月变动",
        threshold_value=-20, unit="percent_monthly_change", direction="below",
        mechanism="Exchange reserves declining >20%/month → exchange run risk → withdrawal freezes → cascading trust failure",
        cascade=["stablecoin_depeg", "defi_liquidity_crunch", "contagion_to_tradfi"],
        data_source="CryptoQuant; Glassnode", source_document="CryptoQuant Exchange Reserve Monitor",
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
