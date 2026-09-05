"""Durable source/target mappings with a small expiring in-memory cache."""

from __future__ import annotations
import json
import sqlite3
import time
from dataclasses import asdict
from pathlib import Path
from ..settings import FORWARD_RECORD_TTL_SECONDS
from .models import ForwardRecord


class ForwardIndex:
    """Tracks copied target messages for edited-message updates."""

    def __init__(self, path: Path | None = None) -> None:
        self._records: dict[tuple[int, int], ForwardRecord] = {}
        self._db: sqlite3.Connection | None = None
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            self._db = sqlite3.connect(path, isolation_level=None)
            self._db.execute(
                "CREATE TABLE IF NOT EXISTS forwards (source_chat INTEGER, source_message INTEGER, "
                "payload TEXT NOT NULL, PRIMARY KEY(source_chat, source_message))"
            )

    def close(self) -> None:
        if self._db is not None:
            self._db.close()

    def _cleanup_expired(self) -> None:
        """Removes forward records older than the configured TTL."""
        now = time.monotonic()
        expired_keys = [
            key
            for key, record in self._records.items()
            if now - record.stored_at > FORWARD_RECORD_TTL_SECONDS
        ]
        for key in expired_keys:
            self._records.pop(key, None)

    def set_record(
        self,
        source_chat_id: int,
        source_message_id: int,
        target_message_ids: dict[int, int],
        edit_history: list[str] | None = None,
        edit_mode: str = "",
        last_body: str = "",
        media_signature: str = "",
    ) -> None:
        """Stores target message ids for one source message."""
        self._cleanup_expired()
        record = ForwardRecord(
            source_chat_id=source_chat_id,
            source_message_id=source_message_id,
            target_message_ids=dict(target_message_ids),
            edit_history=list(edit_history or []),
            edit_mode=edit_mode,
            last_body=last_body,
            media_signature=media_signature,
        )
        if self._db is not None:
            payload = asdict(record)
            payload.pop("stored_at")  # monotonic time is only meaningful inside this process
            self._db.execute(
                "INSERT OR REPLACE INTO forwards VALUES (?,?,?)",
                (source_chat_id, source_message_id, json.dumps(payload)),
            )
        self._records[(source_chat_id, source_message_id)] = record

    def get_record(self, source_chat_id: int, source_message_id: int) -> ForwardRecord | None:
        """Returns the forward record for one source message."""
        self._cleanup_expired()
        key = (source_chat_id, source_message_id)
        record = self._records.get(key)
        if record is None and self._db is not None:
            row = self._db.execute(
                "SELECT payload FROM forwards WHERE source_chat=? AND source_message=?", key,
            ).fetchone()
            if row is not None:
                data = json.loads(row[0])
                data["target_message_ids"] = {int(k): int(v) for k, v in data["target_message_ids"].items()}
                record = ForwardRecord(**data)
                self._records[key] = record
        return record

    def remove_record(self, source_chat_id: int, source_message_id: int) -> ForwardRecord | None:
        """Removes and returns the forward record for one source message."""
        record = self.get_record(source_chat_id, source_message_id)
        key = (source_chat_id, source_message_id)
        if self._db is not None:
            self._db.execute("DELETE FROM forwards WHERE source_chat=? AND source_message=?", key)
        self._records.pop(key, None)
        return record
