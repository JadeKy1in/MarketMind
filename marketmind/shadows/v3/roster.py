"""The long-term shadow roster (SPEC_v3 §6.2): single source of truth for S3.

Each entry names the shadow's domain, the tickers its daily context covers
(`watchlist`), the domain benchmark written into its ledger records, and
whether it is live. A shadow goes live only with a complete methodology prompt
in `prompts/<name>.md` (SPEC §6.2 precondition).

IDs keep the namespaced form already used by gateway/fred_client.SHADOW_FRED_SERIES.
Watchlists hold Robinhood-tradable, ledger-settleable symbols only (US stocks,
ETFs, crypto as BASE-USD); the runner re-checks them against the universe.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

PROMPT_DIR = Path(__file__).resolve().parent / "prompts"

ACTIVE = "active"
PENDING_PROMPT = "pending_prompt"

SECTORS = ["XLK", "XLF", "XLE", "XLV", "XLI", "XLY", "XLP", "XLU", "XLB", "XLRE", "XLC"]


@dataclass(frozen=True)
class RosterEntry:
    shadow_id: str
    name: str                      # short name, also the prompt file stem
    display_name: str
    group: str                     # fundamental | momentum | contrarian | short | derivatives | cross_market
    domain: str
    watchlist: tuple[str, ...]
    domain_benchmark: str
    status: str = ACTIVE
    news_keywords: tuple[str, ...] = field(default_factory=tuple)  # empty = all news
    notes: str = ""

    @property
    def prompt_path(self) -> Path:
        return PROMPT_DIR / f"{self.name}.md"


def _e(shadow_id, display_name, group, domain, watchlist, bench, status=ACTIVE,
       keywords=(), notes="") -> RosterEntry:
    name = shadow_id.rsplit(":", 1)[-1]
    if shadow_id == "contrarian:crash:hunter":
        name = "crash_hunter"
    return RosterEntry(shadow_id, name, display_name, group, domain, tuple(watchlist), bench,
                       status, tuple(keywords), notes)


ROSTER: tuple[RosterEntry, ...] = (
    # ── Fundamental (17) ────────────────────────────────────────────────────
    _e("expert:gold:bullion_broker", "Bullion Broker", "fundamental", "precious metals",
       ["GLD", "SLV", "GDX", "GDXJ", "SIL", "NEM", "AEM", "WPM", "PPLT"], "GLD",
       keywords=["gold", "silver", "precious", "bullion", "platinum", "central bank", "real yield"]),
    _e("expert:crypto:chain_oracle", "Chain Oracle", "fundamental", "major crypto (BTC/ETH)",
       ["BTC-USD", "ETH-USD", "SOL-USD", "IBIT", "ETHA", "COIN", "MSTR"], "BTC-USD",
       keywords=["bitcoin", "crypto", "ethereum", "stablecoin", "etf flow", "blockchain"]),
    _e("expert:crypto:defi_scout", "DeFi Scout", "fundamental", "altcoins and DeFi",
       ["SOL-USD", "AVAX-USD", "LINK-USD", "UNI-USD", "AAVE-USD", "DOGE-USD", "BTC-USD", "ETH-USD"],
       "ETH-USD",
       keywords=["defi", "altcoin", "token", "solana", "crypto"]),
    _e("expert:energy:oil_geologist", "Oil Geologist", "fundamental", "energy",
       ["USO", "XLE", "XOP", "XOM", "CVX", "COP", "OXY", "SLB", "UNG"], "XLE",
       keywords=["oil", "crude", "opec", "energy", "natural gas", "petroleum", "refin", "brent"]),
    _e("expert:bonds:yield_whisperer", "Yield Whisperer", "fundamental", "rates and credit",
       ["TLT", "IEF", "SHY", "TIP", "EDV", "HYG", "LQD", "TBT"], "AGG",
       keywords=["treasury", "bond", "yield", "fed", "rate", "inflation", "credit", "auction"]),
    _e("expert:vol:vega_trader", "Vega Trader", "fundamental", "volatility",
       ["VXX", "UVXY", "SVXY", "SPY", "QQQ"], "SPY",
       keywords=["vix", "volatility", "options", "selloff", "hedg", "risk-off"]),
    _e("expert:em:frontier_scout", "Frontier Scout", "fundamental",
       "emerging markets ex-China",
       ["EEM", "INDA", "EWZ", "EWW", "EWY", "EWT", "EZA", "TUR", "ARGT"], "EEM",
       keywords=["emerging", "india", "brazil", "mexico", "korea", "taiwan", "turkey",
                 "argentina", "south africa"]),
    _e("expert:tech:silicon_oracle", "Silicon Oracle", "fundamental", "technology",
       ["QQQ", "SMH", "NVDA", "AMD", "AVGO", "TSM", "MSFT", "AAPL", "GOOGL", "META", "AMZN"],
       "XLK", keywords=["tech", "ai", "software", "chip", "semiconductor", "cloud", "nvidia"]),
    _e("expert:financials:bank_examiner", "Bank Examiner", "fundamental", "financials",
       ["XLF", "KRE", "JPM", "BAC", "WFC", "C", "GS", "MS", "SCHW"], "XLF",
       keywords=["bank", "financial", "loan", "credit", "deposit", "lender", "brokerage"]),
    _e("expert:healthcare:trial_reviewer", "Trial Reviewer", "fundamental", "healthcare",
       ["XLV", "IBB", "XBI", "LLY", "UNH", "JNJ", "MRK", "ABBV", "PFE", "VRTX"], "XLV",
       keywords=["fda", "drug", "trial", "health", "pharma", "biotech", "medicare", "approval"]),
    _e("expert:consumer:wallet_watcher", "Wallet Watcher", "fundamental", "consumer",
       ["XLY", "XLP", "XRT", "AMZN", "WMT", "COST", "HD", "MCD", "NKE", "TGT"], "XLY",
       keywords=["retail", "consumer", "sales", "sentiment", "spending", "shopper", "restaurant"]),
    _e("expert:industrials:factory_floor", "Factory Floor", "fundamental", "industrials",
       ["XLI", "ITA", "CAT", "DE", "GE", "HON", "BA", "LMT", "UNP", "ETN"], "XLI",
       keywords=["pmi", "manufacturing", "industrial", "factory", "defense", "aerospace",
                 "freight", "orders"]),
    _e("expert:metals:steel_trader", "Steel Trader", "fundamental", "industrial metals",
       ["XME", "COPX", "CPER", "FCX", "SCCO", "NUE", "CLF", "AA"], "XME",
       keywords=["steel", "copper", "iron ore", "aluminum", "lme", "mining", "metal"]),
    _e("expert:agriculture:harvest_seer", "Harvest Seer", "fundamental", "agriculture",
       ["DBA", "CORN", "WEAT", "SOYB", "ADM", "BG", "MOS", "NTR", "DE"], "DBA",
              keywords=["crop", "grain", "wheat", "corn", "soybean", "usda", "fertilizer", "drought"]),
    _e("expert:realestate:reit_analyst", "REIT Analyst", "fundamental", "real estate",
       ["VNQ", "XLRE", "PLD", "AMT", "EQIX", "O", "SPG", "ITB", "XHB"], "VNQ",
       keywords=["reit", "real estate", "housing", "mortgage", "home", "property", "rent"]),
    _e("expert:fx:currency_dealer", "Currency Dealer", "fundamental", "currencies",
       ["UUP", "UDN", "FXE", "FXY", "FXB", "FXF", "FXA", "FXC"], "UUP",
       keywords=["dollar", "euro", "yen", "pound", "currency", "forex", "fx", "boj", "ecb"]),
    _e("expert:macro:cycle_reader", "Cycle Reader", "fundamental", "macro cross-asset",
       ["SPY", "QQQ", "IWM", "TLT", "GLD", "UUP", "DBC", "HYG", "EEM", "BTC-USD"], "SPY"),
    # ── Momentum (4) ────────────────────────────────────────────────────────
    _e("momentum:intraday:scalper", "Scalper", "momentum", "intraday (daily-bar approximation)",
       ["SPY", "QQQ", "IWM", "NVDA", "TSLA", "AAPL", "AMD", "META", "BTC-USD"], "SPY",
       notes="intraday_approx: daily bars only; hold 1 day, next open to that close"),
    _e("momentum:weekly:trend_rider", "Trend Rider", "momentum", "weekly trends",
       ["SPY", "QQQ", "IWM", *SECTORS, "GLD", "TLT", "BTC-USD"], "SPY"),
    _e("momentum:event:news_hound", "News Hound", "momentum", "event-driven",
       ["SPY", "QQQ", "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AVGO",
        "JPM", "XOM", "LLY", "UNH"], "SPY",
       notes="context adds up to 10 tradable tickers named in today's news"),
    _e("momentum:sector:rotation_engine", "Rotation Engine", "momentum", "sector rotation",
       ["SPY", *SECTORS], "SPY"),
    # ── Contrarian (4) ──────────────────────────────────────────────────────
    _e("contrarian:consensus:fade_master", "Fade Master", "contrarian", "consensus fading",
       ["SPY", "QQQ", "IWM"], "SPY",
       notes="only shadow that sees ConsensusExtractor output (yesterday's shadow directions)"),
    _e("contrarian:range_bound:sideways_scout", "Sideways Scout", "contrarian", "range trading",
       ["SPY", "QQQ", "IWM", "DIA", "XLU", "XLP", "GLD", "TLT"], "SPY"),
    _e("contrarian:panic:vol_surfer", "Vol Surfer", "contrarian", "panic buying",
       ["SPY", "QQQ", "IWM", "VXX", "SVXY", "HYG"], "SPY"),
    _e("contrarian:crash:hunter", "Crash Hunter", "contrarian", "systemic bubble / crash",
       ["SPY", "QQQ", "SH", "PSQ", "TLT", "GLD", "VXX", "HYG"], "SPY"),
    # ── Short (2) ───────────────────────────────────────────────────────────
    _e("expert:short:bear_tracker", "Bear Tracker", "short", "fundamental shorts",
       ["SPY", "QQQ", "ARKK", "TSLA", "PLTR", "SMCI", "COIN"], "SPY",        keywords=["going concern", "material weakness", "restate", "guidance cut", "lowers guidance",
                 "downgrade", "probe", "subpoena", "fraud", "short seller", "bankrupt", "delist",
                 "impairment", "misses", "layoff"],
       notes="context adds up to 10 tradable tickers named in SEC full-text red-flag filings"),
    _e("short:squeeze:squeeze_watch", "Squeeze Watch", "short", "crowded shorts / squeezes",
       # Nasdaq-listed only: Nasdaq's API has no short interest for NYSE names (GME, AMC, CVNA)
       ["IWM", "UPST", "SOFI", "LCID", "RIVN", "PLUG", "OPEN", "CELH", "BYND"], "IWM",
              keywords=["short interest", "short squeeze", "squeeze", "short seller", "meme", "retail traders"],
       notes="context adds Nasdaq short interest (shares, change, days to cover) per stock"),
    # ── Derivatives and odds (2) ────────────────────────────────────────────
    _e("derivatives:options:options_reader", "Options Reader", "derivatives",
       "options-implied signals",
       ["SPY", "QQQ", "IWM", "NVDA", "TSLA", "AAPL", "AMZN", "META", "AMD"], "SPY",
              keywords=["options", "unusual activity", "call buying", "put buying", "volatility", "expiration"],
       notes="context adds Nasdaq option-chain summaries per ticker"),
    # BLOCKED (2026-09-28), NOT ABANDONED: needs real-money prediction-market odds
    # (Kalshi / Polymarket public APIs). They are unreachable from the owner's current
    # location (Riyadh network resets TLS; likely local gambling-site policy) and the
    # owner chose not to work around local rules. Resume when those APIs are reachable
    # directly: see SPEC_v3 §13.1 and AGENTS.md "Open work" for the steps.
    _e("derivatives:odds:odds_analyst", "Odds Analyst", "derivatives", "prediction-market odds",
       ["SPY", "TLT", "GLD", "UUP", "BTC-USD"], "SPY", status=PENDING_PROMPT,
       notes="BLOCKED: no reachable real-money prediction-market data; see SPEC_v3 §13.1"),
    # ── Cross-market (3) ────────────────────────────────────────────────────
    _e("cross:china:dragon_watch", "Dragon Watch", "cross_market", "China / Asia",
       ["FXI", "KWEB", "MCHI", "ASHR", "BABA", "PDD", "JD", "BIDU", "EWH"], "FXI",
              keywords=["china", "chinese", "beijing", "pboc", "yuan", "renminbi", "hong kong", "hang seng",
                 "stimulus", "xi ", "taiwan", "asia", "alibaba", "tencent", "中国", "央行", "港股",
                 "A股", "人民币"]),
    _e("cross:japan:carry_watch", "Carry Watch", "cross_market", "Japan and global carry",
       ["EWJ", "DXJ", "FXY", "UUP", "SPY", "QQQ"], "EWJ",
       keywords=["japan", "yen", "boj", "bank of japan", "nikkei", "topix", "carry", "ueda",
                 "jgb"]),
    _e("cross:europe:euro_watch", "Euro Watch", "cross_market", "Europe",
       ["VGK", "EZU", "FEZ", "EWG", "EWU", "EWQ", "FXE"], "VGK",
       keywords=["europe", "euro", "ecb", "lagarde", "germany", "german", "france", "french",
                 "britain", "uk ", "bank of england", "eurozone", "dax", "ftse", "stoxx"]),
)


def by_id() -> dict[str, RosterEntry]:
    return {r.shadow_id: r for r in ROSTER}


def active() -> list[RosterEntry]:
    """Live shadows: status active and a prompt file present."""
    return [r for r in ROSTER if r.status == ACTIVE and r.prompt_path.exists()]


def load_prompt(entry: RosterEntry) -> str:
    return entry.prompt_path.read_text(encoding="utf-8")
