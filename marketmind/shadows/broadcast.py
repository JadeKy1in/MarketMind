"""Information Broadcast — Resolution 2: JSON-based atomic shadow broadcasting.

Writes user L1 chat history + viewpoints as JSON files to data/broadcast/.
Shadows poll this directory to discover user input and other shadows' signals.

Design: Phase C Resolution 2 (phase3-plan.md:270-304) — Red Team approved.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("marketmind.shadows.broadcast")


# ── Data types ──────────────────────────────────────────────────────────────

@dataclass
class BroadcastMessage:
    """A single broadcast item delivered to shadows."""
    message_id: str
    source_type: str        # "user_viewpoint" | "chat_history" | "attachment_ocr"
    source_path: str         # original file path (for attachments) or empty
    extracted_text: str      # the actual content
    metadata: dict           # {timestamp, author, tags, ...}
    confidence: float = 1.0  # always 1.0 for user-provided content
    created_at: str = ""

    MAX_TEXT_BYTES = 500_000  # 500KB cap per Resolution 2


# ── Broadcast Writer ─────────────────────────────────────────────────────────

class BroadcastWriter:
    """Writes broadcast messages to data/broadcast/ with atomic file operations.

    Resolution 2 Spec:
    - Storage path: data/broadcast/YYYY/MM/DD/{timestamp}_{content_hash[:8]}.json
    - Atomic write: tmp file → os.replace() (atomic on POSIX, NTFS)
    - Security: UUID disk names, _DEFANG on content, no executable formats
    """

    def __init__(self, data_dir: str = "data"):
        self.base_dir = Path(data_dir) / "broadcast"
        self._today_str = datetime.now(timezone.utc).strftime("%Y/%m/%d")

    @property
    def today_dir(self) -> Path:
        d = self.base_dir / self._today_str
        d.mkdir(parents=True, exist_ok=True)  # idempotent — fast path if exists
        return d

    def write(self, msg: BroadcastMessage) -> Path | None:
        """Write a single broadcast message atomically. Returns path or None on failure."""
        # Sanitize content through _DEFANG (mandatory — prompt injection defense)
        from marketmind.shadows.shadow_agent import defang_text
        msg.extracted_text = defang_text(msg.extracted_text)
        msg.created_at = datetime.now(timezone.utc).isoformat()

        # Enforce 500KB cap on total serialized payload
        payload = {
            "message_id": msg.message_id,
            "source_type": msg.source_type,
            "source_path": msg.source_path,
            "extracted_text": msg.extracted_text,
            "metadata": msg.metadata,
            "confidence": msg.confidence,
            "created_at": msg.created_at,
        }
        payload_bytes = json.dumps(payload, indent=2, ensure_ascii=False, default=str).encode("utf-8")
        if len(payload_bytes) > BroadcastMessage.MAX_TEXT_BYTES:
            logger.error("Broadcast message exceeds 500KB cap (%d bytes) — rejected", len(payload_bytes))
            return None

        # Generate safe filename: UUID.json (not user-provided)
        safe_name = f"{uuid.uuid4().hex}.json"
        tmp_path = self.today_dir / f".{safe_name}.tmp.{os.getpid()}"
        final_path = self.today_dir / safe_name

        try:
            # Sync write is acceptable here: payloads are small (<10KB JSON),
            # broadcast happens in a background shadow task, and the atomic
            # replace must happen AFTER the write completes.
            tmp_path.write_text(
                json.dumps(payload, indent=2, ensure_ascii=False, default=str),
                encoding="utf-8",
            )
            # Atomic replace (atomic on POSIX and NTFS; FAT32 handled in _atomic_replace)
            self._atomic_replace(str(tmp_path), str(final_path))
            logger.info("Broadcast written: %s (%d chars)", safe_name, len(msg.extracted_text))
            return final_path
        except Exception as e:
            logger.warning("Broadcast write failed: %s", e)
            # Clean up temp file
            try:
                tmp_path.unlink(missing_ok=True)
            except Exception:
                logger.warning("broadcast temp file cleanup failed", exc_info=True)
            return None

    def write_chat_history(self, user_ideas: list[str], ai_responses: list[str],
                           chat_context: str = "") -> list[Path]:
        """Write L1 chat history as broadcast messages for shadows.

        IMPORTANT (per docs/dev/phase_b_ideation_notes.md): Shadows see user's raw opinions
        and chat history, but NOT the main AI's pre-discussion analysis. Main AI
        analysis is excluded to prevent anchoring.
        """
        paths: list[Path] = []
        now = datetime.now(timezone.utc)

        # 1. User viewpoints (each idea as separate message for shadow filtering)
        for i, idea in enumerate(user_ideas):
            msg = BroadcastMessage(
                message_id=f"user_viewpoint_{now.strftime('%Y%m%d')}_{i}",
                source_type="user_viewpoint",
                source_path="",
                extracted_text=idea,
                metadata={"author": "user", "turn": i, "timestamp": now.isoformat()},
            )
            p = self.write(msg)
            if p:
                paths.append(p)

        # 2. Full chat context (user + AI dialogue — shadows self-filter)
        if chat_context:
            msg = BroadcastMessage(
                message_id=f"chat_history_{now.strftime('%Y%m%d')}",
                source_type="chat_history",
                source_path="",
                extracted_text=chat_context,
                metadata={"author": "user+ai_dialogue", "timestamp": now.isoformat()},
            )
            p = self.write(msg)
            if p:
                paths.append(p)

        # Write sentinel file (F: guarantees shadow reads complete broadcast set)
        if paths:
            sentinel = {
                "file_count": len(paths),
                "content_hash": hashlib.sha256(
                    "".join(p.name for p in paths).encode()
                ).hexdigest()[:16],
                "created_at": now.isoformat(),
            }
            sentinel_path = self.today_dir / ".ready"
            sentinel_path.write_text(
                json.dumps(sentinel, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )

        logger.info("Broadcast: %d messages + sentinel written for %d user ideas", len(paths), len(user_ideas))
        return paths

    @staticmethod
    def _atomic_replace(src: str, dst: str) -> None:
        """Atomic file replacement. os.replace() is atomic on POSIX and NTFS.
        For FAT32, attempts os.replace() and falls back to copy+delete.
        """
        try:
            os.replace(src, dst)
        except OSError:
            # Fallback for filesystems without atomic rename (e.g. FAT32)
            import shutil
            shutil.copy2(src, dst)
            os.unlink(src)


# ── Broadcast Reader ─────────────────────────────────────────────────────────

class BroadcastReader:
    """Reads broadcast messages for shadow consumption.

    Shadows call poll_today() at the start of their analysis cycle to discover
    new broadcast files. Each shadow self-filters based on domain relevance.
    """

    def __init__(self, data_dir: str = "data"):
        self.base_dir = Path(data_dir) / "broadcast"
        self._seen: set[str] = set()  # deduplicate across polls

    def poll_today(self, date_str: str | None = None) -> list[BroadcastMessage]:
        """Read all broadcast messages for today (or a specific date).

        Returns list of BroadcastMessage objects. Shadows should self-filter
        by domain relevance before using.
        """
        if date_str is None:
            date_str = datetime.now(timezone.utc).strftime("%Y/%m/%d")

        # Normalize date format: both yyyy-mm-dd and yyyy/mm/dd accepted
        date_str = date_str.replace("-", "/")
        # Security: validate to prevent path traversal
        import re as _re
        if not _re.match(r"^\d{4}/\d{2}/\d{2}$", date_str):
            logger.warning("BroadcastReader: rejected invalid date_str %r", date_str[:50])
            return []

        broadcast_dir = self.base_dir / date_str
        if not broadcast_dir.exists():
            return []

        # Wait for sentinel file (F: guarantees complete broadcast set)
        sentinel = broadcast_dir / ".ready"
        if not sentinel.exists():
            return []  # broadcast not yet complete

        messages: list[BroadcastMessage] = []
        for f in sorted(broadcast_dir.glob("*.json")):
            if f.name in self._seen:
                continue
            # Skip non-UUID files and temp files
            if f.name.startswith("."):
                continue
            # Security: only allow .json files
            if f.suffix != ".json":
                logger.warning("Non-JSON file in broadcast dir: %s — skipped", f.name)
                continue

            try:
                # Security: reject files over 1MB before reading into memory
                f_size = f.stat().st_size
                if f_size > 1_048_576:  # 1MB hard cap
                    logger.warning("Broadcast file too large (%d bytes): %s — skipped", f_size, f.name)
                    continue
                data = json.loads(f.read_text(encoding="utf-8"))
                msg = BroadcastMessage(
                    message_id=data.get("message_id", ""),
                    source_type=data.get("source_type", ""),
                    source_path=data.get("source_path", ""),
                    extracted_text=data.get("extracted_text", ""),
                    metadata=data.get("metadata", {}),
                    confidence=float(data.get("confidence", 1.0)),
                    created_at=data.get("created_at", ""),
                )
                messages.append(msg)
                self._seen.add(f.name)
            except (json.JSONDecodeError, KeyError, ValueError) as e:
                logger.warning("Corrupt broadcast file: %s — %s", f.name, e)
                continue

        return messages

    def filter_by_domain(self, messages: list[BroadcastMessage],
                        domain_keywords: dict[str, list[str]]) -> list[BroadcastMessage]:
        """Filter broadcast messages by domain relevance.

        Each shadow has a domain (e.g. 'tech', 'energy'). This method matches
        broadcast content against domain keywords to find relevant messages.
        """
        relevant: list[BroadcastMessage] = []
        for msg in messages:
            text_lower = msg.extracted_text.lower()
            for domain, keywords in domain_keywords.items():
                if any(kw.lower() in text_lower for kw in keywords):
                    relevant.append(msg)
                    break
        return relevant

    @staticmethod
    def extract_user_opinions(messages: list[BroadcastMessage]) -> list[str]:
        """Extract user viewpoint texts from broadcast messages."""
        return [m.extracted_text for m in messages
                if m.source_type in ("user_viewpoint", "chat_history")]
