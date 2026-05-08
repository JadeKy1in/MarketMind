"""
event_templates.py - Classic causal-chain templates for event-driven engine.

This file contains two compile-time constant dictionaries:

1. CAUSAL_CHAIN_TEMPLATES: Classic multi-order causal chain templates
   used by the Blue Team for forward reasoning.

2. ALTERNATIVE_DATA_PLAYBOOK: Physical-world alternative data sources
   used by the Red Team for adversarial verification.

Both are designed for no-code modification: simply add new entries
to extend the engine's domain knowledge without changing Python code.
"""

# ---------------------------------------------------------------------------
# CAUSAL_CHAIN_TEMPLATES: Blue Team forward-reasoning knowledge base
# ---------------------------------------------------------------------------
# Each template has:
#   - trigger_keywords:  words in macro_events that match this template
#   - template_chain:    human-readable template name
#   - red_team_focus:    hint for Red Team on what to challenge

CAUSAL_CHAIN_TEMPLATES = {
    "war_to_energy_to_fertilizer_to_agriculture": {
        "trigger_keywords": [
            "military", "war", "strait", "hormuz", "missile",
            "invasion", "conflict", "hostility", "blockade",
        ],
        "template_chain": (
            "Military conflict -> Energy supply disruption -> "
            "Feedstock cost surge -> Fertilizer production squeeze -> "
            "Crop input cost inflation -> Agricultural commodity spike"
        ),
        "red_team_focus": (
            "Alternative fertilizer supply routes, existing "
            "phosphate/potash stockpiles, non-urea substitution"
        ),
    },
    "sanctions_to_financial_plumbing": {
        "trigger_keywords": [
            "sanction", "SWIFT", "freeze", "asset freeze", "embargo",
            "export control", "entity list",
        ],
        "template_chain": (
            "Sanctions imposed -> Correspondent banking frozen -> "
            "Letters of credit unavailable -> Commodity shipments halted -> "
            "Spot/futures basis blowout"
        ),
        "red_team_focus": (
            "Alternative payment rails (CIPS, bilateral swap lines), "
            "barter trade precedents, third-country intermediary evasion"
        ),
    },
    "tariff_to_supply_chain_restructuring": {
        "trigger_keywords": [
            "tariff", "trade war", "import duty", "protection",
            "reciprocal tariff",
        ],
        "template_chain": (
            "Tariff imposed -> Input cost for downstream industry rises -> "
            "Margin compression -> Production shift to alternative sourcing -> "
            "Short-term disruption -> Long-term supply reconfiguration"
        ),
        "red_team_focus": (
            "Transshipment triangulation data, existing inventory buffers, "
            "tariff exemption/quota loopholes"
        ),
    },
    "pandemic_to_labor_to_logistics": {
        "trigger_keywords": [
            "pandemic", "outbreak", "lockdown", "quarantine", "virus",
            "epidemic", "health emergency",
        ],
        "template_chain": (
            "Outbreak in logistics hub -> Worker absenteeism -> "
            "Port congestion -> Container dwell time surge -> "
            "Shipping schedule collapse -> Factory input shortage -> "
            "Downstream production halt"
        ),
        "red_team_focus": (
            "Real-time port congestion indices, trucking spot rates, "
            "warehouse vacancy rates, alternative transport (rail/air)"
        ),
    },
    "rate_hike_to_credit_to_capex": {
        "trigger_keywords": [
            "rate hike", "monetary policy", "FOMC", "tightening",
            "yield", "interest rate", "hike",
        ],
        "template_chain": (
            "Rate hike -> Corporate spread widening -> "
            "Marginal borrowers excluded -> Capex projects cancelled -> "
            "Capital goods orders decline -> Industrial contraction -> "
            "Employment weakening"
        ),
        "red_team_focus": (
            "Existing corporate cash reserves, pre-existing credit lines, "
            "government fiscal offset (subsidies, infrastructure spend)"
        ),
    },
}

# ---------------------------------------------------------------------------
# ALTERNATIVE_DATA_PLAYBOOK: Red Team physical-evidence catalog
# ---------------------------------------------------------------------------
# Each category maps to a list of physical-world data sources that are:
#   a) Hard for any single actor to fabricate at scale
#   b) Independent of government statistical agencies' narrative
#   c) Observable in near-real-time or with short lag

ALTERNATIVE_DATA_PLAYBOOK = {
    "industrial_production": [
        "Satellite NO2 tropospheric column density over industrial zones",
        "Provincial-level industrial electricity consumption (grid operator data)",
        "Nighttime light intensity satellite imagery (VIIRS/DMSP)",
        "Industrial park water consumption metering data",
    ],
    "consumer_demand": [
        "Credit card transaction volume growth (aggregated, anonymized)",
        "Shipping container import volumes at major ports (port authority data)",
        "Logistics warehouse utilization rates (CBRE/JLL industrial reports)",
    ],
    "demographics_birth_rate": [
        "BCG vaccine batch release volumes (national drug administration)",
        "Hospital obstetrics department revenue (public hospital financials)",
        "Diaper/infant formula sales volumes (Nielsen/retail scanner data)",
    ],
    "fertilizer_supply_chain": [
        "Real-time urea port inventory at key chokepoints (ship-tracking + port data)",
        "BDI fertilizer-route sub-index (Baltic Exchange)",
        "TTF natural gas futures term structure (ICE Endex)",
        "Russia/China land-route urea export volumes (customs harmonized data)",
    ],
    "oil_supply_disruption": [
        "AIS tanker tracking: route deviations, idling, floating storage",
        "Crude oil options market put/call skew (CME/ICE derivatives data)",
    ],
    "trade_supply_chain_decoupling": [
        "Transshipment volumes through third countries (Vietnam/Mexico customs)",
        "Intermediate goods trade data (HS code level, UN Comtrade)",
    ],
}


def match_templates(event_titles: list[str]) -> list[dict]:
    """Return all templates whose trigger_keywords appear in event_titles.

    Args:
        event_titles: List of macro event title strings.

    Returns:
        Matching template dicts with template name attached.
    """
    matched = []
    for name, tmpl in CAUSAL_CHAIN_TEMPLATES.items():
        for kw in tmpl["trigger_keywords"]:
            for title in event_titles:
                if kw.lower() in title.lower():
                    matched.append({"name": name, **tmpl})
                    break
            else:
                continue
            break
    return matched