from __future__ import annotations

import json

from app.nxt_cloud.config import CloudConfig
from app.nxt_cloud.outbox import TelegramSender, format_shadow_message


TEST_BODY = "Telegram connectivity test only — no signal, no order, no schedule."


def build_test_message() -> str:
    return format_shadow_message(TEST_BODY)


def main() -> int:
    config = CloudConfig.from_env()
    if config.environment != "SHADOW" or config.notification_mode != "telegram":
        raise RuntimeError("Telegram test requires SHADOW with NXT_NOTIFICATION_MODE=telegram")
    TelegramSender(config.telegram_bot_token, config.telegram_chat_id)(build_test_message())
    print(json.dumps({"status": "TELEGRAM_TEST_SENT", "environment": "SHADOW"}, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
