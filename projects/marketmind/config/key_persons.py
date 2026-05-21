"""Key person / influencer tracker for named-entity social media monitoring.

Swiss Finance Institute (2026): finfluencer picks = -2.3% returns;
fading them = +6.8% alpha. Most finfluencers are CONTRARIAN signals.

Keith Gill (Roaring Kitty) and Donald Trump are DIRECTIONAL signals:
- Gill: documented market-moving power (May 2026: $500M GME position, 800%+ surge)
- Trump: policy catalyst (tariffs, executive orders, regulatory changes)

Category system (market-figure-intelligence-module.md §2):
  I   = policymaker (central bank governors, finance ministers)
  II  = political (presidents, congress members)
  III = executive (CEOs of major public companies)
  IV  = activist investor (hedge fund activists)
  V   = fund manager (13F filers, macro thinkers)
  VI  = celebrity / finfluencer

This config is domain-reasoned, not backtest-optimized (Law 3 compliance).

Usage: `from marketmind.config.key_persons import KEY_PERSONS, KeyPerson`
"""
from dataclasses import dataclass


@dataclass
class KeyPerson:
    name: str
    keywords: list[str]       # trigger keywords in news titles
    signal_direction: str     # "directional" | "contrarian" | "confirmatory"
    platforms: list[str]      # where they post
    fraud_risk: str           # "low" | "medium" | "high"
    has_dedicated_source: bool  # True if this person has a dedicated Source entry
    category: str = "VI"      # I-VI per market-figure-intelligence-module.md §2
    notes: str = ""


KEY_PERSONS: list[KeyPerson] = [
    # ═══════════════════════════════════════════════════════════════════════════
    # CATEGORY I — Policymakers (DIRECTIONAL — follow the signal)
    # Acemoglu, Johnson & Kermani (2016): political connections → 6-12% CAR
    # Gorodnichenko et al.: Fed chair tone → 200bp S&P 500 impact
    # ═══════════════════════════════════════════════════════════════════════════

    KeyPerson(
        name="Jerome Powell",
        keywords=["jerome powell", "jay powell", "powell", "fed chair", "federal reserve chair"],
        signal_direction="directional",
        platforms=["fed_website"],
        fraud_risk="low",
        has_dedicated_source=True,  # fed RSS via source_authority.py
        category="I",
        notes=(
            "DIRECTIONAL — DO NOT INVERT. Fed Chair. Every FOMC press conference, "
            "congressional testimony, and public speech moves markets. "
            "Gorodnichenko et al.: Fed chair tone → up to 200bp S&P 500 impact. "
            "FOMC voting member with highest information advantage (distance-to-decision = 0)."
        ),
    ),
    KeyPerson(
        name="Christine Lagarde",
        keywords=["christine lagarde", "lagarde", "ecb president", "ecb chair"],
        signal_direction="directional",
        platforms=["ecb_website"],
        fraud_risk="low",
        has_dedicated_source=True,  # ECB RSS via source_authority.py
        category="I",
        notes=(
            "DIRECTIONAL — DO NOT INVERT. ECB President. "
            "Eurozone monetary policy decisions directly impact EUR/USD, European equities, "
            "and sovereign bond yields. Every press conference is a market event."
        ),
    ),
    KeyPerson(
        name="Kazuo Ueda",
        keywords=["kazuo ueda", "ueda", "boj governor", "bank of japan governor"],
        signal_direction="directional",
        platforms=["boj_website"],
        fraud_risk="low",
        has_dedicated_source=False,
        category="I",
        notes=(
            "DIRECTIONAL — DO NOT INVERT. BOJ Governor. "
            "Yen carry trade linchpin. BOJ policy shifts directly impact JPY pairs, "
            "Nikkei 225, and global fixed income. Any hint of rate normalization = major market event."
        ),
    ),

    # ═══════════════════════════════════════════════════════════════════════════
    # CATEGORY II — Political Figures (DIRECTIONAL — follow the signal)
    # Kleczka (2020): Trump company-specific tweets → ±0.25% AR, +19% volume
    # ═══════════════════════════════════════════════════════════════════════════

    KeyPerson(
        name="Donald Trump",
        keywords=["trump", "donald trump", "potus", "president trump"],
        signal_direction="directional",
        platforms=["truth_social", "x"],
        fraud_risk="low",
        has_dedicated_source=True,  # trumpstruth.org RSS feed
        category="II",
        notes=(
            "DIRECTIONAL — DO NOT INVERT. Policy catalyst: tariff/executive order/"
            "deregulation posts move markets. Dedicated source: trumpstruth.org/feed RSS. "
            "~90% noise ratio — aggressive pre-flight keyword filter required. "
            "Kleczka (2020): company-specific tweets → ±0.25% abnormal returns."
        ),
    ),
    KeyPerson(
        name="Nancy Pelosi",
        keywords=["nancy pelosi", "pelosi", "speaker pelosi"],
        signal_direction="directional",
        platforms=["congress_trades"],
        fraud_risk="low",
        has_dedicated_source=False,  # MCP capitol-trades
        category="II",
        notes=(
            "DIRECTIONAL — follow congressional trade disclosures. "
            "Most tracked congress member for stock trading. "
            "Disclosure filings via STOCK Act. Data source: @anguslin/mcp-capitol-trades. "
            "Historical returns significantly above market average (controversial but documented)."
        ),
    ),

    # ═══════════════════════════════════════════════════════════════════════════
    # CATEGORY III — Corporate Executives (DIRECTIONAL — follow the signal)
    # ═══════════════════════════════════════════════════════════════════════════

    KeyPerson(
        name="Elon Musk",
        keywords=["elon musk", "elon", "musk"],
        signal_direction="contrarian",
        platforms=["x"],
        fraud_risk="medium",
        has_dedicated_source=False,
        category="III",
        notes=(
            "CONTRARIAN — invert. Tesla/TSLA, crypto, gov contracts affected by statements. "
            "Medium fraud risk: criticized for biased/market-moving statements. "
            "Evidence of declining market influence over time — monitor quarterly."
        ),
    ),
    KeyPerson(
        name="Jensen Huang",
        keywords=["jensen huang", "jensen", "nvidia ceo", "nvda ceo"],
        signal_direction="directional",
        platforms=["x", "conference"],
        fraud_risk="low",
        has_dedicated_source=False,
        category="III",
        notes=(
            "DIRECTIONAL — DO NOT INVERT. NVIDIA CEO. NVDA is the most important stock "
            "in the AI trade (3T+ market cap). Huang's keynote speeches, earnings calls, "
            "and product announcements directly move semiconductor sector and broader tech. "
            "GTC conference keynotes are major market catalysts."
        ),
    ),
    KeyPerson(
        name="Jamie Dimon",
        keywords=["jamie dimon", "dimon", "jpmorgan ceo", "jpm ceo"],
        signal_direction="directional",
        platforms=["conference", "interview"],
        fraud_risk="low",
        has_dedicated_source=False,
        category="III",
        notes=(
            "DIRECTIONAL — DO NOT INVERT. JPMorgan Chase CEO. "
            "Annual shareholder letter is widely read by the market. "
            "Comments on economy, regulation, and banking sector carry significant weight. "
            "Longest-serving major bank CEO — institutional credibility is high."
        ),
    ),

    # ═══════════════════════════════════════════════════════════════════════════
    # CATEGORY V — Fund Managers (CONFIRMATORY — 13F is backward-looking)
    # ═══════════════════════════════════════════════════════════════════════════

    KeyPerson(
        name="Warren Buffett",
        keywords=["warren buffett", "buffett", "berkshire hathaway", "brk"],
        signal_direction="confirmatory",
        platforms=["13f_filing"],
        fraud_risk="low",
        has_dedicated_source=False,  # SEC 13F EDGAR
        category="V",
        notes=(
            "CONFIRMATORY — NOT directional. 13F filings are backward-looking (45-day lag). "
            "Berkshire Hathaway's quarterly 13F is the most-watched institutional filing. "
            "Use as confirmation/sentiment check, not as entry signal. "
            "Buffett's annual letter and interviews carry additional weight."
        ),
    ),
    KeyPerson(
        name="Michael Burry",
        keywords=["michael burry", "burry", "scion", "scion asset"],
        signal_direction="directional",
        platforms=["x", "13f_filing"],
        fraud_risk="low",
        has_dedicated_source=False,  # SEC 13F EDGAR
        category="V",
        notes=(
            "DIRECTIONAL — DO NOT INVERT. Scion Asset Management. "
            "Known for contrarian macro bets (2008 housing crash, 2021 meme stock short). "
            "13F filings reveal concentrated positions. "
            "X posts (when active) contain macro warnings. "
            "Signal is rare but high-impact when it appears."
        ),
    ),

    # ═══════════════════════════════════════════════════════════════════════════
    # CATEGORY VI — Celebrities / Finfluencers (CONTRARIAN — invert the signal)
    # Swiss Finance Institute (2026): fading finfluencer picks = +6.8% alpha
    # Keasey et al. (2025): influencer posts → short-term price changes, fast reversal
    # ═══════════════════════════════════════════════════════════════════════════

    KeyPerson(
        name="Keith Gill",
        keywords=["roaring kitty", "keith gill", "deepfuckingvalue", "dfv"],
        signal_direction="directional",
        platforms=["x", "youtube", "reddit"],
        fraud_risk="low",
        has_dedicated_source=False,
        category="VI",
        notes=(
            "DIRECTIONAL — DO NOT INVERT (special case: documented market-moving power). "
            "May 2026: $500M GME position, 800%+ surge, $4B short-seller losses. "
            "X posts trigger trading halts. The ONLY finfluencer whose signal is NOT contrarian. "
            "Category VI by platform but Category I by market impact."
        ),
    ),
    KeyPerson(
        name="Graham Stephan",
        keywords=["graham stephan"],
        signal_direction="contrarian",
        platforms=["youtube"],
        fraud_risk="low",
        has_dedicated_source=False,
        category="VI",
        notes="5.15M YouTube subs. Real estate/mortgage focus.",
    ),
    KeyPerson(
        name="Jeremy Lefebvre",
        keywords=["jeremy lefebvre", "financial education"],
        signal_direction="contrarian",
        platforms=["youtube"],
        fraud_risk="medium",
        has_dedicated_source=False,
        category="VI",
        notes="921K YouTube subs. Medium fraud risk: criticized for biased recommendations.",
    ),
    KeyPerson(
        name="Andrei Jikh",
        keywords=["andrei jikh"],
        signal_direction="contrarian",
        platforms=["youtube"],
        fraud_risk="low",
        has_dedicated_source=False,
        category="VI",
        notes="3M+ YouTube subs. Crypto focus.",
    ),
    KeyPerson(
        name="George Gammon",
        keywords=["george gammon"],
        signal_direction="contrarian",
        platforms=["youtube"],
        fraud_risk="low",
        has_dedicated_source=False,
        category="VI",
        notes="579K YouTube subs. Macro/economic focus.",
    ),
    KeyPerson(
        name="Tom Nash",
        keywords=["tom nash"],
        signal_direction="contrarian",
        platforms=["youtube"],
        fraud_risk="low",
        has_dedicated_source=False,
        category="VI",
        notes="607K YouTube subs. Early PLTR investor.",
    ),
]
