"""Command replies with auto-delete, including the scheduled-message special path."""

from __future__ import annotations
import asyncio
import logging
from datetime import UTC, datetime, timedelta
from pyrogram.types import LinkPreviewOptions, Message
from ..settings import SCHEDULED_REPLY_DELETE_DELAY_SECONDS, SCHEDULED_REPLY_NOTICE


async def delete_message_after_delay(message: Message, delay_seconds: int) -> None:
    """Deletes a message after a short delay and ignores permission errors."""
    await asyncio.sleep(delay_seconds)
    try:
        await message.delete()
    except Exception:
        logging.debug("Message %s could not be deleted.", getattr(message, "id", "unknown"))


def compute_scheduled_reply_date(message: Message, delay_seconds: int) -> datetime:
    """Computes a safe schedule_date for a reply to a scheduled command.

    Uses the command's own schedule_date so both messages line up side-by-side
    in the scheduled view. Falls back to ~30 days in the future when the
    command's time is too close to fire before our delete delay can run, so
    the reply never reaches the chat partner even if cleanup is missed. Pyrogram
    forks may expose scheduled message dates as timezone-aware datetimes, so all
    comparisons use the same timezone type as the incoming date.
    """
    raw_date = getattr(message, "date", None)
    if raw_date is None:
        now = datetime.now(tz=UTC)
        return now + timedelta(days=30)

    if raw_date.tzinfo is not None and raw_date.utcoffset() is not None:
        now = datetime.now(raw_date.tzinfo)
        candidate = raw_date
    else:
        now = datetime.now()
        candidate = raw_date

    fallback = now + timedelta(days=30)
    if candidate <= now + timedelta(seconds=delay_seconds + 10):
        return fallback
    return candidate


async def send_and_delete_message(message: Message, text: str, delay_seconds: int) -> None:
    """Sends a command response and schedules both messages for deletion.

    When the command itself was scheduled (Pyrogram-fork ``message.scheduled``
    is true), the reply is sent as a scheduled message with the command's own
    ``schedule_date`` so both appear next to each other in the scheduled view.
    Scheduled-view replies stay visible for 30 seconds and get an explicit
    AutoDelete notice; normal chat replies keep their per-command delay.
    """
    if getattr(message, "scheduled", False):
        delay_seconds = SCHEDULED_REPLY_DELETE_DELAY_SECONDS
        client = message._client
        reply = await client.send_message(
            chat_id=message.chat.id,
            text=f"{SCHEDULED_REPLY_NOTICE}\n\n{text}",
            schedule_date=compute_scheduled_reply_date(message, delay_seconds),
            link_preview_options=LinkPreviewOptions(is_disabled=True),
        )
    else:
        reply = await message.reply_text(text, link_preview_options=LinkPreviewOptions(is_disabled=True))
    asyncio.create_task(delete_message_after_delay(reply, delay_seconds))
    asyncio.create_task(delete_message_after_delay(message, delay_seconds))
