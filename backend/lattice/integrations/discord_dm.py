"""Send Discord DMs via the bot REST API (no discord.py required)."""

from __future__ import annotations

import logging

import httpx

from lattice.config import settings

logger = logging.getLogger(__name__)

_BASE = "https://discord.com/api/v10"


async def send_dm(content: str) -> bool:
    """Send a DM to the configured owner. Returns True on success."""
    token = settings.discord_bot_token
    owner_id = settings.discord_owner_id
    if not token or not owner_id:
        logger.debug("discord DM skipped — token or owner_id not configured")
        return False

    headers = {"Authorization": f"Bot {token}", "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=10.0) as client:
        # Step 1: open (or reuse) DM channel
        r = await client.post(
            f"{_BASE}/users/@me/channels",
            headers=headers,
            json={"recipient_id": owner_id},
        )
        if r.status_code not in (200, 201):
            logger.warning("discord DM: failed to open channel — %s %s", r.status_code, r.text)
            return False
        channel_id = r.json()["id"]

        # Step 2: send message
        r2 = await client.post(
            f"{_BASE}/channels/{channel_id}/messages",
            headers=headers,
            json={"content": content},
        )
        if r2.status_code not in (200, 201):
            logger.warning("discord DM: failed to send — %s %s", r2.status_code, r2.text)
            return False

    logger.info("discord DM sent: %s", content[:80])
    return True
