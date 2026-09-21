from __future__ import annotations

import io
import json
import threading
import unittest
import urllib.request
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest import mock
from wsgiref.simple_server import make_server

from app.nxt_cloud.config import CloudConfig
from app.nxt_cloud.outbox import PostgresOutbox, SHADOW_DISCLAIMER, SHADOW_PREFIX
from app.nxt_cloud.postgres import PostgresRepository
from app.nxt_cloud.quantity import render_quantity_calculator
from app.nxt_cloud.scanner import CloudScanner, DataGateError, validate_candle_sets
from app.nxt_cloud.web import CloudWebApp


ROOT = Path(__file__).resolve().parents[1]


class FakeVerifier:
    def __init__(self, claims: dict | None = None) -> None:
        self.claims = claims or {"sub": "owner-1", "email": "owner@example.com", "aal": "aal2"}

    def verify(self, token: str) -> dict:
        if token == "bad":
            raise ValueError("bad token")
        return self.claims


class FakeRepository:
    def __init__(self) -> None:
        self.ready = True
        self.writes = []
        self.bundles = []
        self.followups = []
        self.outbox = []
        self.delivered = []
        self.failed = []
        self.locked = False
        self.completed = False

    def ping(self):
        return self.ready

    def schema_current(self):
        return self.ready

    def dashboard_state(self, owner_user_id):
        return {"environment": "SHADOW", "owner": owner_user_id, "signals": [], "scanRuns": [], "followupRecommendations": []}

    def list_records(self, kind, owner_user_id, limit, offset):
        return [{"kind": kind, "owner": owner_user_id, "limit": limit, "offset": offset}]

    def record_decision(self, owner_user_id, payload, idempotency_key):
        self.writes.append(("decision", owner_user_id, payload, idempotency_key))
        return {"status": "recorded"}

    def track_position(self, owner_user_id, payload, idempotency_key):
        self.writes.append(("position", owner_user_id, payload, idempotency_key))
        return {"status": "tracked"}

    def record_followup_outcome(self, owner_user_id, recommendation_id, payload, idempotency_key):
        self.writes.append(("followup", owner_user_id, recommendation_id, payload, idempotency_key))
        return {"status": "Applied"}

    @contextmanager
    def scan_lock(self, lock_key):
        yield not self.locked

    def completed_scan_exists(self, environment, candle_date, rule_version):
        return self.completed

    def existing_signal_ids(self, environment):
        return set()

    def accepted_monitor_subjects(self, environment):
        return []

    def persist_scan_bundle(self, bundle):
        self.bundles.append(bundle)

    def persist_followup_recommendations(self, environment, items):
        self.followups.extend(items)

    def enqueue_outbox(self, environment, delivery_key, message, metadata):
        if any(item["delivery_key"] == delivery_key for item in self.outbox):
            return False
        self.outbox.append({"outbox_id": str(len(self.outbox) + 1), "delivery_key": delivery_key, "message": message, "metadata": metadata, "attempts": 0})
        return True

    def pending_outbox(self, environment, limit=20):
        return self.outbox[:limit]

    def mark_outbox_delivered(self, outbox_id):
        self.delivered.append(outbox_id)

    def mark_outbox_failed(self, outbox_id, error_code):
        self.failed.append((outbox_id, error_code))


class FakeCursor:
    def __init__(self, fetchone_values=None):
        self.fetchone_values = list(fetchone_values or [])
        self.executed = []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, query, params=()):
        self.executed.append((query, params))

    def fetchone(self):
        return self.fetchone_values.pop(0) if self.fetchone_values else None

    def fetchall(self):
        return []


class FakeConnection:
    def __init__(self, cursor):
        self._cursor = cursor

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def cursor(self):
        return self._cursor

    def transaction(self):
        return self


class FakePool:
    def __init__(self, cursor):
        self._connection = FakeConnection(cursor)

    def connection(self):
        return self._connection


def cloud_config(**updates) -> CloudConfig:
    values = {
        "role": "web",
        "environment": "SHADOW",
        "port": 8080,
        "allowed_origins": ("https://nxt.example",),
        "owner_user_ids": ("owner-1",),
        "owner_emails": ("owner@example.com",),
        "health_token": "health-secret",
    }
    values.update(updates)
    return CloudConfig(**values)


def wsgi_call(app, method="GET", path="/", token=None, body=None, headers=None, cookie=""):
    raw = b"" if body is None else json.dumps(body).encode("utf-8")
    environ = {
        "REQUEST_METHOD": method,
        "PATH_INFO": path,
        "QUERY_STRING": "",
        "CONTENT_LENGTH": str(len(raw)),
        "CONTENT_TYPE": "application/json",
        "wsgi.input": io.BytesIO(raw),
        "wsgi.url_scheme": "https",
        "SERVER_NAME": "nxt.example",
        "SERVER_PORT": "443",
    }
    if token:
        environ["HTTP_AUTHORIZATION"] = f"Bearer {token}"
    if cookie:
        environ["HTTP_COOKIE"] = cookie
    for key, value in (headers or {}).items():
        environ["HTTP_" + key.upper().replace("-", "_")] = value
    captured = {}

    def start_response(status, response_headers):
        captured["status"] = status
        captured["headers"] = dict(response_headers)

    response = b"".join(app(environ, start_response))
    return int(captured["status"].split()[0]), captured["headers"], response


class ConfigSafetyTests(unittest.TestCase):
    def test_shadow_only_and_public_binance_only(self):
        with self.assertRaises(ValueError):
            CloudConfig.from_env({"ROLE": "web", "NXT_ENVIRONMENT": "ACTIVE"})
        with self.assertRaises(ValueError):
            CloudConfig.from_env({"ROLE": "scanner", "NXT_USDM_KLINES_URL": "https://example.com/klines"})

    def test_binance_credentials_are_forbidden(self):
        with self.assertRaises(ValueError):
            CloudConfig.from_env({"ROLE": "scanner", "BINANCE_API_KEY": "must-not-exist"})


class WebSecurityTests(unittest.TestCase):
    def setUp(self):
        self.repo = FakeRepository()
        self.app = CloudWebApp(cloud_config(), self.repo, FakeVerifier())

    def test_health_is_public_and_readiness_is_token_limited(self):
        status, _, body = wsgi_call(self.app, path="/healthz")
        self.assertEqual(200, status)
        self.assertTrue(json.loads(body)["alive"])
        self.assertEqual(401, wsgi_call(self.app, path="/readyz")[0])
        self.assertEqual(200, wsgi_call(self.app, path="/readyz", headers={"X-NXT-Health-Token": "health-secret"})[0])

    def test_business_routes_require_valid_mfa_owner(self):
        self.assertEqual(401, wsgi_call(self.app, path="/api/state")[0])
        self.assertEqual(200, wsgi_call(self.app, path="/api/state", token="ok")[0])
        weak = CloudWebApp(cloud_config(), self.repo, FakeVerifier({"sub": "owner-1", "email": "owner@example.com", "aal": "aal1"}))
        self.assertEqual(401, wsgi_call(weak, path="/api/state", token="ok")[0])
        outsider = CloudWebApp(cloud_config(), self.repo, FakeVerifier({"sub": "other", "email": "other@example.com", "aal": "aal2"}))
        self.assertEqual(401, wsgi_call(outsider, path="/api/state", token="ok")[0])

    def test_cookie_write_requires_origin_csrf_and_idempotency(self):
        cookie = "__Host-nxt_session=ok; nxt_csrf=abc"
        headers = {"Origin": "https://nxt.example", "X-CSRF-Token": "abc", "Idempotency-Key": "decision-1"}
        self.assertEqual(401, wsgi_call(self.app, method="POST", path="/api/decisions", body={"signalId": "s", "decision": "Accept"}, cookie=cookie, headers={"Origin": "https://nxt.example", "Idempotency-Key": "decision-1"})[0])
        self.assertEqual(401, wsgi_call(self.app, method="POST", path="/api/decisions", body={"signalId": "s", "decision": "Accept"}, cookie=cookie, headers={"X-CSRF-Token": "abc", "Idempotency-Key": "decision-1"})[0])
        self.assertEqual(401, wsgi_call(self.app, method="POST", path="/api/decisions", body={"signalId": "s", "decision": "Accept"}, cookie=cookie, headers={**headers, "Origin": "https://evil.example"})[0])
        self.assertEqual(200, wsgi_call(self.app, method="POST", path="/api/decisions", body={"signalId": "s", "decision": "Accept"}, cookie=cookie, headers=headers)[0])
        self.assertEqual(1, len(self.repo.writes))

    def test_bearer_write_still_requires_idempotency(self):
        status, _, _ = wsgi_call(self.app, method="POST", path="/api/positions", token="ok", body={"signalId": "s", "quantity": 1, "entryPrice": 10})
        self.assertEqual(400, status)

    def test_legacy_mutation_routes_do_not_exist(self):
        for path in ("/scan", "/equity", "/decision", "/track-position", "/followup-outcome"):
            self.assertEqual(404, wsgi_call(self.app, method="POST", path=path, token="ok", body={})[0])

    def test_security_headers_are_present(self):
        _, headers, _ = wsgi_call(self.app, path="/healthz")
        self.assertEqual("DENY", headers["X-Frame-Options"])
        self.assertEqual("nosniff", headers["X-Content-Type-Options"])
        self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])

    def test_wsgi_app_serves_real_http_health_request(self):
        server = make_server("127.0.0.1", 0, self.app)
        thread = threading.Thread(target=server.handle_request, daemon=True)
        thread.start()
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{server.server_port}/healthz", timeout=5) as response:
                self.assertEqual(200, response.status)
        finally:
            server.server_close()
            thread.join(timeout=5)


class QuantityPrivacyTests(unittest.TestCase):
    def test_cloud_quantity_is_ephemeral_and_has_no_leverage(self):
        payload = render_quantity_calculator()
        for forbidden in ("<form", "fetch(", "XMLHttpRequest", "localStorage", "sessionStorage", "name=", "leverage"):
            self.assertNotIn(forbidden, payload)
        self.assertIn("qty=riskUsd/riskUnit", payload)
        self.assertIn("qty*.3", payload)
        self.assertIn("qty*.1", payload)
        self.assertIn("qty*.6", payload)


def candle_rows(latest_date: date, count=240):
    start = latest_date - timedelta(days=count - 1)
    return [
        {
            "localDate": (start + timedelta(days=index)).isoformat(),
            "time": index * 86_400_000,
            "closeTime": index * 86_400_000 + 86_399_999,
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.0,
            "volume": 1.0,
            "closed": True,
        }
        for index in range(count)
    ]


class FakeMarket:
    def __init__(self, rows_by_symbol):
        self.rows_by_symbol = rows_by_symbol

    def daily_candles(self, symbol):
        value = self.rows_by_symbol[symbol]
        if isinstance(value, Exception):
            raise value
        return value


class FakeOutbox:
    def __init__(self):
        self.items = []

    def enqueue(self, delivery_key, message, metadata):
        self.items.append((delivery_key, message, metadata))
        return True

    def flush(self):
        return len(self.items)


class ScannerControlTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 9, 21, 1, 5, tzinfo=timezone.utc)
        latest = self.now.date() - timedelta(days=1)
        self.rows = {symbol: candle_rows(latest) for symbol in ("BTCUSDT", "BNBUSDT", "SOLUSDT")}
        self.repo = FakeRepository()
        self.outbox = FakeOutbox()
        self.config = cloud_config(role="scanner")

    def test_all_symbol_gate_rejects_missing_stale_and_invalid_rows(self):
        with self.assertRaises(DataGateError):
            validate_candle_sets({"BTCUSDT": self.rows["BTCUSDT"]}, self.config.symbols, "2026-09-20")
        stale = dict(self.rows)
        stale["SOLUSDT"] = candle_rows(date(2026, 9, 19))
        with self.assertRaises(DataGateError):
            validate_candle_sets(stale, self.config.symbols, "2026-09-20")
        invalid = {key: [dict(row) for row in value] for key, value in self.rows.items()}
        invalid["BNBUSDT"][-1]["low"] = 110
        with self.assertRaises(DataGateError):
            validate_candle_sets(invalid, self.config.symbols, "2026-09-20")

    def test_fetch_failure_writes_no_business_state(self):
        broken = dict(self.rows)
        broken["BNBUSDT"] = RuntimeError("network blocked")
        scanner = CloudScanner(self.config, FakeMarket(broken), self.repo, self.outbox, now_fn=lambda: self.now)
        with self.assertRaises(RuntimeError):
            scanner.run_once()
        self.assertEqual([], self.repo.bundles)

    def test_overlap_and_completed_runs_skip_without_writes(self):
        self.repo.locked = True
        scanner = CloudScanner(self.config, FakeMarket(self.rows), self.repo, self.outbox, now_fn=lambda: self.now)
        self.assertEqual("SKIPPED_LOCKED", scanner.run_once()["status"])
        self.repo.locked = False
        self.repo.completed = True
        self.assertEqual("SKIPPED_COMPLETED", scanner.run_once()["status"])
        self.assertEqual([], self.repo.bundles)

    def test_success_is_finite_persist_first_then_notify(self):
        signal = {"id": "signal-1", "symbol": "BTCUSDT", "side": "LONG", "signalType": "Primary", "signalDate": "2026-09-20"}
        scanner = CloudScanner(self.config, FakeMarket(self.rows), self.repo, self.outbox, now_fn=lambda: self.now)
        with (
            mock.patch("app.nxt_cloud.scanner.rules.btc_regime_by_date", return_value={}),
            mock.patch("app.nxt_cloud.scanner.rules.latest_signal_for_symbol", side_effect=[signal, None, None]),
        ):
            result = scanner.run_once()
        self.assertEqual("COMPLETED", result["status"])
        self.assertEqual(1, result["newSignals"])
        self.assertEqual(1, len(self.repo.bundles))
        self.assertTrue(self.outbox.items[0][0].startswith("cloud-shadow:"))


class OutboxSafetyTests(unittest.TestCase):
    def test_prefix_disclaimer_dedupe_and_delivery(self):
        repo = FakeRepository()
        sent = []
        outbox = PostgresOutbox(repo, sent.append)
        self.assertTrue(outbox.enqueue("cloud-shadow:test:1", "hello", {}))
        self.assertFalse(outbox.enqueue("cloud-shadow:test:1", "hello", {}))
        self.assertTrue(repo.outbox[0]["message"].startswith(SHADOW_PREFIX))
        self.assertIn(SHADOW_DISCLAIMER, repo.outbox[0]["message"])
        self.assertEqual(1, outbox.flush())
        self.assertEqual(["1"], repo.delivered)

    def test_local_namespace_is_rejected(self):
        with self.assertRaises(ValueError):
            PostgresOutbox(FakeRepository(), lambda _: None).enqueue("signal:local-key", "hello", {})


class PostgresAdapterContractTests(unittest.TestCase):
    def test_decision_write_uses_transaction_lock_and_parameters(self):
        cursor = FakeCursor([None])
        repository = PostgresRepository("", pool=FakePool(cursor))
        with mock.patch("app.nxt_cloud.postgres.uuid.uuid4", return_value="decision-id"):
            result = repository.record_decision("owner-1", {"signalId": "signal-1", "decision": "Accept", "note": "reviewed"}, "idem-1")
        self.assertEqual({"decisionId": "decision-id", "status": "recorded"}, result)
        queries = [query for query, _ in cursor.executed]
        self.assertIn("pg_advisory_xact_lock", queries[0])
        self.assertTrue(any("INSERT INTO decisions" in query for query in queries))
        self.assertTrue(all("owner-1" not in query and "signal-1" not in query for query in queries))

    def test_invalid_business_values_are_rejected_before_sql(self):
        cursor = FakeCursor()
        repository = PostgresRepository("", pool=FakePool(cursor))
        with self.assertRaises(ValueError):
            repository.record_decision("owner-1", {"signalId": "s", "decision": "Execute"}, "idem")
        with self.assertRaises(ValueError):
            repository.track_position("owner-1", {"signalId": "s", "quantity": 0, "entryPrice": 10}, "idem")
        self.assertEqual([], cursor.executed)


class BuildContractTests(unittest.TestCase):
    def test_container_is_non_root_and_one_image_supports_two_roles(self):
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        entrypoint = (ROOT / "app" / "nxt_cloud" / "entrypoint.py").read_text(encoding="utf-8")
        self.assertRegex(dockerfile.splitlines()[0], r"^FROM python:3\.13\.7-slim@sha256:[0-9a-f]{64}$")
        self.assertIn("USER nxt", dockerfile)
        self.assertIn("app.nxt_cloud.entrypoint", dockerfile)
        self.assertIn('config.role == "web"', entrypoint)
        self.assertIn("run_scanner", entrypoint)

    def test_cloud_source_has_no_signed_binance_path_or_key_header(self):
        source = "\n".join(path.read_text(encoding="utf-8") for path in (ROOT / "app" / "nxt_cloud").glob("*.py"))
        for forbidden in ("/fapi/v1/order", "/fapi/v2/account", "X-MBX-APIKEY", "signature="):
            self.assertNotIn(forbidden, source)

    def test_dependency_versions_are_exactly_pinned(self):
        lines = [line for line in (ROOT / "requirements-cloud.lock").read_text(encoding="utf-8").splitlines() if line]
        self.assertTrue(all("==" in line for line in lines))


if __name__ == "__main__":
    unittest.main()
