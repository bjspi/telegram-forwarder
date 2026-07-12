"""Message rules: exclusion, direction and content predicates."""

from __future__ import annotations
from fnmatch import fnmatch
from pyrogram.types import Message
from .models import ListenerRule


def get_message_text(message: Message) -> str:
    """Returns the most useful textual content for exclusion matching."""
    return (message.text or message.caption or "").strip()


def should_exclude_message(message: Message, rule: ListenerRule) -> bool:
    """Checks whether the message is a command or matches any exclusion pattern."""
    text = get_message_text(message)
    if not text:
        return False
    if text.startswith("/"):
        return True
    return any(fnmatch(text, pattern) for pattern in rule.exclusions)


def is_outgoing_message(message: Message) -> bool:
    """Returns whether the message should be treated as outgoing."""
    if bool(getattr(message, "outgoing", False)):
        return True
    from_user = getattr(message, "from_user", None)
    return bool(from_user is not None and getattr(from_user, "is_self", False))


def should_copy_by_direction(message: Message, rule: ListenerRule) -> bool:
    """Checks whether the message direction is enabled for the listener."""
    outgoing = is_outgoing_message(message)
    if outgoing and not rule.copy_outgoing:
        return False
    if not outgoing and not rule.copy_incoming:
        return False
    return True


def get_editable_content(message: Message) -> tuple[str, str]:
    """Returns the editable content type and body for a message."""
    if message.text:
        return "text", message.text
    if message.caption:
        return "caption", message.caption
    return "", ""
