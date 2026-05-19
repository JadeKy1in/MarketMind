#!/usr/bin/env python3
"""Generate comprehensive pipeline fixtures by constructing data structures directly.

This bypasses HTTP/LLM calls that would hang. Fixtures use realistic synthetic data
following the shape of actual pipeline outputs (NewsItem, TriageResult, HypothesisResult, etc.).

Usage:
    cd E:/AI_Studio_Workspace/projects/marketmind
    PYTHONPATH=E:/AI_Studio_Workspace/projects python regenerate_fixtures.py
"""

from __future__ import annotations
import sys
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from marketmind.test_fixtures import save_fixture

# ── Stage 1: Scout (NewsItem-like dicts) ─────────────────────────────────────

SCOUT_NORMAL = [
    {
        "headline": "ECB holds rates steady at 4.25%, signals patience on cuts",
        "url": "https://example.com/ecb-rates",
        "source_name": "Reuters",
        "source_tier": 1,
        "published_at": "2026-05-19T08:00:00Z",
        "content_preview": "The European Central Bank maintained its key interest rate at 4.25%..."
    },
    {
        "headline": "US CPI unexpectedly drops to 2.8%, fueling rate cut bets",
        "url": "https://example.com/us-cpi",
        "source_name": "Bloomberg",
        "source_tier": 1,
        "published_at": "2026-05-19T07:30:00Z",
        "content_preview": "US consumer price inflation fell to 2.8% year-on-year in April..."
    },
    {
        "headline": "NVIDIA reports record Q1 revenue, AI chip demand surges",
        "url": "https://example.com/nvidia-earnings",
        "source_name": "CNBC",
        "source_tier": 1,
        "published_at": "2026-05-19T06:45:00Z",
        "content_preview": "NVIDIA posted record quarterly revenue of $42 billion..."
    },
    {
        "headline": "Gold hits new all-time high above $3,200 amid geopolitical tensions",
        "url": "https://example.com/gold-ath",
        "source_name": "Financial Times",
        "source_tier": 1,
        "published_at": "2026-05-19T06:00:00Z",
        "content_preview": "Gold prices surged past $3,200 per ounce on Monday..."
    },
    {
        "headline": "Treasury yields slide as bond market prices in two 2026 cuts",
        "url": "https://example.com/treasury-yields",
        "source_name": "WSJ",
        "source_tier": 1,
        "published_at": "2026-05-19T05:30:00Z",
        "content_preview": "US Treasury yields fell across the curve as traders increased bets on rate cuts..."
    },
    {
        "headline": "China PMI surprises to upside, manufacturing expands for third month",
        "url": "https://example.com/china-pmi",
        "source_name": "Reuters",
        "source_tier": 1,
        "published_at": "2026-05-19T05:00:00Z",
        "content_preview": "China's official manufacturing PMI rose to 51.2 in April, beating expectations..."
    },
    {
        "headline": "Oil prices jump 3% after OPEC+ extends production cuts",
        "url": "https://example.com/opec-cuts",
        "source_name": "Bloomberg",
        "source_tier": 1,
        "published_at": "2026-05-19T04:30:00Z",
        "content_preview": "Crude oil prices rose sharply after OPEC+ announced an extension of production cuts..."
    },
    {
        "headline": "Apple supplier Foxconn warns of chip shortage extending into 2027",
        "url": "https://example.com/foxconn-chip",
        "source_name": "Nikkei Asia",
        "source_tier": 2,
        "published_at": "2026-05-19T04:00:00Z",
        "content_preview": "Foxconn executives warned that semiconductor shortages may persist..."
    },
    {
        "headline": "BOJ Governor Ueda hints at possible rate hike in July meeting",
        "url": "https://example.com/boj-hike",
        "source_name": "Nikkei Asia",
        "source_tier": 2,
        "published_at": "2026-05-19T03:30:00Z",
        "content_preview": "Bank of Japan Governor Kazuo Ueda signaled readiness to raise rates..."
    },
    {
        "headline": "SEC approves first spot Ethereum ETF, crypto markets rally",
        "url": "https://example.com/sec-eth-etf",
        "source_name": "CoinDesk",
        "source_tier": 3,
        "published_at": "2026-05-19T03:00:00Z",
        "content_preview": "The SEC granted approval for the first spot Ethereum ETF..."
    },
    {
        "headline": "European natural gas prices surge on Norway pipeline maintenance",
        "url": "https://example.com/natgas-europe",
        "source_name": "Reuters",
        "source_tier": 1,
        "published_at": "2026-05-19T02:30:00Z",
        "content_preview": "European natural gas futures jumped 8% after Norway announced..."
    },
    {
        "headline": "Tesla cuts prices again in China, EV price war intensifies",
        "url": "https://example.com/tesla-china-cuts",
        "source_name": "CNBC",
        "source_tier": 1,
        "published_at": "2026-05-19T02:00:00Z",
        "content_preview": "Tesla reduced prices on its Model Y and Model 3 in China..."
    },
    {
        "headline": "UK inflation sticky at 3.1%, BOE rate cut timeline pushed back",
        "url": "https://example.com/uk-cpi",
        "source_name": "BBC",
        "source_tier": 2,
        "published_at": "2026-05-19T01:30:00Z",
        "content_preview": "UK CPI came in at 3.1% for April, above the 2.9% forecast..."
    },
    {
        "headline": "Microsoft announces $50B AI infrastructure investment plan",
        "url": "https://example.com/msft-ai-invest",
        "source_name": "WSJ",
        "source_tier": 1,
        "published_at": "2026-05-19T01:00:00Z",
        "content_preview": "Microsoft unveiled a $50 billion plan to expand its AI cloud infrastructure..."
    },
    {
        "headline": "Emerging market currencies under pressure as dollar strengthens",
        "url": "https://example.com/em-fx-pressure",
        "source_name": "Financial Times",
        "source_tier": 1,
        "published_at": "2026-05-19T00:30:00Z",
        "content_preview": "Emerging market currencies faced broad selling pressure..."
    },
]

SCOUT_EMPTY = []

# ── Stage 2: Flash Triage (TriageResult-like dicts) ─────────────────────────

FLASH_NORMAL = [
    {
        "headline": "ECB holds rates steady at 4.25%",
        "source_name": "Reuters",
        "source_tier": 1,
        "scores": {
            "market_impact": 7,
            "cross_source_corroboration": 8,
            "contradicts_consensus": 2,
            "investigative_depth_needed": 5,
            "urgency": 6
        },
        "classification": "macro",
        "affected_assets": ["EUR/USD", "DAX"],
        "cluster_hints": ["eurozone", "monetary_policy"],
        "cluster_id": 1,
        "head_index": 0,
        "direction": "neutral",
        "confidence": 0.65,
        "event_type": "monetary_policy",
    },
    {
        "headline": "US CPI drops to 2.8%",
        "source_name": "Bloomberg",
        "source_tier": 1,
        "scores": {
            "market_impact": 9,
            "cross_source_corroboration": 9,
            "contradicts_consensus": 7,
            "investigative_depth_needed": 6,
            "urgency": 10
        },
        "classification": "macro",
        "affected_assets": ["SPX", "TLT", "IWM"],
        "cluster_hints": ["inflation", "fed_policy"],
        "cluster_id": 2,
        "head_index": 1,
        "direction": "bullish",
        "confidence": 0.80,
        "event_type": "economic_data",
    },
    {
        "headline": "NVIDIA record Q1 revenue",
        "source_name": "CNBC",
        "source_tier": 1,
        "scores": {
            "market_impact": 6,
            "cross_source_corroboration": 7,
            "contradicts_consensus": 4,
            "investigative_depth_needed": 3,
            "urgency": 4
        },
        "classification": "company",
        "affected_assets": ["NVDA", "SMH", "QQQ"],
        "cluster_hints": ["ai_chips", "earnings"],
        "cluster_id": 3,
        "head_index": 2,
        "direction": "bullish",
        "confidence": 0.75,
        "event_type": "earnings",
    },
    {
        "headline": "Gold hits new ATH above $3,200",
        "source_name": "Financial Times",
        "source_tier": 1,
        "scores": {
            "market_impact": 8,
            "cross_source_corroboration": 8,
            "contradicts_consensus": 3,
            "investigative_depth_needed": 5,
            "urgency": 5
        },
        "classification": "macro",
        "affected_assets": ["GLD", "GDX", "XAU/USD"],
        "cluster_hints": ["safe_haven", "geopolitical"],
        "cluster_id": 4,
        "head_index": 3,
        "direction": "bullish",
        "confidence": 0.70,
        "event_type": "geopolitical",
    },
    {
        "headline": "Treasury yields slide on rate cut bets",
        "source_name": "WSJ",
        "source_tier": 1,
        "scores": {
            "market_impact": 7,
            "cross_source_corroboration": 6,
            "contradicts_consensus": 5,
            "investigative_depth_needed": 4,
            "urgency": 5
        },
        "classification": "macro",
        "affected_assets": ["TLT", "IEF", "SHY"],
        "cluster_hints": ["bonds", "rate_cuts"],
        "cluster_id": 5,
        "head_index": 4,
        "direction": "bullish",
        "confidence": 0.72,
        "event_type": "monetary_policy",
    },
    {
        "headline": "China PMI surprises to upside",
        "source_name": "Reuters",
        "source_tier": 1,
        "scores": {
            "market_impact": 7,
            "cross_source_corroboration": 7,
            "contradicts_consensus": 6,
            "investigative_depth_needed": 5,
            "urgency": 4
        },
        "classification": "macro",
        "affected_assets": ["FXI", "MCHI", "CNH"],
        "cluster_hints": ["china", "manufacturing"],
        "cluster_id": 6,
        "head_index": 5,
        "direction": "bullish",
        "confidence": 0.68,
        "event_type": "economic_data",
    },
    {
        "headline": "OPEC+ extends production cuts",
        "source_name": "Bloomberg",
        "source_tier": 1,
        "scores": {
            "market_impact": 8,
            "cross_source_corroboration": 8,
            "contradicts_consensus": 3,
            "investigative_depth_needed": 4,
            "urgency": 6
        },
        "classification": "macro",
        "affected_assets": ["USO", "XLE", "CL=F"],
        "cluster_hints": ["oil", "supply"],
        "cluster_id": 7,
        "head_index": 6,
        "direction": "bullish",
        "confidence": 0.78,
        "event_type": "geopolitical",
    },
    {
        "headline": "Apple supplier Foxconn warns of chip shortage",
        "source_name": "Nikkei Asia",
        "source_tier": 2,
        "scores": {
            "market_impact": 5,
            "cross_source_corroboration": 4,
            "contradicts_consensus": 2,
            "investigative_depth_needed": 4,
            "urgency": 3
        },
        "classification": "company",
        "affected_assets": ["AAPL", "SOXX", "TSM"],
        "cluster_hints": ["semiconductors", "supply_chain"],
        "cluster_id": 8,
        "head_index": 7,
        "direction": "bearish",
        "confidence": 0.55,
        "event_type": "supply_chain",
    },
    {
        "headline": "BOJ hints at possible July rate hike",
        "source_name": "Nikkei Asia",
        "source_tier": 2,
        "scores": {
            "market_impact": 8,
            "cross_source_corroboration": 6,
            "contradicts_consensus": 7,
            "investigative_depth_needed": 6,
            "urgency": 5
        },
        "classification": "macro",
        "affected_assets": ["USD/JPY", "EWJ", "NKY"],
        "cluster_hints": ["japan", "yen", "carry_trade"],
        "cluster_id": 9,
        "head_index": 8,
        "direction": "bearish",
        "confidence": 0.73,
        "event_type": "monetary_policy",
    },
    {
        "headline": "Tesla cuts prices again in China",
        "source_name": "CNBC",
        "source_tier": 1,
        "scores": {
            "market_impact": 6,
            "cross_source_corroboration": 7,
            "contradicts_consensus": 3,
            "investigative_depth_needed": 3,
            "urgency": 4
        },
        "classification": "company",
        "affected_assets": ["TSLA", "NIO", "XPEV"],
        "cluster_hints": ["ev", "china", "price_war"],
        "cluster_id": 10,
        "head_index": 9,
        "direction": "bearish",
        "confidence": 0.62,
        "event_type": "corporate_action",
    },
]

FLASH_EMPTY = []

# ── Stage 3: HVR Investigation (HypothesisResult-like dicts) ─────────────────

HVR_NORMAL = [
    {
        "hypothesis": "Disinflation Trend Accelerates — Rate Cut Cycle Broadens",
        "refined_hypothesis": "US CPI drop to 2.8% represents a structural break in the disinflation trajectory, not a one-off. Federal Reserve will deliver two 25bp cuts in 2026, starting July. This re-rates growth equities and duration-sensitive assets.",
        "confidence": 0.82,
        "verdict": "ACTIONABLE",
        "expectation_gap": "Market pricing only 60% probability of July cut vs 85% implied by data",
        "direction": "bullish",
        "core_logic": "CPI at 2.8% is the lowest since early 2025. Shelter costs decelerating. Core services ex-housing at 2.1% annualized 3-month. This is not noise — it's a regime shift in inflation dynamics.",
        "risk_level": "medium",
        "time_window": "3-6 months",
        "bear_case": "Shelter costs re-accelerate in Q3 due to seasonal factors. Oil price spike from OPEC+ cuts flows through to headline CPI. Fed stays on hold.",
        "bear_case_confidence": 0.25,
        "logic_chain": "CPI↓ → Fed dovish pivot → real yields↓ → P/E expansion → growth/tech outperforms",
        "verification_scores": {
            "layer_1_market": 0.85,
            "layer_2_fundamental": 0.78,
            "layer_3_multisource": 0.82,
            "layer_4_historical": 0.74,
            "weighted_confidence": 0.82,
            "verdict": "ACTIONABLE"
        },
    },
    {
        "hypothesis": "BOJ Policy Normalization Triggers Yen Appreciation Wave",
        "refined_hypothesis": "BOJ will hike rates in July to 0.50%, sparking a 15-20% yen appreciation against USD over 6 months. This unwinds JPY-funded carry trades and creates EM FX contagion risk.",
        "confidence": 0.75,
        "verdict": "ACTIONABLE",
        "expectation_gap": "Consensus sees BOJ on hold until Q4; we see July as the pivot point",
        "direction": "bearish",
        "core_logic": "Ueda's hawkish shift is deliberate. Spring wage negotiations delivered 3.8% average raise — highest since 1991. Real wages turning positive for first time in 2 years. BOJ has a narrow window before global slowdown closes it.",
        "risk_level": "high",
        "time_window": "2-4 months",
        "bear_case": "BOJ delays to October or later. Global recession fears force dovish hold. Yen stays weak.",
        "bear_case_confidence": 0.30,
        "logic_chain": "BOJ hike → JPY strength → carry trade unwind → risk-off → EM FX sell-off → volatility spike",
        "verification_scores": {
            "layer_1_market": 0.72,
            "layer_2_fundamental": 0.80,
            "layer_3_multisource": 0.68,
            "layer_4_historical": 0.75,
            "weighted_confidence": 0.75,
            "verdict": "ACTIONABLE"
        },
    },
    {
        "hypothesis": "Gold Bull Market Enters Acceleration Phase Above $3,200",
        "refined_hypothesis": "Gold's breakout above $3,200 is driven by structural central bank buying (800+ tonnes in 2025), not just geopolitical fear. Institutional re-allocation from bonds to gold accelerates as real yields stay negative in most DM economies.",
        "confidence": 0.78,
        "verdict": "ACTIONABLE",
        "expectation_gap": "Retail still underweight gold; ETF flows only starting to turn positive",
        "direction": "bullish",
        "core_logic": "Central bank gold purchases running at 800+ tonnes/year vs 450 pre-2022. China PBOC alone added 320 tonnes in 2025. This is a structural demand shift, not a cyclical trade. Bond market risk is pushing sovereign wealth funds into gold.",
        "risk_level": "medium",
        "time_window": "6-12 months",
        "bear_case": "Peace breakthrough in major conflict zones. Dollar strengthens sharply on rate differential. Gold corrects 10-15%.",
        "bear_case_confidence": 0.20,
        "logic_chain": "CB buying↑ + real yields↓ + geopolitical risk↑ → structural bid → $3,500-3,800 target",
        "verification_scores": {
            "layer_1_market": 0.82,
            "layer_2_fundamental": 0.76,
            "layer_3_multisource": 0.79,
            "layer_4_historical": 0.71,
            "weighted_confidence": 0.78,
            "verdict": "ACTIONABLE"
        },
    },
    {
        "hypothesis": "NVIDIA Earnings Beat Masks AI Capex Sustainability Risk",
        "refined_hypothesis": "NVDA's Q1 beat is impressive but forward guidance implied decelerating growth rate. Hyperscaler capex ($250B in 2025) is unsustainable at current ROI. AI infrastructure spending peaks in H2 2026, then normalizes.",
        "confidence": 0.68,
        "verdict": "MONITOR",
        "expectation_gap": "Street models 35% revenue growth in 2027 — we see 15-20% as more realistic",
        "direction": "neutral",
        "core_logic": "Hyperscaler capex running at 18% of revenue vs 10% historical norm. ROIC on AI infra is 6-8% vs 12-15% for traditional cloud. This math doesn't work long-term. NVDA is pricing perfection.",
        "risk_level": "high",
        "time_window": "6-12 months",
        "bear_case": "AI adoption accelerates beyond expectations. Enterprise AI revenue grows 5x. Hyperscalers find monetization model.",
        "bear_case_confidence": 0.35,
        "logic_chain": "Capex/revenue ratio↑ → ROIC↓ → spending deceleration → semi cycle peak → multiple compression",
        "verification_scores": {
            "layer_1_market": 0.65,
            "layer_2_fundamental": 0.72,
            "layer_3_multisource": 0.60,
            "layer_4_historical": 0.68,
            "weighted_confidence": 0.68,
            "verdict": "MONITOR"
        },
    },
    {
        "hypothesis": "European Energy Crisis 2.0 — Gas Price Spike Has Second-Round Effects",
        "refined_hypothesis": "Norway pipeline maintenance is a short-term trigger but exposes Europe's structural gas dependency. If Asian LNG demand picks up in Q3 (summer cooling), European gas prices could spike 40%+. This hits chemical and industrial sectors hardest.",
        "confidence": 0.62,
        "verdict": "MONITOR",
        "expectation_gap": "Market treating this as a 2-week blip; we see risk of 3-6 month elevated prices",
        "direction": "bearish",
        "core_logic": "EU gas storage at 58% vs 72% last year. LNG import capacity maxed out. Asian LNG competition for Q3 cooling season. Industrial demand destruction threshold is around EUR 45/MWh — we're at EUR 38 and rising.",
        "risk_level": "medium",
        "time_window": "1-3 months",
        "bear_case": "Norway maintenance completed ahead of schedule. Mild weather reduces demand. LNG cargoes re-route to Europe.",
        "bear_case_confidence": 0.40,
        "logic_chain": "Gas supply↓ → prices↑ → industrial margins↓ → chemicals/metals sector↓ → EU growth↓",
        "verification_scores": {
            "layer_1_market": 0.70,
            "layer_2_fundamental": 0.55,
            "layer_3_multisource": 0.60,
            "layer_4_historical": 0.65,
            "weighted_confidence": 0.62,
            "verdict": "MONITOR"
        },
    },
]

HVR_EMPTY = []

# ── Stage 4: L1 Narrative Analysis (Layer1Result-like dicts) ─────────────────

LAYER1_NORMAL = {
    "overall_narrative": (
        "The dominant market narrative on 2026-05-19 is a decisive pivot toward "
        "monetary easing, driven by the US CPI surprise to 2.8%. This is the first "
        "time since early 2025 that inflation has printed below 3%, and markets are "
        "aggressively re-pricing the rate cut trajectory. The 2-year Treasury yield "
        "fell 18bp on the print, the largest single-day move since the SVB crisis. "
        "Equity markets are celebrating the 'Fed put' revival, with SPX futures up "
        "1.2% and the VIX falling below 14."
    ),
    "event_grade": "A",
    "matrix_quadrant": "Growth + Easing",
    "sentiment": "bullish",
    "key_themes": [
        "Disinflation acceleration — CPI 2.8%, core services ex-housing at 2.1% annualized",
        "Fed pivot repricing — market now pricing 2 cuts in 2026, first in July",
        "Gold as structural allocation — central banks buying 800+ tonnes/year",
        "BOJ divergence — Japan normalizing while US easing, yen appreciation risk",
        "AI capex sustainability — hyperscaler spending at 18% of revenue vs 10% norm",
    ],
    "signals": [
        {
            "source": "US CPI (May 19)",
            "signal": "Disinflation confirms, rate cuts back on table",
            "strength": "strong",
            "direction": "bullish",
            "affected_assets": ["SPX", "TLT", "QQQ", "IWM"],
        },
        {
            "source": "Gold ATH (May 19)",
            "signal": "Structural safe-haven demand driven by CB buying",
            "strength": "strong",
            "direction": "bullish",
            "affected_assets": ["GLD", "GDX", "XAU/USD"],
        },
        {
            "source": "BOJ Hints (May 19)",
            "signal": "Japan rate normalization creates carry trade unwind risk",
            "strength": "moderate",
            "direction": "bearish",
            "affected_assets": ["USD/JPY", "EWJ", "FXY"],
        },
        {
            "source": "OPEC+ Cuts (May 19)",
            "signal": "Oil supply tightening supports energy sector",
            "strength": "moderate",
            "direction": "bullish",
            "affected_assets": ["USO", "XLE"],
        },
        {
            "source": "Foxconn Chip Warning (May 19)",
            "signal": "Semiconductor supply chain risk persists",
            "strength": "weak",
            "direction": "neutral",
            "affected_assets": ["SOXX", "TSM", "NVDA"],
        },
    ],
}

LAYER1_EMPTY = {
    "overall_narrative": "No significant market-moving events detected on this date. Markets trading in low-volatility range-bound pattern with no clear directional catalysts.",
    "event_grade": "C",
    "matrix_quadrant": "Neutral",
    "sentiment": "neutral",
    "key_themes": [],
    "signals": [],
}

# ── Main generation ─────────────────────────────────────────────────────────

def main():
    fixtures_dir = Path(__file__).resolve().parent / "test_fixtures"
    print(f"Generating fixtures in: {fixtures_dir}")

    generated = []

    # Stage 1: Scout
    for name, data in [("normal", SCOUT_NORMAL), ("empty", SCOUT_EMPTY)]:
        save_fixture("stage1_scout", name, data)
        generated.append(f"stage1_scout_{name}")
        print(f"  [OK] stage1_scout/{name} — {len(data)} articles")

    # Stage 2: Flash Triage
    for name, data in [("normal", FLASH_NORMAL), ("empty", FLASH_EMPTY)]:
        save_fixture("stage2_flash", name, data)
        generated.append(f"stage2_flash_{name}")
        print(f"  [OK] stage2_flash/{name} — {len(data)} triage results")

    # Stage 3: HVR Investigation
    for name, data in [("normal", HVR_NORMAL), ("empty", HVR_EMPTY)]:
        save_fixture("stage3_hvr", name, data)
        generated.append(f"stage3_hvr_{name}")
        print(f"  [OK] stage3_hvr/{name} — {len(data)} hypotheses")

    # Stage 4: Layer 1 Narrative Analysis
    for name, data in [("normal", LAYER1_NORMAL), ("empty", LAYER1_EMPTY)]:
        save_fixture("stage4_layer1", name, data)
        generated.append(f"stage4_layer1_{name}")
        signals_count = len(data.get("signals", []))
        print(f"  [OK] stage4_layer1/{name} — {signals_count} signals, sentiment={data['sentiment']}")

    print(f"\nGenerated {len(generated)} fixtures:")
    for g in generated:
        print(f"  - {g}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
