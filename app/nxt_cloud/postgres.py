from __future__ import annotations

import json
import uuid
from collections.abc import Mapping, Sequence
from contextlib import contextmanager
from typing import Any


REQUIRED_SCHEMA_VERSION = 2
LIST_QUERIES = {
    "signals": "SELECT signal_id, symbol, side, signal_type, signal_date, payload, created_at FROM signals WHERE environment = 'SHADOW' AND owner_user_id = %s ORDER BY signal_date DESC, created_at DESC LIMIT %s OFFSET %s",
    "scans": "SELECT run_id, candle_date, status, source, input_hash, rule_version, started_at, finished_at, errors_json FROM scan_runs WHERE environment = 'SHADOW' AND owner_user_id = %s ORDER BY started_at DESC LIMIT %s OFFSET %s",
    "followups": "SELECT recommendation_id, signal_id, position_id, candle_date, action, priority, status, outcome, payload, created_at FROM followup_recommendations WHERE environment = 'SHADOW' AND owner_user_id = %s ORDER BY candle_date DESC, priority, created_at DESC LIMIT %s OFFSET %s",
    "decisions": "SELECT DISTINCT ON (signal_id) decision_id, signal_id, decision, note, created_at FROM decisions WHERE environment = 'SHADOW' AND owner_user_id = %s ORDER BY signal_id, created_at DESC, decision_id DESC LIMIT %s OFFSET %s",
    "positions": "SELECT position_id, signal_id, entry_price, quantity, lifecycle, payload, created_at, updated_at FROM manual_positions WHERE environment = 'SHADOW' AND owner_user_id = %s ORDER BY updated_at DESC LIMIT %s OFFSET %s",
}


def _json(value: object) -> str:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False, default=str)


class PostgresRepository:
    """Short-transaction PostgreSQL adapter. Schema creation belongs to P4 migrations."""

    def __init__(self, database_url: str, pool: Any | None = None) -> None:
        if pool is not None:
            self.pool = pool
            return
        if not database_url:
            raise ValueError("DATABASE_URL is required")
        try:
            from psycopg.rows import dict_row
            from psycopg_pool import ConnectionPool
        except ImportError as exc:
            raise RuntimeError("psycopg[binary,pool] is required for PostgreSQL") from exc
        self.pool = ConnectionPool(
            database_url,
            min_size=0,
            max_size=4,
            timeout=10,
            kwargs={"row_factory": dict_row, "connect_timeout": 10},
            open=False,
        )

    @contextmanager
    def _connection(self):
        # Gunicorn may construct the WSGI app before forking a worker. Opening
        # psycopg_pool background threads lazily avoids inheriting a broken
        # pre-fork pool in the serving process.
        if getattr(self.pool, "closed", False):
            self.pool.open()
        with self.pool.connection() as conn:
            yield conn

    def close(self) -> None:
        close = getattr(self.pool, "close", None)
        if close:
            close()

    def ping(self) -> bool:
        try:
            with self._connection() as conn, conn.cursor() as cur:
                cur.execute("SELECT 1 AS ok")
                row = cur.fetchone()
                return bool(row and (row.get("ok") if isinstance(row, dict) else row[0]) == 1)
        except Exception:
            return False

    def schema_current(self) -> bool:
        try:
            with self._connection() as conn, conn.cursor() as cur:
                cur.execute("SELECT COALESCE(MAX(version), 0) AS version FROM schema_migrations")
                row = cur.fetchone()
                version = row.get("version") if isinstance(row, dict) else row[0]
                return int(version) >= REQUIRED_SCHEMA_VERSION
        except Exception:
            return False

    def dashboard_state(self, owner_user_id: str) -> Mapping[str, object]:
        return {
            "environment": "SHADOW",
            "signals": list(self.list_records("signals", owner_user_id, 50, 0)),
            "scanRuns": list(self.list_records("scans", owner_user_id, 20, 0)),
            "followupRecommendations": list(self.list_records("followups", owner_user_id, 100, 0)),
            "decisions": list(self.list_records("decisions", owner_user_id, 100, 0)),
            "positions": list(self.list_records("positions", owner_user_id, 100, 0)),
        }

    def list_records(self, kind: str, owner_user_id: str, limit: int, offset: int) -> Sequence[Mapping[str, object]]:
        query = LIST_QUERIES.get(kind)
        if query is None:
            raise ValueError("unsupported record type")
        with self._connection() as conn, conn.cursor() as cur:
            cur.execute(query, (owner_user_id, limit, offset))
            return list(cur.fetchall())

    @staticmethod
    def _existing_idempotent(cur: Any, owner_user_id: str, key: str, operation: str) -> Mapping[str, object] | None:
        cur.execute(
            "SELECT response_json FROM idempotency_keys WHERE owner_user_id = %s AND idempotency_key = %s AND operation = %s",
            (owner_user_id, key, operation),
        )
        row = cur.fetchone()
        if not row:
            return None
        value = row.get("response_json") if isinstance(row, dict) else row[0]
        return value if isinstance(value, dict) else json.loads(value)

    @staticmethod
    def _lock_idempotency(cur: Any, owner_user_id: str, key: str, operation: str) -> None:
        cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"{owner_user_id}:{operation}:{key}",))

    @staticmethod
    def _save_idempotent(cur: Any, owner_user_id: str, key: str, operation: str, response: Mapping[str, object]) -> None:
        cur.execute(
            "INSERT INTO idempotency_keys(owner_user_id, idempotency_key, operation, response_json) VALUES (%s, %s, %s, %s::jsonb)",
            (owner_user_id, key, operation, _json(response)),
        )

    def record_decision(self, owner_user_id: str, payload: Mapping[str, object], idempotency_key: str) -> Mapping[str, object]:
        operation = "decision"
        decision = str(payload["decision"])
        if decision not in {"Accept", "Reject", "Watchlist"}:
            raise ValueError("decision must be Accept, Reject or Watchlist")
        with self._connection() as conn, conn.transaction(), conn.cursor() as cur:
            self._lock_idempotency(cur, owner_user_id, idempotency_key, operation)
            prior = self._existing_idempotent(cur, owner_user_id, idempotency_key, operation)
            if prior:
                return prior
            decision_id = str(uuid.uuid4())
            cur.execute(
                "INSERT INTO decisions(decision_id, environment, owner_user_id, signal_id, decision, note) VALUES (%s, 'SHADOW', %s, %s, %s, %s)",
                (decision_id, owner_user_id, str(payload["signalId"]), decision, str(payload.get("note", ""))),
            )
            response = {"decisionId": decision_id, "status": "recorded"}
            self._save_idempotent(cur, owner_user_id, idempotency_key, operation, response)
            return response

    def track_position(self, owner_user_id: str, payload: Mapping[str, object], idempotency_key: str) -> Mapping[str, object]:
        operation = "position"
        quantity = float(payload["quantity"])
        entry_price = float(payload["entryPrice"])
        if quantity <= 0 or entry_price <= 0:
            raise ValueError("quantity and entryPrice must be positive")
        with self._connection() as conn, conn.transaction(), conn.cursor() as cur:
            self._lock_idempotency(cur, owner_user_id, idempotency_key, operation)
            prior = self._existing_idempotent(cur, owner_user_id, idempotency_key, operation)
            if prior:
                return prior
            position_id = str(uuid.uuid4())
            cur.execute(
                "INSERT INTO manual_positions(position_id, environment, owner_user_id, signal_id, entry_price, quantity, lifecycle) VALUES (%s, 'SHADOW', %s, %s, %s, %s, 'OPEN')",
                (position_id, owner_user_id, str(payload["signalId"]), entry_price, quantity),
            )
            response = {"positionId": position_id, "status": "tracked"}
            self._save_idempotent(cur, owner_user_id, idempotency_key, operation, response)
            return response

    def record_followup_outcome(self, owner_user_id: str, recommendation_id: str, payload: Mapping[str, object], idempotency_key: str) -> Mapping[str, object]:
        operation = "followup-outcome"
        outcome = str(payload["outcome"])
        if outcome not in {"Applied", "Not Applied", "Snoozed", "Already Closed"}:
            raise ValueError("invalid follow-up outcome")
        with self._connection() as conn, conn.transaction(), conn.cursor() as cur:
            self._lock_idempotency(cur, owner_user_id, idempotency_key, operation)
            prior = self._existing_idempotent(cur, owner_user_id, idempotency_key, operation)
            if prior:
                return prior
            cur.execute(
                "UPDATE followup_recommendations SET status = 'Acknowledged', outcome = %s, outcome_at = now() WHERE recommendation_id = %s AND owner_user_id = %s AND environment = 'SHADOW' RETURNING recommendation_id",
                (outcome, recommendation_id, owner_user_id),
            )
            if not cur.fetchone():
                raise ValueError("follow-up recommendation not found")
            response = {"recommendationId": recommendation_id, "status": "Acknowledged", "outcome": outcome}
            self._save_idempotent(cur, owner_user_id, idempotency_key, operation, response)
            return response

    @contextmanager
    def scan_lock(self, lock_key: str):
        with self._connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT pg_try_advisory_lock(hashtext(%s)) AS acquired", (lock_key,))
            row = cur.fetchone()
            acquired = bool(row.get("acquired") if isinstance(row, dict) else row[0])
            try:
                yield acquired
            finally:
                if acquired:
                    cur.execute("SELECT pg_advisory_unlock(hashtext(%s))", (lock_key,))

    def completed_scan_exists(self, environment: str, candle_date: str, rule_version: str) -> bool:
        with self._connection() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM scan_runs WHERE environment = %s AND candle_date = %s AND rule_version = %s AND status = 'COMPLETED' LIMIT 1",
                (environment, candle_date, rule_version),
            )
            return cur.fetchone() is not None

    def existing_signal_ids(self, environment: str) -> set[str]:
        with self._connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT signal_id FROM signals WHERE environment = %s", (environment,))
            return {str(row.get("signal_id") if isinstance(row, dict) else row[0]) for row in cur.fetchall()}

    def accepted_monitor_subjects(self, environment: str) -> Sequence[Mapping[str, object]]:
        with self._connection() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT signal_id, symbol, signal_payload AS signal, plan_payload AS plan, position_id, position_payload AS position, acknowledged_actions AS \"acknowledgedActions\", pending_followup AS \"pendingFollowup\" FROM accepted_monitor_subjects WHERE environment = %s",
                (environment,),
            )
            subjects = list(cur.fetchall())
        for subject in subjects:
            pending = subject.get("pendingFollowup") if isinstance(subject, dict) else None
            if not isinstance(pending, dict):
                continue
            payload = dict(pending)
            subject["pendingFollowup"] = {
                "recommendation_id": payload.get("recommendationId") or payload.get("recommendation_id"),
                "action": payload.get("action"),
                "action_label": payload.get("actionLabel") or payload.get("action_label") or payload.get("action"),
                "priority": payload.get("priority", 99),
                "payload": payload,
            }
        return subjects

    def persist_scan_bundle(self, bundle: Mapping[str, object]) -> None:
        run = bundle["run"]
        with self._connection() as conn, conn.transaction(), conn.cursor() as cur:
            cur.execute(
                "INSERT INTO scan_runs(run_id, environment, owner_user_id, candle_date, status, source, input_hash, rule_version, started_at, finished_at, errors_json) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb) ON CONFLICT (environment, candle_date, rule_version, source) DO NOTHING",
                (run["runId"], run["environment"], run.get("ownerUserId"), run["candleDate"], run["status"], run["source"], run["inputHash"], run["ruleVersion"], run["startedAt"], run["finishedAt"], _json(run.get("errors", []))),
            )
            for item in bundle.get("symbols", []):
                cur.execute(
                    "INSERT INTO scan_run_symbols(run_id, symbol, latest_closed_date, row_count, data_hash, status) VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT (run_id, symbol) DO NOTHING",
                    (run["runId"], item["symbol"], item["latestClosedDate"], item["rowCount"], item["dataHash"], item["status"]),
                )
            for signal in bundle.get("signals", []):
                cur.execute(
                    "INSERT INTO signals(signal_id, environment, owner_user_id, symbol, side, signal_type, signal_date, rule_version, payload) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb) ON CONFLICT (environment, signal_id) DO NOTHING",
                    (signal["id"], run["environment"], run.get("ownerUserId"), signal["symbol"], signal["side"], signal["signalType"], signal["signalDate"], run["ruleVersion"], _json(signal)),
                )
                cur.execute(
                    "INSERT INTO trade_plans(plan_id, environment, owner_user_id, signal_id, rule_version, status, payload) VALUES (%s,%s,%s,%s,%s,'LEGACY_AUDIT',%s::jsonb) ON CONFLICT (environment, plan_id) DO NOTHING",
                    (f"{signal['id']}:{run['ruleVersion']}", run["environment"], run.get("ownerUserId"), signal["id"], run["ruleVersion"], _json({"orders": signal.get("orders", []), "legacyFixedRisk": True})),
                )

    def persist_followup_recommendations(self, environment: str, items: Sequence[Mapping[str, object]]) -> None:
        with self._connection() as conn, conn.transaction(), conn.cursor() as cur:
            for item in items:
                cur.execute(
                    "INSERT INTO followup_recommendations(recommendation_id, environment, owner_user_id, signal_id, position_id, candle_date, action, priority, status, payload) SELECT %s,%s,s.owner_user_id,%s,%s,%s,%s,%s,%s,%s::jsonb FROM signals s WHERE s.environment=%s AND s.signal_id=%s ON CONFLICT (environment, recommendation_id) DO NOTHING",
                    (item["recommendationId"], environment, item["signalId"], item.get("positionId"), item["candleDate"], item["action"], item["priority"], item["status"], _json(item), environment, item["signalId"]),
                )

    def enqueue_outbox(self, environment: str, delivery_key: str, message: str, metadata: Mapping[str, object]) -> bool:
        with self._connection() as conn, conn.transaction(), conn.cursor() as cur:
            cur.execute(
                "INSERT INTO notification_outbox(outbox_id, environment, delivery_key, channel, message, metadata, status) VALUES (%s,%s,%s,'TELEGRAM',%s,%s::jsonb,'PENDING') ON CONFLICT (environment, delivery_key) DO NOTHING RETURNING outbox_id",
                (str(uuid.uuid4()), environment, delivery_key, message, _json(metadata)),
            )
            return cur.fetchone() is not None

    def pending_outbox(self, environment: str, limit: int = 20) -> Sequence[Mapping[str, object]]:
        with self._connection() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT outbox_id, delivery_key, message, metadata, attempts FROM notification_outbox WHERE environment = %s AND status IN ('PENDING','FAILED') ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT %s",
                (environment, limit),
            )
            return list(cur.fetchall())

    def mark_outbox_delivered(self, outbox_id: str) -> None:
        with self._connection() as conn, conn.transaction(), conn.cursor() as cur:
            cur.execute("UPDATE notification_outbox SET status='DELIVERED', delivered_at=now(), attempts=attempts+1, last_error_code=NULL WHERE outbox_id=%s", (outbox_id,))

    def mark_outbox_failed(self, outbox_id: str, error_code: str) -> None:
        with self._connection() as conn, conn.transaction(), conn.cursor() as cur:
            cur.execute("UPDATE notification_outbox SET status='FAILED', attempts=attempts+1, last_error_code=%s WHERE outbox_id=%s", (error_code[:80], outbox_id))
