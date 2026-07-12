"""In-memory index of copied target messages, used for edit propagation."""

from __future__ import annotations
import time
from ..settings import FORWARD_RECORD_TTL_SECONDS
from .models import ForwardRecord


class ForwardIndex:
    """Tracks copied target messages for edited-message updates."""

    def __init__(self) -> None:
        self._records: dict[tuple[int, int], ForwardRecord] = {}

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
    ) -> None:
        """Stores target message ids for one source message."""
        self._cleanup_expired()
        self._records[(source_chat_id, source_message_id)] = ForwardRecord(
            source_chat_id=source_chat_id,
            source_message_id=source_message_id,
            target_message_ids=dict(target_message_ids),
            edit_history=list(edit_history or []),
            edit_mode=edit_mode,
            last_body=last_body,
        )

    def get_record(self, source_chat_id: int, source_message_id: int) -> ForwardRecord | None:
        """Returns the forward record for one source message."""
        self._cleanup_expired()
        return self._records.get((source_chat_id, source_message_id))

    def remove_record(self, source_chat_id: int, source_message_id: int) -> ForwardRecord | None:
        """Removes and returns the forward record for one source message."""
        self._cleanup_expired()
        return self._records.pop((source_chat_id, source_message_id), None)
