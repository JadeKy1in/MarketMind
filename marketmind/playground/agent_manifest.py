"""Agent manifest — self-declaration format for every playground agent.

Each agent declares WHAT it does, WHAT it outputs, and HOW it should be
evaluated. No hardcoded type taxonomy — classification emerges from
accumulated manifests over time.

Design invariant: manifest is the agent's own claim about itself.
The auditor verifies these claims against actual performance.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class AgentManifest:
    """Self-declaration by a playground agent.

    All fields are claims by the agent author. The auditor treats them
    as hypotheses to be verified, not as ground truth.
    """

    agent_id: str          # unique slug, e.g. "serenity-reply"
    display_name: str      # human-readable, e.g. "Serenity Semiconductor Analyst"
    description: str       # 1-3 sentences on what this agent does

    # ── Free-form output characterization (no enum!) ──
    output_character: str  # e.g. "directional call on individual stocks",
                           # "market regime label", "sentiment score 0-100",
                           # "risk binary flag", "supply chain bottleneck list"

    # ── Data requirements ──
    public_data_sources: list[str] = field(default_factory=list)
    # e.g. ["Yahoo Finance price data", "SEC EDGAR filings", "RSS: semiconductor news"]
    requires_proprietary_data: bool = False
    # If True, agent needs data not in public Scout output — triggers
    # [enhanced_data] label on all performance records.

    # ── Evaluation preferences (claims, not verdicts) ──
    primary_metric: str = "direction_accuracy"
    # What the agent considers its MAIN success metric.
    # Free-form string — auditor maps to available computation.
    secondary_metrics: list[str] = field(default_factory=list)
    # e.g. ["sharpe_ratio", "max_drawdown", "profit_factor"]
    min_sample_size: int = 20
    # Minimum decisions before evaluation is meaningful.
    min_observation_days: int = 60
    # Minimum calendar days before first audit.

    # ── Integration target (if upgraded) ──
    target_pipeline_node: str = ""
    # Where in the main pipeline this agent's output fits, IF it passes audit.
    # e.g. "decision_signal_source", "l1_narrative_input", "red_team_input"
    # Empty = not yet determined, or agent is meta/utility.

    # ── Metadata ──
    version: str = "1.0.0"
    author: str = ""
    installed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    tags: list[str] = field(default_factory=list)


def load_manifest(agent_dir: Path) -> AgentManifest | None:
    """Load an agent manifest from its directory."""
    manifest_path = agent_dir / "manifest.json"
    if not manifest_path.exists():
        return None
    with open(manifest_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return AgentManifest(
        agent_id=data["agent_id"],
        display_name=data["display_name"],
        description=data["description"],
        output_character=data.get("output_character", ""),
        public_data_sources=data.get("public_data_sources", []),
        requires_proprietary_data=data.get("requires_proprietary_data", False),
        primary_metric=data.get("primary_metric", "direction_accuracy"),
        secondary_metrics=data.get("secondary_metrics", []),
        min_sample_size=data.get("min_sample_size", 20),
        min_observation_days=data.get("min_observation_days", 60),
        target_pipeline_node=data.get("target_pipeline_node", ""),
        version=data.get("version", "1.0.0"),
        author=data.get("author", ""),
        tags=data.get("tags", []),
    )


def discover_agents(playground_dir: Path) -> list[AgentManifest]:
    """Discover all installed playground agents with valid manifests."""
    agents_dir = playground_dir / "agents"
    if not agents_dir.exists():
        return []
    manifests: list[AgentManifest] = []
    for agent_dir in sorted(agents_dir.iterdir()):
        if not agent_dir.is_dir():
            continue
        manifest = load_manifest(agent_dir)
        if manifest:
            manifests.append(manifest)
    return manifests
