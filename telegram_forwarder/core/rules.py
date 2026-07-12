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


"""Media attributes that can carry a self-destruct timer (view/listen-once)."""
SELF_DESTRUCT_MEDIA_TYPES: tuple[str, ...] = ("photo", "video", "voice", "video_note", "animation")


def is_view_once_message(message: Message) -> bool:
    """Returns whether the message carries self-destructing (view/listen-once) media.

    Telegram marks view-once photos/videos and listen-once voice/video notes
    with a ``ttl_seconds`` value on the media object (0x7FFFFFFF for
    view-once, otherwise the self-destruct timer). Any truthy TTL counts.
    """
    if getattr(message, "ttl_seconds", None):
        return True
    for media_type in SELF_DESTRUCT_MEDIA_TYPES:
        media = getattr(message, media_type, None)
        if media is not None and getattr(media, "ttl_seconds", None):
            return True
    return False


def passes_view_once_filter(message: Message, rule: ListenerRule) -> bool:
    """Checks whether the message passes the listener's view-once-only filter."""
    return not rule.view_once_only or is_view_once_message(message)


def get_editable_content(message: Message) -> tuple[str, str]:
    """Returns the editable content type and body for a message."""
    if message.text:
        return "text", message.text
    if message.caption:
        return "caption", message.caption
    return "", ""
