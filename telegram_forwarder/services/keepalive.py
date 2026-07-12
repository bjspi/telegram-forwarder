"""Keep-alive sending and scheduling.

Keep-alives use one-shot ``date`` jobs that reschedule themselves in their
``finally`` block — not cron jobs. The per-day random offset
(``time_of_day_delta``) needs a fresh runtime computation every day;
``compute_next_keepalive_run_from_day`` guarantees the next run is strictly in
the future. ``sync_keepalive_jobs`` is the single entry point for rebuilding
the schedule from config; never call ``add_job`` directly from a command handler.
"""

from __future__ import annotations
import logging
import random
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from apscheduler.jobstores.base import JobLookupError
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from pyrogram import Client
from pyrogram.errors import RPCError
from ..core.config_store import BotConfigStore
from ..core.models import KeepAliveRule
from ..settings import DEFAULT_KEEPALIVE_MESSAGE, KEEPALIVE_DUPLICATE_WINDOW_SECONDS


def parse_hms(value: str) -> tuple[int, int, int]:
    """Parses a time string in HH:MM:SS format."""
    parts = value.strip().split(":")
    if len(parts) != 3:
        raise ValueError("Time format must be HH:MM:SS.")

    hour, minute, second = (int(part) for part in parts)
    if not 0 <= hour <= 23:
        raise ValueError("Hour must be between 00 and 23.")
    if not 0 <= minute <= 59:
        raise ValueError("Minute must be between 00 and 59.")
    if not 0 <= second <= 59:
        raise ValueError("Second must be between 00 and 59.")
    return hour, minute, second


def render_keepalive_message_text(message_text: str, now: datetime) -> str:
    """Renders optional placeholders inside one keep-alive message string."""
    replacements = {
        "{timestamp}": now.strftime("%Y-%m-%d %H:%M:%S"),
        "{date}": now.strftime("%d.%m.%Y"),
        "{time}": now.strftime("%H:%M:%S"),
    }
    rendered_text = message_text
    for placeholder, value in replacements.items():
        rendered_text = rendered_text.replace(placeholder, value)
    return rendered_text


def compute_next_keepalive_run_from_day(
    rule: KeepAliveRule,
    timezone_name: str,
    minimum_day_offset: int,
) -> datetime:
    """Computes the next execution time, optionally forcing scheduling from a later day onward."""
    tz = ZoneInfo(timezone_name)
    now = datetime.now(tz=tz)
    hour, minute, second = parse_hms(rule.time_of_day)
    base_time = now.replace(hour=hour, minute=minute, second=second, microsecond=0)

    delta_seconds = max(0.0, float(rule.time_of_day_delta)) * 3600.0

    day_offset = max(0, minimum_day_offset)
    while True:
        next_day_base = (base_time + timedelta(days=day_offset)).replace(microsecond=0)
        offset_seconds = random.uniform(-delta_seconds, delta_seconds) if delta_seconds else 0.0
        run_time = next_day_base + timedelta(seconds=offset_seconds)
        if run_time > now:
            return run_time
        day_offset += 1


async def send_keepalive_message(
    scheduler: AsyncIOScheduler,
    store: BotConfigStore,
    client: Client,
    rule: KeepAliveRule,
) -> None:
    """Sends a keep-alive message for a configured chat.

    Reschedules the next run in the ``finally`` block, and suppresses duplicate
    sends inside the KEEPALIVE_DUPLICATE_WINDOW_SECONDS idempotency window.
    """
    try:
        now = datetime.now(ZoneInfo(store.timezone))
        last_sent_at = store.keepalive_last_sent_at.get(rule.chat_id)
        if last_sent_at is not None and (now - last_sent_at).total_seconds() < KEEPALIVE_DUPLICATE_WINDOW_SECONDS:
            logging.warning(
                "Suppressed duplicate keep-alive for chat %s (%s) inside the guard window.",
                rule.chat_id,
                rule.chat_name or "unknown",
            )
            return
        message_text = rule.message_text
        if isinstance(message_text, list):
            choices = [item for item in (str(entry).strip() for entry in message_text) if item]
            message_text = random.choice(choices) if choices else DEFAULT_KEEPALIVE_MESSAGE
        await client.send_message(rule.chat_id, render_keepalive_message_text(message_text, now))
        store.keepalive_last_sent_at[rule.chat_id] = now
        logging.info(
            "Keep-alive sent successfully to chat %s (%s).",
            rule.chat_id,
            rule.chat_name or "unknown",
        )
    except (OSError, TimeoutError, RPCError):
        logging.warning(
            "Keep-alive for chat %s skipped due to a network/API problem.",
            rule.chat_id,
            exc_info=True,
        )
    except Exception:
        logging.exception("Error while sending the keep-alive message for chat %s.", rule.chat_id)
    finally:
        next_rule = store.get_keepalive(rule.chat_id)
        if next_rule is not None:
            schedule_keepalive_job(scheduler, store, client, next_rule, minimum_day_offset=1)


def schedule_keepalive_job(
    scheduler: AsyncIOScheduler,
    store: BotConfigStore,
    client: Client,
    rule: KeepAliveRule,
    minimum_day_offset: int = 0,
) -> None:
    """Schedules the next one-shot keep-alive run for a rule."""
    if not rule.enabled:
        return
    job_id = f"keepalive:{rule.chat_id}"
    scheduler.add_job(
        send_keepalive_message,
        "date",
        id=job_id,
        replace_existing=True,
        run_date=compute_next_keepalive_run_from_day(rule, store.timezone, minimum_day_offset),
        args=[scheduler, store, client, rule],
        misfire_grace_time=3600,
    )


def sync_keepalive_jobs(scheduler: AsyncIOScheduler, store: BotConfigStore, client: Client) -> None:
    """Rebuilds all keep-alive jobs from the current config."""
    existing_job_ids = {job.id for job in scheduler.get_jobs() if job.id.startswith("keepalive:")}
    desired_job_ids: set[str] = set()

    for rule in store.all_keepalives():
        if not rule.enabled:
            continue
        job_id = f"keepalive:{rule.chat_id}"
        desired_job_ids.add(job_id)
        schedule_keepalive_job(scheduler, store, client, rule)

    for job_id in existing_job_ids - desired_job_ids:
        try:
            scheduler.remove_job(job_id)
        except JobLookupError:
            pass
