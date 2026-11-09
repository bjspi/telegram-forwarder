"""Dataclass models for listener, keep-alive and forward state."""

from __future__ import annotations
import time
from dataclasses import dataclass, field

# A target without a forum topic. Telegram's own id for the General topic is
# 1; posting there needs no thread id, so both are stored as "no topic".
NO_TOPIC_ID: int = 0
GENERAL_TOPIC_ID: int = 1
# Separates chat and topic in the textual target form `<chat>:<topic_id>`.
TOPIC_SEPARATOR: str = ":"


@dataclass(slots=True)
class ChatRef:
    """Stores a chat id together with a readable display name.

    A forward target may additionally point at one forum topic of a
    supergroup: ``topic_id`` is Telegram's message-thread id, ``NO_TOPIC_ID``
    means the chat itself (which is the General topic in a forum).
    """

    chat_id: int
    chat_name: str = ""
    topic_id: int = NO_TOPIC_ID
    topic_name: str = ""


@dataclass(slots=True)
class ListenerRule:
    """Defines how one source chat is copied into one or more target chats.

    A listener holds at most one target per chat: forward records and the
    pause list are keyed by target chat id, so a target's forum topic is an
    attribute of that target, not a second target in the same group.
    """

    source_chat_id: int
    source_chat_name: str = ""
    target_chats: list[ChatRef] = field(default_factory=list)
    exclusions: list[str] = field(default_factory=list)
    name_prefix: bool = False
    copy_incoming: bool = True
    copy_outgoing: bool = True
    store_edits: bool = False
    mark_target_unread: bool = False
    view_once: str = "off"
    enabled: bool = True
    # Individually paused targets. Kept separate from target_chats so pausing
    # is reversible without losing the chat reference.
    disabled_target_ids: list[int] = field(default_factory=list)

    @property
    def target_chat_ids(self) -> list[int]:
        """Returns target chat ids for the listener."""
        return [target.chat_id for target in self.target_chats]

    @property
    def active_target_chat_ids(self) -> list[int]:
        """Returns target chat ids that are not individually paused."""
        paused = set(self.disabled_target_ids)
        return [target.chat_id for target in self.target_chats if target.chat_id not in paused]

    @property
    def active_targets(self) -> list[ChatRef]:
        """Returns the targets (chat plus optional topic) that are not paused."""
        paused = set(self.disabled_target_ids)
        return [target for target in self.target_chats if target.chat_id not in paused]

    def find_target(self, target_chat_id: int) -> ChatRef | None:
        """Returns the configured target for one chat id, if any."""
        for target in self.target_chats:
            if target.chat_id == target_chat_id:
                return target
        return None

    def is_target_active(self, target_chat_id: int) -> bool:
        """Returns whether one target participates in forwarding."""
        return target_chat_id not in self.disabled_target_ids


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
    media_signature: str = ""
    stored_at: float = field(default_factory=time.monotonic)
