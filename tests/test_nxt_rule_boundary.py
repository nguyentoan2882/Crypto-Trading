from __future__ import annotations

import hashlib
import inspect
import json
import re
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from app import nxt_signal_app as local_app
from app.nxt_core import rules
from app.nxt_core.comparison import exact_match
from app.nxt_core.ports import MarketDataPort, NotifierPort, RuleRepositoryPort


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = ROOT / "tests" / "fixtures" / "nxt_rule_golden_v1.json"
CACHE_DIR = ROOT / "data_cache" / "binance_usdm_futures_1d_live"


def _candles_at_cutoff(symbol: str, cutoff_utc: str) -> tuple[list[dict], str]:
    path = CACHE_DIR / f"{symbol}_1d.json"
    raw_bytes = path.read_bytes()
    raw = json.loads(raw_bytes)
    cutoff = datetime.fromisoformat(cutoff_utc.replace("Z", "+00:00"))
    cutoff_ms = int(cutoff.timestamp() * 1000)
    rows = []
    for source in raw:
        if int(source["time"]) >= cutoff_ms + 86_400_000:
            continue
        row = dict(source)
        row["localDate"] = datetime.fromtimestamp(int(row["time"]) / 1000, timezone.utc).date().isoformat()
        row["closed"] = int(row["closeTime"]) < cutoff_ms
        rows.append(row)
    return rows, hashlib.sha256(raw_bytes).hexdigest().upper()


class GoldenRuleParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

    def test_signal_fixture_matches_exactly_after_normalization(self) -> None:
        case = self.fixture["signalCase"]
        candle_sets = {}
        for symbol, metadata in case["inputs"].items():
            rows, file_hash = _candles_at_cutoff(symbol, case["cutoffUtc"])
            self.assertEqual(metadata["sha256"], file_hash)
            self.assertEqual(metadata["rowsUsed"], len(rows))
            candle_sets[symbol] = rows

        regime = rules.btc_regime_by_date(candle_sets["BTCUSDT"])
        actual = {
            symbol: rules.latest_signal_for_symbol(
                symbol,
                candle_sets[symbol],
                regime,
                detected_at="2000-01-01T00:00:00Z",
            )
            for symbol in sorted(candle_sets)
        }
        self.assertTrue(exact_match(case["expected"], actual))

    def test_followup_fixture_matches_exactly(self) -> None:
        case = self.fixture["followupCase"]
        actual = rules.evaluate_accepted_signal_followup(
            case["subject"],
            case["candles"],
            evaluation_date="2026-01-02",
        )
        self.assertEqual(case["expected"], actual)

    def test_fixed_inputs_are_deterministic(self) -> None:
        case = self.fixture["followupCase"]
        first = rules.evaluate_accepted_signal_followup(
            case["subject"], case["candles"], evaluation_date="2026-01-02"
        )
        second = rules.evaluate_accepted_signal_followup(
            case["subject"], case["candles"], evaluation_date="2026-01-02"
        )
        self.assertEqual(first, second)


class RuleBoundaryTests(unittest.TestCase):
    def test_engine_source_has_no_storage_or_http_side_effects(self) -> None:
        source = inspect.getsource(rules)
        for forbidden in ("urllib", "sqlite3", "nxt_mvp_store", "urlopen(", "write_text(", "open("):
            self.assertNotIn(forbidden, source)

    def test_adapter_contracts_are_structural(self) -> None:
        class Market:
            def daily_candles(self, symbol):
                return []

        class Repository:
            def existing_signal_ids(self):
                return set()

            def accepted_monitor_subjects(self):
                return []

            def persist_scan_result(self, result, *, started_at):
                return None

            def persist_followup_recommendations(self, items):
                return items

        class Notifier:
            def enqueue(self, *, delivery_key, message, metadata):
                return None

            def flush(self):
                return 0

        self.assertIsInstance(Market(), MarketDataPort)
        self.assertIsInstance(Repository(), RuleRepositoryPort)
        self.assertIsInstance(Notifier(), NotifierPort)

    def test_quantity_calculator_has_no_persistence_or_network_write_path(self) -> None:
        rendered = local_app.add_quantity_calculator("<html><body></body></html>", None, {})
        injected = rendered.split("<dialog", 1)[1]
        self.assertNotIn("localStorage", injected)
        self.assertNotIn("sessionStorage", injected)
        self.assertNotIn("fetch(", injected)
        self.assertNotIn("XMLHttpRequest", injected)
        self.assertNotIn("<form", injected)
        self.assertIsNone(re.search(r"<input[^>]+\bname=", injected))

    def test_legacy_dashboard_entrypoint_still_renders_after_extraction(self) -> None:
        state = {
            "signals": [],
            "positions": [],
            "recommendations": [],
            "followupRecommendations": [],
            "scanRuns": [],
            "auditEvents": [],
            "equityHistory": [],
            "settings": {},
            "currentEquity": None,
        }
        with (
            mock.patch.object(local_app.store, "init_db"),
            mock.patch.object(local_app.store, "import_legacy_history"),
            mock.patch.object(local_app.store, "dashboard_state", return_value=state),
            mock.patch.object(local_app, "load_json", return_value=[]),
        ):
            rendered = local_app.page()
        self.assertIn("Trading desk", rendered)
        self.assertIn("NXT v3.5", rendered)


if __name__ == "__main__":
    unittest.main()
