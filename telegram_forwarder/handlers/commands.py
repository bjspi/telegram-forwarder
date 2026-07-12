"""Slash-command handlers (all gated by filters.me, each cleans up after itself).

IMPORTANT (rule for userbots sharing one account): a userbot may only delete
its OWN commands. There once was a catch-all ``cleanup_unknown_commands`` that
deleted — via ``filters.me & filters.regex(r"^/\\S+")`` — EVERY self-sent slash
message not listed in KNOWN_COMMANDS, in every chat (not chat-scoped). It wiped
out commands belonging to other bots running on the same account (e.g. a
reply bot's /reply, a transcriber bot's commands). Removed. Never build an
unknown-command catch-all — unknown commands may belong to a sibling bot.
"""

from __future__ import annotations
import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from pyrogram import Client, filters
from pyrogram.types import Message
from ..connection.chats import build_recent_chats_text, resolve_chat_ref, resolve_target_chats
from ..core.config_store import BotConfigStore
from ..core.models import ChatRef
from ..core.naming import get_chat_name_from_chat
from ..services.keepalive import parse_hms, sync_keepalive_jobs
from ..settings import CONFIG_ALL_DELETE_DELAY_SECONDS, LIST_CHATS_DELETE_DELAY_SECONDS
from ..ui.formatting import (
    build_config_text_for_rules,
    build_help_text,
    build_keepalive_config_text,
    format_chat_ref,
    format_chat_refs,
    get_status_text,
)
from ..ui.replies import send_and_delete_message
from .filters import CMD_BASE


async def resolve_copy_command_args(client: Client, message: Message) -> tuple[ChatRef, list[ChatRef], bool | None]:
    """Resolves /copy arguments to either current-chat mode or explicit source-target mode."""
    command_args: list[str] = list(message.command[1:])
    if not command_args:
        raise ValueError("Usage: /copy <target> [more...] or /copy <source> <target> [more...]")

    name_prefix: bool | None = None
    filtered_command_args: list[str] = []
    for command_arg in command_args:
        normalized_arg = command_arg.strip().lower()
        if normalized_arg == "--name-prefix":
            name_prefix = True
            continue
        if normalized_arg == "--no-name-prefix":
            name_prefix = False
            continue
        filtered_command_args.append(command_arg)
    command_args = filtered_command_args

    if not command_args:
        raise ValueError("Usage: /copy <target> [more...] [--name-prefix] or /copy <source> <target> [more...] [--name-prefix]")

    if len(command_args) == 1:
        return (
            ChatRef(chat_id=int(message.chat.id), chat_name=get_chat_name_from_chat(message.chat)),
            await resolve_target_chats(client, command_args),
            name_prefix,
        )

    source_chat: ChatRef = await resolve_chat_ref(client, command_args[0])
    target_chats: list[ChatRef] = await resolve_target_chats(client, command_args[1:])
    return source_chat, target_chats, name_prefix


def register_command_handlers(app: Client, store: BotConfigStore, scheduler: AsyncIOScheduler) -> None:
    """Registers all slash-command handlers on the client.

    Must be called BEFORE the forward listeners are registered: Pyrogram
    dispatches to the first matching handler per group, so commands have to
    win against the catch-all message listener.
    """

    @app.on_message(CMD_BASE & filters.command("helpf", prefixes="/"))
    async def help_command(_: Client, message: Message) -> None:
        """Shows the available commands in any chat."""
        try:
            await send_and_delete_message(message, build_help_text(store), LIST_CHATS_DELETE_DELAY_SECONDS)
        except Exception:
            logging.exception("Error in /helpf handler for chat %s.", message.chat.id)

    @app.on_message(CMD_BASE & filters.command("show_id", prefixes="/"))
    async def show_id_command(_: Client, message: Message) -> None:
        """Shows the current chat id."""
        try:
            title = message.chat.title or message.chat.first_name or "Unknown"
            await send_and_delete_message(
                message,
                f"Chat id: `{message.chat.id}`\nTitle: {title}",
                store.delete_delay_seconds,
            )
        except Exception:
            logging.exception("Error in /show_id handler for chat %s.", message.chat.id)

    @app.on_message(CMD_BASE & filters.command("list_chats", prefixes="/"))
    async def list_chats_command(client: Client, message: Message) -> None:
        """Shows the latest dialogs with readable names and chat ids."""
        try:
            await send_and_delete_message(
                message,
                await build_recent_chats_text(client, limit=20),
                LIST_CHATS_DELETE_DELAY_SECONDS,
            )
        except Exception:
            logging.exception("Error in /list_chats handler for chat %s.", message.chat.id)

    @app.on_message(CMD_BASE & filters.command("config", prefixes="/"))
    async def config_command(client: Client, message: Message) -> None:
        """Shows listener configuration for current source, one source, or all sources."""
        try:
            args = list(message.command[1:])
            delay_seconds = store.delete_delay_seconds

            if not args:
                rule = store.get_listener(message.chat.id)
                text = build_config_text_for_rules(
                    f"Config for current chat `{message.chat.id}`:",
                    [rule] if rule is not None else [],
                )
            elif len(args) == 1 and args[0].strip().lower() == "all":
                text = (
                    f"{build_config_text_for_rules('All listeners:', store.all_listeners())}\n\n"
                    f"{build_keepalive_config_text('All keep-alives:', store.all_keepalives())}"
                )
                delay_seconds = CONFIG_ALL_DELETE_DELAY_SECONDS
            elif len(args) == 1:
                source_chat = await resolve_chat_ref(client, args[0])
                rule = store.get_listener(source_chat.chat_id)
                text = build_config_text_for_rules(
                    f"Config for source `{format_chat_ref(source_chat)}`:",
                    [rule] if rule is not None else [],
                )
            else:
                text = "Usage: /config or /config <source> or /config all"

            await send_and_delete_message(message, text, delay_seconds)
        except Exception:
            logging.exception("Error in /config handler for chat %s.", message.chat.id)

    @app.on_message(CMD_BASE & filters.command("copy", prefixes="/"))
    async def copy_command(client: Client, message: Message) -> None:
        """Registers or extends a listener in current-chat or explicit source-target mode."""
        try:
            if len(message.command) < 2:
                await send_and_delete_message(
                    message,
                    "Usage: /copy <target> [more...] [--name-prefix] or /copy <source> <target> [more...] [--name-prefix]",
                    store.delete_delay_seconds,
                )
                return

            source_chat, target_chats, name_prefix = await resolve_copy_command_args(client, message)
            rule, added_target_chats = store.upsert_listener(
                source_chat=source_chat,
                target_chats=target_chats,
                name_prefix=name_prefix,
            )
            sync_keepalive_jobs(scheduler, store, app)

            if added_target_chats:
                result_text = (
                    "Listener updated: "
                    f"`{format_chat_ref(ChatRef(rule.source_chat_id, rule.source_chat_name))}` -> `{format_chat_refs(added_target_chats)}` added.\n"
                )
            else:
                result_text = (
                    "No change: all given source->target rules already existed.\n"
                )

            await send_and_delete_message(
                message,
                (
                    f"{result_text}"
                    f"Source: `{format_chat_ref(ChatRef(rule.source_chat_id, rule.source_chat_name))}`\n"
                    f"Active targets: `{format_chat_refs(rule.target_chats)}`\n"
                    f"name_prefix: `{rule.name_prefix}`\n"
                    f"Exclusions: {', '.join(rule.exclusions) or '(none)'}\n"
                    f"{get_status_text(store)}"
                ),
                store.delete_delay_seconds,
            )
        except Exception as exc:
            await send_and_delete_message(
                message,
                f"Copy could not be set: {exc}",
                store.delete_delay_seconds,
            )

    @app.on_message(CMD_BASE & filters.command("stop", prefixes="/"))
    async def stop_command(client: Client, message: Message) -> None:
        """Stops one source entirely or removes one specific source-target mapping."""
        try:
            args = list(message.command[1:])
            if not args:
                removed = store.remove_listener(message.chat.id)
                if removed is None:
                    await send_and_delete_message(
                        message,
                        "No listener is active for this chat.",
                        store.delete_delay_seconds,
                    )
                    return

                await send_and_delete_message(
                    message,
                    f"Listener stopped: `{format_chat_ref(ChatRef(removed.source_chat_id, removed.source_chat_name))}` -> `{format_chat_refs(removed.target_chats)}`",
                    store.delete_delay_seconds,
                )
                return

            source_chat = await resolve_chat_ref(client, args[0])
            if len(args) == 1:
                removed = store.remove_listener(source_chat.chat_id)
                if removed is None:
                    await send_and_delete_message(
                        message,
                        f"Source `{format_chat_ref(source_chat)}` is not configured.",
                        store.delete_delay_seconds,
                    )
                    return
                await send_and_delete_message(
                    message,
                    f"All connections removed for `{format_chat_ref(source_chat)}`.",
                    store.delete_delay_seconds,
                )
                return

            target_chat = await resolve_chat_ref(client, args[1])
            rule, removed_targets = store.remove_listener_targets(source_chat.chat_id, [target_chat.chat_id])
            if rule is None:
                await send_and_delete_message(
                    message,
                    f"Source `{format_chat_ref(source_chat)}` is not configured.",
                    store.delete_delay_seconds,
                )
                return
            if not removed_targets:
                await send_and_delete_message(
                    message,
                    f"Connection `{format_chat_ref(source_chat)}` -> `{format_chat_ref(target_chat)}` does not exist.",
                    store.delete_delay_seconds,
                )
                return
            remaining_rule = store.get_listener(source_chat.chat_id)
            remaining_text = (
                f"Remaining targets: `{format_chat_refs(remaining_rule.target_chats)}`"
                if remaining_rule is not None
                else "No remaining targets."
            )
            await send_and_delete_message(
                message,
                f"Connection removed: `{format_chat_ref(source_chat)}` -> `{format_chat_ref(target_chat)}`\n{remaining_text}",
                store.delete_delay_seconds,
            )
        except Exception:
            logging.exception("Error in /stop handler for chat %s.", message.chat.id)

    @app.on_message(CMD_BASE & filters.command("keepalive", prefixes="/"))
    async def keepalive_command(_: Client, message: Message) -> None:
        """Creates, updates or disables a chat-specific keep-alive."""
        try:
            raw_value = message.command[1].strip().lower() if len(message.command) >= 2 else store.default_keepalive_time
            if raw_value == "pause":
                rule = store.toggle_keepalive_enabled(message.chat.id)
                sync_keepalive_jobs(scheduler, store, app)
                if rule is None:
                    await send_and_delete_message(
                        message,
                        "No keep-alive is set for this chat.",
                        store.delete_delay_seconds,
                    )
                    return
                state_text = "active" if rule.enabled else "paused"
                await send_and_delete_message(
                    message,
                    f"Keep-alive for `{rule.chat_id}` is now `{state_text}`.",
                    store.delete_delay_seconds,
                )
                return
            if raw_value == "off":
                removed = store.remove_keepalive(message.chat.id)
                sync_keepalive_jobs(scheduler, store, app)
                text = (
                    f"Keep-alive removed for `{message.chat.id}`."
                    if removed is not None
                    else "No keep-alive was set for this chat."
                )
                await send_and_delete_message(message, text, store.delete_delay_seconds)
                return

            parse_hms(raw_value)
            rule = store.upsert_keepalive(message.chat.id, raw_value)
            sync_keepalive_jobs(scheduler, store, app)
            await send_and_delete_message(
                message,
                f"Keep-alive active for `{rule.chat_id}` at `{rule.time_of_day}`.",
                store.delete_delay_seconds,
            )
        except Exception as exc:
            await send_and_delete_message(
                message,
                f"Keep-alive could not be set: {exc}",
                store.delete_delay_seconds,
            )
