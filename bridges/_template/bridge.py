"""Bridge template. Run this as its own long-lived process."""

from aiverywhere.integrations.bridges.base import Bridge


class TemplateBridge(Bridge):
    channel = "template"

    async def verify(self, event: dict) -> bool:
        # Verify the platform signature/session before trusting the event.
        return False

    async def normalize(self, event: dict) -> dict:
        # Return {account, conversation, message_id, text}.
        raise NotImplementedError

    async def send(self, route: dict, text: str) -> dict:
        # Call the native platform API and return an acknowledgement.
        raise NotImplementedError


if __name__ == "__main__":
    raise SystemExit("Implement the platform bridge before running.")
