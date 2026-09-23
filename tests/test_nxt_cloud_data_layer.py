from __future__ import annotations

import hashlib
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from scripts.nxt_cloud_import_sqlite import (
    _render_statement,
    build_database_url,
    build_batches,
    emit_sql,
    read_source,
    source_manifest,
)
from scripts.nxt_cloud_migrate import migration_files


ROOT = Path(__file__).resolve().parents[1]


class MigrationContractTests(unittest.TestCase):
    def test_schema_covers_repository_and_denies_direct_client_access(self):
        sql = (ROOT / "cloud" / "migrations" / "0001_shadow_schema.sql").read_text(encoding="utf-8")
        for name in (
            "schema_migrations",
            "scan_runs",
            "scan_run_symbols",
            "signals",
            "trade_plans",
            "decisions",
            "manual_positions",
            "followup_recommendations",
            "notification_outbox",
            "idempotency_keys",
            "legacy_import_records",
            "accepted_monitor_subjects",
        ):
            if name == "schema_migrations":
                continue  # Bootstrapped atomically by the migration runner.
            self.assertIn(name, sql)
        self.assertEqual(10, sql.count("ENABLE ROW LEVEL SECURITY"))
        self.assertIn("security_invoker = true", sql)
        self.assertIn("CHECK (environment = 'SHADOW')", sql)

    def test_migration_inventory_is_contiguous_and_checksummed(self):
        found = migration_files(ROOT / "cloud" / "migrations")
        self.assertEqual([1, 2], [version for version, _, _ in found])
        self.assertRegex(found[0][2], r"^[0-9a-f]{64}$")
        outcome_sql = found[1][1].read_text(encoding="utf-8")
        self.assertIn("ADD COLUMN outcome text", outcome_sql)
        self.assertIn("legacy_import_records", outcome_sql)


class CopyOnlyImporterTests(unittest.TestCase):
    def test_database_url_percent_encodes_credentials_and_requires_tls(self):
        self.assertEqual(
            build_database_url("db.example", "postgres.project", "p@ss/word"),
            "postgresql://postgres.project:p%40ss%2Fword@db.example:5432/postgres?sslmode=require",
        )

    def test_sql_emitter_quotes_values_and_wraps_transaction(self):
        self.assertEqual(
            _render_statement("INSERT INTO demo(a,b,c) VALUES (%s,%s,%s)", ("O'Reilly", None, 3)),
            "INSERT INTO demo(a,b,c) VALUES ('O''Reilly',NULL,3);",
        )
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "import.sql"
            counts = emit_sql(target, [("INSERT INTO demo(a) VALUES (%s) ON CONFLICT DO NOTHING", [("x",)])])
            sql = target.read_text(encoding="utf-8")
            self.assertEqual(counts, {"batch1": 1})
            self.assertTrue(sql.startswith("BEGIN;\nSELECT pg_advisory_xact_lock"))
            self.assertIn("INSERT INTO demo(a) VALUES ('x') ON CONFLICT DO NOTHING;", sql)
            self.assertIn("COMMIT;", sql)

    def test_read_only_source_and_deterministic_idempotent_batches(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.sqlite"
            with closing(sqlite3.connect(source)) as conn:
                conn.executescript(
                    "CREATE TABLE scan_runs(run_id TEXT PRIMARY KEY, started_at TEXT, finished_at TEXT, status TEXT, candle_date TEXT, errors_json TEXT, system_name TEXT);"
                    "CREATE TABLE signals(signal_id TEXT PRIMARY KEY, run_id TEXT, symbol TEXT, side TEXT, signal_type TEXT, signal_date TEXT, payload_json TEXT, created_at TEXT);"
                    "CREATE TABLE settings(key TEXT PRIMARY KEY, value TEXT, updated_at TEXT);"
                )
                conn.execute(
                    "INSERT INTO scan_runs VALUES(?,?,?,?,?,?,?)",
                    ("run-1", "2026-09-20T00:00:00Z", "2026-09-20T00:01:00Z", "Completed", "2026-09-19", "[]", "rule-v1"),
                )
                conn.execute(
                    "INSERT INTO signals VALUES(?,?,?,?,?,?,?,?)",
                    ("signal-1", "run-1", "BTCUSDT", "LONG", "Primary", "2026-09-19", '{"id":"signal-1"}', "2026-09-20T00:01:00Z"),
                )
                conn.execute("INSERT INTO settings VALUES('equity','100000','2026-09-20T00:00:00Z')")
                conn.commit()
            before = hashlib.sha256(source.read_bytes()).hexdigest()
            first = read_source(source)
            second = read_source(source)
            self.assertEqual(first, second)
            self.assertEqual(before, hashlib.sha256(source.read_bytes()).hexdigest())
            self.assertEqual(source_manifest(source, first), source_manifest(source, second))
            batches = build_batches(first, "owner-1")
            self.assertTrue(all("ON CONFLICT DO NOTHING" in query for query, _ in batches))
            self.assertEqual(1, len(batches[0][1]))
            self.assertEqual(1, len(batches[1][1]))
            self.assertEqual(3, len(batches[-1][1]))

    def test_invalid_or_orphan_business_rows_are_retained_only_as_legacy(self):
        rows = {
            "signals": [],
            "decisions": [
                {"decision_id": "d1", "signal_id": "missing", "decision": "Accept"},
                {"decision_id": "d2", "signal_id": "missing", "decision": "Reject"},
            ],
            "manual_positions": [{"position_id": "p1", "signal_id": "missing", "entry_price": 0, "quantity": 1}],
        }
        batches = build_batches(rows, "owner-1")
        self.assertEqual([], batches[3][1])
        self.assertEqual([], batches[4][1])
        self.assertEqual(3, len(batches[-1][1]))
        self.assertEqual({"d1", "d2", "p1"}, {item[2] for item in batches[-1][1]})

    def test_followup_outcome_is_normalized_from_local_source(self):
        rows = {
            "signals": [{"signal_id": "s1", "symbol": "BTCUSDT", "side": "LONG", "signal_type": "Primary", "signal_date": "2026-09-18", "payload_json": "{}"}],
            "followup_recommendations": [{
                "recommendation_id": "r1", "signal_id": "s1", "candle_date": "2026-09-21", "action": "TAKE_TP1_30_MOVE_BE",
                "priority": 1, "status": "Acknowledged", "outcome": "Applied", "payload_json": "{}",
            }],
        }
        batches = build_batches(rows, "owner-1")
        self.assertEqual("Applied", batches[5][1][0][8])


if __name__ == "__main__":
    unittest.main()
