"""Text renderers for the control bot's menu screens."""

from __future__ import annotations
import time
from ..core.config_store import BotConfigStore
from ..core.models import ChatRef, KeepAliveRule, ListenerRule
from ..ui.formatting import format_chat_ref, format_keepalive_delta_text

MAIN_MENU_TEXT = (
    "🎛 **Telegram Forwarder — Control**\n\n"
    "Pick a section to view or change the live configuration."
)

# Prompts for the multi-step add flows.
ADD_LISTENER_SOURCE_TEXT = (
    "➕ **New listener** — step 1 of 2\n\n"
    "Pick the **source** chat (where messages are copied *from*), "
    "or type its id / @username."
)
ADD_LISTENER_TARGET_TEXT = (
    "➕ **New listener** — step 2 of 2\n\n"
    "Pick the **target** chat (where messages are copied *to*), "
    "or type its id / @username."
)
ADD_TARGET_TEXT = (
    "➕ **Add target**\n\n"
    "Pick the additional **target** chat, or type its id / @username."
)
ADD_KEEPALIVE_CHAT_TEXT = (
    "➕ **New keep-alive** — step 1 of 2\n\n"
    "Pick the chat for the daily ping, or type its id / @username."
)
ADD_KEEPALIVE_TIME_TEXT = (
    "➕ **New keep-alive** — step 2 of 2\n\n"
    "Send the time of day as **HH:MM:SS** (e.g. `08:00:00`)."
)
TYPE_CHAT_TEXT = "✍️ Send me the chat **id** (e.g. `-1001234567890`) or a **@username**."


def _state_chip(active: bool) -> str:
    """Returns the shared running/paused chip for text renderings."""
    return "▶️" if active else "⏸"


def _format_target_line(rule: ListenerRule, target: ChatRef) -> str:
    """Formats one target bullet with its pause state."""
    return f"• {_state_chip(rule.is_target_active(target.chat_id))} `{format_chat_ref(target)}`"


def _direction_text(rule: ListenerRule) -> str:
    """Returns a human word for the copy direction of a listener."""
    if rule.copy_incoming and rule.copy_outgoing:
        return "both"
    if rule.copy_incoming:
        return "incoming"
    if rule.copy_outgoing:
        return "outgoing"
    return "none"


def _format_age(seconds: float) -> str:
    """Formats a duration in seconds as a compact age like `45s` or `12m`."""
    if seconds < 90:
        return f"{seconds:.0f}s"
    minutes = seconds / 60
    if minutes < 90:
        return f"{minutes:.0f}m"
    return f"{minutes / 60:.1f}h"


def render_overview_text(store: BotConfigStore) -> str:
    """Builds the status screen: health plus a compact rule summary."""
    listeners = store.all_listeners()
    keepalives = store.all_keepalives()
    paused_listeners = sum(1 for rule in listeners if not rule.enabled)
    paused_keepalives = sum(1 for rule in keepalives if not rule.enabled)
    health_age = _format_age(time.monotonic() - store.last_healthy_at)

    lines = [
        "📊 **Telegram Forwarder — Status**",
        "",
        f"🩺 Telegram: last successful check {health_age} ago",
        f"📡 Listeners: {len(listeners) - paused_listeners} active · {paused_listeners} paused",
        f"⏰ Keep-alives: {len(keepalives) - paused_keepalives} on · {paused_keepalives} off",
    ]

    if listeners:
        lines += ["", "📡 **Listeners**"]
        for rule in listeners:
            source = format_chat_ref(ChatRef(rule.source_chat_id, rule.source_chat_name))
            paused_targets = len(rule.disabled_target_ids)
            target_note = f"{len(rule.target_chats)} target{'s' if len(rule.target_chats) != 1 else ''}"
            if paused_targets:
                target_note += f" ({paused_targets} paused)"
            lines.append(
                f"{_state_chip(rule.enabled)} `{source}` → {target_note} · {_direction_text(rule)}"
                + (f" · view-once {rule.view_once}" if rule.view_once != "off" else "")
            )

    if keepalives:
        lines += ["", "⏰ **Keep-alives**"]
        for keepalive in keepalives:
            chat = format_chat_ref(ChatRef(keepalive.chat_id, keepalive.chat_name))
            delta = format_keepalive_delta_text(keepalive.time_of_day_delta)
            lines.append(
                f"{'✅' if keepalive.enabled else '▫️'} `{chat}` @ {keepalive.time_of_day}{delta}"
            )

    return "\n".join(lines)


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
    return (
        f"⏰ **Keep-alives** ({count})\n\n"
        "Tap one to toggle it, 🕒 to change its time, 🗑 to delete it."
    )


def render_listener_detail_text(rule: ListenerRule, keepalive: KeepAliveRule | None) -> str:
    """Builds the per-listener detail screen."""
    source = format_chat_ref(ChatRef(rule.source_chat_id, rule.source_chat_name))
    keepalive_text = (
        f"{'enabled' if keepalive.enabled else 'disabled'} @ {keepalive.time_of_day}"
        if keepalive is not None
        else "not configured"
    )
    target_lines = "\n".join(_format_target_line(rule, target) for target in rule.target_chats) or "• none"
    return (
        f"📡 **Listener** `{source}`\n\n"
        f"**State:** {_state_chip(rule.enabled)} {'active' if rule.enabled else 'paused'}\n"
        f"**Direction:** {_direction_text(rule)} · **View-once:** {rule.view_once}\n"
        f"**Name prefix:** {'on' if rule.name_prefix else 'off'} · "
        f"**Store edits:** {'on' if rule.store_edits else 'off'} · "
        f"**Mark unread:** {'on' if rule.mark_target_unread else 'off'}\n"
        f"**Keep-alive:** {keepalive_text}\n\n"
        f"🎯 **Targets ({len(rule.target_chats)})**\n{target_lines}"
    )


def render_listener_targets_text(rule: ListenerRule) -> str:
    """Builds the per-target management screen."""
    source = format_chat_ref(ChatRef(rule.source_chat_id, rule.source_chat_name))
    return (
        f"🎯 **Targets** of `{source}`\n\n"
        "Tap a target to pause or resume it — paused targets keep their "
        "settings and can be resumed any time. 🗑 removes a target for good."
    )


def render_delete_listener_text(rule: ListenerRule) -> str:
    """Builds the confirm screen for deleting a whole listener."""
    source = format_chat_ref(ChatRef(rule.source_chat_id, rule.source_chat_name))
    return (
        f"🗑 **Delete listener** `{source}`?\n\n"
        f"This removes the listener and all {len(rule.target_chats)} of its "
        "target connections. Messages already forwarded stay untouched.\n"
        "To stop forwarding temporarily, pause the listener instead."
    )


def render_remove_target_text(rule: ListenerRule, target: ChatRef) -> str:
    """Builds the confirm screen for removing one target."""
    source = format_chat_ref(ChatRef(rule.source_chat_id, rule.source_chat_name))
    return (
        f"🗑 **Remove target** `{format_chat_ref(target)}` from `{source}`?\n\n"
        "The connection is removed for good. To stop it temporarily, "
        "pause the target instead."
    )


def render_delete_keepalive_text(keepalive: KeepAliveRule) -> str:
    """Builds the confirm screen for deleting a keep-alive."""
    chat = format_chat_ref(ChatRef(keepalive.chat_id, keepalive.chat_name))
    return (
        f"🗑 **Delete keep-alive** for `{chat}` (@ {keepalive.time_of_day})?\n\n"
        "The daily ping is removed for good. To skip it temporarily, "
        "toggle it off instead."
    )


def render_edit_keepalive_time_text(keepalive: KeepAliveRule) -> str:
    """Builds the prompt for changing a keep-alive's time."""
    chat = format_chat_ref(ChatRef(keepalive.chat_id, keepalive.chat_name))
    return (
        f"🕒 **New time** for `{chat}` (currently {keepalive.time_of_day})\n\n"
        "Send the time of day as **HH:MM:SS** (e.g. `08:00:00`)."
    )
