"""Command and callback-query handlers for the control bot.

Every handler is gated to a single owner user id via ``filters.user`` (commands)
and an explicit id check (callbacks), so only the configured owner can view or
change anything. All config mutations go through the shared ``BotConfigStore``,
so the userbot picks them up on its next message; keep-alive changes also
rebuild the scheduler jobs immediately.
"""

from __future__ import annotations
import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from pyrogram import Client, filters
from pyrogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from ..core.config_store import BotConfigStore
from ..services.keepalive import sync_keepalive_jobs
from ..settings import CONTROL_BOT_OWNER_ID
from .keyboards import (
    keepalives_keyboard,
    listener_detail_keyboard,
    listeners_keyboard,
    main_menu_keyboard,
)
from .views import (
    MAIN_MENU_TEXT,
    render_keepalives_text,
    render_listener_detail_text,
    render_listeners_text,
    render_overview_text,
)


def register_control_handlers(
    bot: Client,
    store: BotConfigStore,
    scheduler: AsyncIOScheduler,
    userbot: Client,
) -> None:
    """Registers the owner-only command and callback handlers on the bot client."""
    owner = filters.user(CONTROL_BOT_OWNER_ID)

    def listener_detail(source_chat_id: int) -> tuple[str, InlineKeyboardMarkup] | None:
        """Renders one listener's detail screen, or None if it no longer exists."""
        rule = store.get_listener(source_chat_id)
        if rule is None:
            return None
        keepalive = store.get_keepalive(source_chat_id)
        return render_listener_detail_text(rule, keepalive), listener_detail_keyboard(rule, keepalive)

    @bot.on_message(filters.command(["start", "menu"]) & owner)
    async def open_menu(_: Client, message: Message) -> None:
        """Opens the main control menu."""
        try:
            await message.reply_text(MAIN_MENU_TEXT, reply_markup=main_menu_keyboard())
        except Exception:
            logging.exception("Control bot: failed to open the main menu.")

    @bot.on_callback_query(owner)
    async def on_callback(_: Client, callback_query: CallbackQuery) -> None:
        """Routes an inline-button tap to the matching screen or config change."""
        data = str(callback_query.data or "")
        try:
            screen = await _route(data)
            if screen is None:
                await callback_query.answer()
                return
            text, markup = screen
            await callback_query.answer()
            await callback_query.edit_message_text(text, reply_markup=markup)
        except Exception:
            logging.exception("Control bot: error handling callback %r.", data)
            try:
                await callback_query.answer("Something went wrong.", show_alert=True)
            except Exception:
                logging.debug("Control bot: could not answer callback after error.", exc_info=True)

    async def _route(data: str) -> tuple[str, InlineKeyboardMarkup] | None:
        """Maps callback data to a rendered screen, applying any config change first."""
        if data in ("nop", ""):
            return None
        if data == "home":
            return MAIN_MENU_TEXT, main_menu_keyboard()
        if data == "ov":
            return render_overview_text(store), main_menu_keyboard()
        if data == "lst":
            return render_listeners_text(store), listeners_keyboard(store)
        if data == "kal":
            return render_keepalives_text(store), keepalives_keyboard(store)

        parts = data.split("|")
        head = parts[0]

        if head == "l":
            return listener_detail(int(parts[1]))

        if head == "ls":
            source_chat_id, option, value = int(parts[1]), parts[2], parts[3]
            store.set_listener_option(source_chat_id, option, value if option == "view_once" else value == "1")
            return listener_detail(source_chat_id)

        if head == "ld":
            source_chat_id, direction = int(parts[1]), parts[2]
            store.set_listener_direction(
                source_chat_id,
                copy_incoming=direction in ("in", "both"),
                copy_outgoing=direction in ("out", "both"),
            )
            return listener_detail(source_chat_id)

        if head == "k":
            chat_id, return_to = int(parts[1]), (parts[2] if len(parts) > 2 else "kal")
            store.toggle_keepalive_enabled(chat_id)
            sync_keepalive_jobs(scheduler, store, userbot)
            if return_to == "l":
                return listener_detail(chat_id)
            return render_keepalives_text(store), keepalives_keyboard(store)

        return None
