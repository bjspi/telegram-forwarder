"""Pyrogram client factory and compatibility patches."""

from __future__ import annotations
from pyrogram import Client
from pyrogram.raw import types as raw_types
from ..settings import ACCOUNT, API_HASH, API_ID, PHONE_NR, SESSION_DIR


def create_client() -> Client:
    """Builds the Pyrogram userbot client with its session file under session/."""
    return Client(
        str(SESSION_DIR / ACCOUNT),
        phone_number=PHONE_NR,
        api_id=API_ID,
        api_hash=API_HASH,
    )


def patch_pyrogram_dialog_compat() -> None:
    """Adds compatibility aliases for dialog fields across Pyrogram fork variants."""
    if not hasattr(raw_types.Dialog, "unread_poll_vote_count"):
        raw_types.Dialog.unread_poll_vote_count = property(  # type: ignore[attr-defined]
            lambda self: getattr(self, "unread_poll_votes_count", 0)
        )
