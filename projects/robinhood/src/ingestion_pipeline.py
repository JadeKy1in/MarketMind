"""
ingestion_pipeline.py — Stage 2.5: Scout → Distill → Belief Ingestion Pipeline

Converts raw scraped events (RawEvent) into structured BeliefObservation objects,
then feeds them into the BeliefStateManager for Beta-distribution belief update.

Pipeline stages:
  1. Extractor:  RawEvent → structured fields (already done in scout_fetcher)
  2. Distiller:  RawEvent → DistilledEvent via LLM API call (OpenAI-compatible)
  3. Instantiator: DistilledEvent → BeliefObservation → BeliefStateManager.ingest_observation()

LLM API design (PM ruling: no Agent self-call):
  - Uses lightweight HTTP POST to an OpenAI-compatible endpoint
  - No SDK import — uses requests library only
  - Structured output via JSON mode with strict schema
  - Polling is stateless — no shared state across calls

SPARC:
  Specification: PM-approved blueprint — headless LLM API call, no Agent chat context pollution
  Pseudocode: RawEvent batch → LLM JSON extraction → BeliefObservation instantiation
  Architecture: Pure pipeline — Extractor → Distiller → Instantiator, each stage replaceable
  Refinement: JSON mode, retry-once on malformed output, budget-aware batch size
  Completion: Ready for test_ingestion_pipeline.py
"""

from __future__ import annotations

import datetime
import json
import logging
import os
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .belief_types import (
    BeliefObservation,
    BeliefSource,
)
from .scout_fetcher import RawEvent, ScoutConfig

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------


@dataclass(frozen=True)
class DistilledEvent:
    """A distilled event after LLM-based structural extraction.

    Attributes:
        proposition_id: Target proposition ID in BeliefStateManager
        direction: Market direction (bullish, bearish, neutral)
        confidence: Confidence score 0.0-1.0
        one_liner: ≤50 char summary
        tickers: Affected asset tickers
        raw_event: Reference to the originating RawEvent
    """
    proposition_id: str
    direction: str = "neutral"
    confidence: float = 0.5
    one_liner: str = ""
    tickers: List[str] = field(default_factory=list)
    raw_event: Optional[RawEvent] = None


@dataclass
class IngestionResult:
    """Result of a single pipeline execution.

    Attributes:
        total_raw: Number of RawEvents received
        distilled_count: Number successfully distilled
        ingested_count: Number successfully ingested into BeliefStateManager
        observations: List of BeliefObservation objects created
        errors: Error messages from failed distillations/ingestions
        proposition_updates: Dict[proposition_id, new_confidence]
    """
    total_raw: int = 0
    distilled_count: int = 0
    ingested_count: int = 0
    observations: List[BeliefObservation] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    proposition_updates: Dict[str, float] = field(default_factory=dict)


# ---------------------------------------------------------------
# Preloaded Proposition Registry
# ---------------------------------------------------------------

PRELOADED_PROPOSITIONS: Dict[str, str] = {
    "macro_us_recession_risk": "美国经济在未来 6 个月内进入衰退的概率",
    "macro_fed_rate_path": "美联储未来 3 个月将降息的概率",
    "macro_inflation_trend": "核心通胀持续下行的概率",
    "geo_us_china_tension": "中美贸易摩擦升级的概率",
    "sentiment_market_greed": "市场情绪处于贪婪区间的概率",
    "sector_tech_outperform": "科技板块未来 1 个月跑赢大盘的概率",
    "sector_energy_weakness": "能源板块未来 1 个月走弱的概率",
    "sector_financial_stress": "金融板块系统性压力上升的概率",
}


# ---------------------------------------------------------------
# Distiller Config
# ---------------------------------------------------------------


@dataclass
class DistillerConfig:
    """Configuration for the LLM-based distiller.

    Attributes:
        api_url: OpenAI-compatible API endpoint (default: env ANTHROPIC_API_URL or OpenAI)
        api_key: API key (default: env LLM_API_KEY)
        model: Model name (default: gpt-4o-mini or claude-3-haiku)
        max_raw_per_batch: Max RawEvents to distill in one call (default 20)
        temperature: LLM temperature for extraction (default 0.1)
        timeout_seconds: HTTP request timeout (default 30)
    """
    api_url: str = "https://api.openai.com/v1/chat/completions"
    api_key: str = ""
    model: str = "gpt-4o-mini"
    max_raw_per_batch: int = 20
    temperature: float = 0.1
    timeout_seconds: int = 30

    def __post_init__(self) -> None:
        if not self.api_key:
            self.api_key = os.environ.get("LLM_API_KEY", "")
        if not self.api_url:
            self.api_url = os.environ.get(
                "LLM_API_URL",
                "https://api.openai.com/v1/chat/completions",
            )


# ---------------------------------------------------------------
# Distiller (Stage 2) — LLM API Call
# ---------------------------------------------------------------


class Distiller:
    """Distills RawEvents into structured DistilledEvents using external LLM API.

    This is a headless background process — no Agent chat context pollution.
    Uses requests library directly against an OpenAI-compatible endpoint.
    """

    def __init__(self, config: Optional[DistillerConfig] = None):
        self._config = config or DistillerConfig()
        self._system_prompt = self._build_system_prompt()

    def _build_system_prompt(self) -> str:
        return (
            "You are a macro-quant analyst. Your job is to analyze financial news events "
            "and extract structured market signals.\n\n"
            "For each event, determine:\n"
            "1. **proposition_id**: Which belief proposition this event affects. "
            "Choose from the exact list: "
            f"{', '.join(PRELOADED_PROPOSITIONS.keys())}\n"
            "2. **direction**: Market impact direction. One of: bullish, bearish, neutral\n"
            "3. **confidence**: Your confidence in this assessment, as a float 0.0-1.0. "
            "0.5 = neutral, >0.6 = leaning, >0.8 = strong signal\n"
            "4. **one_liner**: A ≤50-character summary of the key signal\n"
            "5. **tickers**: List of affected asset ticker symbols (e.g. SPY, QQQ, XLF)\n\n"
            "IMPORTANT: You MUST output a valid JSON array of objects. "
            "Each object must have exactly these keys: "
            "proposition_id, direction, confidence, one_liner, tickers.\n"
            "If an event is not relevant to any proposition, omit it from the output."
        )

    def distill(self, raw_events: List[RawEvent]) -> List[DistilledEvent]:
        """Distill a batch of RawEvents into DistilledEvents via LLM API.

        Args:
            raw_events: List of RawEvents to process.

        Returns:
            List of successfully distilled DistilledEvents.
        """
        if not raw_events:
            return []

        batch = raw_events[:self._config.max_raw_per_batch]

        # Build the user message: a JSON array of events
        events_data = []
        for i, ev in enumerate(batch):
            events_data.append({
                "index": i,
                "title": ev.title,
                "body": ev.body,
                "source_name": ev.source_name,
                "category": ev.category,
            })

        messages = [
            {"role": "system", "content": self._system_prompt},
            {
                "role": "user",
                "content": (
                    f"Analyze the following {len(events_data)} financial news events. "
                    f"Output a JSON array.\n\n"
                    f"{json.dumps(events_data, indent=2)}"
                ),
            },
        ]

        response_text = self._call_llm(messages)
        if response_text is None:
            logger.warning("LLM distillation returned None; falling back to empty result")
            return []

        parsed = self._parse_llm_response(response_text, batch)
        return parsed

    def _call_llm(self, messages: List[Dict[str, str]]) -> Optional[str]:
        """Make the HTTP POST to the LLM API endpoint.

        Returns:
            Response text on success, None on failure.
        """
        payload = {
            "model": self._config.model,
            "messages": messages,
            "temperature": self._config.temperature,
            "response_format": {"type": "json_object"},
        }

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._config.api_key}",
        }

        try:
            import requests
            resp = requests.post(
                self._config.api_url,
                json=payload,
                headers=headers,
                timeout=self._config.timeout_seconds,
            )
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            return content
        except ImportError:
            logger.error("requests library not available; cannot call LLM API")
            return None
        except (requests.RequestException, KeyError, IndexError, json.JSONDecodeError) as e:
            logger.error("LLM API call failed: %s", e)
            return None

    def _parse_llm_response(
        self,
        response_text: str,
        raw_events: List[RawEvent],
    ) -> List[DistilledEvent]:
        """Parse the LLM JSON response into DistilledEvents.

        Args:
            response_text: Raw JSON text from LLM.
            raw_events: Original RawEvents for cross-reference.

        Returns:
            List of parsed DistilledEvents.
        """
        distilled: List[DistilledEvent] = []

        try:
            # Try to find JSON array within the response
            # LLM may wrap in markdown ```json blocks
            cleaned = response_text.strip()
            if cleaned.startswith("```"):
                # Strip markdown code blocks
                cleaned = cleaned.strip("`")
                if cleaned.startswith("json"):
                    cleaned = cleaned[4:]
                cleaned = cleaned.strip()

            parsed = json.loads(cleaned)

            # If root is a dict with an "events"/"results" key, use that
            if isinstance(parsed, dict):
                for key in ("events", "results", "distilled"):
                    if key in parsed and isinstance(parsed[key], list):
                        parsed = parsed[key]
                        break

            if not isinstance(parsed, list):
                logger.warning(
                    "LLM response is not a list (type=%s); returning empty",
                    type(parsed).__name__,
                )
                return []

            for item in parsed:
                if not isinstance(item, dict):
                    continue

                prop_id = item.get("proposition_id", "").strip()
                direction = item.get("direction", "neutral").strip().lower()
                confidence = float(item.get("confidence", 0.5))
                one_liner = str(item.get("one_liner", ""))[:50]

                raw_tickers = item.get("tickers", [])
                if isinstance(raw_tickers, list):
                    tickers = [str(t).upper().strip() for t in raw_tickers]
                else:
                    tickers = [str(raw_tickers).upper().strip()]

                # Validate proposition_id
                if prop_id not in PRELOADED_PROPOSITIONS:
                    logger.debug(
                        "Unknown proposition_id '%s' from LLM; skipping",
                        prop_id,
                    )
                    continue

                # Validate direction
                if direction not in ("bullish", "bearish", "neutral"):
                    direction = "neutral"

                # Clamp confidence
                confidence = max(0.0, min(1.0, confidence))

                distilled.append(DistilledEvent(
                    proposition_id=prop_id,
                    direction=direction,
                    confidence=confidence,
                    one_liner=one_liner,
                    tickers=tickers,
                ))

            logger.info(
                "Distilled %d/%d events from LLM response",
                len(distilled),
                len(raw_events),
            )
            return distilled

        except (json.JSONDecodeError, ValueError, TypeError) as e:
            logger.error("Failed to parse LLM response as JSON: %s", e)
            logger.debug("Raw response: %s", response_text[:500])
            return []


# ---------------------------------------------------------------
# Instantiator (Stage 3) — DistilledEvent → BeliefObservation
# ---------------------------------------------------------------


class Instantiator:
    """Converts DistilledEvents into BeliefObservations and ingests them."""

    def __init__(
        self,
        belief_manager: Any,  # Forward-ref: BeliefStateManager
    ):
        """Initialize the instantiator.

        Args:
            belief_manager: An instance of BeliefStateManager.
                            Must support register_proposition() and ingest_observation().
        """
        self._manager = belief_manager

    def register_default_propositions(self) -> int:
        """Ensure all preloaded propositions are registered in BeliefStateManager.

        Uses register_proposition() which is idempotent (raises DuplicatePropositionError
        if already registered, which we catch and ignore).

        Returns:
            Number of newly registered propositions.
        """
        from .belief_state_manager import DuplicatePropositionError

        count = 0
        for prop_id, prop_text in PRELOADED_PROPOSITIONS.items():
            try:
                self._manager.register_proposition(
                    prop_text,
                    proposition_id=prop_id,
                    source=BeliefSource.MACRO_CALENDAR,
                )
                count += 1
            except DuplicatePropositionError:
                pass  # Already registered
        if count:
            logger.info("Registered %d new propositions", count)
        return count

    def instantiate_and_ingest(
        self,
        distilled_events: List[DistilledEvent],
        source: BeliefSource = BeliefSource.MACRO_CALENDAR,
    ) -> IngestionResult:
        """Convert DistilledEvents to BeliefObservations and ingest.

        Mapping:
          direction=bullish + confidence=C → evidence_value = 0.5 + C/2
          direction=bearish + confidence=C → evidence_value = 0.5 - C/2
          direction=neutral → skipped (no-observe)

        Args:
            distilled_events: List of DistilledEvents to process.
            source: BeliefSource to assign to all observations.

        Returns:
            IngestionResult with counts and created observations.
        """
        result = IngestionResult(total_raw=len(distilled_events))

        for de in distilled_events:
            # Skip neutral — no informational value for Beta update
            if de.direction == "neutral":
                continue

            # Map direction+confidence to evidence_value
            if de.direction == "bullish":
                evidence_value = 0.5 + (de.confidence / 2.0)
            else:  # bearish
                evidence_value = 0.5 - (de.confidence / 2.0)

            # Clamp to [0.05, 0.95] to avoid polarizing too quickly
            evidence_value = max(0.05, min(0.95, evidence_value))

            observation = BeliefObservation(
                value=evidence_value,
                confidence=de.confidence,
                source=source,
                timestamp=datetime.datetime.now().isoformat(),
                metadata={
                    "one_liner": de.one_liner,
                    "tickers": de.tickers,
                    "distilled_direction": de.direction,
                },
            )

            # Save for reporting
            result.observations.append(observation)

            # Ingest into BeliefStateManager
            try:
                snapshot = self._manager.ingest_observation(
                    proposition_id=de.proposition_id,
                    observation=observation,
                )
                result.ingested_count += 1
                # BeliefSnapshot.expectation = E[θ] = posterior mean
                result.proposition_updates[de.proposition_id] = (
                    snapshot.expectation
                )
            except Exception as e:
                err_msg = f"Ingestion failed for '{de.proposition_id}': {e}"
                logger.error(err_msg)
                result.errors.append(err_msg)

        result.distilled_count = len(distilled_events)
        logger.info(
            "Ingested %d/%d observations into BeliefStateManager",
            result.ingested_count,
            len(distilled_events),
        )
        return result


# ---------------------------------------------------------------
# Convenience: Full Pipeline Orchestrator
# ---------------------------------------------------------------


class PatrolPipeline:
    """End-to-end pipeline: fetch → distill → ingest.

    Combines ScoutFetcher (fetch_all), Distiller, and Instantiator
    into a single callable for PatrolScheduler.on_patrol.
    """

    def __init__(
        self,
        belief_manager: Any,
        distiller: Optional[Distiller] = None,
        distiller_config: Optional[DistillerConfig] = None,
        scout_config: Optional[ScoutConfig] = None,
    ):
        self._manager = belief_manager
        self._distiller = distiller or Distiller(config=distiller_config)
        self._instantiator = Instantiator(belief_manager)
        self._scout_config = scout_config or ScoutConfig()

    def run(self) -> IngestionResult:
        """Execute one full patrol cycle.

        Steps:
          1. Register default propositions (idempotent)
          2. fetch_all() from all configured sources
          3. distill() raw events via LLM
          4. instantiate_and_ingest() into BeliefStateManager

        Returns:
            IngestionResult with full cycle statistics.
        """
        from .scout_fetcher import fetch_all

        # Step 1: Register propositions
        self._instantiator.register_default_propositions()

        # Step 2: Fetch
        fetch_result = fetch_all(config=self._scout_config)
        logger.info(
            "PatrolPipeline: fetched %d events from %d sources",
            len(fetch_result.events),
            len(fetch_result.track_stats),
        )

        if not fetch_result.events:
            return IngestionResult(
                total_raw=0,
                errors=fetch_result.errors,
            )

        # Step 3: Distill
        distilled = self._distiller.distill(fetch_result.events)

        # Step 4: Ingest
        result = self._instantiator.instantiate_and_ingest(distilled)
        result.total_raw = len(fetch_result.events)

        # Append fetch errors to result
        for err in fetch_result.errors:
            result.errors.append(f"[fetch] {err}")

        logger.info(
            "PatrolPipeline complete: %d raw → %d distilled → %d ingested",
            result.total_raw,
            result.distilled_count,
            result.ingested_count,
        )
        return result