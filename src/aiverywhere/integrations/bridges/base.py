"""Public bridge abstraction.

A bridge is a separate long-running process that owns one platform connection.
It converts native events into the generic channel envelope and sends replies
back through the native platform. The core only reads bridge manifests.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod


class Bridge(ABC):
    """Minimal contract for a resident platform bridge.

    Implementations live in the project/instance `bridges/` directory and are
    started by their own process. The core never imports them.
    """

    channel: str

    @abstractmethod
    async def verify(self, event: dict) -> bool:
        """Return True only after authenticating the native platform event."""
        raise NotImplementedError

    @abstractmethod
    async def normalize(self, event: dict) -> dict:
        """Return {account, conversation, message_id, text} from a native event."""
        raise NotImplementedError

    @abstractmethod
    async def send(self, route: dict, text: str) -> dict:
        """Send text to the route's native account/conversation.

        Return a dict with `state` (`accepted` or `delivered`) and `receipt`.
        """
        raise NotImplementedError

    async def submit(self, message: dict, *, base_url: str | None = None,
                     token: str | None = None) -> dict:
        """Submit a normalized message to the local supervisor."""
        import httpx

        base = (base_url or os.getenv("AIVERYWHERE_DAEMON_URL")
                or "http://127.0.0.1:8765").rstrip("/")
        auth = token or os.getenv("AIVERYWHERE_DAEMON_TOKEN", "")
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"{base}/api/channels/{self.channel}/messages",
                headers={"X-Aiverywhere-Token": auth, "Content-Type": "application/json"},
                json=message)
            response.raise_for_status()
            return response.json()

    async def health(self) -> dict:
        return {"ok": True, "channel": self.channel}
