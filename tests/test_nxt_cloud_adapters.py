from __future__ import annotations

import io
import json
import threading
import unittest
import urllib.parse
import urllib.request
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest import mock
from wsgiref.simple_server import make_server

from app.nxt_cloud.config import CloudConfig
from app.nxt_cloud.outbox import DisabledNotificationOutbox, PostgresOutbox, SHADOW_DISCLAIMER, SHADOW_PREFIX, TelegramSender
from app.nxt_cloud.postgres import PostgresRepository
from app.nxt_cloud.quantity import render_quantity_calculator
from app.nxt_cloud.scanner import CloudScanner, DataGateError, validate_candle_sets
from scripts.nxt_cloud_telegram_test import build_test_message
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
    def __init__(self, fetchone_values=None, fetchall_values=None):
        self.fetchone_values = list(fetchone_values or [])
        self.fetchall_values = list(fetchall_values or [])
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
        return self.fetchall_values


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
        self.closed = False
        self.open_calls = 0

    def open(self):
        self.closed = False
        self.open_calls += 1

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
        "supabase_url": "https://project.supabase.co",
        "supabase_publishable_key": "public-test-key",
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

    def test_notification_mode_defaults_disabled_and_rejects_unknown_mode(self):
        self.assertEqual("disabled", CloudConfig.from_env({"ROLE": "scanner"}).notification_mode)
        with self.assertRaises(ValueError):
            CloudConfig.from_env({"ROLE": "scanner", "NXT_NOTIFICATION_MODE": "auto"})

    def test_force_run_is_scanner_only_and_uses_a_safe_short_token(self):
        self.assertEqual("manual-20260922", CloudConfig.from_env({"ROLE": "scanner", "NXT_FORCE_RUN_ID": "manual-20260922"}).force_run_id)
        with self.assertRaises(ValueError):
            CloudConfig.from_env({"ROLE": "web", "NXT_FORCE_RUN_ID": "manual-20260922"})
        with self.assertRaises(ValueError):
            CloudConfig.from_env({"ROLE": "scanner", "NXT_FORCE_RUN_ID": "unsafe token"})


class WebSecurityTests(unittest.TestCase):
    def setUp(self):
        self.repo = FakeRepository()
        self.app = CloudWebApp(cloud_config(), self.repo, FakeVerifier())

    def test_health_is_public_and_readiness_is_token_limited(self):
        status, _, body = wsgi_call(self.app, path="/healthz")
        self.assertEqual(200, status)
        self.assertTrue(json.loads(body)["alive"])
        self.assertEqual(200, wsgi_call(self.app, path="/health")[0])
        self.assertEqual(401, wsgi_call(self.app, path="/readyz")[0])
        self.assertEqual(200, wsgi_call(self.app, path="/readyz", headers={"X-NXT-Health-Token": "health-secret"})[0])
        self.assertEqual(401, wsgi_call(self.app, path="/ready")[0])
        self.assertEqual(200, wsgi_call(self.app, path="/ready", headers={"X-NXT-Health-Token": "health-secret"})[0])

    def test_business_routes_require_password_authenticated_owner(self):
        self.assertEqual(401, wsgi_call(self.app, path="/api/state")[0])
        self.assertEqual(200, wsgi_call(self.app, path="/api/state", token="ok")[0])
        password_only = CloudWebApp(cloud_config(), self.repo, FakeVerifier({"sub": "owner-1", "email": "owner@example.com", "aal": "aal1"}))
        self.assertEqual(200, wsgi_call(password_only, path="/api/state", token="ok")[0])
        unauthenticated = CloudWebApp(cloud_config(), self.repo, FakeVerifier({"sub": "owner-1", "email": "owner@example.com", "aal": "aal0"}))
        self.assertEqual(401, wsgi_call(unauthenticated, path="/api/state", token="ok")[0])
        outsider = CloudWebApp(cloud_config(), self.repo, FakeVerifier({"sub": "other", "email": "other@example.com", "aal": "aal2"}))
        self.assertEqual(401, wsgi_call(outsider, path="/api/state", token="ok")[0])

    def test_browser_login_is_public_and_session_accepts_password_aal1_owner(self):
        status, headers, body = wsgi_call(self.app, path="/login")
        self.assertEqual(200, status)
        self.assertIn("Mật khẩu Supabase Auth".encode("utf-8"), body)
        self.assertNotIn(b"totp", body.lower())
        self.assertNotIn(b"/factors/", body)
        self.assertIn("connect-src 'self' https://project.supabase.co", headers["Content-Security-Policy"])

        password_only = CloudWebApp(cloud_config(), self.repo, FakeVerifier({"sub": "owner-1", "email": "owner@example.com", "aal": "aal1"}))
        status, headers, body = wsgi_call(
            password_only,
            method="POST",
            path="/auth/session",
            token="ok",
            body={},
            headers={"Origin": "https://nxt.example"},
        )
        self.assertEqual(200, status)
        self.assertIn("__Host-nxt_session=ok", headers["Set-Cookie"])
        self.assertEqual("aal1", json.loads(body)["aal"])

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

    def test_dashboard_renders_signal_and_followup_action_center(self):
        self.repo.dashboard_state = lambda _owner: {
            "environment": "SHADOW",
            "signals": [
                {
                    "signal_id": "signal-1",
                    "payload": {
                        "id": "signal-1",
                        "symbol": "BTCUSDT",
                        "side": "LONG",
                        "signalType": "Primary",
                        "signalDate": "2026-09-21",
                        "detectedAt": "2026-09-21T01:02:03Z",
                        "entryPrice": 100.0,
                        "initialStop": 90.0,
                    },
                }
            ],
            "decisions": [],
            "positions": [],
            "scanRuns": [],
            "followupRecommendations": [
                {
                    "recommendation_id": "rec-1",
                    "action": "MOVE_STOP_TO_BE",
                    "status": "Pending",
                    "candle_date": "2026-09-21",
                    "created_at": "2026-09-21T03:04:05+00:00",
                    "payload": {
                        "symbol": "BTCUSDT",
                        "side": "LONG",
                        "actionLabel": "Move stop to BE",
                        "rationale": "TP1 reached",
                    },
                }
            ],
        }
        status, _, body = wsgi_call(self.app, path="/", token="ok")
        self.assertEqual(200, status)
        page = body.decode("utf-8")
        self.assertIn("Action Center", page)
        self.assertIn("2 pending", page)
        self.assertIn('data-decision="Accept"', page)
        self.assertIn('data-decision="Reject"', page)
        self.assertIn('data-decision="Watchlist"', page)
        self.assertIn('data-outcome="Applied"', page)
        self.assertIn("Move stop to BE", page)
        self.assertIn("Signal D1: 2026-09-21 · Phát hiện: 2026-09-21 08:02 ICT", page)
        self.assertIn("Nến D1: 2026-09-21 · Tạo: 2026-09-21 10:04 ICT", page)
        self.assertIn('content="width=device-width,initial-scale=1,viewport-fit=cover"', page)
        self.assertIn("html,body{max-width:100%;overflow-x:hidden}", page)
        self.assertIn("table,tbody,tr,td{display:block;width:100%}", page)
        self.assertIn('data-label="Symbol"', page)
        self.assertIn('data-label="Quantity"', page)

    def test_dashboard_action_center_matches_local_followup_filter(self):
        self.repo.dashboard_state = lambda _owner: {
            "environment": "SHADOW",
            "signals": [],
            "decisions": [],
            "positions": [],
            "scanRuns": [],
            "followupRecommendations": [
                {
                    "recommendation_id": "stale-1",
                    "action": "DATA_STALE",
                    "status": "Pending",
                    "payload": {"symbol": "BTCUSDT", "side": "LONG", "actionLabel": "KHONG THE DANH GIA - DATA STALE"},
                },
                {
                    "recommendation_id": "none-1",
                    "action": "NO_ACTION",
                    "status": "Pending",
                    "payload": {"symbol": "BNBUSDT", "side": "LONG", "actionLabel": "No action"},
                },
                {
                    "recommendation_id": "action-1",
                    "action": "MOVE_STOP_TO_BE",
                    "status": "Pending",
                    "payload": {"symbol": "SOLUSDT", "side": "SHORT", "actionLabel": "Move stop to BE", "rationale": "TP1 reached"},
                },
                {
                    "recommendation_id": "history-1",
                    "action": "TAKE_TP1_30_MOVE_BE",
                    "status": "Acknowledged",
                    "outcome": "Applied",
                    "payload": {"symbol": "BTCUSDT", "side": "LONG", "actionLabel": "Take TP1", "rationale": "Historical action"},
                },
                {
                    "recommendation_id": "reminder-1",
                    "action": "PENDING_CONFIRMATION",
                    "status": "Reminder",
                    "payload": {"symbol": "BNBUSDT", "side": "LONG", "actionLabel": "Pending confirmation", "rationale": "Confirm external trade"},
                },
            ],
        }
        status, _, body = wsgi_call(self.app, path="/", token="ok")
        self.assertEqual(200, status)
        page = body.decode("utf-8")
        self.assertNotIn("DATA STALE", page)
        self.assertNotIn("No action", page)
        self.assertIn("Move stop to BE", page)
        self.assertIn("Take TP1", page)
        self.assertIn("Applied", page)
        self.assertIn("Pending confirmation", page)
        self.assertIn("2 pending", page)

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
        self.assertIn('id="qty-notional"', payload)
        self.assertIn("notional=qty*entry", payload)
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
        signal = {
            "id": "signal-1",
            "symbol": "BTCUSDT",
            "side": "LONG",
            "signalType": "Primary",
            "signalDate": "2026-09-20",
            "entryDate": "2026-09-21",
            "entryPrice": 100.0,
            "initialStop": 90.0,
            "tp1": 120.0,
            "atr14": 8.0,
            "rsi14": 55.0,
            "distanceToEma50Atr": 0.5,
            "orders": [],
        }
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
        self.assertIn("NXT v3.5 Portfolio", self.outbox.items[0][1])
        self.assertIn("<b>ACTION CAN LUU Y:", self.outbox.items[0][1])

    def test_stale_followup_is_persisted_for_audit_but_not_notified(self):
        self.repo.accepted_monitor_subjects = lambda _environment: [{"signal_id": "signal-1", "symbol": "BTCUSDT"}]
        stale = {
            "recommendationId": "stale-1",
            "signalId": "signal-1",
            "symbol": "BTCUSDT",
            "action": "DATA_STALE",
        }
        scanner = CloudScanner(self.config, FakeMarket(self.rows), self.repo, self.outbox, now_fn=lambda: self.now)
        with (
            mock.patch("app.nxt_cloud.scanner.rules.btc_regime_by_date", return_value={}),
            mock.patch("app.nxt_cloud.scanner.rules.latest_signal_for_symbol", return_value=None),
            mock.patch("app.nxt_cloud.scanner.rules.evaluate_accepted_signal_followup", return_value=stale),
        ):
            result = scanner.run_once()
        self.assertEqual("COMPLETED", result["status"])
        self.assertEqual([stale], self.repo.followups)
        self.assertEqual([], self.outbox.items)

    def test_force_run_bypasses_completed_gate_and_namespaces_delivery(self):
        self.repo.completed = True
        signal = {
            "id": "signal-force-1",
            "symbol": "BTCUSDT",
            "side": "LONG",
            "signalType": "Primary",
            "signalDate": "2026-09-20",
            "entryDate": "2026-09-21",
            "entryPrice": 100.0,
            "initialStop": 90.0,
            "tp1": 120.0,
            "atr14": 8.0,
            "rsi14": 55.0,
            "distanceToEma50Atr": 0.5,
            "orders": [],
        }
        config = cloud_config(role="scanner", force_run_id="manual-20260922")
        scanner = CloudScanner(config, FakeMarket(self.rows), self.repo, self.outbox, now_fn=lambda: self.now)
        with (
            mock.patch("app.nxt_cloud.scanner.rules.btc_regime_by_date", return_value={}),
            mock.patch("app.nxt_cloud.scanner.rules.latest_signal_for_symbol", side_effect=[signal, None, None]),
        ):
            result = scanner.run_once()
        self.assertEqual("COMPLETED", result["status"])
        self.assertEqual("manual-20260922", result["forceRunId"])
        self.assertEqual(1, len(self.repo.bundles))
        self.assertEqual("BINANCE_USDM_PUBLIC_1D:FORCE:MANUAL-20260922", self.repo.bundles[0]["run"]["source"])
        self.assertIn(":force:manual-20260922", self.outbox.items[0][0])
        self.assertEqual("manual-20260922", self.outbox.items[0][2]["forceRunId"])


class OutboxSafetyTests(unittest.TestCase):
    def test_cloud_telegram_connectivity_message_is_unambiguously_shadow(self):
        message = build_test_message()
        self.assertTrue(message.startswith(SHADOW_PREFIX))
        self.assertIn(SHADOW_DISCLAIMER, message)
        self.assertIn("no signal, no order, no schedule", message)

    def test_disabled_mode_never_persists_or_delivers_notifications(self):
        outbox = DisabledNotificationOutbox()
        self.assertFalse(outbox.enqueue("cloud-shadow:test:disabled", "hello", {}))
        self.assertEqual(1, outbox.suppressed)
        self.assertEqual(0, outbox.flush())
        with self.assertRaises(ValueError):
            outbox.enqueue("local:test", "hello", {})

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

    def test_cloud_sender_uses_same_html_parse_mode_as_local(self):
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = b'{"ok":true}'
        with mock.patch("app.nxt_cloud.outbox.urllib.request.urlopen", return_value=response) as urlopen:
            TelegramSender("token", "chat")("<b>ACTION</b>")
        request = urlopen.call_args.args[0]
        payload = urllib.parse.parse_qs(request.data.decode("utf-8"))
        self.assertEqual(["HTML"], payload["parse_mode"])
        self.assertEqual(["<b>ACTION</b>"], payload["text"])


class PostgresAdapterContractTests(unittest.TestCase):
    def test_pool_opens_lazily_in_serving_process(self):
        pool = FakePool(FakeCursor([{"ok": 1}]))
        pool.closed = True
        repository = PostgresRepository("", pool=pool)
        self.assertTrue(repository.ping())
        self.assertEqual(1, pool.open_calls)

    def test_monitor_pending_payload_is_normalized_for_shared_rule_engine(self):
        pending = {
            "recommendationId": "rec-1",
            "action": "MOVE_STOP_TO_BE",
            "actionLabel": "Move stop",
            "priority": 4,
        }
        cursor = FakeCursor(fetchall_values=[{"signal_id": "signal-1", "pendingFollowup": pending}])
        repository = PostgresRepository("", pool=FakePool(cursor))
        subject = repository.accepted_monitor_subjects("SHADOW")[0]
        normalized = subject["pendingFollowup"]
        self.assertEqual("rec-1", normalized["recommendation_id"])
        self.assertEqual("MOVE_STOP_TO_BE", normalized["action"])
        self.assertEqual(pending, normalized["payload"])

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

    def test_followup_outcome_uses_local_status_and_outcome_model(self):
        cursor = FakeCursor([None, {"recommendation_id": "rec-1"}])
        repository = PostgresRepository("", pool=FakePool(cursor))
        result = repository.record_followup_outcome("owner-1", "rec-1", {"outcome": "Already Closed"}, "idem-1")
        self.assertEqual({"recommendationId": "rec-1", "status": "Acknowledged", "outcome": "Already Closed"}, result)
        update = next((query, params) for query, params in cursor.executed if "UPDATE followup_recommendations" in query)
        self.assertIn("status = 'Acknowledged'", update[0])
        self.assertIn("outcome = %s", update[0])
        self.assertEqual(("Already Closed", "rec-1", "owner-1"), update[1])


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
