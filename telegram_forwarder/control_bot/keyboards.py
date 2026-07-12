"""Inline-keyboard builders for the control bot menu.

Callback-data scheme (``|``-separated, well under Telegram's 64-byte limit):

- ``home``                      — main menu
- ``ov``                        — overview
- ``lst``                       — listeners list
- ``kal``                       — keep-alives list
- ``l|<cid>``                   — open one listener's detail view
- ``ls|<cid>|<option>|<value>`` — set a listener option (view_once / flags)
- ``ld|<cid>|<in|out|both>``    — set a listener's copy direction
- ``k|<cid>|<ret>``             — toggle one keep-alive; ``ret`` is where to
                                  return afterwards (``kal`` list or ``l`` detail)
- ``nop``                       — inert label button
"""

from __future__ import annotations
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from ..core.config_store import BotConfigStore
from ..core.models import ChatRef, KeepAliveRule, ListenerRule


def _mark(active: bool, label: str) -> str:
    """Prefixes a button label with a check mark when the option is active."""
    return f"✅ {label}" if active else f"▫️ {label}"


def _btn(text: str, data: str) -> InlineKeyboardButton:
    """Shorthand for a callback button."""
    return InlineKeyboardButton(text, callback_data=data)


def main_menu_keyboard() -> InlineKeyboardMarkup:
    """Builds the top-level menu keyboard."""
    return InlineKeyboardMarkup(
        [
            [_btn("📊 Overview", "ov")],
            [_btn("📡 Listeners", "lst"), _btn("⏰ Keep-alives", "kal")],
        ]
    )


def listeners_keyboard(store: BotConfigStore) -> InlineKeyboardMarkup:
    """Builds a keyboard listing every configured listener as a button."""
    rows: list[list[InlineKeyboardButton]] = []
    for rule in store.all_listeners():
        label = rule.source_chat_name or str(rule.source_chat_id)
        rows.append([_btn(f"📡 {label}", f"l|{rule.source_chat_id}")])
    if not rows:
        rows.append([_btn("No listeners configured", "nop")])
    rows.append([_btn("➕ Add listener", "ladd")])
    rows.append([_btn("⬅️ Back", "home")])
    return InlineKeyboardMarkup(rows)


def keepalives_keyboard(store: BotConfigStore) -> InlineKeyboardMarkup:
    """Builds a keyboard listing every keep-alive; tapping one toggles it."""
    rows: list[list[InlineKeyboardButton]] = []
    for rule in store.all_keepalives():
        name = rule.chat_name or str(rule.chat_id)
        rows.append([_btn(_mark(rule.enabled, f"{name} @ {rule.time_of_day}"), f"k|{rule.chat_id}|kal")])
    if not rows:
        rows.append([_btn("No keep-alives configured", "nop")])
    rows.append([_btn("➕ Add keep-alive", "kadd")])
    rows.append([_btn("⬅️ Back", "home")])
    return InlineKeyboardMarkup(rows)


def recent_chats_keyboard(recent: list[ChatRef]) -> InlineKeyboardMarkup:
    """Builds a picker of recently active chats plus a type/cancel fallback.

    Buttons carry the chat's index in ``recent`` (``pick|<index>``) rather than
    its id, keeping callback data short; the handler maps it back via the
    pending action's stored list.
    """
    rows: list[list[InlineKeyboardButton]] = []
    for index, chat in enumerate(recent):
        label = chat.chat_name or str(chat.chat_id)
        rows.append([_btn(f"{index + 1}. {label}", f"pick|{index}")])
    rows.append([_btn("✍️ Type id / @username", "typ")])
    rows.append([_btn("✖️ Cancel", "cancel")])
    return InlineKeyboardMarkup(rows)


def cancel_keyboard() -> InlineKeyboardMarkup:
    """Builds a single-button cancel keyboard for text-input steps."""
    return InlineKeyboardMarkup([[_btn("✖️ Cancel", "cancel")]])


def listener_detail_keyboard(rule: ListenerRule, keepalive: KeepAliveRule | None) -> InlineKeyboardMarkup:
    """Builds the per-listener settings keyboard with live toggle states."""
    cid = rule.source_chat_id
    both = rule.copy_incoming and rule.copy_outgoing
    incoming_only = rule.copy_incoming and not rule.copy_outgoing
    outgoing_only = rule.copy_outgoing and not rule.copy_incoming

    rows: list[list[InlineKeyboardButton]] = [
        [_btn("— Direction —", "nop")],
        [
            _btn(_mark(incoming_only, "Incoming"), f"ld|{cid}|in"),
            _btn(_mark(outgoing_only, "Outgoing"), f"ld|{cid}|out"),
            _btn(_mark(both, "Both"), f"ld|{cid}|both"),
        ],
        [_btn("— View-once media —", "nop")],
        [
            _btn(_mark(rule.view_once == "off", "Off"), f"ls|{cid}|view_once|off"),
            _btn(_mark(rule.view_once == "on", "On"), f"ls|{cid}|view_once|on"),
            _btn(_mark(rule.view_once == "only", "Only"), f"ls|{cid}|view_once|only"),
        ],
        [_btn("— Options —", "nop")],
        [
            _btn(_mark(rule.name_prefix, "Name prefix"), f"ls|{cid}|name_prefix|{0 if rule.name_prefix else 1}"),
            _btn(_mark(rule.store_edits, "Store edits"), f"ls|{cid}|store_edits|{0 if rule.store_edits else 1}"),
        ],
        [_btn(_mark(rule.mark_target_unread, "Mark target unread"), f"ls|{cid}|mark_target_unread|{0 if rule.mark_target_unread else 1}")],
    ]
    if keepalive is not None:
        rows.append([_btn(_mark(keepalive.enabled, f"Keep-alive @ {keepalive.time_of_day}"), f"k|{cid}|l")])
    rows.append([_btn("⬅️ Back", "lst")])
    return InlineKeyboardMarkup(rows)
