"""Message, edit and raw-update listeners for the forward pipeline."""

from __future__ import annotations
import logging
from typing import Any
from pyrogram import Client
from pyrogram.errors import RPCError
from pyrogram.raw import types as raw_types
from pyrogram.types import Message
from ..core.config_store import BotConfigStore
from ..core.forward_index import ForwardIndex
from ..core.rules import (
    get_editable_content,
    get_message_text,
    is_outgoing_message,
    passes_view_once_filter,
    should_copy_by_direction,
    should_exclude_message,
)
from ..services.forwarding import (
    copy_or_replace_message,
    delete_forwarded_targets,
    edit_forwarded_message,
)
from ..ui.formatting import format_chat_refs
from .filters import SCHEDULED_FILTER


def register_forward_handlers(app: Client, store: BotConfigStore, forward_index: ForwardIndex) -> None:
    """Registers the forwarding listeners on the client.

    Must be called AFTER the command handlers: Pyrogram dispatches to the
    first matching handler per group, and the catch-all message listener
    would otherwise swallow slash commands.
    """

    @app.on_message(~SCHEDULED_FILTER)
    async def message_listener(client: Client, message: Message) -> None:
        """Copies incoming messages from configured source chats.

        Scheduled messages (still sitting in the scheduled view) are ignored on
        purpose: forwarding them at planning time would double-copy when they
        actually fire. ``from_scheduled`` (a previously-scheduled message that
        just got sent) is *not* blocked here so the actual delivery still
        propagates.
        """
        try:
            rule = store.get_listener(message.chat.id)
            if rule is None:
                return
            if not rule.enabled:
                logging.debug("Message %s in %s skipped: listener is paused.", message.id, message.chat.id)
                return
            logging.info(
                "New message %s detected in source %s (%s). Targets: %s | direction=%s | name_prefix=%s | text: %r",
                message.id,
                message.chat.id,
                rule.source_chat_name or "unknown",
                format_chat_refs(rule.target_chats),
                "outgoing" if is_outgoing_message(message) else "incoming",
                rule.name_prefix,
                get_message_text(message)[:3],
            )
            if should_exclude_message(message, rule):
                logging.info("Message %s in %s skipped by exclusion.", message.id, message.chat.id)
                return
            if not should_copy_by_direction(message, rule):
                logging.info(
                    "Message %s in %s skipped by direction filter. incoming=%s outgoing=%s",
                    message.id,
                    message.chat.id,
                    rule.copy_incoming,
                    rule.copy_outgoing,
                )
                return
            if not passes_view_once_filter(message, rule):
                logging.info(
                    "Message %s in %s skipped by view-once filter (view_once=%s).",
                    message.id,
                    message.chat.id,
                    rule.view_once,
                )
                return
            await copy_or_replace_message(client, message, rule, forward_index)
        except Exception:
            logging.exception("Error in message listener for chat %s at message %s.", message.chat.id, message.id)

    @app.on_edited_message(~SCHEDULED_FILTER)
    async def edited_message_listener(client: Client, message: Message) -> None:
        """Replaces forwarded copies when a source message gets edited.

        Edits inside the scheduled view are ignored: the forwarded copy does
        not exist yet, and the actual send will go through the regular path.
        """
        try:
            rule = store.get_listener(message.chat.id)
            if rule is None or not rule.enabled:
                return
            if (
                should_exclude_message(message, rule)
                or not should_copy_by_direction(message, rule)
                or not passes_view_once_filter(message, rule)
            ):
                record = forward_index.remove_record(message.chat.id, message.id)
                if record is not None:
                    await delete_forwarded_targets(client, record.target_message_ids)
                return
            record = forward_index.get_record(message.chat.id, message.id)
            content_type, body = get_editable_content(message)
            # Reactions/view-counts also fire on_edited_message. If the
            # editable content is unchanged it is not a real edit -> do not
            # re-copy the targets. Also covers media without caption ("" == "").
            if record is not None and record.edit_mode == content_type and record.last_body == body:
                return
            if record is not None and content_type:
                await edit_forwarded_message(client, message, rule, record, forward_index)
                return
            await copy_or_replace_message(client, message, rule, forward_index)
        except Exception:
            logging.exception("Error in edited-message listener for chat %s at message %s.", message.chat.id, message.id)

    @app.on_raw_update()
    async def read_history_listener(client: Client, update: Any, _: dict, __: dict) -> None:
        """Mirrors source-chat read events onto configured target chats.

        Telegram fires ``UpdateReadHistoryInbox`` (private/group) or
        ``UpdateReadChannelInbox`` (supergroup/channel) as soon as the own
        user marks something as read in a chat (typically by opening it).
        For configured source chats we mirror that onto all targets by
        calling ``read_chat_history`` there. The target chat thus follows
        the source chat and does not stay unread when the source was just
        read.
        """
        try:
            if isinstance(update, raw_types.UpdateReadHistoryInbox):
                peer = update.peer
                if isinstance(peer, raw_types.PeerUser):
                    source_chat_id = int(peer.user_id)
                elif isinstance(peer, raw_types.PeerChat):
                    source_chat_id = -int(peer.chat_id)
                elif isinstance(peer, raw_types.PeerChannel):
                    source_chat_id = -1000000000000 - int(peer.channel_id)
                else:
                    return
            elif isinstance(update, raw_types.UpdateReadChannelInbox):
                source_chat_id = -1000000000000 - int(update.channel_id)
            else:
                return

            rule = store.get_listener(source_chat_id)
            if rule is None or not rule.enabled:
                return

            logging.info(
                "Source %s (%s) was read, propagating read_chat_history to %d target(s).",
                source_chat_id,
                rule.source_chat_name or "unknown",
                len(rule.active_target_chat_ids),
            )

            for target_chat_id in rule.active_target_chat_ids:
                try:
                    await client.read_chat_history(target_chat_id)
                except (OSError, TimeoutError, RPCError) as exc:
                    logging.warning(
                        "Target chat %s unreachable after source read: %s",
                        target_chat_id,
                        exc,
                    )
                except Exception:
                    logging.debug(
                        "Target chat %s could not be marked as read after source read.",
                        target_chat_id,
                        exc_info=True,
                    )
        except Exception:
            logging.exception("Error in read-history raw-update handler.")
