"""Key person / influencer tracker for named-entity social media monitoring.

Swiss Finance Institute (2026): finfluencer picks = -2.3% returns;
fading them = +6.8% alpha. Most finfluencers are CONTRARIAN signals.

Keith Gill (Roaring Kitty) and Donald Trump are the only DIRECTIONAL signals:
- Gill: documented market-moving power (May 2026: $500M GME position, 800%+ surge)
- Trump: policy catalyst (tariffs, executive orders, regulatory changes)

This config is domain-reasoned, not backtest-optimized (Law 3 compliance).

Usage: `from marketmind.config.key_persons import KEY_PERSONS, KeyPerson`
"""
from dataclasses import dataclass


@dataclass
class KeyPerson:
    name: str
    keywords: list[str]       # trigger keywords in news titles
    signal_direction: str     # "directional" | "contrarian" | "context_dependent"
    platforms: list[str]      # where they post
    fraud_risk: str           # "low" | "medium" | "high"
    has_dedicated_source: bool  # True if this person has a dedicated Source entry
    notes: str = ""


KEY_PERSONS: list[KeyPerson] = [
    # ── Market Movers (DIRECTIONAL — follow the signal) ──────────────────
    KeyPerson(
        name="Donald Trump",
        keywords=["trump", "donald trump", "potus"],
        signal_direction="directional",
        platforms=["truth_social", "x"],
        fraud_risk="low",
        has_dedicated_source=True,  # trumpstruth.org RSS feed
        notes=(
            "DIRECTIONAL — DO NOT INVERT. Policy catalyst: tariff/executive order/"
            "deregulation posts move markets. Dedicated source: trumpstruth.org/feed RSS. "
            "~90% noise ratio — aggressive pre-flight keyword filter required."
        ),
    ),
    KeyPerson(
        name="Keith Gill",
        keywords=["roaring kitty", "keith gill", "deepfuckingvalue", "dfv"],
        signal_direction="directional",
        platforms=["x", "youtube", "reddit"],
        fraud_risk="low",
        has_dedicated_source=False,
        notes=(
            "DIRECTIONAL — DO NOT INVERT. #1 market mover. "
            "May 2026: $500M GME position, 800%+ surge, $4B short-seller losses. "
            "X posts trigger trading halts. The only finfluencer whose signal is NOT contrarian."
        ),
    ),

    # ── Finfluencers (CONTRARIAN — invert the signal) ─────────────────────
    # Swiss Finance Institute (2026): fading finfluencer picks = +6.8% alpha
    KeyPerson(
        name="Elon Musk",
        keywords=["elon musk", "elon", "musk"],
        signal_direction="contrarian",
        platforms=["x"],
        fraud_risk="medium",
        has_dedicated_source=False,
        notes=(
            "CONTRARIAN — invert. Tesla/TSLA, crypto, gov contracts affected by statements. "
            "Medium fraud risk: criticized for biased/market-moving statements."
        ),
    ),
    KeyPerson(
        name="Graham Stephan",
        keywords=["graham stephan"],
        signal_direction="contrarian",
        platforms=["youtube"],
        fraud_risk="low",
        has_dedicated_source=False,
        notes="5.15M YouTube subs. Real estate/mortgage focus.",
    ),
    KeyPerson(
        name="Jeremy Lefebvre",
        keywords=["jeremy lefebvre", "financial education"],
        signal_direction="contrarian",
        platforms=["youtube"],
        fraud_risk="medium",
        has_dedicated_source=False,
        notes="921K YouTube subs. Medium fraud risk: criticized for biased recommendations.",
    ),
    KeyPerson(
        name="Andrei Jikh",
        keywords=["andrei jikh"],
        signal_direction="contrarian",
        platforms=["youtube"],
        fraud_risk="low",
        has_dedicated_source=False,
        notes="3M+ YouTube subs. Crypto focus.",
    ),
    KeyPerson(
        name="George Gammon",
        keywords=["george gammon"],
        signal_direction="contrarian",
        platforms=["youtube"],
        fraud_risk="low",
        has_dedicated_source=False,
        notes="579K YouTube subs. Macro/economic focus.",
    ),
    KeyPerson(
        name="Tom Nash",
        keywords=["tom nash"],
        signal_direction="contrarian",
        platforms=["youtube"],
        fraud_risk="low",
        has_dedicated_source=False,
        notes="607K YouTube subs. Early PLTR investor.",
    ),
]
