"""High-level setup of the optional control bot."""

from __future__ import annotations
import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from pyrogram import Client
from pyrogram.types import BotCommand
from ..core.config_store import BotConfigStore
from ..settings import CONTROL_BOT_OWNER_ID, CONTROL_BOT_TOKEN
from .client import create_control_bot_client
from .handlers import register_control_handlers


def create_control_bot(
    store: BotConfigStore,
    scheduler: AsyncIOScheduler,
    userbot: Client,
) -> Client | None:
    """Builds and wires the control bot, or returns None when it is not configured.

    Requires both CONTROL_BOT_TOKEN and CONTROL_BOT_OWNER_ID: without an owner
    the bot would accept commands from anyone, so it refuses to start.
    """
    if not CONTROL_BOT_TOKEN:
        return None
    if not CONTROL_BOT_OWNER_ID:
        logging.warning(
            "CONTROL_BOT_TOKEN is set but CONTROL_BOT_OWNER_ID is 0; "
            "refusing to start the control bot without an owner."
        )
        return None

    bot = create_control_bot_client()
    register_control_handlers(bot, store, scheduler, userbot)
    return bot


async def configure_bot_commands(bot: Client) -> None:
    """Registers the bot's slash-command menu (the BotFather-style command list)."""
    await bot.set_bot_commands(
        [
            BotCommand("menu", "Open the control menu"),
            BotCommand("status", "Show health and rule status"),
            BotCommand("start", "Open the control menu"),
        ]
    )
