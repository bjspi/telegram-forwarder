"""Command, callback-query and text handlers for the control bot.

Every handler is gated to a single owner user id via ``filters.user`` (commands
and text) and the owner-only callback filter, so only the configured owner can
view or change anything. All config mutations go through the shared
``BotConfigStore``, so the userbot picks them up on its next message; keep-alive
changes also rebuild the scheduler jobs immediately.

Adding a listener or keep-alive is a small multi-step flow (see :mod:`.state`):
the owner either picks a chat from their most recently active chats (fetched
live through the userbot) or types a chat id / @username, which is verified by
resolving it; keep-alive times are verified as ``HH:MM:SS``.
"""

from __future__ import annotations
import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from pyrogram import Client, filters
from pyrogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from ..connection.chats import get_recent_chats, resolve_chat_ref
from ..core.config_store import BotConfigStore
from ..core.models import ChatRef
from ..services.keepalive import parse_hms, sync_keepalive_jobs
from ..settings import CONTROL_BOT_OWNER_ID
from .keyboards import (
    cancel_keyboard,
    keepalives_keyboard,
    listener_detail_keyboard,
    listeners_keyboard,
    main_menu_keyboard,
    recent_chats_keyboard,
)
from .state import (
    KIND_KEEPALIVE,
    KIND_LISTENER,
    STEP_CHAT,
    STEP_SOURCE,
    STEP_TARGET,
    STEP_TIME,
    PendingAction,
)
from .views import (
    ADD_KEEPALIVE_CHAT_TEXT,
    ADD_KEEPALIVE_TIME_TEXT,
    ADD_LISTENER_SOURCE_TEXT,
    ADD_LISTENER_TARGET_TEXT,
    MAIN_MENU_TEXT,
    TYPE_CHAT_TEXT,
    render_keepalives_text,
    render_listener_detail_text,
    render_listeners_text,
    render_overview_text,
)

Screen = tuple[str, InlineKeyboardMarkup]
RECENT_CHATS_LIMIT = 20


def register_control_handlers(
    bot: Client,
    store: BotConfigStore,
    scheduler: AsyncIOScheduler,
    userbot: Client,
) -> None:
    """Registers the owner-only command, callback and text handlers on the bot."""
    owner = filters.user(CONTROL_BOT_OWNER_ID)
    pending: dict[int, PendingAction] = {}

    def listener_detail(source_chat_id: int) -> Screen | None:
        """Renders one listener's detail screen, or None if it no longer exists."""
        rule = store.get_listener(source_chat_id)
        if rule is None:
            return None
        keepalive = store.get_keepalive(source_chat_id)
        return render_listener_detail_text(rule, keepalive), listener_detail_keyboard(rule, keepalive)

    def apply_chat_choice(user_id: int, action: PendingAction, chosen: ChatRef) -> Screen | None:
        """Advances a pending flow with a chosen/verified chat and returns the next screen."""
        if action.kind == KIND_LISTENER and action.step == STEP_SOURCE:
            action.source = chosen
            action.step = STEP_TARGET
            action.awaiting_text = False
            return ADD_LISTENER_TARGET_TEXT, recent_chats_keyboard(action.recent)

        if action.kind == KIND_LISTENER and action.step == STEP_TARGET and action.source is not None:
            store.upsert_listener(source_chat=action.source, target_chats=[chosen])
            pending.pop(user_id, None)
            return listener_detail(action.source.chat_id)

        if action.kind == KIND_KEEPALIVE and action.step == STEP_CHAT:
            action.source = chosen
            action.step = STEP_TIME
            action.awaiting_text = True
            return ADD_KEEPALIVE_TIME_TEXT, cancel_keyboard()

        pending.pop(user_id, None)
        return None

    async def route(data: str, user_id: int) -> Screen | None:
        """Maps callback data to a rendered screen, applying any config change first."""
        if data in ("nop", ""):
            return None
        if data == "home":
            pending.pop(user_id, None)
            return MAIN_MENU_TEXT, main_menu_keyboard()
        if data == "ov":
            return render_overview_text(store), main_menu_keyboard()
        if data == "lst":
            return render_listeners_text(store), listeners_keyboard(store)
        if data == "kal":
            return render_keepalives_text(store), keepalives_keyboard(store)

        if data == "ladd":
            recent = await get_recent_chats(userbot, RECENT_CHATS_LIMIT)
            pending[user_id] = PendingAction(kind=KIND_LISTENER, step=STEP_SOURCE, recent=recent)
            return ADD_LISTENER_SOURCE_TEXT, recent_chats_keyboard(recent)
        if data == "kadd":
            recent = await get_recent_chats(userbot, RECENT_CHATS_LIMIT)
            pending[user_id] = PendingAction(kind=KIND_KEEPALIVE, step=STEP_CHAT, recent=recent)
            return ADD_KEEPALIVE_CHAT_TEXT, recent_chats_keyboard(recent)

        if data == "cancel":
            action = pending.pop(user_id, None)
            if action is not None and action.kind == KIND_KEEPALIVE:
                return render_keepalives_text(store), keepalives_keyboard(store)
            return render_listeners_text(store), listeners_keyboard(store)

        if data == "typ":
            action = pending.get(user_id)
            if action is None:
                return None
            action.awaiting_text = True
            return TYPE_CHAT_TEXT, cancel_keyboard()

        parts = data.split("|")
        head = parts[0]

        if head == "pick":
            action = pending.get(user_id)
            index = int(parts[1])
            if action is None or index >= len(action.recent):
                return None
            return apply_chat_choice(user_id, action, action.recent[index])

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

    @bot.on_message(filters.command(["start", "menu"]) & owner)
    async def open_menu(_: Client, message: Message) -> None:
        """Opens the main control menu and clears any half-finished flow."""
        try:
            pending.pop(message.from_user.id, None)
            await message.reply_text(MAIN_MENU_TEXT, reply_markup=main_menu_keyboard())
        except Exception:
            logging.exception("Control bot: failed to open the main menu.")

    @bot.on_callback_query(owner)
    async def on_callback(_: Client, callback_query: CallbackQuery) -> None:
        """Routes an inline-button tap to the matching screen or config change."""
        data = str(callback_query.data or "")
        try:
            screen = await route(data, callback_query.from_user.id)
            await callback_query.answer()
            if screen is not None:
                text, markup = screen
                await callback_query.edit_message_text(text, reply_markup=markup)
        except Exception:
            logging.exception("Control bot: error handling callback %r.", data)
            try:
                await callback_query.answer("Something went wrong.", show_alert=True)
            except Exception:
                logging.debug("Control bot: could not answer callback after error.", exc_info=True)

    @bot.on_message(filters.text & owner)
    async def on_text(_: Client, message: Message) -> None:
        """Consumes free-text input for a pending flow (chat id/@username or time)."""
        text = (message.text or "").strip()
        if text.startswith("/"):
            return
        action = pending.get(message.from_user.id)
        if action is None or not action.awaiting_text:
            return
        try:
            if action.kind == KIND_KEEPALIVE and action.step == STEP_TIME and action.source is not None:
                try:
                    parse_hms(text)
                except ValueError as exc:
                    await message.reply_text(f"⚠️ {exc}\nSend the time as HH:MM:SS, or /menu to cancel.")
                    return
                store.upsert_keepalive(action.source.chat_id, text)
                sync_keepalive_jobs(scheduler, store, userbot)
                pending.pop(message.from_user.id, None)
                await message.reply_text(render_keepalives_text(store), reply_markup=keepalives_keyboard(store))
                return

            try:
                chat_ref = await resolve_chat_ref(userbot, text)
            except ValueError as exc:
                await message.reply_text(f"⚠️ {exc}")
                return
            except Exception:
                logging.warning("Control bot: could not resolve %r.", text, exc_info=True)
                await message.reply_text(
                    "⚠️ Couldn't find that chat. Send a valid id or @username, or /menu to cancel."
                )
                return

            action.awaiting_text = False
            screen = apply_chat_choice(message.from_user.id, action, chat_ref)
            if screen is None:
                await message.reply_text("That target no longer exists. /menu to start over.")
                return
            reply_text, markup = screen
            await message.reply_text(reply_text, reply_markup=markup)
        except Exception:
            logging.exception("Control bot: error handling text input.")
            await message.reply_text("Something went wrong. Send /menu to start over.")
