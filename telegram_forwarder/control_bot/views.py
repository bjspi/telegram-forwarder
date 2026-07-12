"""Text renderers for the control bot's menu screens."""

from __future__ import annotations
from ..core.config_store import BotConfigStore
from ..core.models import ChatRef, KeepAliveRule, ListenerRule
from ..ui.formatting import (
    build_config_text_for_rules,
    build_keepalive_config_text,
    format_chat_ref,
    format_chat_refs,
)

MAIN_MENU_TEXT = (
    "🎛 **Telegram Forwarder — Control**\n\n"
    "Pick a section to view or change the live configuration."
)


def render_overview_text(store: BotConfigStore) -> str:
    """Builds the full overview across listeners and keep-alives."""
    return (
        f"{build_config_text_for_rules('📡 Listeners', store.all_listeners())}\n\n"
        f"{build_keepalive_config_text('⏰ Keep-alives', store.all_keepalives())}"
    )


def render_listeners_text(store: BotConfigStore) -> str:
    """Builds the listeners-list screen header."""
    count = len(store.all_listeners())
    if not count:
        return "📡 **Listeners**\n\nNo listeners configured yet."
    return f"📡 **Listeners** ({count})\n\nPick one to change its settings."


def render_keepalives_text(store: BotConfigStore) -> str:
    """Builds the keep-alives-list screen header."""
    count = len(store.all_keepalives())
    if not count:
        return "⏰ **Keep-alives**\n\nNo keep-alives configured yet."
    return f"⏰ **Keep-alives** ({count})\n\nTap one to enable or disable it."


def render_listener_detail_text(rule: ListenerRule, keepalive: KeepAliveRule | None) -> str:
    """Builds the per-listener detail screen."""
    source = format_chat_ref(ChatRef(rule.source_chat_id, rule.source_chat_name))
    direction = (
        "both" if rule.copy_incoming and rule.copy_outgoing
        else "incoming" if rule.copy_incoming
        else "outgoing" if rule.copy_outgoing
        else "none"
    )
    keepalive_text = (
        f"{'enabled' if keepalive.enabled else 'disabled'} @ {keepalive.time_of_day}"
        if keepalive is not None
        else "not configured"
    )
    return (
        f"📡 **Listener**\n\n"
        f"**Source:** `{source}`\n"
        f"**Targets:** `{format_chat_refs(rule.target_chats)}`\n\n"
        f"**Direction:** {direction}\n"
        f"**View-once:** {rule.view_once}\n"
        f"**Name prefix:** {'on' if rule.name_prefix else 'off'}\n"
        f"**Store edits:** {'on' if rule.store_edits else 'off'}\n"
        f"**Mark target unread:** {'on' if rule.mark_target_unread else 'off'}\n"
        f"**Keep-alive:** {keepalive_text}"
    )
