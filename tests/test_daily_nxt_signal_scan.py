from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import daily_nxt_signal_scan as scanner


class TelegramOutboxTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_outbox = scanner.OUTBOX_PATH
        self.original_delivery_state = scanner.DELIVERY_STATE_PATH
        self.original_daily_state = scanner.DAILY_SCAN_STATE_PATH
        self.original_send = scanner.send_telegram
        self.original_scan = scanner.core.scan_and_persist
        self.original_http_json = scanner.core.http_json
        self.original_mark_notified = scanner.core.store.mark_followups_notified
        scanner.OUTBOX_PATH = Path(self.temp_dir.name) / "telegram_outbox.json"
        scanner.DELIVERY_STATE_PATH = Path(self.temp_dir.name) / "telegram_delivery_state.json"
        scanner.DAILY_SCAN_STATE_PATH = Path(self.temp_dir.name) / "daily_scan_state.json"

    def tearDown(self) -> None:
        scanner.OUTBOX_PATH = self.original_outbox
        scanner.DELIVERY_STATE_PATH = self.original_delivery_state
        scanner.DAILY_SCAN_STATE_PATH = self.original_daily_state
        scanner.send_telegram = self.original_send
        scanner.core.scan_and_persist = self.original_scan
        scanner.core.http_json = self.original_http_json
        scanner.core.store.mark_followups_notified = self.original_mark_notified
        self.temp_dir.cleanup()

    def test_queue_deduplicates_and_flushes(self) -> None:
        delivered: list[str] = []
        scanner.send_telegram = delivered.append
        scanner.queue_telegram("signal", "signal:one", "message")
        scanner.queue_telegram("signal", "signal:one", "message")

        self.assertEqual(1, len(scanner.load_outbox()))
        self.assertEqual(1, scanner.flush_outbox())
        self.assertEqual(["message"], delivered)
        self.assertEqual([], scanner.load_outbox())

    def test_failed_delivery_retains_message(self) -> None:
        scanner.queue_telegram("signal", "signal:one", "message")

        def fail(_: str) -> None:
            raise RuntimeError("offline")

        scanner.send_telegram = fail
        with self.assertRaisesRegex(RuntimeError, "offline"):
            scanner.flush_outbox()
        self.assertEqual(1, len(scanner.load_outbox()))

    def test_delivered_key_prevents_duplicate_notification(self) -> None:
        delivered: list[str] = []
        scanner.send_telegram = delivered.append
        scanner.queue_telegram("no-signal", "no-signal:today", "message")
        self.assertEqual(1, scanner.flush_outbox())
        scanner.queue_telegram("no-signal", "no-signal:today", "message")
        self.assertEqual([], scanner.load_outbox())
        self.assertEqual(["message"], delivered)

    def test_successful_daily_scan_skips_recovery_run(self) -> None:
        scanner.save_json_object(scanner.DAILY_SCAN_STATE_PATH, {"successDate": scanner.local_day()})
        scanner.core.scan_and_persist = lambda: self.fail("scan should have been skipped")
        old_skip = os.environ.get("NXT_SKIP_IF_DAILY_SUCCESS")
        os.environ["NXT_SKIP_IF_DAILY_SUCCESS"] = "1"
        try:
            self.assertEqual(0, scanner.main())
        finally:
            if old_skip is None:
                os.environ.pop("NXT_SKIP_IF_DAILY_SUCCESS", None)
            else:
                os.environ["NXT_SKIP_IF_DAILY_SUCCESS"] = old_skip

    def test_scan_error_sends_only_error_notification(self) -> None:
        delivered: list[str] = []
        scanner.send_telegram = delivered.append
        scanner.core.scan_and_persist = lambda: {
            "scannedAt": "2026-08-05T00:10:06Z",
            "checked": [],
            "newSignals": [],
            "errors": [{"symbol": "BTCUSDT", "error": "network blocked"}],
        }
        old_notify_errors = os.environ.get("NXT_NOTIFY_ERRORS")
        old_notify_no_signal = os.environ.get("NXT_NOTIFY_NO_SIGNAL")
        os.environ["NXT_NOTIFY_ERRORS"] = "1"
        os.environ["NXT_NOTIFY_NO_SIGNAL"] = "1"
        try:
            self.assertEqual(1, scanner.main())
        finally:
            if old_notify_errors is None:
                os.environ.pop("NXT_NOTIFY_ERRORS", None)
            else:
                os.environ["NXT_NOTIFY_ERRORS"] = old_notify_errors
            if old_notify_no_signal is None:
                os.environ.pop("NXT_NOTIFY_NO_SIGNAL", None)
            else:
                os.environ["NXT_NOTIFY_NO_SIGNAL"] = old_notify_no_signal

        self.assertEqual(1, len(delivered))
        self.assertIn("scan error", delivered[0])
        self.assertNotIn("no new entry signal", delivered[0])

    def test_entry_message_bolds_required_action(self) -> None:
        message = scanner.build_message(
            [
                {
                    "id": "sig:1",
                    "symbol": "BTCUSDT",
                    "side": "LONG",
                    "signalType": "Primary",
                    "signalDate": "2026-08-05",
                    "entryDate": "2026-08-06",
                    "entryPrice": 100.0,
                    "initialStop": 90.0,
                    "tp1": 120.0,
                    "atr14": 8.0,
                    "rsi14": 55.0,
                    "distanceToEma50Atr": 0.5,
                    "orders": [],
                }
            ]
        )
        self.assertIn("<b>ACTION CAN LUU Y:", message)
        self.assertIn("</b>", message)

    def test_send_telegram_uses_html_parse_mode(self) -> None:
        captured = []
        scanner.core.http_json = lambda url, data=None: captured.append((url, data))
        old_token = os.environ.get("NXT_TELEGRAM_BOT_TOKEN")
        old_chat = os.environ.get("NXT_TELEGRAM_CHAT_ID")
        os.environ["NXT_TELEGRAM_BOT_TOKEN"] = "token"
        os.environ["NXT_TELEGRAM_CHAT_ID"] = "chat"
        try:
            scanner.send_telegram("<b>ACTION</b>")
        finally:
            if old_token is None:
                os.environ.pop("NXT_TELEGRAM_BOT_TOKEN", None)
            else:
                os.environ["NXT_TELEGRAM_BOT_TOKEN"] = old_token
            if old_chat is None:
                os.environ.pop("NXT_TELEGRAM_CHAT_ID", None)
            else:
                os.environ["NXT_TELEGRAM_CHAT_ID"] = old_chat
        self.assertEqual("HTML", captured[0][1]["parse_mode"])

    def test_followup_delivery_marks_recommendations_notified(self) -> None:
        delivered: list[str] = []
        marked: list[list[str]] = []
        scanner.send_telegram = delivered.append
        scanner.core.store.mark_followups_notified = marked.append
        scanner.queue_telegram("followup", "followup:one", "<b>ACTION</b>", ["rec:one"])
        self.assertEqual(1, scanner.flush_outbox())
        self.assertEqual(["<b>ACTION</b>"], delivered)
        self.assertEqual([["rec:one"]], marked)


if __name__ == "__main__":
    unittest.main()
