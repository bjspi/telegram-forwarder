"""Chat resolution (id/username -> ChatRef) and dialog listing."""

from __future__ import annotations
import inspect
from datetime import datetime
from typing import Any
from pyrogram import Client
from ..core.models import GENERAL_TOPIC_ID, NO_TOPIC_ID, TOPIC_SEPARATOR, ChatRef
from ..core.naming import get_chat_name_from_chat

# Upper bound for the control bot's topic picker (one button per topic).
FORUM_TOPICS_LIMIT: int = 30


async def resolve_chat_ref(client: Client, raw_value: str) -> ChatRef:
    """Resolves a numeric chat id or username into a chat reference with display name."""
    candidate = raw_value.strip()
    if not candidate:
        raise ValueError("Please provide a chat id or username.")

    chat = await client.get_chat(candidate if not candidate.lstrip("-").isdigit() else int(candidate))
    return ChatRef(chat_id=int(chat.id), chat_name=get_chat_name_from_chat(chat))


async def resolve_target_ref(client: Client, raw_value: str) -> ChatRef:
    """Resolves a target given as ``<chat>`` or ``<chat>:<topic_id>``.

    The topic is verified against the chat's forum topics, so a typo fails
    here instead of at the first forwarded message.
    """
    chat_part, separator, topic_part = raw_value.strip().rpartition(TOPIC_SEPARATOR)
    if not separator:
        return await resolve_chat_ref(client, raw_value)
    if not topic_part.isdigit():
        raise ValueError(f"Topic id must be a number: {raw_value}")

    target = await resolve_chat_ref(client, chat_part)
    topic_id = int(topic_part)
    if topic_id in (NO_TOPIC_ID, GENERAL_TOPIC_ID):
        return target
    topic_name = await get_forum_topic_name(client, target.chat_id, topic_id)
    if topic_name is None:
        raise ValueError(f"Topic {topic_id} does not exist in {target.chat_name or target.chat_id}.")
    target.topic_id = topic_id
    target.topic_name = topic_name
    return target


async def get_forum_topic_name(client: Client, chat_id: int, topic_id: int) -> str | None:
    """Returns the name of one forum topic, or None if the chat has no such topic."""
    topic = await client.get_forum_topic(chat_id, topic_id)
    if topic is None or isinstance(topic, list) or getattr(topic, "is_deleted", False):
        return None
    return str(topic.name or "")


async def resolve_target_chats(client: Client, raw_values: list[str]) -> list[ChatRef]:
    """Resolves one or more targets (chat id/username, optionally with ``:<topic_id>``)."""
    if not raw_values:
        raise ValueError("Please provide at least one target chat id or username.")
    resolved_target_chats: list[ChatRef] = []
    for raw_value in raw_values:
        resolved_target_chats.append(await resolve_target_ref(client, raw_value))
    return resolved_target_chats


async def get_forum_topic_targets(client: Client, chat: ChatRef, limit: int = FORUM_TOPICS_LIMIT) -> list[ChatRef]:
    """Returns one target reference per forum topic of a chat, most recently active first.

    Empty for chats that are not forums. The General topic is left out: it is
    addressed by the plain chat reference.
    """
    resolved_chat = await client.get_chat(chat.chat_id)
    if not getattr(resolved_chat, "is_forum", False):
        return []
    topic_targets: list[ChatRef] = []
    async for topic in client.get_forum_topics(chat.chat_id, limit=limit):
        topic_id = int(topic.message_thread_id)
        if topic_id == GENERAL_TOPIC_ID or getattr(topic, "is_deleted", False):
            continue
        topic_targets.append(
            ChatRef(chat_id=chat.chat_id, chat_name=chat.chat_name, topic_id=topic_id, topic_name=str(topic.name or ""))
        )
    return topic_targets


async def _collect_recent_dialogs(client: Client, limit: int) -> list[Any]:
    """Collects and de-duplicates the most recently active dialogs, newest first."""
    collected_dialogs: list[Any] = []
    seen_chat_ids: set[int] = set()

    for chat_list in (0, 1):
        dialogs: Any = client.get_dialogs(chat_list=chat_list)

        if inspect.isasyncgen(dialogs):
            async for dialog in dialogs:
                chat_id = int(dialog.chat.id)
                if chat_id in seen_chat_ids:
                    continue
                seen_chat_ids.add(chat_id)
                collected_dialogs.append(dialog)
        else:
            for dialog in dialogs:
                chat_id = int(dialog.chat.id)
                if chat_id in seen_chat_ids:
                    continue
                seen_chat_ids.add(chat_id)
                collected_dialogs.append(dialog)

    sorted_dialogs: list[Any] = sorted(
        collected_dialogs,
        key=lambda dialog: getattr(getattr(dialog, "top_message", None), "date", datetime.min),
        reverse=True,
    )
    return sorted_dialogs[:limit]


async def get_recent_chats(client: Client, limit: int = 20) -> list[ChatRef]:
    """Returns the most recently active dialogs as chat references (id + display name)."""
    dialogs = await _collect_recent_dialogs(client, limit)
    return [
        ChatRef(chat_id=int(dialog.chat.id), chat_name=get_chat_name_from_chat(dialog.chat))
        for dialog in dialogs
    ]


async def build_recent_chats_text(client: Client, limit: int = 20) -> str:
    """Builds a text listing the most recently active dialogs with chat ids."""
    lines: list[str] = ["Recent chats:"]
    for index, dialog in enumerate(await _collect_recent_dialogs(client, limit), start=1):
        chat = dialog.chat
        chat_type_text: str = str(getattr(chat, "type", "")).split(".")[-1].lower() or "unknown"
        title: str = str(
            chat.title
            or " ".join(part for part in [chat.first_name, chat.last_name] if part).strip()
            or (f"@{chat.username}" if chat.username else chat.id)
        )
        top_message = getattr(dialog, "top_message", None)
        last_activity = getattr(top_message, "date", None)
        last_activity_text = last_activity.strftime("%Y-%m-%d %H:%M:%S") if last_activity else "unknown"
        lines.append(f"{index}. [{chat_type_text}] {title} -> `{chat.id}` | last activity: {last_activity_text}")

    if len(lines) == 1:
        lines.append("No chats found.")
    return "\n".join(lines)
