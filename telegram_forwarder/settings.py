"""Central configuration: .env loading, credentials and all tuning constants.

Credentials come exclusively from the environment (.env). No fallbacks in
source, so live credentials can never be committed by accident. Request an
API id and hash at: https://my.telegram.org/auth?to=apps
"""

from __future__ import annotations
import os
from pathlib import Path
from typing import Any
import pyrogram
from dotenv import load_dotenv

# Load .env next to the script before any credentials are read.
load_dotenv()

ACCOUNT = os.environ.get("TG_ACCOUNT", "")
PHONE_NR = os.environ.get("TG_PHONE_NR", "")
API_ID_RAW = os.environ.get("TG_API_ID", "")
API_HASH = os.environ.get("TG_API_HASH", "")


def _require_credentials() -> int:
    """Validates that all Telegram credentials are present and returns API_ID as int."""
    missing = [
        name for name, value in (
            ("TG_ACCOUNT", ACCOUNT),
            ("TG_PHONE_NR", PHONE_NR),
            ("TG_API_ID", API_ID_RAW),
            ("TG_API_HASH", API_HASH),
        )
        if not value
    ]
    if missing:
        raise RuntimeError(
            "Missing environment variables: " + ", ".join(missing)
            + ". Set them in .env or export them before starting."
        )
    try:
        return int(API_ID_RAW)
    except ValueError as exc:
        raise RuntimeError(f"TG_API_ID is not a number: {API_ID_RAW!r}") from exc


API_ID = _require_credentials()


def _env_str(name: str, default: str) -> str:
    """Returns env-var value, falling back to default if unset or empty."""
    return os.environ.get(name, "") or default


def _env_int(name: str, default: int) -> int:
    """Returns env-var value parsed as int, falling back to default if unset/empty."""
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer, was: {raw!r}") from exc


def _env_bool(name: str, default: bool) -> bool:
    """Returns env-var value parsed as bool, falling back to default if unset/empty."""
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    raise RuntimeError(f"{name} must be true/false, was: {raw!r}")


# ~~~~~~ ALL TUNING VALUES COME FROM .env ~~~~~~ #
# The defaults below only apply when the env variable is missing. The
# canonical source of configuration is .env / .env.example.

# General
TIMEZONE = _env_str("TIMEZONE", "Europe/Berlin")
LOGS_DIR = Path(_env_str("LOGS_DIR", "logs"))
SESSION_DIR = Path("session")
LOG_RETENTION_DAYS = max(0, _env_int("LOG_RETENTION_DAYS", 10))
CONFIG_PATH = Path(_env_str("CONFIG_PATH", "bot_config.json"))

# Chat commands: false = register no slash-command handlers at all; the bot is
# then purely passive and configured exclusively through bot_config.json.
ENABLE_CHAT_COMMANDS = _env_bool("ENABLE_CHAT_COMMANDS", True)

# Optionally restrict slash commands to a single chat id (e.g. a private group
# containing only yourself). 0 = commands work in every chat. Get the id with
# /show_id. Only relevant when ENABLE_CHAT_COMMANDS=true.
COMMANDS_CHAT_ID = _env_int("COMMANDS_CHAT_ID", 0)

# Optional control bot: a separate BotFather bot that exposes an inline-button
# menu to toggle listener/keep-alive settings. Empty token = disabled. It only
# talks to CONTROL_BOT_OWNER_ID (your own numeric user id) and refuses to start
# without one, so nobody else can control the userbot.
CONTROL_BOT_TOKEN = _env_str("CONTROL_BOT_TOKEN", "")
CONTROL_BOT_OWNER_ID = _env_int("CONTROL_BOT_OWNER_ID", 0)

# Auto-delete for slash-command replies
DELETE_DELAY_SECONDS = _env_int("DELETE_DELAY_SECONDS", 5)
LIST_CHATS_DELETE_DELAY_SECONDS = _env_int("LIST_CHATS_DELETE_DELAY_SECONDS", 20)
CONFIG_ALL_DELETE_DELAY_SECONDS = _env_int("CONFIG_ALL_DELETE_DELAY_SECONDS", 30)
SCHEDULED_REPLY_DELETE_DELAY_SECONDS = 30
SCHEDULED_REPLY_NOTICE = "(AutoDelete in 30s)"

# Hot-reload and forward-index TTL
CONFIG_RELOAD_INTERVAL_SECONDS = _env_int("CONFIG_RELOAD_INTERVAL_SECONDS", 5)
FORWARD_RECORD_TTL_SECONDS = _env_int("FORWARD_RECORD_TTL_SECONDS", 24 * 60 * 60)

# Keep-alive
DEFAULT_KEEPALIVE_TIME = _env_str("DEFAULT_KEEPALIVE_TIME", "08:00:00")
KEEPALIVE_DUPLICATE_WINDOW_SECONDS = _env_int("KEEPALIVE_DUPLICATE_WINDOW_SECONDS", 300)

# Reconnect pause after a network/RPC error in the app.start() main loop
NETWORK_RETRY_DELAY_SECONDS = _env_int("NETWORK_RETRY_DELAY_SECONDS", 10)

# Active health check: on "No route to host" pyrogram retry-loops internally
# and never raises an exception outward. Without external pinging the bot
# hangs silently. We periodically call get_me() with a timeout; if that stays
# unsuccessful for too long, we exit hard so the supervisor restarts us.
HEALTH_CHECK_INTERVAL_SECONDS = _env_int("HEALTH_CHECK_INTERVAL_SECONDS", 60)
HEALTH_CHECK_TIMEOUT_SECONDS = _env_int("HEALTH_CHECK_TIMEOUT_SECONDS", 30)
MAX_UNHEALTHY_DURATION_SECONDS = _env_int("MAX_UNHEALTHY_DURATION_SECONDS", 15 * 60)

# Default keep-alive text (with Pyrogram version) — internal only, overridable
# per chat via bot_config.json; not in .env because it is dynamic.
DEFAULT_KEEPALIVE_MESSAGE = f"// Daily Keep Alive Ping ☀️ // Pyrogram Version {pyrogram.__version__}"

# Default exclusions (filter the bot's own slash commands out of the forward
# path). Managed per listener in bot_config.json, therefore not in .env.
DEFAULT_EXCLUSION_PATTERNS: list[str] = [
    "/help*",
    "/show_id*",
    "/copy*",
    "/stop*",
    "/keepalive*",
]

DEFAULT_CONFIG: dict[str, Any] = {
    "settings": {
        "timezone": TIMEZONE,
        "delete_delay_seconds": DELETE_DELAY_SECONDS,
        "config_reload_interval_seconds": CONFIG_RELOAD_INTERVAL_SECONDS,
        "default_keepalive_time": DEFAULT_KEEPALIVE_TIME,
        "default_keepalive_message": DEFAULT_KEEPALIVE_MESSAGE,
    },
    "listeners": [],
    "keepalives": [],
}
