"""Fills in missing chat names in old configs and persists them."""

from __future__ import annotations
import logging
from pyrogram import Client
from ..connection.chats import get_forum_topic_name
from ..core.config_store import BotConfigStore
from ..core.naming import get_chat_name_from_chat


async def enrich_listener_chat_names(client: Client, store: BotConfigStore) -> None:
    """Fills missing source/target chat names and target topic names and persists them."""
    for rule in store.all_listeners():
        source_chat_name: str | None = None
        target_chat_names: dict[int, str] = {}
        target_topic_names: dict[int, str] = {}

        try:
            if not rule.source_chat_name:
                source_chat = await client.get_chat(rule.source_chat_id)
                source_chat_name = get_chat_name_from_chat(source_chat)
        except Exception:
            logging.debug("Source chat name for %s could not be resolved.", rule.source_chat_id, exc_info=True)

        for target_chat in rule.target_chats:
            if target_chat.chat_name:
                continue
            try:
                resolved_target_chat = await client.get_chat(target_chat.chat_id)
                target_chat_names[target_chat.chat_id] = get_chat_name_from_chat(resolved_target_chat)
            except Exception:
                logging.debug("Target chat name for %s could not be resolved.", target_chat.chat_id, exc_info=True)

        for target_chat in rule.target_chats:
            if not target_chat.topic_id or target_chat.topic_name:
                continue
            try:
                topic_name = await get_forum_topic_name(client, target_chat.chat_id, target_chat.topic_id)
                if topic_name is None:
                    logging.warning(
                        "Topic %s of target chat %s (listener %s) does not exist; forwards to it will fail.",
                        target_chat.topic_id, target_chat.chat_id, rule.source_chat_id,
                    )
                    continue
                target_topic_names[target_chat.chat_id] = topic_name
            except Exception:
                logging.debug(
                    "Topic name for %s in target chat %s could not be resolved.",
                    target_chat.topic_id, target_chat.chat_id, exc_info=True,
                )

        if source_chat_name or target_chat_names or target_topic_names:
            if store.update_listener_chat_names(
                source_chat_id=rule.source_chat_id,
                source_chat_name=source_chat_name,
                target_chat_names=target_chat_names,
                target_topic_names=target_topic_names,
            ):
                logging.info("Filled in missing chat names for listener %s.", rule.source_chat_id)


async def enrich_keepalive_chat_names(client: Client, store: BotConfigStore) -> None:
    """Fills missing keep-alive chat names in old configs and persists them."""
    for rule in store.all_keepalives():
        if rule.chat_name:
            continue
        try:
            keepalive_chat = await client.get_chat(rule.chat_id)
            if store.update_keepalive_chat_name(rule.chat_id, get_chat_name_from_chat(keepalive_chat)):
                logging.info("Filled in missing chat name for keep-alive %s.", rule.chat_id)
        except Exception:
            logging.debug("Keep-alive chat name for %s could not be resolved.", rule.chat_id, exc_info=True)
