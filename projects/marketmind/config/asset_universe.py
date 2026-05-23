"""Robinhood-tradable asset universe."""
from dataclasses import dataclass, field


@dataclass
class Asset:
    ticker: str
    name: str
    asset_class: str
    sector: str | None = None
    factor_exposures: dict[str, float] = field(default_factory=dict)

    @property
    def robinhood_tradable(self) -> bool:
        return self.asset_class in ("equity", "etf", "crypto")


ASSET_UNIVERSE: dict[str, Asset] = {
    "SPY": Asset("SPY", "SPDR S&P 500 ETF", "etf", None, {"beta": 1.0}),
    "QQQ": Asset("QQQ", "Invesco QQQ Trust", "etf", "Technology", {"beta": 1.2, "rate": -0.3}),
    "IWM": Asset("IWM", "iShares Russell 2000", "etf", None, {"beta": 1.1, "rate": -0.4}),
    "DIA": Asset("DIA", "SPDR Dow Jones", "etf", None, {"beta": 0.9}),
    "TLT": Asset("TLT", "iShares 20+ Year Treasury", "etf", None, {"rate": 1.0, "beta": -0.3}),
    "GLD": Asset("GLD", "SPDR Gold Trust", "etf", None, {"gold": 1.0, "beta": 0.0}),
    "SLV": Asset("SLV", "iShares Silver Trust", "etf", None, {"gold": 0.8, "beta": 0.1}),
    "USO": Asset("USO", "United States Oil Fund", "etf", "Energy", {"oil": 1.0, "beta": 0.2}),
    "UNG": Asset("UNG", "United States Natural Gas", "etf", "Energy", {"oil": 0.6, "beta": 0.1}),
    "DBA": Asset("DBA", "Invesco DB Agriculture", "etf", None, {"agri": 1.0, "beta": 0.1}),
    "EEM": Asset("EEM", "iShares MSCI Emerging Markets", "etf", None, {"beta": 1.1, "rate": -0.2}),
    "XLF": Asset("XLF", "Financial Select Sector", "etf", "Financials", {"rate": 0.5, "beta": 1.0}),
    "XLK": Asset("XLK", "Technology Select Sector", "etf", "Technology", {"beta": 1.2, "rate": -0.4}),
    "XLE": Asset("XLE", "Energy Select Sector", "etf", "Energy", {"oil": 0.9, "beta": 0.9}),
    "XLV": Asset("XLV", "Health Care Select Sector", "etf", "Healthcare", {"beta": 0.7}),
    "AAPL": Asset("AAPL", "Apple Inc.", "equity", "Technology", {"beta": 1.2, "rate": -0.3}),
    "MSFT": Asset("MSFT", "Microsoft Corp.", "equity", "Technology", {"beta": 1.1, "rate": -0.2}),
    "NVDA": Asset("NVDA", "NVIDIA Corp.", "equity", "Technology", {"beta": 1.5, "rate": -0.4}),
    "GOOGL": Asset("GOOGL", "Alphabet Inc.", "equity", "Technology", {"beta": 1.1, "rate": -0.2}),
    "AMZN": Asset("AMZN", "Amazon.com Inc.", "equity", "Consumer", {"beta": 1.1, "rate": -0.2}),
    "META": Asset("META", "Meta Platforms Inc.", "equity", "Technology", {"beta": 1.3, "rate": -0.3}),
    "TSLA": Asset("TSLA", "Tesla Inc.", "equity", "Consumer", {"beta": 1.8, "rate": -0.5, "oil": -0.2}),
    "JPM": Asset("JPM", "JPMorgan Chase & Co.", "equity", "Financials", {"rate": 0.6, "beta": 1.0}),
    "XOM": Asset("XOM", "Exxon Mobil Corp.", "equity", "Energy", {"oil": 0.9, "beta": 0.8}),
    "BTC-USD": Asset("BTC-USD", "Bitcoin", "crypto", None, {"beta": 1.5, "rate": -0.3, "gold": 0.3}),
}


def get_asset(ticker: str) -> Asset | None:
    return ASSET_UNIVERSE.get(ticker.upper())


def get_assets_by_class(asset_class: str) -> list[Asset]:
    return [a for a in ASSET_UNIVERSE.values() if a.asset_class == asset_class]


def get_assets_by_sector(sector: str) -> list[Asset]:
    return [a for a in ASSET_UNIVERSE.values() if a.sector == sector]
