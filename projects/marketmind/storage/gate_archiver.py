"""Gate conversation archiver: dual JSONL + Markdown format with integrity verification.

Canonical data source is JSONL — pipeline AI review MUST parse JSONL, not Markdown.
Markdown is a rendered view for human reading only.
"""
from __future__ import annotations
import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from marketmind.storage.archivist import MarketMindArchive

logger = logging.getLogger("marketmind.storage.gate_archiver")


@dataclass
class GateTurn:
    """A single conversational turn within a Gate 1/2/3 session.

    content_type is MANDATORY for downstream pipeline filtering — every
    JSONL line records it so that review agents can select only
    user_free_text, system_decision, etc.
    """
    turn: int
    speaker: str          # "AI" | "USER"
    type: str             # hypothesis_card | question | bear_case_detail |
                          # direction_selection | pivot | confirmation | system
    content_type: str     # user_free_text | system_decision | ai_response | structured_data
    text: str | None = None
    data: dict | None = None       # structured fields (direction, confidence, …)
    warnings: list[str] | None = None  # from input_guard sanitization
    timestamp: str = ""             # ISO-8601 UTC; auto-filled on log_turn if empty


class GateArchiver:
    """Archives Gate 1/2/3 conversations in JSONL + Markdown dual format.

    JSONL is the canonical / machine-readable source (one JSON object per
    line).  Markdown is a human-readable companion with HTML-comment-based
    content wrapping for injection safety (C1 mitigation from security
    audit).
    """

    def __init__(self, archive: MarketMindArchive):
        self.archive = archive
        self._gate_number: int | None = None
        self._session_id: str | None = None
        self._jsonl_path: Path | None = None
        self._md_path: Path | None = None
        self._turn_count: int = 0

    # ── public API ──────────────────────────────────────────────────────

    async def start_session(self, gate_number: int, session_id: str) -> Path:
        """Create the JSONL and MD files for a new gate session.

        Returns the JSONL path (canonical data source).
        """
        self._gate_number = gate_number
        self._session_id = session_id
        self._turn_count = 0

        gate_dir = self.archive.today_path() / "gates"
        gate_dir.mkdir(parents=True, exist_ok=True)

        self._jsonl_path = gate_dir / f"gate{gate_number}_conversation.jsonl"
        self._md_path = gate_dir / f"gate{gate_number}_conversation.md"

        # Fresh files
        self._jsonl_path.write_text("", encoding="utf-8")

        now_label = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        self._md_path.write_text(f"# Gate {gate_number} — {now_label}\n\n", encoding="utf-8")

        logger.info("Gate %d session %s started: %s", gate_number, session_id, self._jsonl_path)
        return self._jsonl_path

    async def log_turn(self, turn: GateTurn) -> None:
        """Append one turn to both JSONL (as a line) and MD (as a section)."""
        if not self._jsonl_path or not self._md_path:
            raise RuntimeError("Session not started. Call start_session() first.")

        # Timestamp auto-fill
        if not turn.timestamp:
            turn.timestamp = datetime.now(timezone.utc).isoformat()

        # ── JSONL (canonical) ────────────────────────────────────────
        jsonl_line = self._turn_to_jsonl_line(turn)

        # Atomic append: validate via temp file, then append.
        tmp = self._jsonl_path.with_suffix(".tmp")
        tmp.write_text(jsonl_line + "\n", encoding="utf-8")
        # Verify the line round-trips as valid JSON
        json.loads(tmp.read_text(encoding="utf-8").strip())
        with open(self._jsonl_path, "a", encoding="utf-8") as fh:
            fh.write(jsonl_line + "\n")
        tmp.unlink(missing_ok=True)

        # ── Markdown (human-readable) ────────────────────────────────
        md_section = self._render_turn_md(turn)
        with open(self._md_path, "a", encoding="utf-8") as fh:
            fh.write(md_section)

        self._turn_count += 1

    async def log_decision(self, decision_data: dict) -> None:
        """Write the final gate decision as gateN_decision.json (atomic write).

        Uses MarketMindArchive.save_json which does temp-file → rename,
        preventing partial writes on crash.
        """
        if self._gate_number is None:
            raise RuntimeError("Session not started. Call start_session() first.")

        payload: dict = {}
        payload.update(decision_data)
        payload.setdefault("gate", self._gate_number)
        payload.setdefault("session_id", self._session_id)
        if "timestamp" not in payload:
            payload["timestamp"] = datetime.now(timezone.utc).isoformat()

        filepath = self.archive.save_json("gates", f"gate{self._gate_number}_decision", payload)
        logger.info("Gate %d decision archived: %s", self._gate_number, filepath)

    async def close_session(self) -> dict:
        """Write integrity footer to MD, reset internal state.

        Returns:
            dict with keys: jsonl_hash, turn_count, jsonl_path, md_path
        """
        if not self._jsonl_path or not self._md_path:
            raise RuntimeError("Session not started. Call start_session() first.")

        jsonl_hash = self._hash_file(self._jsonl_path)
        now_iso = datetime.now(timezone.utc).isoformat()

        footer = (
            f"\n---\n"
            f"**Archive integrity**: JSONL hash `{jsonl_hash}` | "
            f"{self._turn_count} events | {now_iso}\n"
            f"**JSONL path**: {self._jsonl_path}\n"
            f"**Canonical source**: JSONL. "
            f"This Markdown is a rendered view for human reading only.\n"
        )

        with open(self._md_path, "a", encoding="utf-8") as fh:
            fh.write(footer)

        logger.info(
            "Gate %d session closed: %d turns, hash %s",
            self._gate_number, self._turn_count, jsonl_hash,
        )

        result = {
            "jsonl_hash": jsonl_hash,
            "turn_count": self._turn_count,
            "jsonl_path": str(self._jsonl_path),
            "md_path": str(self._md_path),
        }

        # Reset
        self._gate_number = None
        self._session_id = None
        self._jsonl_path = None
        self._md_path = None
        self._turn_count = 0

        return result

    # ── private helpers ──────────────────────────────────────────────────

    def _turn_to_jsonl_line(self, turn: GateTurn) -> str:
        """Convert a GateTurn to a single JSONL line.

        data dict fields are merged at top level so downstream consumers
        can filter on direction, confidence, etc. without nested parsing.
        """
        line: dict = {
            "turn": turn.turn,
            "speaker": turn.speaker,
            "type": turn.type,
            "content_type": turn.content_type,
            "timestamp": turn.timestamp,
        }
        if turn.text is not None:
            line["text"] = turn.text
        if turn.data:
            line.update(turn.data)
        if turn.warnings is not None:
            line["warnings"] = turn.warnings
        return json.dumps(line, ensure_ascii=False, default=str)

    def _render_turn_md(self, turn: GateTurn) -> str:
        """Render one turn as a Markdown section.

        User content is ALWAYS wrapped in USER_TEXT_START/END HTML comments
        (C1 injection mitigation).  System decisions / structured data are
        wrapped in SYSTEM_DECISION_START/END.
        """
        lines = [f"## Turn {turn.turn} — {turn.speaker} ({turn.type})\n\n"]

        if turn.speaker == "USER":
            # C1 mitigation: ALL user-originated content is wrapped
            lines.append("<!-- USER_TEXT_START -->\n")
            if turn.text:
                lines.append(f"> {turn.text}\n")
            if turn.data:
                lines.append(self._render_data_fields(turn.data))
            lines.append("<!-- USER_TEXT_END -->\n")
        elif turn.content_type in ("system_decision", "structured_data"):
            lines.append("<!-- SYSTEM_DECISION_START -->\n")
            if turn.text:
                lines.append(f"{turn.text}\n\n")
            if turn.data:
                lines.append(self._render_data_fields(turn.data))
            lines.append("<!-- SYSTEM_DECISION_END -->\n")
        else:
            # ai_response or other — render as plain text
            if turn.text:
                lines.append(f"{turn.text}\n\n")
            if turn.data:
                lines.append(self._render_data_fields(turn.data))

        lines.append("\n")
        return "".join(lines)

    @staticmethod
    def _render_data_fields(data: dict) -> str:
        """Render structured data fields as bold key-value pairs."""
        parts = []
        for key, value in data.items():
            parts.append(f"**{key}**: {value}\n")
        return "".join(parts)

    @staticmethod
    def _hash_file(path: Path) -> str:
        """SHA-256 hex digest (first 16 chars) of file content."""
        return hashlib.sha256(path.read_bytes()).hexdigest()[:16]
