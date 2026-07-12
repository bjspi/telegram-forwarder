"""Forward/edit pipeline: copies, replaces and edits messages in target chats.

The copy path has a two-stage fallback: Pyrogram's ``message.copy()`` first;
on failure (or protected content) the media is downloaded and re-uploaded as a
fresh message. Only the fallback path can apply ``name_prefix`` to media
captions. Every ``message.download()`` is guarded with try/finally +
``safe_unlink`` because Pyrogram never deletes the files in ./downloads/ itself.
"""

from __future__ import annotations
import logging
from pathlib import Path
from typing import Any
from pyrogram import Client
from pyrogram.errors import RPCError
from pyrogram.types import Message
from ..core.forward_index import ForwardIndex
from ..core.models import ForwardRecord, ListenerRule
from ..core.naming import build_rendered_body, maybe_prefix_text
from ..core.rules import get_editable_content, is_outgoing_message


def detect_media_type(message: Message) -> str:
    """Returns the kind of downloadable media in a message, or '' for text-only."""
    for media_type in ("document", "photo", "video", "audio", "voice", "animation", "sticker", "video_note"):
        if getattr(message, media_type, None):
            return media_type
    return ""


def safe_unlink(path: Any) -> None:
    """Deletes a temporary download path and ignores missing files."""
    if path is None:
        return
    try:
        Path(str(path)).unlink(missing_ok=True)
    except OSError:
        logging.debug("Temp download %s could not be deleted.", path, exc_info=True)


async def send_media_from_path(
    client: Client,
    target_chat_id: int,
    media_type: str,
    path: str,
    caption: str,
) -> Message | None:
    """Sends a previously downloaded media file using the matching pyrogram method."""
    if media_type == "document":
        return await client.send_document(target_chat_id, path, caption=caption)
    if media_type == "photo":
        return await client.send_photo(target_chat_id, path, caption=caption)
    if media_type == "video":
        return await client.send_video(target_chat_id, path, caption=caption)
    if media_type == "audio":
        return await client.send_audio(target_chat_id, path, caption=caption)
    if media_type == "voice":
        return await client.send_voice(target_chat_id, path, caption=caption)
    if media_type == "animation":
        return await client.send_animation(target_chat_id, path, caption=caption)
    if media_type == "sticker":
        return await client.send_sticker(target_chat_id, path)
    if media_type == "video_note":
        return await client.send_video_note(target_chat_id, path)
    return None


async def send_text_message(
    client: Client,
    target_chat_id: int,
    text: str,
) -> Message | None:
    """Sends plain text to a target chat."""
    try:
        return await client.send_message(target_chat_id, text)
    except Exception:
        logging.debug(
            "Sending the text message to %s failed.",
            target_chat_id,
            exc_info=True,
        )
    return None


async def mark_chat_unread_safely(client: Client, chat_id: int) -> None:
    """Marks a chat as unread without failing the forwarding pipeline."""
    try:
        await client.mark_chat_unread(chat_id)
        logging.info("Target chat %s marked as unread.", chat_id)
    except (OSError, TimeoutError, RPCError) as exc:
        logging.warning(
            "Target chat %s could not be marked as unread due to a network/API problem: %s",
            chat_id,
            exc,
        )
    except Exception:
        logging.debug(
            "Target chat %s could not be marked as unread.",
            chat_id,
            exc_info=True,
        )


async def resend_message_with_fallback(
    client: Client,
    message: Message,
    target_chat_id: int,
    name_prefix: bool = False,
) -> Message | None:
    """Re-uploads or recreates a message when Telegram copy is blocked."""
    caption = maybe_prefix_text(message, message.caption or "", name_prefix)
    media_type = detect_media_type(message)
    copied_message: Message | None = None
    path: Any = None

    try:
        if not media_type and message.text:
            copied_message = await client.send_message(
                target_chat_id,
                maybe_prefix_text(message, message.text, name_prefix),
            )
        else:
            path = await message.download()
            copied_message = await send_media_from_path(
                client, target_chat_id, media_type or "document", str(path), caption,
            )
        if copied_message is not None:
            logging.info(
                "Fallback for message %s from source %s to %s succeeded.",
                message.id,
                message.chat.id,
                target_chat_id,
            )
    except (OSError, TimeoutError, RPCError):
        logging.warning(
            "Fallback for message %s to %s failed due to a network/API problem.",
            message.id,
            target_chat_id,
            exc_info=True,
        )
    except Exception:
        logging.exception(
            "Re-upload failed for message %s to %s.",
            message.id,
            target_chat_id,
        )
    finally:
        safe_unlink(path)
    return copied_message


async def copy_message_to_target(
    client: Client,
    message: Message,
    target_chat_id: int,
    name_prefix: bool = False,
) -> int | None:
    """Copies a message to the target chat with a media re-upload fallback."""
    if name_prefix:
        copied_message = await resend_message_with_fallback(client, message, target_chat_id, name_prefix=True)
        return int(copied_message.id) if copied_message is not None else None

    try:
        if getattr(message.chat, "has_protected_content", False) or getattr(message, "has_protected_content", False):
            raise RuntimeError("protected_content")

        copied = await message.copy(chat_id=target_chat_id)
        logging.info(
            "Message %s from source %s successfully copied to %s.",
            message.id,
            message.chat.id,
            target_chat_id,
        )
        # copy() returns a list for media groups; the first message counts here.
        copied_first = copied[0] if isinstance(copied, list) else copied
        return int(copied_first.id)
    except (OSError, TimeoutError, RPCError) as exc:
        logging.warning(
            "Copy for message %s to %s failed due to a network/API problem: %s",
            message.id,
            target_chat_id,
            exc,
        )
    except Exception as exc:
        logging.warning(
            "Copy failed for message %s to %s: %s",
            message.id,
            target_chat_id,
            exc,
        )

    copied_message = await resend_message_with_fallback(client, message, target_chat_id, name_prefix=False)
    return int(copied_message.id) if copied_message is not None else None


async def copy_message_to_targets(
    client: Client,
    message: Message,
    target_chat_ids: list[int],
    name_prefix: bool = False,
    mark_target_unread: bool = False,
) -> dict[int, int]:
    """Copies one message sequentially to all configured target chats."""
    target_message_ids: dict[int, int] = {}
    for target_chat_id in target_chat_ids:
        copied_message_id = await copy_message_to_target(client, message, target_chat_id, name_prefix=name_prefix)
        if copied_message_id is not None:
            target_message_ids[target_chat_id] = copied_message_id
            if mark_target_unread:
                await mark_chat_unread_safely(client, target_chat_id)
    return target_message_ids


async def delete_forwarded_targets(client: Client, target_message_ids: dict[int, int]) -> None:
    """Deletes a set of forwarded target messages."""
    for target_chat_id, target_message_id in target_message_ids.items():
        try:
            await client.delete_messages(target_chat_id, target_message_id)
        except Exception:
            logging.debug(
                "Target message %s in chat %s could not be deleted.",
                target_message_id,
                target_chat_id,
                exc_info=True,
            )


async def copy_or_replace_message(
    client: Client,
    message: Message,
    rule: ListenerRule,
    forward_index: ForwardIndex,
) -> None:
    """Copies or replaces a source message across all listener targets."""
    existing_record = forward_index.get_record(message.chat.id, message.id)
    if existing_record is not None:
        await delete_forwarded_targets(client, existing_record.target_message_ids)

    # Outgoing (own messages) must never mark the target as unread — that is
    # a copy of my own statement, not incoming content.
    effective_mark_unread = rule.mark_target_unread and not is_outgoing_message(message)
    target_message_ids = await copy_message_to_targets(
        client,
        message,
        rule.target_chat_ids,
        name_prefix=rule.name_prefix,
        mark_target_unread=effective_mark_unread,
    )
    if target_message_ids:
        content_type, body = get_editable_content(message)
        if rule.store_edits and content_type and body:
            forward_index.set_record(
                message.chat.id,
                message.id,
                target_message_ids,
                edit_history=[build_rendered_body(message, body, rule.name_prefix)],
                edit_mode=content_type,
                last_body=body,
            )
        else:
            forward_index.set_record(
                message.chat.id,
                message.id,
                target_message_ids,
                edit_mode=content_type,
                last_body=body,
            )
    else:
        forward_index.remove_record(message.chat.id, message.id)


async def resend_message_with_caption_override(
    client: Client,
    message: Message,
    target_chat_id: int,
    caption: str,
) -> Message | None:
    """Re-sends a source message with a custom caption."""
    media_type = detect_media_type(message)
    if not media_type:
        if message.text:
            try:
                return await client.send_message(target_chat_id, caption)
            except Exception:
                logging.debug(
                    "Re-send with caption override for message %s to %s failed.",
                    message.id,
                    target_chat_id,
                    exc_info=True,
                )
        return None

    path: Any = None
    try:
        path = await message.download()
        return await send_media_from_path(client, target_chat_id, media_type, str(path), caption)
    except Exception:
        logging.debug(
            "Re-send with caption override for message %s to %s failed.",
            message.id,
            target_chat_id,
            exc_info=True,
        )
        return None
    finally:
        safe_unlink(path)


async def edit_forwarded_message(
    client: Client,
    message: Message,
    rule: ListenerRule,
    record: ForwardRecord,
    forward_index: ForwardIndex,
) -> None:
    """Edits forwarded messages in place when possible."""
    content_type, body = get_editable_content(message)
    if not content_type or not body:
        await copy_or_replace_message(client, message, rule, forward_index)
        return
    if record.edit_mode == content_type and record.last_body == body:
        return

    rendered_body = build_rendered_body(message, body, rule.name_prefix)
    edit_history: list[str] | None = None
    if rule.store_edits:
        edit_history = list(record.edit_history) if record.edit_history else [rendered_body]
        if record.edit_history:
            edit_history.append(f"edited to: {body}")
        rendered_text = "\n".join(edit_history)
    else:
        rendered_text = rendered_body

    target_message_ids = dict(record.target_message_ids)

    for target_chat_id, target_message_id in list(target_message_ids.items()):
        try:
            if content_type == "text":
                await client.edit_message_text(target_chat_id, target_message_id, rendered_text)
            else:
                await client.edit_message_caption(target_chat_id, target_message_id, rendered_text)
            continue
        except Exception:
            logging.debug(
                "Edit for message %s in chat %s failed, re-sending.",
                target_message_id,
                target_chat_id,
                exc_info=True,
            )

        try:
            await client.delete_messages(target_chat_id, target_message_id)
        except Exception:
            logging.debug(
                "Old target message %s in chat %s could not be deleted.",
                target_message_id,
                target_chat_id,
                exc_info=True,
            )

        if content_type == "text":
            replacement_message = await send_text_message(client, target_chat_id, rendered_text)
            replacement_message_id = int(replacement_message.id) if replacement_message is not None else None
        else:
            replacement_message = await resend_message_with_caption_override(client, message, target_chat_id, rendered_text)
            replacement_message_id = int(replacement_message.id) if replacement_message is not None else None
        if replacement_message_id is not None:
            target_message_ids[target_chat_id] = replacement_message_id
            if rule.mark_target_unread and not is_outgoing_message(message):
                await mark_chat_unread_safely(client, target_chat_id)
        else:
            target_message_ids.pop(target_chat_id, None)

    if target_message_ids:
        forward_index.set_record(
            message.chat.id,
            message.id,
            target_message_ids,
            edit_history=edit_history,
            edit_mode=content_type,
            last_body=body,
        )
    else:
        forward_index.remove_record(message.chat.id, message.id)
