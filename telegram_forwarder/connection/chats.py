"""Chat resolution (id/username -> ChatRef) and dialog listing."""

from __future__ import annotations
import inspect
from datetime import datetime
from typing import Any
from pyrogram import Client
from ..core.models import ChatRef
from ..core.naming import get_chat_name_from_chat


async def resolve_chat_ref(client: Client, raw_value: str) -> ChatRef:
    """Resolves a numeric chat id or username into a chat reference with display name."""
    candidate = raw_value.strip()
    if not candidate:
        raise ValueError("Please provide a chat id or username.")

    chat = await client.get_chat(candidate if not candidate.lstrip("-").isdigit() else int(candidate))
    return ChatRef(chat_id=int(chat.id), chat_name=get_chat_name_from_chat(chat))


async def resolve_target_chats(client: Client, raw_values: list[str]) -> list[ChatRef]:
    """Resolves one or more numeric chat ids or usernames to chat references."""
    if not raw_values:
        raise ValueError("Please provide at least one target chat id or username.")
    resolved_target_chats: list[ChatRef] = []
    for raw_value in raw_values:
        resolved_target_chats.append(await resolve_chat_ref(client, raw_value))
    return resolved_target_chats


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
