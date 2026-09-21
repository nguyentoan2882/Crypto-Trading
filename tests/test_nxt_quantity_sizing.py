from __future__ import annotations

import gc
import tempfile
import unittest
from pathlib import Path

from app import nxt_mvp_store as store
from app import nxt_signal_app as core


def make_signal(symbol: str, entry: float, stop: float) -> dict:
    return {
        "id": f"sig:test:{symbol}",
        "symbol": symbol,
        "side": "LONG" if stop < entry else "SHORT",
        "signalType": "Primary",
        "signalDate": "2026-08-09",
        "entryDate": "2026-08-10",
        "entryPrice": entry,
        "initialStop": stop,
        "tp1": entry + (entry - stop) * 2.5,
        "riskPerUnit": abs(entry - stop),
        "orders": [],
    }


class QuantitySizingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.original_app_dir = store.APP_DIR
        self.original_db_path = store.DB_PATH
        store.APP_DIR = Path(self.temp.name)
        store.DB_PATH = store.APP_DIR / "quantity-test.sqlite"
        store.init_db()

    def tearDown(self) -> None:
        store.APP_DIR = self.original_app_dir
        store.DB_PATH = self.original_db_path
        gc.collect()
        self.temp.cleanup()

    def set_equity(self, leverage: float = 2.0) -> None:
        store.append_equity(20_000.0, 2.0, leverage, 6.0, "Sizing test", "")

    def test_needs_review_without_equity_and_risk(self) -> None:
        status, plan, equity_id = store.calculate_plan(make_signal("BTCUSDT", 100.0, 90.0))
        self.assertEqual("Needs Review", status)
        self.assertIn("Current Equity/Risk", plan["reason"])
        self.assertIsNone(equity_id)

    def test_each_symbol_uses_its_own_risk_per_unit(self) -> None:
        self.set_equity()
        cases = [
            ("BTCUSDT", 60_000.0, 59_000.0, 0.4),
            ("BNBUSDT", 600.0, 580.0, 20.0),
            ("SOLUSDT", 150.0, 145.0, 80.0),
        ]

        for symbol, entry, stop, expected_qty in cases:
            with self.subTest(symbol=symbol):
                status, plan, _ = store.calculate_plan(make_signal(symbol, entry, stop))
                sizing = plan["sizing"]
                self.assertEqual("Ready", status)
                self.assertAlmostEqual(400.0, plan["equitySnapshot"]["riskUsd"], places=10)
                self.assertAlmostEqual(expected_qty, sizing["quantityBase"], places=10)
                self.assertAlmostEqual(400.0, sizing["quantityBase"] * sizing["riskPerUnit"], places=10)

    def test_quantity_split_is_30_10_60_and_sums_to_full_size(self) -> None:
        self.set_equity()
        _, plan, _ = store.calculate_plan(make_signal("BNBUSDT", 600.0, 580.0))
        sizing = plan["sizing"]
        qty = sizing["quantityBase"]

        self.assertAlmostEqual(qty * 0.30, sizing["tp1Qty30Pct"], places=10)
        self.assertAlmostEqual(qty * 0.10, sizing["partialQty10Pct"], places=10)
        self.assertAlmostEqual(qty * 0.60, sizing["tailQty60Pct"], places=10)
        self.assertAlmostEqual(
            qty,
            sizing["tp1Qty30Pct"] + sizing["partialQty10Pct"] + sizing["tailQty60Pct"],
            places=10,
        )

    def test_leverage_changes_margin_reference_not_quantity(self) -> None:
        self.set_equity(leverage=1.0)
        signal = make_signal("SOLUSDT", 150.0, 145.0)
        _, one_x, _ = store.calculate_plan(signal)

        with store.connect() as conn:
            store.set_setting(conn, "leverage", 5.0)
        _, five_x, _ = store.calculate_plan(signal)

        self.assertAlmostEqual(one_x["sizing"]["quantityBase"], five_x["sizing"]["quantityBase"], places=10)
        self.assertAlmostEqual(one_x["sizing"]["notional"] / 5.0, five_x["sizing"]["marginReference"], places=10)

    def test_zero_risk_per_unit_is_rejected_by_calculation(self) -> None:
        self.set_equity()
        signal = make_signal("BTCUSDT", 100.0, 100.0)
        with self.assertRaises(ZeroDivisionError):
            store.calculate_plan(signal)

    def test_per_signal_quantity_popup_is_injected_with_saved_defaults(self) -> None:
        page = core.add_quantity_calculator(
            (
                "<html><head><style></style></head><body>"
                '<button type="button" class="signal-quantity-button" '
                'data-symbol="BTCUSDT" data-entry="100" data-stop="90">Tinh quantity</button>'
                "<form method=\"post\" action=\"/scan\"></form></body></html>"
            ),
            {"new_equity": 20_000.0},
            {"risk_pct": 2.0, "leverage": 3.0},
        )

        self.assertNotIn('id="open-quantity-calculator"', page)
        self.assertIn('class="signal-quantity-button"', page)
        self.assertIn("document.querySelectorAll('.signal-quantity-button')", page)
        self.assertIn('id="quantity-calculator"', page)
        self.assertIn('id="calculate-quantity"', page)
        self.assertIn('id="qty-equity" type="number" min="0" step="any" value="20000.0"', page)
        self.assertIn('id="qty-risk-pct" type="hidden" value="2.0"', page)
        self.assertIn('id="qty-leverage" type="hidden" value="3.0"', page)
        self.assertIn("qty=riskUsd/riskPerUnit", page)
        self.assertIn("Entry và Stop phải khác nhau.", page)


if __name__ == "__main__":
    unittest.main()
