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


async def health_check_tick(client: Client, store: BotConfigStore) -> None:
    """Pings Telegram via get_me() and forces a process exit on prolonged outages.

    pyrogram retries connection failures internally without raising, so a network
    outage on the host keeps the event loop alive while the bot is effectively
    dead. We track the last successful round-trip; if more than
    MAX_UNHEALTHY_DURATION_SECONDS pass without one, we exit hard and let the
    process supervisor (e.g. supervisord) restart us.
    """
    try:
        await asyncio.wait_for(client.get_me(), timeout=HEALTH_CHECK_TIMEOUT_SECONDS)
        store.last_healthy_at = time.monotonic()
        logging.debug("Health check OK.")
        return
    except TimeoutError:
        logging.warning("Health check: get_me() timed out after %ss.", HEALTH_CHECK_TIMEOUT_SECONDS)
    except (OSError, RPCError):
        logging.warning("Health check: network/API error.", exc_info=True)
    except Exception:
        logging.exception("Health check: unexpected error.")

    elapsed_seconds = time.monotonic() - store.last_healthy_at
    if elapsed_seconds >= MAX_UNHEALTHY_DURATION_SECONDS:
        logging.critical(
            "Connection not restored for %.0fs (limit %ss). Exiting process for supervisor restart.",
            elapsed_seconds,
            MAX_UNHEALTHY_DURATION_SECONDS,
        )
        # Hard exit: SystemExit/raise would be swallowed by pyrogram-internal
        # tasks. os._exit skips atexit hooks, which is fine because the
        # supervisor restarts us anyway.
        logging.shutdown()
        os._exit(1)
