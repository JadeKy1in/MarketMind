"""Asset-class / proxy groups for advisor votes (owner decision 2026-09-29).

A vote on any member counts for the whole group: a long on GC=F supports a GLD trend
entry. Anything not listed is its own group (the exact ticker). Inverse and leveraged
products and yield indices (^TNX) are left out on purpose: their direction is flipped
or distorted relative to the group.
"""
from __future__ import annotations

ASSET_GROUPS: dict[str, tuple[str, ...]] = {
    "crypto": ("BTC-USD", "ETH-USD", "SOL-USD", "AVAX-USD", "LINK-USD", "UNI-USD", "AAVE-USD",
               "DOGE-USD", "XRP-USD", "ADA-USD", "BTC=F", "ETH=F", "IBIT", "FBTC", "GBTC",
               "BITO", "ETHA", "ETHE"),
    "precious_metals": ("GLD", "IAU", "GLDM", "SLV", "PPLT", "GC=F", "SI=F", "PL=F",
                        "GDX", "GDXJ", "SIL"),
    "us_equity_index": ("SPY", "VOO", "IVV", "VTI", "QQQ", "QQQM", "IWM", "DIA",
                        "ES=F", "NQ=F", "YM=F", "RTY=F", "^GSPC", "^NDX", "^DJI", "^RUT"),
    "long_rates": ("TLT", "IEF", "TLH", "EDV", "GOVT", "ZN=F", "ZB=F", "ZF=F", "UB=F"),
    "energy": ("USO", "BNO", "XLE", "XOP", "OIH", "VDE", "CL=F", "BZ=F"),
    "natural_gas": ("UNG", "NG=F"),
    "industrial_metals": ("CPER", "COPX", "HG=F"),
    "us_dollar": ("UUP", "DX-Y.NYB", "DX=F"),
    # sector ETFs -> their sector
    "sector_tech": ("XLK", "VGT", "SMH", "SOXX"),
    "sector_financials": ("XLF", "VFH", "KBE", "KRE"),
    "sector_health": ("XLV", "VHT", "IBB", "XBI"),
    "sector_industrials": ("XLI", "VIS"),
    "sector_discretionary": ("XLY", "VCR"),
    "sector_staples": ("XLP", "VDC"),
    "sector_utilities": ("XLU", "VPU"),
    "sector_materials": ("XLB", "VAW"),
    "sector_real_estate": ("XLRE", "VNQ", "IYR"),
    "sector_communication": ("XLC", "VOX"),
}

_BY_TICKER: dict[str, str] = {}
for _group, _members in ASSET_GROUPS.items():
    for _t in _members:
        if _t in _BY_TICKER:                     # one group per ticker, checked at import
            raise ValueError(f"{_t} is in both {_BY_TICKER[_t]} and {_group}")
        _BY_TICKER[_t] = _group


def asset_group(ticker: str) -> str:
    """The ticker's group, or the upper-cased ticker itself ("other" fallback)."""
    t = (ticker or "").strip().upper()
    return _BY_TICKER.get(t, t)
