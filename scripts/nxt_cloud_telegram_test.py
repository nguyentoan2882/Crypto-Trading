from __future__ import annotations

import json

import psycopg

from app.nxt_cloud.config import CloudConfig
from app.nxt_cloud.outbox import TelegramSender, format_shadow_message


TEST_BODY = "Telegram connectivity test only — no signal, no order, no schedule."


def build_test_message() -> str:
    return format_shadow_message(TEST_BODY)


def assert_outbox_empty(database_url: str) -> None:
    if not database_url:
        raise RuntimeError("Telegram test requires DATABASE_URL for the outbox safety check")
    with psycopg.connect(database_url) as connection:
        row = connection.execute(
            "SELECT count(*) FROM notification_outbox "
            "WHERE environment = 'SHADOW' AND status IN ('PENDING', 'FAILED')"
        ).fetchone()
    pending = int(row[0]) if row else -1
    if pending != 0:
        raise RuntimeError(f"Telegram test blocked: SHADOW outbox has {pending} pending/failed message(s)")


def main() -> int:
    config = CloudConfig.from_env()
    if config.environment != "SHADOW" or config.notification_mode != "telegram":
        raise RuntimeError("Telegram test requires SHADOW with NXT_NOTIFICATION_MODE=telegram")
    assert_outbox_empty(config.database_url)
    TelegramSender(config.telegram_bot_token, config.telegram_chat_id)(build_test_message())
    print(json.dumps({"status": "TELEGRAM_TEST_SENT", "environment": "SHADOW"}, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
