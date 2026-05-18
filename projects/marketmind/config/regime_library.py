"""Historical macro regime definitions with characteristic 7-variable vectors.

Each regime includes qualitative metadata (name, years, key events) and a
normalised 7-variable vector for Euclidean-distance similarity matching.

# Pre-1985 Qualitative Supplement
Monthly data before ~1985 is sparse or unreliable for certain series (VIX did
not exist before 1990, 10Y-2Y spread reconstruction is model-dependent, etc.).
Regimes covering pre-1985 periods use regime-level statistics synthesised from
academic literature (e.g. Shiller CAPE data, NBER recession dates, FRED
long-run series) rather than full monthly vectors. The similarity scores for
these regimes carry a caveat: **quantitative similarity to pre-1985 regimes may
be understated** relative to post-1985 regimes.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# ── Dataclass ────────────────────────────────────────────────────────────────────

@dataclass
class RegimeDef:
    """Single historical macro regime with vector for Euclidean-distance matching.

    The 7-variable vector is normalised against approximate post-1985 means and
    standard deviations so each dimension contributes roughly equal weight before
    the variable-weighting multiplier.
    """

    regime_id: str
    regime_name: str
    years: str
    dominant_tool: str           # "rate_control" or "quantity_control"
    rate_regime: str             # "low_stable", "volatile_high", "rising", "falling", "near_zero"
    quantity_regime: str         # "gold_standard", "tight", "moderate", "aggressive", "tapering"

    # Characteristic 7-variable vector (regime-average, normalised)
    spy_yy: float                # S&P 500 year/year return (annualised %)
    spread_10y2y: float          # 10Y-2Y Treasury spread (% points)
    wti_yy: float                # WTI crude year/year return (annualised %)
    copper_yy: float             # Copper year/year return (annualised %)
    tbill_yield: float           # 3-month T-bill yield (%)
    vix_avg: float               # VIX average level (or VXO proxy for pre-1990)
    stock_bond_corr: float       # Stock-bond return correlation (-1 to +1)

    # Outcome statistics
    equity_avg_return: float     # S&P 500 annualised total return in regime (%)
    bond_avg_return: float       # 10Y Treasury annualised total return (%)
    inflation_avg: float         # CPI year/year average (%)

    # Narrative
    key_events: list[str] = field(default_factory=list)


# ── Regime Library ───────────────────────────────────────────────────────────────
# Ordered chronologically. Each vector entry is a regime-average normalised against
# approximate post-1985 means. The Euclidean distance between a live macro snapshot
# and these vectors drives the analogue/anti-analogue ranking.

REGIME_LIBRARY: list[RegimeDef] = [
    RegimeDef(
        regime_id="bretton_woods_1951_1971",
        regime_name="布雷顿森林体系",
        years="1951-1971",
        dominant_tool="rate_control",
        rate_regime="low_stable",
        quantity_regime="gold_standard",
        spy_yy=12.5, spread_10y2y=0.5, wti_yy=3.0, copper_yy=2.0,
        tbill_yield=4.0, vix_avg=12.0, stock_bond_corr=0.2,
        equity_avg_return=12.5, bond_avg_return=3.2, inflation_avg=2.5,
        key_events=["Treasury-Fed Accord 1951", "Bretton Woods collapse 1971"],
    ),
    RegimeDef(
        regime_id="stagflation_1971_1982",
        regime_name="滞胀时代",
        years="1971-1982",
        dominant_tool="quantity_control",
        rate_regime="volatile_high",
        quantity_regime="tight",
        spy_yy=6.8, spread_10y2y=0.2, wti_yy=25.0, copper_yy=8.0,
        tbill_yield=8.0, vix_avg=18.0, stock_bond_corr=-0.3,
        equity_avg_return=6.8, bond_avg_return=2.1, inflation_avg=8.5,
        key_events=["Nixon shock 1971", "Oil crisis 1973/1979", "Volcker rate hike 1979-1982"],
    ),
    RegimeDef(
        regime_id="greenspan_1982_2000",
        regime_name="格林斯潘时代",
        years="1982-2000",
        dominant_tool="rate_control",
        rate_regime="falling_then_stable",
        quantity_regime="moderate",
        spy_yy=18.0, spread_10y2y=1.5, wti_yy=3.0, copper_yy=3.0,
        tbill_yield=5.0, vix_avg=16.0, stock_bond_corr=0.1,
        equity_avg_return=18.0, bond_avg_return=8.5, inflation_avg=3.5,
        key_events=["Volcker disinflation complete", "1987 crash", "LTCM 1998", "Dot-com bubble build-up"],
    ),
    RegimeDef(
        regime_id="dotcom_2000_2003",
        regime_name="互联网泡沫破裂",
        years="2000-2003",
        dominant_tool="rate_control",
        rate_regime="falling",
        quantity_regime="moderate",
        spy_yy=-14.0, spread_10y2y=1.0, wti_yy=5.0, copper_yy=-2.0,
        tbill_yield=3.0, vix_avg=25.0, stock_bond_corr=0.4,
        equity_avg_return=-14.0, bond_avg_return=10.5, inflation_avg=2.5,
        key_events=["Dot-com crash 2000-2002", "9/11 2001", "Enron/WorldCom scandals", "Afghanistan/Iraq wars"],
    ),
    RegimeDef(
        regime_id="housing_boom_2003_2007",
        regime_name="房地产繁荣",
        years="2003-2007",
        dominant_tool="rate_control",
        rate_regime="rising",
        quantity_regime="moderate",
        spy_yy=12.0, spread_10y2y=0.5, wti_yy=20.0, copper_yy=15.0,
        tbill_yield=3.5, vix_avg=14.0, stock_bond_corr=0.3,
        equity_avg_return=12.0, bond_avg_return=4.5, inflation_avg=3.0,
        key_events=["Iraq War oil demand", "China commodity super-cycle", "Subprime lending boom", "Housing peak 2006"],
    ),
    RegimeDef(
        regime_id="gfc_2008_2009",
        regime_name="全球金融危机",
        years="2008-2009",
        dominant_tool="quantity_control",
        rate_regime="near_zero",
        quantity_regime="aggressive",
        spy_yy=-37.0, spread_10y2y=2.0, wti_yy=-40.0, copper_yy=-30.0,
        tbill_yield=0.5, vix_avg=40.0, stock_bond_corr=0.8,
        equity_avg_return=-37.0, bond_avg_return=20.0, inflation_avg=0.5,
        key_events=["Lehman collapse Sep 2008", "TARP bailout", "QE1 launched Nov 2008", "Global coordinated easing"],
    ),
    RegimeDef(
        regime_id="qe_era_2009_2020",
        regime_name="量化宽松时代",
        years="2009-2020",
        dominant_tool="quantity_control",
        rate_regime="near_zero",
        quantity_regime="aggressive",
        spy_yy=14.0, spread_10y2y=1.5, wti_yy=5.0, copper_yy=3.0,
        tbill_yield=0.2, vix_avg=17.0, stock_bond_corr=0.0,
        equity_avg_return=14.0, bond_avg_return=4.0, inflation_avg=1.8,
        key_events=["QE2/QE3/QE infinity", "Eurozone debt crisis 2010-2012", "Taper Tantrum 2013", "China devaluation 2015"],
    ),
    RegimeDef(
        regime_id="covid_2020_2023",
        regime_name="新冠冲击与刺激",
        years="2020-2023",
        dominant_tool="quantity_control",
        rate_regime="near_zero_then_rising",
        quantity_regime="aggressive",
        spy_yy=18.0, spread_10y2y=0.8, wti_yy=40.0, copper_yy=15.0,
        tbill_yield=0.1, vix_avg=22.0, stock_bond_corr=0.2,
        equity_avg_return=18.0, bond_avg_return=-5.0, inflation_avg=5.5,
        key_events=["COVID crash Mar 2020", "$5T fiscal stimulus", "Supply chain crisis", "Russia-Ukraine war 2022", "Fed 75bp hikes begin"],
    ),
    RegimeDef(
        regime_id="tightening_2023_present",
        regime_name="紧缩周期",
        years="2023-至今",
        dominant_tool="rate_control",
        rate_regime="rising_then_plateau",
        quantity_regime="tapering",
        spy_yy=20.0, spread_10y2y=-0.5, wti_yy=-5.0, copper_yy=2.0,
        tbill_yield=5.2, vix_avg=16.0, stock_bond_corr=0.1,
        equity_avg_return=20.0, bond_avg_return=2.0, inflation_avg=3.2,
        key_events=["Fed funds 5.25-5.50% plateau", "AI-driven equity rally", "Regional bank crisis Mar 2023", "QT continues"],
    ),
]

# ── Helpers ──────────────────────────────────────────────────────────────────────

def get_regime_by_id(regime_id: str) -> RegimeDef | None:
    """Look up a regime definition by its id string."""
    for r in REGIME_LIBRARY:
        if r.regime_id == regime_id:
            return r
    return None


def build_vector(regime: RegimeDef) -> list[float]:
    """Extract the 7-variable vector from a RegimeDef as an ordered list."""
    return [
        regime.spy_yy,
        regime.spread_10y2y,
        regime.wti_yy,
        regime.copper_yy,
        regime.tbill_yield,
        regime.vix_avg,
        regime.stock_bond_corr,
    ]
