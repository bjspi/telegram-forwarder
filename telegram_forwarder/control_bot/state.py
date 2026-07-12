"""Per-owner conversational state for multi-step control-bot flows.

The control bot has exactly one owner, but state is keyed by user id anyway so
the registry stays a plain, self-contained mapping. A pending action tracks
which multi-step flow (add listener / add keep-alive) is in progress, the step
within it, the most recently shown recent-chats list (for index-based picks),
and any chat already chosen.
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
STEP_CHAT: str = "chat"       # keep-alive: choose the chat
STEP_TIME: str = "time"       # keep-alive: enter the HH:MM:SS time


@dataclass(slots=True)
class PendingAction:
    """One in-progress multi-step flow for a single owner."""

    kind: str
    step: str
    recent: list[ChatRef] = field(default_factory=list)
    source: ChatRef | None = None
    awaiting_text: bool = False
