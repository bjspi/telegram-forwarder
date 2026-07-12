"""JSON-backed config store with hot-reload and transparent migration."""

from __future__ import annotations
import json
import time
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any
from ..settings import (
    CONFIG_RELOAD_INTERVAL_SECONDS,
    DEFAULT_CONFIG,
    DEFAULT_EXCLUSION_PATTERNS,
    DEFAULT_KEEPALIVE_MESSAGE,
    DEFAULT_KEEPALIVE_TIME,
    DELETE_DELAY_SECONDS,
    TIMEZONE,
)
from .models import ChatRef, KeepAliveRule, ListenerRule


class BotConfigStore:
    """Persists and manages runtime configuration in a JSON file."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._listeners: dict[int, ListenerRule] = {}
        self._keepalives: dict[int, KeepAliveRule] = {}
        self._settings: dict[str, Any] = {}
        self._mtime_ns: int | None = None
        self.keepalive_last_sent_at: dict[int, datetime] = {}
        # time.monotonic() value of the last successful health check. Set to
        # "now" on startup and refreshed after every successful app.start().
        self.last_healthy_at: float = time.monotonic()

    @property
    def timezone(self) -> str:
        """Returns the configured timezone."""
        return str(self._settings.get("timezone", TIMEZONE))

    @property
    def delete_delay_seconds(self) -> int:
        """Returns the configured command delete delay."""
        return int(self._settings.get("delete_delay_seconds", DELETE_DELAY_SECONDS))

    @property
    def reload_interval_seconds(self) -> int:
        """Returns the configured config reload interval."""
        return int(self._settings.get("config_reload_interval_seconds", CONFIG_RELOAD_INTERVAL_SECONDS))

    @property
    def default_keepalive_message(self) -> str:
        """Returns the configured default keep-alive text."""
        return str(self._settings.get("default_keepalive_message", DEFAULT_KEEPALIVE_MESSAGE))

    @property
    def default_keepalive_time(self) -> str:
        """Returns the configured default keep-alive time."""
        return str(self._settings.get("default_keepalive_time", DEFAULT_KEEPALIVE_TIME))

    @property
    def default_exclusion_patterns(self) -> list[str]:
        """Returns default exclusions for new listeners."""
        return list(DEFAULT_EXCLUSION_PATTERNS)

    def ensure_exists(self) -> None:
        """Creates a default config file when absent."""
        if not self.path.exists():
            self.path.write_text(json.dumps(DEFAULT_CONFIG, indent=2), encoding="utf-8")

    def load(self) -> None:
        """Loads configuration from disk."""
        self.ensure_exists()
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        self._settings = dict(DEFAULT_CONFIG["settings"])
        self._settings.update(payload.get("settings", {}))
        self._settings.pop("default_exclusion_patterns", None)

        listeners = payload.get("listeners", [])
        migration_needed = False
        for item in listeners:
            if "copy_incoming" not in item:
                item["copy_incoming"] = True
                migration_needed = True
            if "copy_outgoing" not in item:
                item["copy_outgoing"] = True
                migration_needed = True
            if "store_edits" not in item:
                item["store_edits"] = False
                migration_needed = True
            if "mark_target_unread" not in item:
                item["mark_target_unread"] = False
                migration_needed = True
            if "view_once_only" not in item:
                item["view_once_only"] = False
                migration_needed = True
            if "exclusions" in item:
                original_exclusions = list(item.get("exclusions", []))
                filtered_exclusions = [
                    str(pattern)
                    for pattern in original_exclusions
                    if str(pattern) not in DEFAULT_EXCLUSION_PATTERNS
                ]
                if not filtered_exclusions:
                    item.pop("exclusions", None)
                else:
                    item["exclusions"] = filtered_exclusions
                if filtered_exclusions != original_exclusions:
                    migration_needed = True

        self._listeners = {
            int(item["source_chat_id"]): ListenerRule(
                source_chat_id=int(item["source_chat_id"]),
                source_chat_name=str(item.get("source_chat_name", "")),
                target_chats=self._normalize_target_chats(item),
                exclusions=[str(pattern) for pattern in item.get("exclusions", []) if str(pattern) not in DEFAULT_EXCLUSION_PATTERNS],
                name_prefix=bool(item.get("name_prefix", False)),
                copy_incoming=bool(item.get("copy_incoming", True)),
                copy_outgoing=bool(item.get("copy_outgoing", True)),
                store_edits=bool(item.get("store_edits", False)),
                mark_target_unread=bool(item.get("mark_target_unread", False)),
                view_once_only=bool(item.get("view_once_only", False)),
            )
            for item in listeners
        }

        keepalives = payload.get("keepalives", [])
        keepalive_migration_needed = False
        for item in keepalives:
            if "chat_name" not in item:
                item["chat_name"] = ""
                keepalive_migration_needed = True
            if "enabled" not in item:
                item["enabled"] = True
                keepalive_migration_needed = True
            if "time_of_day_delta" not in item:
                item["time_of_day_delta"] = 0.0
                keepalive_migration_needed = True
        self._keepalives = {
            int(item["chat_id"]): KeepAliveRule(
                chat_id=int(item["chat_id"]),
                time_of_day=str(item["time_of_day"]),
                message_text=self._normalize_keepalive_message_text(
                    item.get("message_text", self.default_keepalive_message)
                ),
                enabled=bool(item.get("enabled", True)),
                time_of_day_delta=self._normalize_keepalive_delta(item.get("time_of_day_delta", 0.0)),
                chat_name=str(item.get("chat_name", "")),
            )
            for item in keepalives
        }

        self._mtime_ns = self.path.stat().st_mtime_ns

        if migration_needed or keepalive_migration_needed:
            self.save()

    def reload_if_changed(self) -> bool:
        """Reloads the config when the file has changed on disk."""
        self.ensure_exists()
        current_mtime_ns = self.path.stat().st_mtime_ns
        if self._mtime_ns is None or current_mtime_ns != self._mtime_ns:
            previous_settings = dict(self._settings)
            previous_listeners = dict(self._listeners)
            previous_keepalives = dict(self._keepalives)
            previous_mtime_ns = self._mtime_ns
            try:
                self.load()
            except Exception:
                self._settings = previous_settings
                self._listeners = previous_listeners
                self._keepalives = previous_keepalives
                self._mtime_ns = previous_mtime_ns
                raise
            return True
        return False

    def save(self) -> None:
        """Writes the current configuration back to disk."""
        payload = {
            "settings": self._settings,
            "listeners": [asdict(rule) for rule in self._listeners.values()],
            "keepalives": [asdict(rule) for rule in self._keepalives.values()],
        }
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        self._mtime_ns = self.path.stat().st_mtime_ns

    def get_listener(self, source_chat_id: int) -> ListenerRule | None:
        """Returns the configured listener for a source chat."""
        return self._listeners.get(source_chat_id)

    def all_listeners(self) -> list[ListenerRule]:
        """Returns all active listener rules."""
        return list(self._listeners.values())

    def get_keepalive(self, chat_id: int) -> KeepAliveRule | None:
        """Returns the configured keep-alive rule for a chat."""
        return self._keepalives.get(chat_id)

    def upsert_listener(
        self,
        source_chat: ChatRef,
        target_chats: list[ChatRef],
        name_prefix: bool | None = None,
        view_once_only: bool | None = None,
    ) -> tuple[ListenerRule, list[ChatRef]]:
        """Creates or extends a listener for one source chat without duplicating targets."""
        existing = self._listeners.get(source_chat.chat_id)
        exclusions = list(existing.exclusions) if existing else []
        existing_target_chats = existing.target_chats if existing else []
        merged_target_chats = list(existing_target_chats)
        merged_target_chat_ids = {target.chat_id for target in merged_target_chats}
        added_target_chats: list[ChatRef] = []

        for target_chat in target_chats:
            if target_chat.chat_id in merged_target_chat_ids:
                continue
            merged_target_chats.append(target_chat)
            merged_target_chat_ids.add(target_chat.chat_id)
            added_target_chats.append(target_chat)

        rule = ListenerRule(
            source_chat_id=source_chat.chat_id,
            source_chat_name=source_chat.chat_name or (existing.source_chat_name if existing else ""),
            target_chats=merged_target_chats,
            exclusions=exclusions,
            name_prefix=(existing.name_prefix if existing else False) if name_prefix is None else name_prefix,
            copy_incoming=existing.copy_incoming if existing else True,
            copy_outgoing=existing.copy_outgoing if existing else True,
            store_edits=existing.store_edits if existing else False,
            mark_target_unread=existing.mark_target_unread if existing else False,
            view_once_only=(existing.view_once_only if existing else False) if view_once_only is None else view_once_only,
        )
        self._listeners[source_chat.chat_id] = rule
        self.save()
        return rule, added_target_chats

    def remove_listener(self, source_chat_id: int) -> ListenerRule | None:
        """Removes a listener for one source chat."""
        rule = self._listeners.pop(source_chat_id, None)
        if rule is not None:
            self.save()
        return rule

    def remove_listener_targets(self, source_chat_id: int, target_chat_ids: list[int]) -> tuple[ListenerRule | None, list[ChatRef]]:
        """Removes selected targets from one source listener and deletes the listener if empty."""
        rule = self._listeners.get(source_chat_id)
        if rule is None:
            return None, []

        removal_set = set(target_chat_ids)
        removed_targets = [target for target in rule.target_chats if target.chat_id in removal_set]
        if not removed_targets:
            return rule, []

        remaining_targets = [target for target in rule.target_chats if target.chat_id not in removal_set]
        if remaining_targets:
            rule.target_chats = remaining_targets
            self._listeners[source_chat_id] = rule
        else:
            self._listeners.pop(source_chat_id, None)

        self.save()
        return rule, removed_targets

    def all_keepalives(self) -> list[KeepAliveRule]:
        """Returns all keep-alive rules."""
        return list(self._keepalives.values())

    def upsert_keepalive(self, chat_id: int, time_of_day: str) -> KeepAliveRule:
        """Creates or updates the keep-alive rule for one chat."""
        existing_rule = self._keepalives.get(chat_id)
        rule = KeepAliveRule(
            chat_id=chat_id,
            time_of_day=time_of_day,
            message_text=existing_rule.message_text if existing_rule else self.default_keepalive_message,
            enabled=existing_rule.enabled if existing_rule else True,
            time_of_day_delta=existing_rule.time_of_day_delta if existing_rule else 0.0,
            chat_name=existing_rule.chat_name if existing_rule else "",
        )
        self._keepalives[chat_id] = rule
        self.save()
        return rule

    def toggle_keepalive_enabled(self, chat_id: int) -> KeepAliveRule | None:
        """Toggles the enabled state of one keep-alive rule."""
        rule = self._keepalives.get(chat_id)
        if rule is None:
            return None
        rule.enabled = not rule.enabled
        self.save()
        return rule

    def update_keepalive_chat_name(self, chat_id: int, chat_name: str) -> bool:
        """Updates the stored chat name for one keep-alive rule."""
        rule = self._keepalives.get(chat_id)
        if rule is None or not chat_name or rule.chat_name == chat_name:
            return False
        rule.chat_name = chat_name
        self.save()
        return True

    def remove_keepalive(self, chat_id: int) -> KeepAliveRule | None:
        """Removes a keep-alive rule for one chat."""
        rule = self._keepalives.pop(chat_id, None)
        if rule is not None:
            self.save()
        return rule

    def update_listener_chat_names(
        self,
        source_chat_id: int,
        source_chat_name: str | None = None,
        target_chat_names: dict[int, str] | None = None,
    ) -> bool:
        """Updates stored chat names for one listener and persists on change."""
        rule = self._listeners.get(source_chat_id)
        if rule is None:
            return False

        changed = False
        if source_chat_name and source_chat_name != rule.source_chat_name:
            rule.source_chat_name = source_chat_name
            changed = True

        if target_chat_names:
            for target_chat in rule.target_chats:
                resolved_name = target_chat_names.get(target_chat.chat_id, "")
                if resolved_name and resolved_name != target_chat.chat_name:
                    target_chat.chat_name = resolved_name
                    changed = True

        if changed:
            self.save()
        return changed

    def _normalize_target_chats(self, item: dict[str, Any]) -> list[ChatRef]:
        """Normalizes legacy or new config target fields into chat references."""
        if "target_chats" in item:
            raw_target_chats = item["target_chats"]
            if not isinstance(raw_target_chats, list):
                raise ValueError("target_chats must be a list.")
            return [self._normalize_chat_ref(raw_target_chat) for raw_target_chat in raw_target_chats]

        if "target_chat_ids" in item:
            raw_target_chat_ids = item["target_chat_ids"]
            if not isinstance(raw_target_chat_ids, list):
                raise ValueError("target_chat_ids must be a list.")
            return [ChatRef(chat_id=int(target_chat_id), chat_name="") for target_chat_id in raw_target_chat_ids]

        if "target_chat_id" in item:
            return [ChatRef(chat_id=int(item["target_chat_id"]), chat_name="")]

        raise ValueError("Listener requires target_chats, target_chat_ids or target_chat_id.")

    def _normalize_chat_ref(self, item: Any) -> ChatRef:
        """Normalizes one config value into a chat reference."""
        if isinstance(item, dict):
            return ChatRef(
                chat_id=int(item["chat_id"]),
                chat_name=str(item.get("chat_name", "")),
            )
        return ChatRef(chat_id=int(item), chat_name="")

    def _normalize_keepalive_message_text(self, value: Any) -> str | list[str]:
        """Normalizes keep-alive message text into a string or a list of strings."""
        if isinstance(value, list):
            choices = [str(item).strip() for item in value if str(item).strip()]
            return choices or self.default_keepalive_message

        text = str(value).strip()
        return text or self.default_keepalive_message

    def _normalize_keepalive_delta(self, value: Any) -> float:
        """Normalizes keep-alive delta into a non-negative float."""
        try:
            delta = float(value)
        except (TypeError, ValueError):
            return 0.0
        return max(0.0, delta)
