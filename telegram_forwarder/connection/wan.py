"""WAN reachability probe used to classify Telegram outages.

A failed Telegram health check can mean two very different things: the line
itself is dead (a restart fixes nothing, pyrogram reconnects on its own once
the WAN returns) or Telegram alone is unreachable while the internet works
(the stuck-session case a supervisor restart actually repairs). This probe
answers that question — and is only ever called while the Telegram check is
already failing, so normal operation generates no extra traffic.
"""

from __future__ import annotations
import asyncio
import urllib.request
from ..settings import WAN_PROBE_TIMEOUT_SECONDS

# Captive-portal-style endpoints that answer a bodyless HTTP 204 and are built
# for exactly this kind of continuous probing (no rate limiting, no abuse
# detection). Two vendors, so a single vendor outage is not misread as the
# whole WAN being down.
WAN_PROBE_URLS: tuple[str, ...] = (
    "http://connectivitycheck.gstatic.com/generate_204",
    "http://cp.cloudflare.com/generate_204",
)


def _wan_probe(
    urls: tuple[str, ...] = WAN_PROBE_URLS,
    timeout: float = WAN_PROBE_TIMEOUT_SECONDS,
) -> bool:
    """Blocking WAN probe: True when any probe URL answers with HTTP 204."""
    for url in urls:
        try:
            with urllib.request.urlopen(url, timeout=timeout) as response:
                if response.status == 204:
                    return True
        except OSError:
            continue
    return False


async def wan_is_up() -> bool:
    """Run the blocking WAN probe off the event loop."""
    return await asyncio.to_thread(_wan_probe)
