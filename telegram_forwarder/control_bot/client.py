"""Factory for the control bot's Pyrogram client (bot mode)."""

from __future__ import annotations
from pyrogram import Client
from ..settings import API_HASH, API_ID, CONTROL_BOT_TOKEN, SESSION_DIR


def create_control_bot_client() -> Client:
    """Builds the control bot client, with its session file under session/."""
    return Client(
        str(SESSION_DIR / "control_bot"),
        api_id=API_ID,
        api_hash=API_HASH,
        bot_token=CONTROL_BOT_TOKEN,
    )
