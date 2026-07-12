"""Composition root: wires client, scheduler and handlers together and runs the loop.

Reconnection has two layers:

1. Outer loop in :func:`main`: wraps ``app.start()`` / ``idle()`` in
   ``while True``, catches network/RPC errors, sleeps
   ``NETWORK_RETRY_DELAY_SECONDS``, retries. Only kicks in when
   ``app.start()`` itself raises — not when pyrogram retry-loops internally.
2. Health-check job: an active ping mechanism that hard-exits when pyrogram
   is stuck internally (see :mod:`telegram_forwarder.connection.health`).
"""

from __future__ import annotations
import asyncio
import logging
import time
import traceback
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from pyrogram import idle
from pyrogram.errors import RPCError
from .connection.client import create_client, patch_pyrogram_dialog_compat
from .connection.health import health_check_tick
from .control_bot.service import configure_bot_commands, create_control_bot
from .core.config_store import BotConfigStore
from .core.forward_index import ForwardIndex
from .handlers.commands import register_command_handlers
from .handlers.listeners import register_forward_handlers
from .logging_setup import configure_logging, ensure_runtime_directories
from .services.enrichment import enrich_keepalive_chat_names, enrich_listener_chat_names
from .services.keepalive import sync_keepalive_jobs
from .settings import (
    COMMANDS_CHAT_ID,
    CONFIG_PATH,
    ENABLE_CHAT_COMMANDS,
    HEALTH_CHECK_INTERVAL_SECONDS,
    LOGS_DIR,
    NETWORK_RETRY_DELAY_SECONDS,
)
from .ui.formatting import get_status_text


async def main() -> None:
    """Starts the userbot and keeps it running until interrupted."""
    ensure_runtime_directories()
    configure_logging()
    patch_pyrogram_dialog_compat()

    store = BotConfigStore(CONFIG_PATH)
    store.load()

    app = create_client()

    scheduler = AsyncIOScheduler()
    sync_keepalive_jobs(scheduler, store, app)

    def schedule_config_reload(interval_seconds: int) -> None:
        """(Re-)registers the config-reload job with the requested interval."""
        scheduler.add_job(
            reload_config_if_needed,
            "interval",
            seconds=interval_seconds,
            id="config-reload",
            replace_existing=True,
            max_instances=1,
        )

    async def reload_config_if_needed() -> None:
        """Refreshes runtime config and keep-alive jobs from disk."""
        try:
            previous_interval = store.reload_interval_seconds
            if store.reload_if_changed():
                sync_keepalive_jobs(scheduler, store, app)
                await enrich_listener_chat_names(app, store)
                await enrich_keepalive_chat_names(app, store)
                if store.reload_interval_seconds != previous_interval:
                    schedule_config_reload(store.reload_interval_seconds)
                logging.debug("Configuration reloaded: %s", get_status_text(store))
        except Exception:
            logging.exception("Configuration could not be reloaded.")

    schedule_config_reload(store.reload_interval_seconds)

    scheduler.add_job(
        health_check_tick,
        "interval",
        seconds=HEALTH_CHECK_INTERVAL_SECONDS,
        id="health-check",
        replace_existing=True,
        max_instances=1,
        args=[app, store],
    )

    # Order matters: Pyrogram dispatches to the first matching handler per
    # group. Commands must be registered before the catch-all listener.
    if ENABLE_CHAT_COMMANDS:
        register_command_handlers(app, store, scheduler)
        if COMMANDS_CHAT_ID:
            logging.info("Chat commands enabled, restricted to chat %s.", COMMANDS_CHAT_ID)
        else:
            logging.info("Chat commands enabled in all chats.")
    else:
        logging.info(
            "Chat commands disabled (ENABLE_CHAT_COMMANDS=false). "
            "Configuration only via bot_config.json."
        )
    forward_index = ForwardIndex()
    register_forward_handlers(app, store, forward_index)

    control_bot = create_control_bot(store, scheduler, app)

    while True:
        try:
            await app.start()
            store.last_healthy_at = time.monotonic()
            logging.info("Userbot started.")
            await enrich_listener_chat_names(app, store)
            await enrich_keepalive_chat_names(app, store)
            logging.info(get_status_text(store))

            if not scheduler.running:
                scheduler.start()
                logging.info("Scheduler started. Timezone: %s", store.timezone)

            if control_bot is not None and not control_bot.is_connected:
                try:
                    await control_bot.start()
                    await configure_bot_commands(control_bot)
                    logging.info("Control bot started.")
                except Exception:
                    # A bad token must not take the userbot down — disable and go on.
                    logging.exception("Control bot failed to start; continuing without it.")
                    control_bot = None

            await idle()
            break
        except KeyboardInterrupt:
            raise
        except (OSError, TimeoutError, RPCError):
            logging.warning(
                "Network/API problem in the main loop. Retrying connection in %s seconds.",
                NETWORK_RETRY_DELAY_SECONDS,
                exc_info=True,
            )
            try:
                if app.is_connected:
                    await app.stop()
            except Exception:
                logging.exception("Client could not be stopped cleanly after a network error.")
            await asyncio.sleep(NETWORK_RETRY_DELAY_SECONDS)
        except Exception:
            logging.exception("Fatal error during startup or operation.")
            error_path = LOGS_DIR / f"log_{datetime.now():%Y-%m-%d_%H-%M-%S}.txt"
            error_path.write_text(traceback.format_exc(), encoding="utf-8")
            break
        finally:
            if control_bot is not None and control_bot.is_connected:
                try:
                    await control_bot.stop()
                except Exception:
                    logging.exception("Control bot could not be stopped during cleanup.")
            if app.is_connected:
                try:
                    await app.stop()
                except Exception:
                    logging.exception("Client could not be stopped during cleanup.")

    logging.info("Stopping userbot...")
    if scheduler.running:
        scheduler.shutdown()
        logging.info("Scheduler stopped.")


def run() -> None:
    """Synchronous console entry point (used by the installed `telegram-forwarder` script)."""
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nStopped by user (Ctrl+C).")
