"""Playground — isolated experimental agent sandbox.

Agents here operate with an information firewall:
- Allowed: public market data, declared data sources, public filings
- Forbidden: main pipeline outputs (L1/L2/L3/RedTeam/Resonance/Decision), shadow analysis

Every agent self-declares its characteristics via agent_manifest.py.
No hardcoded type classification — taxonomy emerges from observation.
"""
from __future__ import annotations
