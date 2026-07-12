#!/usr/bin/env python3
"""Entry point of the Telegram Forwarder userbot.

The whole application lives in the ``telegram_forwarder`` package next to
this script (flat layout, like yt-dlp or HTTPie), so a plain ``python bot.py``
works from a checkout without installing anything — while ``pip install .`` or
``pipx install`` provide a proper ``telegram-forwarder`` command. The file
name ``bot.py`` is fixed — supervisor configs and external callers depend on it.
"""

from __future__ import annotations
import asyncio
import sys
import traceback
from datetime import datetime
from pathlib import Path


def _write_critical_error_log() -> None:
    """Persists the current traceback to a crash file for post-mortem analysis."""
    try:
        from telegram_forwarder.settings import LOGS_DIR
        logs_dir = LOGS_DIR
    except Exception:
        # settings itself may be the crash cause (e.g. missing .env) —
        # fall back to the default log directory in that case.
        logs_dir = Path("logs")
    logs_dir.mkdir(parents=True, exist_ok=True)
    error_path = logs_dir / f"critical_error_{datetime.now():%Y-%m-%d_%H-%M-%S}.txt"
    error_path.write_text(traceback.format_exc(), encoding="utf-8")


if __name__ == "__main__":
    try:
        # Lazy import: credential errors from telegram_forwarder.settings should
        # land in the except blocks below instead of as a bare import traceback.
        from telegram_forwarder.app import main

        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nStopped by user (Ctrl+C).")
    except RuntimeError as exc:
        # Configuration errors (missing/broken .env values) — print clearly.
        print(f"Startup aborted: {exc}", file=sys.stderr)
        sys.exit(1)
    except Exception:
        _write_critical_error_log()
        print("Critical error before the main function could start.", file=sys.stderr)
        sys.exit(1)
