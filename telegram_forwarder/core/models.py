"""Dataclass models for listener, keep-alive and forward state."""

from __future__ import annotations
import time
from dataclasses import dataclass, field


@dataclass(slots=True)
class ChatRef:
    """Stores a chat id together with a readable display name."""

    chat_id: int
    chat_name: str = ""


@dataclass(slots=True)
class ListenerRule:
    """Defines how one source chat is copied into one or more target chats."""

    source_chat_id: int
    source_chat_name: str = ""
    target_chats: list[ChatRef] = field(default_factory=list)
    exclusions: list[str] = field(default_factory=list)
    name_prefix: bool = False
    copy_incoming: bool = True
    copy_outgoing: bool = True
    store_edits: bool = False
    mark_target_unread: bool = False
    view_once_only: bool = False

    @property
    def target_chat_ids(self) -> list[int]:
        """Returns target chat ids for the listener."""
        return [target.chat_id for target in self.target_chats]


@dataclass(slots=True)
class KeepAliveRule:
    """Defines a daily keep-alive message for one chat."""

    chat_id: int
    time_of_day: str
    message_text: str | list[str]
    enabled: bool = True
    time_of_day_delta: float = 0.0
    chat_name: str = ""


@dataclass(slots=True)
class ForwardRecord:
    """Stores copied target message ids for one source message."""

    source_chat_id: int
    source_message_id: int
    target_message_ids: dict[int, int] = field(default_factory=dict)
    edit_history: list[str] = field(default_factory=list)
    edit_mode: str = ""
    last_body: str = ""
    stored_at: float = field(default_factory=time.monotonic)
