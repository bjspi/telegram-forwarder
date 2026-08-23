"""Active health check with hard exit for supervisor restarts."""

from __future__ import annotations
import asyncio
import logging
import os
import time
from pyrogram import Client
from pyrogram.errors import RPCError
from ..core.config_store import BotConfigStore
from ..settings import HEALTH_CHECK_TIMEOUT_SECONDS, MAX_UNHEALTHY_DURATION_SECONDS
from .wan import wan_is_up


async def health_check_tick(client: Client, store: BotConfigStore) -> None:
    """Pings Telegram via get_me() and forces a process exit on prolonged outages.

    pyrogram retries connection failures internally without raising, so a network
    outage on the host keeps the event loop alive while the bot is effectively
    dead. We track the last successful round-trip; a failed check triggers the
    WAN probe (only then — no extra traffic while healthy) to classify the
    outage. A WAN outage pauses the give-up clock: a restart cannot bring the
    line back, and pyrogram reconnects on its own once it returns. Only when
    Telegram stays unreachable for MAX_UNHEALTHY_DURATION_SECONDS while the
    internet demonstrably works do we exit hard and let the process supervisor
    (e.g. supervisord) restart us — the stuck-session case a restart repairs.
    """
    try:
        await asyncio.wait_for(client.get_me(), timeout=HEALTH_CHECK_TIMEOUT_SECONDS)
        store.last_healthy_at = time.monotonic()
        store.telegram_down_wan_up_since = None
        logging.debug("Health check OK.")
        return
    except TimeoutError:
        logging.warning("Health check: get_me() timed out after %ss.", HEALTH_CHECK_TIMEOUT_SECONDS)
    except (OSError, RPCError):
        logging.warning("Health check: network/API error.", exc_info=True)
    except Exception:
        logging.exception("Health check: unexpected error.")

    now = time.monotonic()
    elapsed_seconds = now - store.last_healthy_at
    if not await wan_is_up():
        store.telegram_down_wan_up_since = None
        logging.warning(
            "Health check: WAN outage (probe endpoints unreachable, Telegram down for %.0fs) - "
            "waiting it out, a restart cannot fix a dead line.",
            elapsed_seconds,
        )
        return
    if store.telegram_down_wan_up_since is None:
        store.telegram_down_wan_up_since = now
    telegram_only_seconds = now - store.telegram_down_wan_up_since
    if telegram_only_seconds >= MAX_UNHEALTHY_DURATION_SECONDS:
        logging.critical(
            "Internet up, but Telegram unreachable for %.0fs (limit %ss). "
            "Exiting process for supervisor restart.",
            telegram_only_seconds,
            MAX_UNHEALTHY_DURATION_SECONDS,
        )
        # Hard exit: SystemExit/raise would be swallowed by pyrogram-internal
        # tasks. os._exit skips atexit hooks, which is fine because the
        # supervisor restarts us anyway.
        logging.shutdown()
        os._exit(1)
