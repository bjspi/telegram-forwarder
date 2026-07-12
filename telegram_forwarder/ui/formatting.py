"""Formatting of listener, keep-alive and help texts for command replies."""

from __future__ import annotations
from ..core.config_store import BotConfigStore
from ..core.models import ChatRef, KeepAliveRule, ListenerRule


def format_chat_ref(chat_ref: ChatRef) -> str:
    """Formats one chat reference for display in logs and command replies."""
    if chat_ref.chat_name:
        return f"{chat_ref.chat_name} ({chat_ref.chat_id})"
    return str(chat_ref.chat_id)


def format_chat_refs(chat_refs: list[ChatRef]) -> str:
    """Formats multiple chat references for display."""
    return ", ".join(format_chat_ref(chat_ref) for chat_ref in chat_refs)


def format_keepalive_message_text(message_text: str | list[str]) -> str:
    """Formats keep-alive message text for config output."""
    if isinstance(message_text, list):
        choices = [item for item in (str(entry).strip() for entry in message_text) if item]
        if not choices:
            return "[]"
        return f"[{', '.join(choices)}]"
    return str(message_text)


def format_keepalive_delta_text(time_of_day_delta: float) -> str:
    """Formats the keep-alive delta for display."""
    delta = max(0.0, float(time_of_day_delta))
    if delta == 0.0:
        return ""
    formatted = f"{delta:.3f}".rstrip("0").rstrip(".")
    return f" ±{formatted}h"


def format_keepalive_enabled_text(enabled: bool) -> str:
    """Formats the enabled state for keep-alive output."""
    return "" if enabled else " [paused]"


def format_listener_line(rule: ListenerRule) -> str:
    """Formats one listener rule for config output."""
    source_ref = ChatRef(rule.source_chat_id, rule.source_chat_name)
    prefix_text = "on" if rule.name_prefix else "off"
    direction_text = f"in={int(rule.copy_incoming)}, out={int(rule.copy_outgoing)}"
    edit_text = f"store_edits={int(rule.store_edits)}"
    unread_text = f"mark_target_unread={int(rule.mark_target_unread)}"
    view_once_text = f"view_once_only={int(rule.view_once_only)}"
    return (
        f"{format_chat_ref(source_ref)} -> {format_chat_refs(rule.target_chats)} "
        f"| name_prefix={prefix_text} | {direction_text} | {edit_text} | {unread_text} | {view_once_text}"
    )


def build_config_text_for_rules(title: str, rules: list[ListenerRule]) -> str:
    """Builds a readable config summary for a set of listener rules."""
    if not rules:
        return f"{title}\nNo listeners found."
    lines: list[str] = [title]
    for index, rule in enumerate(rules, start=1):
        lines.append(f"{index}. {format_listener_line(rule)}")
    return "\n".join(lines)


def build_keepalive_config_text(title: str, keepalives: list[KeepAliveRule]) -> str:
    """Builds a readable config summary for keep-alive rules."""
    if not keepalives:
        return f"{title}\nNo keep-alives found."
    lines: list[str] = [title]
    for index, rule in enumerate(keepalives, start=1):
        lines.append(
            f"{index}. {format_chat_ref(ChatRef(rule.chat_id, rule.chat_name))}"
            f"@{rule.time_of_day}{format_keepalive_delta_text(rule.time_of_day_delta)}"
            f"{format_keepalive_enabled_text(rule.enabled)}:"
            f"{format_keepalive_message_text(rule.message_text)}"
        )
    return "\n".join(lines)


def get_status_text(store: BotConfigStore) -> str:
    """Returns a compact status summary for configured listeners and keep-alives."""
    listeners = store.all_listeners()
    keepalives = store.all_keepalives()
    listener_text = "none" if not listeners else ", ".join(
        f"{format_chat_ref(ChatRef(rule.source_chat_id, rule.source_chat_name))}->{format_chat_refs(rule.target_chats)}"
        f"{' [name_prefix]' if rule.name_prefix else ''}"
        f"{' [mark_target_unread]' if rule.mark_target_unread else ''}"
        f"{' [view_once_only]' if rule.view_once_only else ''}"
        for rule in listeners
    )
    keepalive_text = "none" if not keepalives else ", ".join(
        f"{format_chat_ref(ChatRef(rule.chat_id, rule.chat_name))}@{rule.time_of_day}{format_keepalive_delta_text(rule.time_of_day_delta)}"
        f"{format_keepalive_enabled_text(rule.enabled)}:"
        f"{format_keepalive_message_text(rule.message_text)}"
        for rule in keepalives
    )
    return f"Listener: {listener_text} | KeepAlive: {keepalive_text}"


def build_help_text(store: BotConfigStore) -> str:
    """Returns the user-facing command help."""
    return (
        "**Commands**\n"
        "`/helpf`\n"
        "Shows this help.\n\n"
        "`/show_id`\n"
        "Shows the current chat id.\n\n"
        "`/list_chats`\n"
        "Shows the 20 most recent chats with type, name and chat id. Output is deleted after 20 seconds.\n\n"
        "`/config`\n"
        "Shows the targets for the current chat.\n\n"
        "`/config <source>`\n"
        "Shows all targets for a specific source.\n\n"
        "`/config all`\n"
        "Shows all configured source-target connections.\n\n"
        "`/copy <target> [more...] [--name-prefix] [--view-once-only]`\n"
        "Uses the current chat as source and adds one or more targets.\n\n"
        "`/copy <source> <target> [more...] [--name-prefix] [--view-once-only]`\n"
        "Creates a rule from any chat.\n\n"
        "`/stop`\n"
        "Removes all targets for the current chat.\n\n"
        "`/stop <source>`\n"
        "Removes all targets for this source.\n\n"
        "`/stop <source> <target>`\n"
        "Removes exactly one source-to-target connection.\n\n"
        "`/keepalive <HH:MM:SS>`\n"
        "Sets a daily keep-alive for the current chat.\n\n"
        "`/keepalive`\n"
        "Sets the keep-alive for the current chat to the default time from the JSON.\n\n"
        "`/keepalive pause`\n"
        "Toggles an existing keep-alive for the current chat on or off.\n\n"
        "`/keepalive off`\n"
        "Removes the keep-alive for the current chat.\n\n"
        "**Notes**\n"
        "- Only your own slash commands are processed.\n"
        "- Other users' `/xxxx` messages trigger nothing and are not forwarded.\n"
        "- All slash commands are deleted automatically.\n"
        "- Listeners can carry `source_chat_name`, `target_chats` and `name_prefix` in the JSON.\n"
        "- Listeners can also carry `copy_incoming` and `copy_outgoing` in the JSON.\n"
        "- Listeners can also carry `store_edits` in the JSON.\n"
        "- Listeners can also carry `mark_target_unread` in the JSON.\n"
        "- `name_prefix` is off by default and can be enabled with `--name-prefix`.\n"
        "- `copy_incoming` and `copy_outgoing` both default to `true`.\n"
        "- `store_edits` defaults to `false`.\n"
        "- `mark_target_unread` defaults to `false`.\n"
        "- `view_once_only` defaults to `false`; when `true`, ONLY self-destructing view-once media (photos, videos, voice/video notes) are forwarded — everything else is skipped. Toggle with `--view-once-only` / `--no-view-once-only`.\n"
        "- View-once media is archived as regular (persistent) media in the target chat.\n"
        "- `keepalives[].message_text` can be a string or a list of strings.\n"
        "- `keepalives[].enabled` defaults to `true`.\n"
        "- If it is a list, a random entry is used for each keep-alive.\n"
        "- `keepalives[].message_text` optionally supports `{timestamp}`, `{date}` and `{time}` as placeholders.\n"
        "- `keepalives[].time_of_day_delta` is optional and randomly shifts the time per day by plus/minus X hours.\n"
        "- Exclusions are applied to text or caption via `fnmatch`.\n"
        f"- Default exclusions: `{', '.join(store.default_exclusion_patterns)}`"
    )
