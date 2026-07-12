"""Display names for chats and senders, plus name-prefix rendering."""

from __future__ import annotations
from typing import Any
from pyrogram.types import Message


def get_chat_name_from_chat(chat: Any) -> str:
    """Builds a readable display name from a chat object."""
    return str(
        getattr(chat, "title", None)
        or " ".join(
            part
            for part in [getattr(chat, "first_name", None), getattr(chat, "last_name", None)]
            if part
        ).strip()
        or (f"@{chat.username}" if getattr(chat, "username", None) else "")
        or getattr(chat, "id", "")
    )


def get_sender_display_name(message: Message) -> str:
    """Returns the best-effort display name for the original sender."""
    if getattr(message, "from_user", None) is not None:
        return str(
            " ".join(
                part
                for part in [message.from_user.first_name, message.from_user.last_name]
                if part
            ).strip()
            or (f"@{message.from_user.username}" if message.from_user.username else "")
            or message.from_user.id
        )
    if getattr(message, "sender_chat", None) is not None:
        return get_chat_name_from_chat(message.sender_chat)
    return get_chat_name_from_chat(message.chat)


def build_name_prefixed_text(message: Message, text: str) -> str:
    """Prefixes text with the original sender name."""
    return f"{get_sender_display_name(message)}: {text}"


def maybe_prefix_text(message: Message, text: str, name_prefix: bool) -> str:
    """Optionally prefixes text with the original sender name."""
    if not name_prefix or not text:
        return text
    return build_name_prefixed_text(message, text)


def build_rendered_body(message: Message, body: str, name_prefix: bool) -> str:
    """Builds the body that should be shown in forwarded content."""
    return maybe_prefix_text(message, body, name_prefix)
