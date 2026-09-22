from __future__ import annotations

import json
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping

from app.nxt_cloud.contracts import CloudRepository


SHADOW_PREFIX = "[NXT-CLOUD][SHADOW]"
SHADOW_DISCLAIMER = "TESTING ONLY — local NXT remains official. Recommendation-only; no order execution."


def format_shadow_message(message: str) -> str:
    body = message.strip()
    if body.startswith(SHADOW_PREFIX):
        body = body[len(SHADOW_PREFIX) :].lstrip()
    return f"{SHADOW_PREFIX}\n{SHADOW_DISCLAIMER}\n\n{body}"


class TelegramSender:
    def __init__(self, bot_token: str, chat_id: str, timeout: int = 30) -> None:
        if not bot_token or not chat_id:
            raise ValueError("cloud Telegram bot token and chat id are required")
        self.url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        self.chat_id = chat_id
        self.timeout = timeout

    def __call__(self, message: str) -> None:
        data = urllib.parse.urlencode(
            {
                "chat_id": self.chat_id,
                "text": message,
                "parse_mode": "HTML",
                "disable_web_page_preview": "true",
            }
        ).encode("utf-8")
        request = urllib.request.Request(self.url, data=data, headers={"Content-Type": "application/x-www-form-urlencoded"})
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if not payload.get("ok"):
            raise RuntimeError("Telegram delivery rejected")


class DisabledNotificationOutbox:
    """Discard notifications explicitly while retaining scanner business-state writes."""

    def __init__(self, environment: str = "SHADOW") -> None:
        if environment != "SHADOW":
            raise ValueError("disabled cloud notifications only support SHADOW")
        self.suppressed = 0

    def enqueue(self, delivery_key: str, message: str, metadata: Mapping[str, object]) -> bool:
        if not delivery_key.startswith("cloud-shadow:"):
            raise ValueError("cloud delivery keys must use the cloud-shadow namespace")
        self.suppressed += 1
        return False

    def flush(self) -> int:
        return 0


class PostgresOutbox:
    def __init__(self, repository: CloudRepository, sender: Callable[[str], None], environment: str = "SHADOW") -> None:
        if environment != "SHADOW":
            raise ValueError("cloud outbox only supports SHADOW")
        self.repository = repository
        self.sender = sender
        self.environment = environment

    def enqueue(self, delivery_key: str, message: str, metadata: Mapping[str, object]) -> bool:
        if not delivery_key.startswith("cloud-shadow:"):
            raise ValueError("cloud delivery keys must use the cloud-shadow namespace")
        return self.repository.enqueue_outbox(self.environment, delivery_key, format_shadow_message(message), metadata)

    def flush(self) -> int:
        delivered = 0
        for item in self.repository.pending_outbox(self.environment):
            try:
                message = str(item["message"])
                if not message.startswith(SHADOW_PREFIX):
                    raise ValueError("outbox message is missing the mandatory SHADOW prefix")
                self.sender(message)
                self.repository.mark_outbox_delivered(str(item["outbox_id"]))
                delivered += 1
            except Exception as exc:
                self.repository.mark_outbox_failed(str(item["outbox_id"]), type(exc).__name__)
        return delivered
