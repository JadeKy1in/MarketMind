"""Scan universe of the Minervini SEPA agent (docs/PLAYGROUND_AGENTS.md §8).

A bounded seed list, not the whole market: about 150 US large caps (S&P 500-sized
names across all 11 GICS sectors, as of 2026-09) plus the 11 Select Sector SPDR ETFs.
Why a seed list: the repo has no index-constituent source, and scanning the ~10k symbols
of universe.equities would mean ~10k price-history requests a day. The adapter then
  1. drops seed symbols that are no longer listed (universe.equities, when available);
  2. keeps only instruments whose median 50-day dollar volume (close x volume) is at
     least MIN_DOLLAR_VOLUME, computed from the bars it fetched.
Known bias: today's large caps are yesterday's winners (survivorship), so the scan
over-represents stocks that already ran; relative strength is ranked inside this list,
not across the whole market as IBD does.

Names are short company names for matching headlines (the optional catalyst note).
"""
from __future__ import annotations

MIN_DOLLAR_VOLUME = 50e6          # USD, median of the last 50 complete bars

STOCKS: dict[str, str] = {
    # information technology
    "AAPL": "Apple", "MSFT": "Microsoft", "NVDA": "Nvidia", "AVGO": "Broadcom",
    "ORCL": "Oracle", "CRM": "Salesforce", "ADBE": "Adobe", "AMD": "AMD", "INTC": "Intel",
    "CSCO": "Cisco", "QCOM": "Qualcomm", "TXN": "Texas Instruments", "MU": "Micron",
    "AMAT": "Applied Materials", "LRCX": "Lam Research", "KLAC": "KLA", "ANET": "Arista",
    "NOW": "ServiceNow", "INTU": "Intuit", "PANW": "Palo Alto Networks",
    "CRWD": "CrowdStrike", "PLTR": "Palantir", "SNPS": "Synopsys", "CDNS": "Cadence",
    "MRVL": "Marvell", "IBM": "IBM", "DELL": "Dell", "APP": "AppLovin", "DDOG": "Datadog",
    "NET": "Cloudflare", "SHOP": "Shopify", "TSM": "TSMC",
    # communication services
    "GOOGL": "Alphabet", "META": "Meta", "NFLX": "Netflix", "DIS": "Disney",
    "TMUS": "T-Mobile", "VZ": "Verizon", "T": "AT&T", "CMCSA": "Comcast", "SPOT": "Spotify",
    # consumer discretionary
    "AMZN": "Amazon", "TSLA": "Tesla", "HD": "Home Depot", "MCD": "McDonald's",
    "NKE": "Nike", "SBUX": "Starbucks", "LOW": "Lowe's", "BKNG": "Booking", "TJX": "TJX",
    "CMG": "Chipotle", "ABNB": "Airbnb", "UBER": "Uber", "GM": "General Motors",
    "F": "Ford", "LULU": "Lululemon", "DASH": "DoorDash", "RCL": "Royal Caribbean",
    "ORLY": "O'Reilly",
    # consumer staples
    "WMT": "Walmart", "COST": "Costco", "PG": "Procter & Gamble", "KO": "Coca-Cola",
    "PEP": "PepsiCo", "PM": "Philip Morris", "MO": "Altria", "MDLZ": "Mondelez",
    "CL": "Colgate",
    # health care
    "LLY": "Eli Lilly", "UNH": "UnitedHealth", "JNJ": "Johnson & Johnson", "ABBV": "AbbVie",
    "MRK": "Merck", "PFE": "Pfizer", "TMO": "Thermo Fisher", "ABT": "Abbott",
    "ISRG": "Intuitive Surgical", "AMGN": "Amgen", "GILD": "Gilead", "VRTX": "Vertex",
    "REGN": "Regeneron", "BSX": "Boston Scientific", "DHR": "Danaher", "CVS": "CVS",
    # financials
    "JPM": "JPMorgan", "BAC": "Bank of America", "WFC": "Wells Fargo",
    "GS": "Goldman Sachs", "MS": "Morgan Stanley", "C": "Citigroup", "SCHW": "Schwab",
    "BLK": "BlackRock", "AXP": "American Express", "V": "Visa", "MA": "Mastercard",
    "PYPL": "PayPal", "COF": "Capital One", "SPGI": "S&P Global", "CME": "CME Group",
    "ICE": "Intercontinental Exchange", "KKR": "KKR", "BX": "Blackstone",
    "COIN": "Coinbase", "HOOD": "Robinhood", "BRK-B": "Berkshire",
    # industrials
    "CAT": "Caterpillar", "DE": "Deere", "GE": "GE Aerospace", "HON": "Honeywell",
    "BA": "Boeing", "RTX": "RTX", "LMT": "Lockheed", "UNP": "Union Pacific", "UPS": "UPS",
    "ETN": "Eaton", "GEV": "GE Vernova", "PH": "Parker-Hannifin",
    "WM": "Waste Management", "VRT": "Vertiv", "AXON": "Axon",
    # energy
    "XOM": "Exxon", "CVX": "Chevron", "COP": "ConocoPhillips", "EOG": "EOG Resources",
    "SLB": "SLB", "OXY": "Occidental", "MPC": "Marathon Petroleum", "PSX": "Phillips 66",
    "VLO": "Valero",
    # materials
    "LIN": "Linde", "FCX": "Freeport", "NEM": "Newmont", "SHW": "Sherwin-Williams",
    "NUE": "Nucor", "APD": "Air Products",
    # utilities
    "NEE": "NextEra", "SO": "Southern Company", "DUK": "Duke Energy",
    "CEG": "Constellation Energy", "VST": "Vistra",
    # real estate
    "PLD": "Prologis", "AMT": "American Tower", "EQIX": "Equinix", "SPG": "Simon Property",
}

SECTOR_ETFS: dict[str, str] = {
    "XLB": "materials stocks", "XLC": "communication services", "XLE": "energy stocks",
    "XLF": "financial stocks", "XLI": "industrial stocks", "XLK": "technology stocks",
    "XLP": "consumer staples", "XLRE": "real estate stocks", "XLU": "utilities",
    "XLV": "health care stocks", "XLY": "consumer discretionary",
}

NAMES: dict[str, str] = {**STOCKS, **SECTOR_ETFS}
SEED: tuple[str, ...] = tuple(NAMES)
