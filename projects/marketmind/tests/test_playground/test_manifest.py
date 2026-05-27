"""Test agent manifest loading and discovery."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from marketmind.playground.agent_manifest import (
    AgentManifest, load_manifest, discover_agents,
)


def test_load_manifest():
    """Load a valid manifest from a JSON file."""
    with tempfile.TemporaryDirectory() as td:
        agent_dir = Path(td) / "test-agent"
        agent_dir.mkdir()
        manifest_data = {
            "agent_id": "test-agent",
            "display_name": "Test Agent",
            "description": "A test agent for unit testing",
            "output_character": "directional call on test stocks",
            "public_data_sources": ["RSS news"],
            "requires_proprietary_data": False,
            "primary_metric": "direction_accuracy",
            "secondary_metrics": ["sharpe_ratio"],
            "min_sample_size": 20,
            "min_observation_days": 60,
            "target_pipeline_node": "decision_signal_source",
            "version": "1.0.0",
            "author": "test",
            "tags": ["test"],
        }
        with open(agent_dir / "manifest.json", "w") as f:
            json.dump(manifest_data, f)

        manifest = load_manifest(agent_dir)
        assert manifest is not None
        assert manifest.agent_id == "test-agent"
        assert manifest.display_name == "Test Agent"
        assert manifest.output_character == "directional call on test stocks"
        assert manifest.min_sample_size == 20
        assert manifest.min_observation_days == 60


def test_load_manifest_missing_file():
    """Returns None when manifest.json doesn't exist."""
    with tempfile.TemporaryDirectory() as td:
        agent_dir = Path(td) / "empty-agent"
        agent_dir.mkdir()
        manifest = load_manifest(agent_dir)
        assert manifest is None


def test_discover_agents():
    """Discover all agents with valid manifests in a directory."""
    with tempfile.TemporaryDirectory() as td:
        pg_dir = Path(td)
        agents_dir = pg_dir / "agents"
        agents_dir.mkdir()

        # Create agent A
        agent_a_dir = agents_dir / "agent-a"
        agent_a_dir.mkdir()
        with open(agent_a_dir / "manifest.json", "w") as f:
            json.dump({
                "agent_id": "agent-a",
                "display_name": "Agent A",
                "description": "First test agent",
                "output_character": "directional call",
                "min_sample_size": 20,
                "min_observation_days": 60,
            }, f)

        # Create agent B
        agent_b_dir = agents_dir / "agent-b"
        agent_b_dir.mkdir()
        with open(agent_b_dir / "manifest.json", "w") as f:
            json.dump({
                "agent_id": "agent-b",
                "display_name": "Agent B",
                "description": "Second test agent",
                "output_character": "sentiment score",
                "min_sample_size": 30,
                "min_observation_days": 90,
            }, f)

        # Create a directory without manifest (should be skipped)
        (agents_dir / "not-an-agent").mkdir()

        manifests = discover_agents(pg_dir)
        assert len(manifests) == 2
        agent_ids = {m.agent_id for m in manifests}
        assert agent_ids == {"agent-a", "agent-b"}


def test_discover_agents_empty():
    """Returns empty list when no agents exist."""
    with tempfile.TemporaryDirectory() as td:
        pg_dir = Path(td)
        (pg_dir / "agents").mkdir()
        manifests = discover_agents(pg_dir)
        assert manifests == []


def test_discover_agents_no_agents_dir():
    """Returns empty list when agents directory doesn't exist."""
    with tempfile.TemporaryDirectory() as td:
        manifests = discover_agents(Path(td))
        assert manifests == []


def test_manifest_freeform_output_character():
    """Output character is a free-form string, not constrained to an enum."""
    # Any string should be accepted — no validation against hardcoded types
    manifest = AgentManifest(
        agent_id="novel-agent",
        display_name="Novel Agent",
        description="An agent with a novel output type",
        output_character="generates haiku poems about market volatility",
    )
    assert "haiku" in manifest.output_character
