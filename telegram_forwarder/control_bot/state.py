"""Per-owner conversational state for multi-step control-bot flows.

The control bot has exactly one owner, but state is keyed by user id anyway so
the registry stays a plain, self-contained mapping. A pending action tracks
which multi-step flow (add listener / add keep-alive) is in progress, the step
within it, the most recently shown recent-chats list (for index-based picks),
any chat already chosen and, for forum targets, the offered topics.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from ..core.models import ChatRef

# Flow kinds
KIND_LISTENER: str = "listener"
KIND_KEEPALIVE: str = "keepalive"

# Steps
STEP_SOURCE: str = "source"   # listener: choose the source chat
STEP_TARGET: str = "target"   # listener: choose the target chat
STEP_TOPIC: str = "topic"     # listener: choose a forum topic of the target chat
STEP_CHAT: str = "chat"       # keep-alive: choose the chat
STEP_TIME: str = "time"       # keep-alive: enter the HH:MM:SS time


@dataclass(slots=True)
class PendingAction:
    """One in-progress multi-step flow for a single owner."""

    kind: str
    step: str
    recent: list[ChatRef] = field(default_factory=list)
    source: ChatRef | None = None
    # Set while STEP_TOPIC is open: the chosen forum chat and its topics
    # (index-based picks, like ``recent``).
    target: ChatRef | None = None
    topics: list[ChatRef] = field(default_factory=list)
    awaiting_text: bool = False
