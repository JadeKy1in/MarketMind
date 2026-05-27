"""Playground runner — daily execution of all playground agents.

Enforces information firewall: agents receive ONLY public market data
plus their declared data sources. Main pipeline outputs (L1/L2/L3/RedTeam/
Resonance/Decision) and shadow analysis are NEVER passed to playground agents.
"""
from __future__ import annotations

import asyncio
import json
import logging
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from marketmind.playground.agent_manifest import AgentManifest, discover_agents

logger = logging.getLogger("marketmind.playground.runner")

DEFAULT_PLAYGROUND_DIR = Path(__file__).resolve().parent
AUDIT_LOG_NAME = "playground_decisions.jsonl"


@dataclass
class PlaygroundDecision:
    """A single virtual decision produced by a playground agent.

    This is recorded but NEVER executed. It exists purely for performance
    tracking and audit.
    """
    agent_id: str
    run_id: str             # unique per run, e.g. "2026-05-27T14:30:00Z"
    timestamp: str
    output: dict            # agent's raw output, structure varies by agent
    # Directional calls extracted from output (if applicable)
    directional_calls: list[dict] = field(default_factory=list)
    # e.g. [{"ticker": "AXTI", "direction": "bullish", "confidence": 0.8, "thesis": "..."}]
    metadata: dict = field(default_factory=dict)


@dataclass
class RunResult:
    """Result from running all playground agents."""
    run_id: str
    timestamp: str
    agents_attempted: int
    agents_succeeded: int
    agents_failed: int
    decisions: list[PlaygroundDecision]
    errors: list[dict]  # agent_id -> error info


def _build_public_data_context(news_items: list | None = None,
                               market_data: dict | None = None,
                               playground_news: list[dict] | None = None) -> dict:
    """Build the public-data-only context for playground agents.

    This is the ONLY data passed to playground agents. It must contain
    nothing derived from main pipeline analysis.

    Args:
        news_items: Raw news items from Scout (or equivalent public RSS).
        market_data: Public market data (prices, volumes, etc.).
        playground_news: Additional news from Playground-exclusive RSS sources.
                         These come from playground_fetcher, never from main pipeline.
    """
    context: dict = {
        "source": "public_market_data",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if news_items is not None:
        context["news"] = []
        for item in (news_items or []):
            if hasattr(item, '__dict__'):
                d = {k: v for k, v in item.__dict__.items()
                     if not k.startswith('_')}
            elif isinstance(item, dict):
                d = dict(item)
            else:
                d = {"raw": str(item)[:500]}
            d.pop("flash_signal", None)
            d.pop("flash_scores", None)
            d.pop("triage_result", None)
            d.pop("l1_tag", None)
            d.pop("l2_candidate", None)
            context["news"].append(d)
    else:
        context["news"] = []
    # Merge playground news (tagged so agents can distinguish sources)
    if playground_news:
        for item in playground_news:
            item["_playground_source"] = True
            context["news"].append(item)
    if market_data is not None:
        context["market_data"] = market_data
    # Flag that enhanced data was used
    if playground_news:
        context["enhanced_data"] = True
    return context


def _record_decision(decision: PlaygroundDecision, playground_dir: Path) -> None:
    """Append a decision to the append-only audit log."""
    log_path = playground_dir / "data" / AUDIT_LOG_NAME
    log_path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "agent_id": decision.agent_id,
        "run_id": decision.run_id,
        "timestamp": decision.timestamp,
        "output": decision.output,
        "directional_calls": decision.directional_calls,
        "metadata": decision.metadata,
    }
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


async def run_single_agent(
    manifest: AgentManifest,
    public_context: dict,
    agent_dir: Path,
    *,
    mock: bool = False,
) -> PlaygroundDecision:
    """Run a single playground agent in isolation.

    The agent's adapter module is loaded dynamically from its directory.
    Expected interface: agent_dir / "adapter.py" with function:
        async def analyze(context: dict, *, mock: bool = False) -> dict

    Args:
        manifest: Agent's self-declaration.
        public_context: Public-data-only context (never contains pipeline outputs).
        agent_dir: Path to agent's directory.
        mock: If True, agent should use mock responses (no API cost).

    Returns:
        PlaygroundDecision with agent output.
    """
    import importlib.util
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    adapter_path = agent_dir / "adapter.py"

    if not adapter_path.exists():
        raise FileNotFoundError(f"adapter.py not found in {agent_dir}")

    spec = importlib.util.spec_from_file_location(
        f"playground.agents.{manifest.agent_id}.adapter",
        str(adapter_path),
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    if not hasattr(module, "analyze"):
        raise AttributeError(f"adapter.py for {manifest.agent_id} has no 'analyze' function")

    analyze_fn = getattr(module, "analyze")
    output = await analyze_fn(public_context, mock=mock)

    # Extract directional calls if present
    directional_calls = []
    if isinstance(output, dict):
        calls = output.get("directional_calls", output.get("calls", []))
        if isinstance(calls, list):
            directional_calls = calls

    decision = PlaygroundDecision(
        agent_id=manifest.agent_id,
        run_id=run_id,
        timestamp=datetime.now(timezone.utc).isoformat(),
        output=output,
        directional_calls=directional_calls,
        metadata={
            "manifest_version": manifest.version,
            "public_data_sources": manifest.public_data_sources,
            "mock_mode": mock,
        },
    )

    _record_decision(decision, DEFAULT_PLAYGROUND_DIR)
    return decision


async def run_all_agents(
    news_items: list | None = None,
    market_data: dict | None = None,
    *,
    mock: bool = False,
    playground_dir: Path | None = None,
    fetch_playground_sources: bool = True,
) -> RunResult:
    """Run all installed playground agents with information firewall.

    Each agent runs independently. One agent crashing does not affect others.

    Args:
        news_items: Raw Scout news items (pre-Flash, pre-analysis).
        market_data: Public market data.
        mock: If True, all agents use mock mode.
        playground_dir: Override playground directory for testing.
        fetch_playground_sources: If True, fetch Playground-exclusive RSS
            feeds for active agents before running them.

    Returns:
        RunResult with aggregate statistics and all decisions.
    """
    from marketmind.playground.playground_fetcher import fetch_for_agents, flatten_results

    pg_dir = playground_dir or DEFAULT_PLAYGROUND_DIR
    manifests = discover_agents(pg_dir)

    if not manifests:
        logger.info("Playground: no agents discovered in %s", pg_dir / "agents")
        return RunResult(
            run_id=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
            timestamp=datetime.now(timezone.utc).isoformat(),
            agents_attempted=0,
            agents_succeeded=0,
            agents_failed=0,
            decisions=[],
            errors=[],
        )

    # Fetch Playground-exclusive RSS feeds for active agents
    playground_news: list[dict] | None = None
    if fetch_playground_sources and not mock:
        agent_ids = [m.agent_id for m in manifests]
        fetch_results = await fetch_for_agents(agent_ids)
        playground_news = flatten_results(fetch_results)
        if playground_news:
            logger.info("Playground: fetched %d items from exclusive RSS sources",
                        len(playground_news))

    public_context = _build_public_data_context(
        news_items, market_data, playground_news,
    )
    agents_dir = pg_dir / "agents"

    decisions: list[PlaygroundDecision] = []
    errors: list[dict] = []
    has_enhanced_data = bool(playground_news)

    for manifest in manifests:
        agent_dir = agents_dir / manifest.agent_id
        try:
            decision = await run_single_agent(
                manifest, public_context, agent_dir, mock=mock,
            )
            # Tag decision metadata with enhanced_data status
            if has_enhanced_data:
                decision.metadata["enhanced_data"] = True
            decisions.append(decision)
            logger.info("Playground: %s completed — %d directional calls",
                        manifest.agent_id, len(decision.directional_calls))
        except Exception:
            error_detail = traceback.format_exc()
            logger.warning("Playground: %s failed — %s", manifest.agent_id, error_detail[:200])
            errors.append({
                "agent_id": manifest.agent_id,
                "error": error_detail[:1000],
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

    result = RunResult(
        run_id=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        timestamp=datetime.now(timezone.utc).isoformat(),
        agents_attempted=len(manifests),
        agents_succeeded=len(decisions),
        agents_failed=len(errors),
        decisions=decisions,
        errors=errors,
    )

    logger.info(
        "Playground run complete: %d/%d agents succeeded, %d decisions recorded%s",
        result.agents_succeeded, result.agents_attempted, len(decisions),
        " [enhanced_data]" if has_enhanced_data else "",
    )
    return result
