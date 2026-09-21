from __future__ import annotations

import json

from app.nxt_cloud.config import CloudConfig
from app.nxt_cloud.web import create_app, gunicorn_options


def run_web(config: CloudConfig) -> int:
    try:
        from gunicorn.app.base import BaseApplication
    except ImportError as exc:
        raise RuntimeError("gunicorn is required for ROLE=web") from exc

    app = create_app(config=config)

    class NxtApplication(BaseApplication):
        def load_config(self) -> None:
            for key, value in gunicorn_options(config).items():
                self.cfg.set(key.lower(), value)

        def load(self):
            return app

    NxtApplication().run()
    return 0


def run_scanner(config: CloudConfig) -> int:
    # Keep scanner-only rule/workbook imports out of the web startup path. The
    # web image does not need openpyxl merely to serve the API and dashboard.
    from app.nxt_cloud.market import BinanceUsdMMarketData
    from app.nxt_cloud.outbox import DisabledNotificationOutbox, PostgresOutbox, TelegramSender
    from app.nxt_cloud.postgres import PostgresRepository
    from app.nxt_cloud.scanner import CloudScanner
    from scripts.backtest_nxt32_native_1d_latest import WARMUP_DATE

    repository = PostgresRepository(config.database_url)
    market = BinanceUsdMMarketData(WARMUP_DATE, config.binance_klines_url)
    if config.notification_mode == "disabled":
        outbox = DisabledNotificationOutbox(config.environment)
    else:
        outbox = PostgresOutbox(repository, TelegramSender(config.telegram_bot_token, config.telegram_chat_id), config.environment)
    result = CloudScanner(config, market, repository, outbox).run_once()
    result["notificationMode"] = config.notification_mode
    print(json.dumps(result, separators=(",", ":"), sort_keys=True))
    return 0 if result["status"] in {"COMPLETED", "SKIPPED_COMPLETED", "SKIPPED_LOCKED"} else 1


def main() -> int:
    config = CloudConfig.from_env()
    return run_web(config) if config.role == "web" else run_scanner(config)


if __name__ == "__main__":
    raise SystemExit(main())
