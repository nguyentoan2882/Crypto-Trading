from __future__ import annotations

import tempfile
import unittest
import gc
from pathlib import Path

from app import nxt_mvp_store as store
from app import nxt_signal_app as core
from scripts import daily_nxt_signal_scan as scanner


def signal() -> dict:
    return {
        "id": "sig:test:long",
        "symbol": "BTCUSDT",
        "side": "LONG",
        "signalType": "Primary",
        "signalDate": "2026-07-31",
        "entryDate": "2026-08-01",
        "entryPrice": 100.0,
        "initialStop": 90.0,
        "tp1": 120.0,
        "riskPerUnit": 10.0,
        "btcDirectionalGuard": False,
        "orders": [],
    }


def subject(position: dict | None = None) -> dict:
    return {
        "signal_id": "sig:test:long",
        "position_id": position.get("positionId") if position else None,
        "symbol": "BTCUSDT",
        "side": "LONG",
        "signal": signal(),
        "plan": {"sizing": {"quantityBase": 5.0}},
        "position": position,
        "pendingFollowup": None,
        "acknowledgedActions": [],
    }


def candle(day: str, low: float, high: float, close: float, ssl: int = 1) -> dict:
    return {
        "localDate": day,
        "open": close,
        "low": low,
        "high": high,
        "close": close,
        "closed": True,
        "ssl": ssl,
        "ema50": 95.0,
    }


class FollowupRuleTests(unittest.TestCase):
    def test_no_action_is_explicit_and_theoretical(self) -> None:
        result = core.evaluate_accepted_signal_followup(
            subject(),
            [candle("2026-07-31", 95, 105, 100), candle("2026-08-01", 96, 110, 105)],
        )
        self.assertEqual("NO_ACTION", result["action"])
        self.assertEqual("KHONG CAN THAO TAC", result["actionLabel"])
        self.assertTrue(result["theoretical"])

    def test_tp1_action_includes_move_to_breakeven(self) -> None:
        result = core.evaluate_accepted_signal_followup(
            subject(),
            [candle("2026-07-31", 95, 105, 100), candle("2026-08-01", 96, 121, 118)],
        )
        self.assertEqual("TAKE_TP1_30_MOVE_BE", result["action"])
        self.assertIn("TP1 30%", result["actionLabel"])
        self.assertIn("BE", result["actionLabel"])

    def test_stop_has_priority_when_same_bar_also_touches_tp1(self) -> None:
        result = core.evaluate_accepted_signal_followup(
            subject(),
            [candle("2026-07-31", 95, 105, 100), candle("2026-08-01", 89, 121, 100)],
        )
        self.assertEqual("STOP_LOSS", result["action"])
        self.assertEqual(1, result["priority"])

    def test_tracked_position_is_not_labeled_theoretical(self) -> None:
        position = {
            "positionId": "pos:sig:test:long",
            "entryTime": "2026-08-01",
            "entryPrice": 101.0,
            "quantity": 2.0,
            "currentSl": 91.0,
            "currentTp1": 121.0,
            "lifecycle": "Active",
        }
        result = core.evaluate_accepted_signal_followup(
            subject(position),
            [candle("2026-07-31", 95, 105, 100), candle("2026-08-01", 96, 110, 105)],
        )
        self.assertEqual("Tracked Position", result["trackingStatus"])
        self.assertFalse(result["theoretical"])

    def test_applied_historical_action_is_not_repeated(self) -> None:
        accepted = subject()
        accepted["acknowledgedActions"] = ["TAKE_TP1_30_MOVE_BE"]
        result = core.evaluate_accepted_signal_followup(
            accepted,
            [
                candle("2026-07-31", 95, 105, 100),
                candle("2026-08-01", 96, 121, 118),
                candle("2026-08-02", 101, 115, 110),
            ],
        )
        self.assertEqual("NO_ACTION", result["action"])

    def test_followup_message_bolds_action(self) -> None:
        item = core.evaluate_accepted_signal_followup(
            subject(),
            [candle("2026-07-31", 95, 105, 100), candle("2026-08-01", 96, 110, 105)],
        )
        message = scanner.build_followup_message([item])
        self.assertIn("<b>ACTION: KHONG CAN THAO TAC</b>", message)
        self.assertIn("theoretical", message)

    def test_followup_messages_split_without_breaking_action_blocks(self) -> None:
        item = core.evaluate_accepted_signal_followup(
            subject(),
            [candle("2026-07-31", 95, 105, 100), candle("2026-08-01", 96, 110, 105)],
        )
        second = dict(item)
        second["recommendationId"] = "followup:second"
        second["signalId"] = "sig:second"
        batches = scanner.build_followup_message_batches([item, second], max_length=700)
        self.assertEqual(2, len(batches))
        self.assertTrue(all("<b>ACTION:" in message for message, _ in batches))


class FollowupStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_app_dir = store.APP_DIR
        self.original_db_path = store.DB_PATH
        store.APP_DIR = Path(self.temp_dir.name)
        store.DB_PATH = store.APP_DIR / "test.sqlite"
        store.init_db()

    def tearDown(self) -> None:
        store.APP_DIR = self.original_app_dir
        store.DB_PATH = self.original_db_path
        gc.collect()
        self.temp_dir.cleanup()

    def test_accept_does_not_create_position_and_can_persist_signal_followup(self) -> None:
        sig = signal()
        store.persist_scan_result(
            {
                "systemName": "test",
                "scannedAt": "2026-08-01T00:01:00Z",
                "symbols": ["BTCUSDT"],
                "checked": [{"symbol": "BTCUSDT", "latestDate": "2026-07-31"}],
                "newSignals": [sig],
                "errors": [],
            }
        )
        store.record_decision(sig["id"], "Accept")
        subjects = store.accepted_monitor_subjects()
        self.assertEqual(1, len(subjects))
        self.assertIsNone(subjects[0]["position"])

        rec = core.evaluate_accepted_signal_followup(
            subjects[0],
            [candle("2026-07-31", 95, 105, 100), candle("2026-08-01", 96, 110, 105)],
        )
        store.persist_followup_recommendations([rec, rec])
        state = store.dashboard_state()
        self.assertEqual(0, len(state["positions"]))
        self.assertEqual(1, len(state["followupRecommendations"]))


if __name__ == "__main__":
    unittest.main()
