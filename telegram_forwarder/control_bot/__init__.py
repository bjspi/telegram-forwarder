"""Optional control bot: a BotFather bot with an inline-button config menu.

This is a *separate* Pyrogram client running in bot mode, alongside the
userbot in the same event loop. It shares the userbot's in-memory
``BotConfigStore``, so button edits take effect immediately. Every handler is
locked to a single owner user id — nobody else can control the userbot.
"""
