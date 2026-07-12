"""Telegram message-forwarder userbot.

Package layout (src-layout, relative imports):

- ``settings``      — .env loading, credentials, all tuning constants
- ``logging_setup`` — logging infrastructure and runtime directories
- ``core``          — data models, config store, forward index, message rules
- ``connection``    — Pyrogram client, chat resolution, health check
- ``services``      — forward/edit pipeline, keep-alive scheduling, chat-name enrichment
- ``handlers``      — Pyrogram handlers (slash commands and message listeners)
- ``ui``            — text formatting and auto-delete replies
- ``app``           — composition root: wires everything together and runs the loop
"""
