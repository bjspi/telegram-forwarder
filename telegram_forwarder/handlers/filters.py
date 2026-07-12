"""Custom Pyrogram filters for scheduled messages and command gating.

Pyrogram dispatches UpdateNewScheduledMessage through the regular @on_message
hooks with message.scheduled=True. Commands should be callable from the
scheduled view, but media forwarders must NOT trigger there — otherwise e.g.
scheduled voice messages would be processed twice (once when planned, once
when actually sent). filters.scheduled/from_scheduled do not exist in every
Pyrogram variant, so we defensively build our own predicates.
"""

from __future__ import annotations
from pyrogram import filters
from ..settings import COMMANDS_CHAT_ID

SCHEDULED_FILTER = filters.create(
    lambda _, __, m: bool(getattr(m, "scheduled", False)),
    name="ScheduledFilter",
)
FROM_SCHEDULED_FILTER = filters.create(
    lambda _, __, m: bool(getattr(m, "from_scheduled", False)),
    name="FromScheduledFilter",
)

# Command handlers should fire for normal and for scheduled messages, but —
# defense in depth — not a second time in case the scheduled message ever
# leaks through to the chat partner. filters.me gates all commands to the
# own account (userbot rule).
CMD_BASE = filters.me & ~FROM_SCHEDULED_FILTER

# Optionally scope every command to a single chat (e.g. a private group with
# just yourself), so slash commands only work there and stay out of every
# other conversation. COMMANDS_CHAT_ID=0 keeps the default (commands anywhere).
if COMMANDS_CHAT_ID:
    CMD_BASE = CMD_BASE & filters.chat(COMMANDS_CHAT_ID)
