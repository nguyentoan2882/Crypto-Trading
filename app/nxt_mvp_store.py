from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1] / "runtime" / "nxt_signal_app"
DB_PATH = APP_DIR / "nxt_mvp1.sqlite"
RULE_VERSION = "NXT v3.5 GuardDirectional_30_10At4R_60 legacy-entry-rule"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def ict_today() -> str:
    return datetime.now(timezone(timedelta(hours=7))).date().isoformat()


def connect() -> sqlite3.Connection:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_db() -> None:
    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS settings (
              key TEXT PRIMARY KEY,
              value TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS equity_history (
              id TEXT PRIMARY KEY,
              old_equity REAL,
              new_equity REAL NOT NULL,
              delta_usd REAL,
              delta_pct REAL,
              effective_at TEXT NOT NULL,
              entered_at TEXT NOT NULL,
              reason TEXT NOT NULL,
              note TEXT,
              source TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS scan_runs (
              run_id TEXT PRIMARY KEY,
              started_at TEXT NOT NULL,
              finished_at TEXT NOT NULL,
              status TEXT NOT NULL,
              candle_date TEXT,
              symbols_json TEXT NOT NULL,
              checked_json TEXT NOT NULL,
              errors_json TEXT NOT NULL,
              system_name TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS signals (
              signal_id TEXT PRIMARY KEY,
              run_id TEXT,
              symbol TEXT NOT NULL,
              side TEXT NOT NULL,
              signal_type TEXT NOT NULL,
              signal_date TEXT NOT NULL,
              entry_date TEXT NOT NULL,
              payload_json TEXT NOT NULL,
              created_at TEXT NOT NULL,
              FOREIGN KEY(run_id) REFERENCES scan_runs(run_id)
            );
            CREATE TABLE IF NOT EXISTS trade_plans (
              plan_id TEXT PRIMARY KEY,
              signal_id TEXT NOT NULL,
              version INTEGER NOT NULL,
              status TEXT NOT NULL,
              payload_json TEXT NOT NULL,
              equity_record_id TEXT,
              created_at TEXT NOT NULL,
              UNIQUE(signal_id, version),
              FOREIGN KEY(signal_id) REFERENCES signals(signal_id),
              FOREIGN KEY(equity_record_id) REFERENCES equity_history(id)
            );
            CREATE TABLE IF NOT EXISTS decisions (
              decision_id TEXT PRIMARY KEY,
              signal_id TEXT NOT NULL,
              decision TEXT NOT NULL,
              actor TEXT NOT NULL,
              channel TEXT NOT NULL,
              note TEXT,
              created_at TEXT NOT NULL,
              FOREIGN KEY(signal_id) REFERENCES signals(signal_id)
            );
            CREATE TABLE IF NOT EXISTS manual_positions (
              position_id TEXT PRIMARY KEY,
              signal_id TEXT,
              symbol TEXT NOT NULL,
              side TEXT NOT NULL,
              entry_time TEXT NOT NULL,
              entry_price REAL NOT NULL,
              quantity REAL NOT NULL,
              current_sl REAL,
              current_tp1 REAL,
              lifecycle TEXT NOT NULL,
              rule_version TEXT NOT NULL,
              payload_json TEXT NOT NULL,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              FOREIGN KEY(signal_id) REFERENCES signals(signal_id)
            );
            CREATE TABLE IF NOT EXISTS recommendations (
              recommendation_id TEXT PRIMARY KEY,
              position_id TEXT NOT NULL,
              candle_date TEXT NOT NULL,
              action TEXT NOT NULL,
              status TEXT NOT NULL,
              priority INTEGER NOT NULL,
              rationale TEXT NOT NULL,
              payload_json TEXT NOT NULL,
              created_at TEXT NOT NULL,
              outcome_at TEXT,
              FOREIGN KEY(position_id) REFERENCES manual_positions(position_id)
            );
            CREATE TABLE IF NOT EXISTS followup_recommendations (
              recommendation_id TEXT PRIMARY KEY,
              signal_id TEXT NOT NULL,
              position_id TEXT,
              subject_type TEXT NOT NULL,
              candle_date TEXT NOT NULL,
              action TEXT NOT NULL,
              action_label TEXT NOT NULL,
              status TEXT NOT NULL,
              priority INTEGER NOT NULL,
              rationale TEXT NOT NULL,
              state_version TEXT NOT NULL,
              payload_json TEXT NOT NULL,
              created_at TEXT NOT NULL,
              outcome TEXT,
              outcome_at TEXT,
              notified_at TEXT,
              UNIQUE(signal_id, candle_date, action, state_version),
              FOREIGN KEY(signal_id) REFERENCES signals(signal_id),
              FOREIGN KEY(position_id) REFERENCES manual_positions(position_id)
            );
            CREATE TABLE IF NOT EXISTS audit_events (
              event_id TEXT PRIMARY KEY,
              entity_type TEXT NOT NULL,
              entity_id TEXT NOT NULL,
              action TEXT NOT NULL,
              actor TEXT NOT NULL,
              payload_json TEXT NOT NULL,
              created_at TEXT NOT NULL,
              correlation_id TEXT
            );
            """
        )


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"))


def _rows(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> list[dict]:
    return [dict(row) for row in conn.execute(sql, params).fetchall()]


def append_audit(
    conn: sqlite3.Connection,
    entity_type: str,
    entity_id: str,
    action: str,
    payload: object,
    actor: str = "local-user",
    correlation_id: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO audit_events(event_id, entity_type, entity_id, action, actor, payload_json, created_at, correlation_id)
        VALUES(?,?,?,?,?,?,?,?)
        """,
        (str(uuid.uuid4()), entity_type, entity_id, action, actor, _json(payload), utc_now(), correlation_id),
    )


def set_setting(conn: sqlite3.Connection, key: str, value: object) -> None:
    conn.execute(
        "INSERT INTO settings(key,value,updated_at) VALUES(?,?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
        (key, _json(value), utc_now()),
    )


def get_settings(conn: sqlite3.Connection) -> dict:
    settings = {}
    for row in conn.execute("SELECT key,value FROM settings"):
        settings[row["key"]] = json.loads(row["value"])
    return settings


def current_equity(conn: sqlite3.Connection) -> dict | None:
    row = conn.execute("SELECT * FROM equity_history ORDER BY entered_at DESC LIMIT 1").fetchone()
    return dict(row) if row else None


def append_equity(new_equity: float, risk_pct: float, leverage: float, portfolio_cap_pct: float, reason: str, note: str) -> None:
    if new_equity <= 0:
        raise ValueError("Current Equity phai lon hon 0.")
    if risk_pct <= 0:
        raise ValueError("Risk % phai lon hon 0.")
    with connect() as conn:
        old = current_equity(conn)
        old_value = float(old["new_equity"]) if old else None
        delta = None if old_value is None else new_equity - old_value
        delta_pct = None if old_value in (None, 0) else delta / old_value * 100
        record_id = str(uuid.uuid4())
        now = utc_now()
        conn.execute(
            """
            INSERT INTO equity_history(id, old_equity, new_equity, delta_usd, delta_pct, effective_at, entered_at, reason, note, source)
            VALUES(?,?,?,?,?,?,?,?,?,?)
            """,
            (record_id, old_value, new_equity, delta, delta_pct, now, now, reason or "Manual update", note, "local-app"),
        )
        set_setting(conn, "risk_pct", risk_pct)
        set_setting(conn, "leverage", leverage)
        set_setting(conn, "portfolio_cap_pct", portfolio_cap_pct)
        append_audit(conn, "equity", record_id, "EQUITY_APPEND", {"newEquity": new_equity, "riskPct": risk_pct})


def calculate_plan(signal: dict, conn: sqlite3.Connection | None = None) -> tuple[str, dict, str | None]:
    close_conn = conn is None
    if conn is None:
        conn = connect()
    try:
        equity = current_equity(conn)
        settings = get_settings(conn)
        if not equity or "risk_pct" not in settings:
            return "Needs Review", {"reason": "Chua co Current Equity/Risk % de tinh size."}, None
        risk_pct = float(settings["risk_pct"])
        leverage = float(settings.get("leverage", 1) or 1)
        cap_pct = float(settings.get("portfolio_cap_pct", 0) or 0)
        current = float(equity["new_equity"])
        risk_usd = current * risk_pct / 100
        risk_per_unit = float(signal["riskPerUnit"])
        qty = risk_usd / risk_per_unit
        entry = float(signal["entryPrice"])
        notional = qty * entry
        margin_ref = notional / leverage if leverage > 0 else notional
        plan = {
            "ruleVersion": RULE_VERSION,
            "equitySnapshot": {
                "equityRecordId": equity["id"],
                "currentEquity": current,
                "riskPct": risk_pct,
                "riskUsd": risk_usd,
                "leverage": leverage,
                "portfolioCapPct": cap_pct,
            },
            "sizing": {
                "riskPerUnit": risk_per_unit,
                "quantityBase": qty,
                "notional": notional,
                "marginReference": margin_ref,
                "stopDistancePct": risk_per_unit / entry * 100,
                "tp1Qty30Pct": qty * 0.30,
                "partialQty10Pct": qty * 0.10,
                "tailQty60Pct": qty * 0.60,
            },
            "orders": signal.get("orders", []),
            "warning": "Recommendation-only: app khong gui lenh len Binance.",
        }
        return "Ready", plan, equity["id"]
    finally:
        if close_conn:
            conn.close()


def persist_scan_result(result: dict, started_at: str | None = None) -> None:
    init_db()
    now = utc_now()
    run_id = f"scan:{result.get('scannedAt', now)}"
    checked = result.get("checked", [])
    candle_date = max((item.get("latestDate", "") for item in checked), default="")
    status = "Failed" if result.get("errors") and not checked else "Completed"
    with connect() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO scan_runs(run_id, started_at, finished_at, status, candle_date, symbols_json, checked_json, errors_json, system_name)
            VALUES(?,?,?,?,?,?,?,?,?)
            """,
            (
                run_id,
                started_at or result.get("scannedAt") or now,
                result.get("scannedAt") or now,
                status,
                candle_date,
                _json(result.get("symbols", [])),
                _json(checked),
                _json(result.get("errors", [])),
                result.get("systemName", ""),
            ),
        )
        for signal in result.get("newSignals", []):
            conn.execute(
                """
                INSERT OR IGNORE INTO signals(signal_id, run_id, symbol, side, signal_type, signal_date, entry_date, payload_json, created_at)
                VALUES(?,?,?,?,?,?,?,?,?)
                """,
                (
                    signal["id"],
                    run_id,
                    signal["symbol"],
                    signal["side"],
                    signal["signalType"],
                    signal["signalDate"],
                    signal["entryDate"],
                    _json(signal),
                    signal.get("detectedAt") or now,
                ),
            )
            status_text, plan, equity_record_id = calculate_plan(signal, conn)
            conn.execute(
                """
                INSERT OR IGNORE INTO trade_plans(plan_id, signal_id, version, status, payload_json, equity_record_id, created_at)
                VALUES(?,?,?,?,?,?,?)
                """,
                (f"{signal['id']}:v1", signal["id"], 1, status_text, _json(plan), equity_record_id, now),
            )
            append_audit(conn, "signal", signal["id"], "SIGNAL_PERSISTED", {"runId": run_id, "planStatus": status_text}, correlation_id=run_id)


def import_legacy_history(history: list[dict], system_name: str) -> None:
    if not history:
        return
    init_db()
    now = utc_now()
    run_id = "legacy:signals_history_json"
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO scan_runs(run_id, started_at, finished_at, status, candle_date, symbols_json, checked_json, errors_json, system_name)
            VALUES(?,?,?,?,?,?,?,?,?)
            ON CONFLICT(run_id) DO UPDATE SET system_name=excluded.system_name
            """,
            (run_id, now, now, "Imported", "", "[]", "[]", "[]", system_name),
        )
        for signal in history:
            if not isinstance(signal, dict) or "id" not in signal:
                continue
            conn.execute(
                """
                INSERT OR IGNORE INTO signals(signal_id, run_id, symbol, side, signal_type, signal_date, entry_date, payload_json, created_at)
                VALUES(?,?,?,?,?,?,?,?,?)
                """,
                (
                    signal["id"],
                    run_id,
                    signal.get("symbol", ""),
                    signal.get("side", ""),
                    signal.get("signalType", ""),
                    signal.get("signalDate", ""),
                    signal.get("entryDate", ""),
                    _json(signal),
                    signal.get("detectedAt") or now,
                ),
            )
            plan_exists = conn.execute("SELECT 1 FROM trade_plans WHERE signal_id=? LIMIT 1", (signal["id"],)).fetchone()
            if not plan_exists:
                status_text, plan, equity_record_id = calculate_plan(signal, conn)
                conn.execute(
                    """
                    INSERT INTO trade_plans(plan_id, signal_id, version, status, payload_json, equity_record_id, created_at)
                    VALUES(?,?,?,?,?,?,?)
                    """,
                    (f"{signal['id']}:v1", signal["id"], 1, status_text, _json(plan), equity_record_id, now),
                )


def record_decision(signal_id: str, decision: str, note: str = "") -> None:
    if decision not in {"Accept", "Reject", "Watchlist"}:
        raise ValueError("Decision khong hop le.")
    with connect() as conn:
        decision_id = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO decisions(decision_id, signal_id, decision, actor, channel, note, created_at) VALUES(?,?,?,?,?,?,?)",
            (decision_id, signal_id, decision, "local-user", "app", note, utc_now()),
        )
        append_audit(conn, "signal", signal_id, f"DECISION_{decision.upper()}", {"note": note})


def track_position(signal_id: str, quantity: float | None = None) -> None:
    with connect() as conn:
        row = conn.execute("SELECT payload_json FROM signals WHERE signal_id=?", (signal_id,)).fetchone()
        if not row:
            raise ValueError("Khong tim thay signal de track.")
        signal = json.loads(row["payload_json"])
        plan_row = conn.execute(
            "SELECT payload_json FROM trade_plans WHERE signal_id=? ORDER BY version DESC LIMIT 1", (signal_id,)
        ).fetchone()
        plan = json.loads(plan_row["payload_json"]) if plan_row else {}
        planned_qty = plan.get("sizing", {}).get("quantityBase")
        qty = float(quantity or planned_qty or 0)
        if qty <= 0:
            raise ValueError("Can quantity > 0 de Track Position.")
        position_id = f"pos:{signal_id}"
        now = utc_now()
        payload = {"source": "accepted-signal", "tradePlan": plan}
        conn.execute(
            """
            INSERT INTO manual_positions(position_id, signal_id, symbol, side, entry_time, entry_price, quantity, current_sl, current_tp1, lifecycle, rule_version, payload_json, created_at, updated_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(position_id) DO UPDATE SET quantity=excluded.quantity, updated_at=excluded.updated_at
            """,
            (
                position_id,
                signal_id,
                signal["symbol"],
                signal["side"],
                signal["entryDate"],
                float(signal["entryPrice"]),
                qty,
                float(signal["initialStop"]),
                float(signal["tp1"]),
                "Active",
                RULE_VERSION,
                _json(payload),
                now,
                now,
            ),
        )
        create_recommendation(conn, position_id, signal["entryDate"], "No Action", 3, "Da track vi the. Cho nen D1 tiep theo dong de danh gia lifecycle.", {"signalId": signal_id})
        append_audit(conn, "position", position_id, "POSITION_TRACKED", {"signalId": signal_id, "quantity": qty})


def close_accepted_signal(signal_id: str, note: str = "", close_price: float | None = None) -> dict:
    """Manually close an accepted signal and any active tracked position.

    This is a local bookkeeping action only. It never submits an exchange order.
    """
    init_db()
    with connect() as conn:
        signal_row = conn.execute(
            "SELECT symbol, side FROM signals WHERE signal_id=?",
            (signal_id,),
        ).fetchone()
        if not signal_row:
            raise ValueError("Khong tim thay signal de dong.")

        decision_row = conn.execute(
            "SELECT decision FROM decisions WHERE signal_id=? ORDER BY created_at DESC, decision_id DESC LIMIT 1",
            (signal_id,),
        ).fetchone()
        if not decision_row or decision_row["decision"] != "Accept":
            raise ValueError("Chi co the dong signal co quyet dinh moi nhat la Accept.")

        existing = conn.execute(
            """
            SELECT * FROM followup_recommendations
            WHERE signal_id=? AND action='MANUAL_CLOSE' AND status='Acknowledged'
              AND outcome='Already Closed'
            ORDER BY outcome_at DESC, created_at DESC LIMIT 1
            """,
            (signal_id,),
        ).fetchone()
        if existing:
            return dict(existing)

        position = conn.execute(
            """
            SELECT position_id FROM manual_positions
            WHERE signal_id=? AND lifecycle NOT IN ('Closed','Stopped','Rejected','Expired')
            ORDER BY updated_at DESC LIMIT 1
            """,
            (signal_id,),
        ).fetchone()
        position_id = position["position_id"] if position else None
        now = utc_now()
        close_note = note.strip() or "Nguoi dung dong thu cong tren NXT local."
        close_price_value = float(close_price) if close_price not in (None, "") else None
        if close_price_value is not None and close_price_value <= 0:
            raise ValueError("Gia dong phai lon hon 0.")
        recommendation_id = f"manual-close:{signal_id}"
        payload = {
            "recommendationId": recommendation_id,
            "signalId": signal_id,
            "positionId": position_id,
            "subjectType": "POSITION" if position_id else "SIGNAL",
            "trackingStatus": "Closed manually",
            "symbol": signal_row["symbol"],
            "side": signal_row["side"],
            "candleDate": ict_today(),
            "action": "MANUAL_CLOSE",
            "actionLabel": "DONG LENH THU CONG",
            "status": "Acknowledged",
            "priority": 0,
            "rationale": close_note,
            "stateVersion": "manual-close-v1",
            "recommendationOnly": True,
            "closedAt": now,
            "closePrice": close_price_value,
        }

        conn.execute(
            """
            UPDATE followup_recommendations
            SET status='Acknowledged', outcome='Already Closed', outcome_at=?
            WHERE signal_id=? AND status IN ('Pending','Reminder')
            """,
            (now, signal_id),
        )
        if position_id:
            conn.execute(
                "UPDATE manual_positions SET lifecycle='Closed', updated_at=? WHERE position_id=?",
                (now, position_id),
            )
        conn.execute(
            """
            INSERT INTO followup_recommendations(
              recommendation_id, signal_id, position_id, subject_type, candle_date,
              action, action_label, status, priority, rationale, state_version,
              payload_json, created_at, outcome, outcome_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                recommendation_id,
                signal_id,
                position_id,
                payload["subjectType"],
                payload["candleDate"],
                payload["action"],
                payload["actionLabel"],
                payload["status"],
                payload["priority"],
                payload["rationale"],
                payload["stateVersion"],
                _json(payload),
                now,
                "Already Closed",
                now,
            ),
        )
        append_audit(
            conn,
            "position" if position_id else "signal",
            position_id or signal_id,
            "ACCEPTED_SIGNAL_MANUALLY_CLOSED",
            {"signalId": signal_id, "positionId": position_id, "closePrice": close_price_value, "note": close_note},
        )
        return dict(
            conn.execute(
                "SELECT * FROM followup_recommendations WHERE recommendation_id=?",
                (recommendation_id,),
            ).fetchone()
        )


def create_recommendation(conn: sqlite3.Connection, position_id: str, candle_date: str, action: str, priority: int, rationale: str, payload: object) -> None:
    conn.execute(
        """
        INSERT OR IGNORE INTO recommendations(recommendation_id, position_id, candle_date, action, status, priority, rationale, payload_json, created_at)
        VALUES(?,?,?,?,?,?,?,?,?)
        """,
        (f"rec:{position_id}:{candle_date}:{action}", position_id, candle_date, action, "Pending", priority, rationale, _json(payload), utc_now()),
    )


def accepted_monitor_subjects() -> list[dict]:
    """Return signals whose latest decision is Accept, with an optional active manual position."""
    init_db()
    with connect() as conn:
        rows = _rows(
            conn,
            """
            WITH latest_decision AS (
              SELECT d.signal_id, d.decision,
                     ROW_NUMBER() OVER (PARTITION BY d.signal_id ORDER BY d.created_at DESC, d.decision_id DESC) AS rn
              FROM decisions d
            ), latest_plan AS (
              SELECT tp.signal_id, tp.payload_json,
                     ROW_NUMBER() OVER (PARTITION BY tp.signal_id ORDER BY tp.version DESC) AS rn
              FROM trade_plans tp
            )
            SELECT s.signal_id, s.symbol, s.side, s.signal_date, s.entry_date,
                   s.payload_json AS signal_json, lp.payload_json AS plan_json,
                   p.position_id, p.entry_time, p.entry_price, p.quantity,
                   p.current_sl, p.current_tp1, p.lifecycle, p.rule_version,
                   p.payload_json AS position_json
            FROM signals s
            JOIN latest_decision ld ON ld.signal_id=s.signal_id AND ld.rn=1 AND ld.decision='Accept'
            LEFT JOIN latest_plan lp ON lp.signal_id=s.signal_id AND lp.rn=1
            LEFT JOIN manual_positions p ON p.signal_id=s.signal_id
              AND p.lifecycle NOT IN ('Closed','Stopped','Rejected','Expired')
            WHERE NOT EXISTS (
              SELECT 1 FROM followup_recommendations terminal
              WHERE terminal.signal_id=s.signal_id
                AND terminal.status='Acknowledged'
                AND terminal.outcome IN ('Applied','Already Closed')
                AND terminal.action IN ('STOP_LOSS','BE_STOP','TAIL_EXIT_EMA50','TAIL_EXIT_SSL','MANUAL_CLOSE')
            )
            ORDER BY s.signal_date, s.symbol
            """,
        )
        for row in rows:
            row["signal"] = json.loads(row.pop("signal_json"))
            row["plan"] = json.loads(row.pop("plan_json")) if row.get("plan_json") else {}
            row["position"] = None
            if row.get("position_id"):
                row["position"] = {
                    "positionId": row["position_id"],
                    "entryTime": row["entry_time"],
                    "entryPrice": row["entry_price"],
                    "quantity": row["quantity"],
                    "currentSl": row["current_sl"],
                    "currentTp1": row["current_tp1"],
                    "lifecycle": row["lifecycle"],
                    "ruleVersion": row["rule_version"],
                    "payload": json.loads(row["position_json"]) if row.get("position_json") else {},
                }
            pending = conn.execute(
                """
                SELECT * FROM followup_recommendations
                WHERE signal_id=? AND status='Pending'
                  AND action NOT IN ('NO_ACTION','DATA_STALE','NEEDS_REVIEW')
                ORDER BY priority ASC, candle_date DESC, created_at DESC LIMIT 1
                """,
                (row["signal_id"],),
            ).fetchone()
            row["pendingFollowup"] = dict(pending) if pending else None
            if row["pendingFollowup"]:
                row["pendingFollowup"]["payload"] = json.loads(row["pendingFollowup"].pop("payload_json"))
            row["acknowledgedActions"] = [
                action_row["action"]
                for action_row in conn.execute(
                    """
                    SELECT DISTINCT action FROM followup_recommendations
                    WHERE signal_id=? AND status='Acknowledged' AND outcome IN ('Applied','Already Closed')
                    """,
                    (row["signal_id"],),
                ).fetchall()
            ]
            for key in ("entry_time", "entry_price", "quantity", "current_sl", "current_tp1", "lifecycle", "rule_version", "position_json"):
                row.pop(key, None)
        return rows


def persist_followup_recommendations(items: list[dict]) -> list[dict]:
    """Persist one deterministic recommendation per accepted signal/candle/action/state."""
    if not items:
        return []
    init_db()
    persisted: list[dict] = []
    with connect() as conn:
        for item in items:
            rec_id = item["recommendationId"]
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO followup_recommendations(
                  recommendation_id, signal_id, position_id, subject_type, candle_date,
                  action, action_label, status, priority, rationale, state_version,
                  payload_json, created_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    rec_id,
                    item["signalId"],
                    item.get("positionId"),
                    item["subjectType"],
                    item["candleDate"],
                    item["action"],
                    item["actionLabel"],
                    item.get("status", "Pending"),
                    int(item["priority"]),
                    item["rationale"],
                    item["stateVersion"],
                    _json(item),
                    utc_now(),
                ),
            )
            row = conn.execute(
                "SELECT * FROM followup_recommendations WHERE recommendation_id=?", (rec_id,)
            ).fetchone()
            if row:
                record = dict(row)
                record["payload"] = json.loads(record.pop("payload_json"))
                persisted.append(record)
            if cursor.rowcount:
                append_audit(
                    conn,
                    "signal" if item["subjectType"] == "SIGNAL" else "position",
                    item.get("positionId") or item["signalId"],
                    "FOLLOWUP_RECOMMENDATION_EVALUATED",
                    {"recommendationId": rec_id, "action": item["action"], "candleDate": item["candleDate"]},
                )
    return persisted


def record_followup_outcome(recommendation_id: str, outcome: str) -> None:
    allowed = {"Applied", "Not Applied", "Snoozed", "Already Closed", "Correct Data"}
    if outcome not in allowed:
        raise ValueError("Follow-up outcome khong hop le.")
    with connect() as conn:
        row = conn.execute(
            "SELECT signal_id, position_id FROM followup_recommendations WHERE recommendation_id=?",
            (recommendation_id,),
        ).fetchone()
        if not row:
            raise ValueError("Khong tim thay follow-up recommendation.")
        now = utc_now()
        conn.execute(
            "UPDATE followup_recommendations SET status='Acknowledged', outcome=?, outcome_at=? WHERE recommendation_id=?",
            (outcome, now, recommendation_id),
        )
        append_audit(
            conn,
            "position" if row["position_id"] else "signal",
            row["position_id"] or row["signal_id"],
            "FOLLOWUP_OUTCOME_RECORDED",
            {"recommendationId": recommendation_id, "outcome": outcome},
        )


def mark_followups_notified(recommendation_ids: list[str]) -> None:
    if not recommendation_ids:
        return
    with connect() as conn:
        now = utc_now()
        conn.executemany(
            "UPDATE followup_recommendations SET notified_at=COALESCE(notified_at, ?) WHERE recommendation_id=?",
            [(now, rec_id) for rec_id in recommendation_ids],
        )


def dashboard_state() -> dict:
    init_db()
    with connect() as conn:
        signals = _rows(
            conn,
            """
            SELECT s.*, tp.status AS plan_status, tp.payload_json AS plan_json,
                   (SELECT decision FROM decisions d WHERE d.signal_id=s.signal_id ORDER BY d.created_at DESC LIMIT 1) AS latest_decision,
                   EXISTS(
                     SELECT 1 FROM followup_recommendations fr
                     WHERE fr.signal_id=s.signal_id AND fr.action='MANUAL_CLOSE'
                       AND fr.status='Acknowledged' AND fr.outcome='Already Closed'
                   ) AS manual_closed
            FROM signals s
            LEFT JOIN trade_plans tp ON tp.signal_id=s.signal_id AND tp.version=1
            ORDER BY s.signal_date DESC, s.symbol ASC
            LIMIT 100
            """,
        )
        for signal in signals:
            signal["payload"] = json.loads(signal.pop("payload_json"))
            signal["plan"] = json.loads(signal.pop("plan_json")) if signal.get("plan_json") else {}
        return {
            "dbPath": str(DB_PATH),
            "settings": get_settings(conn),
            "currentEquity": current_equity(conn),
            "equityHistory": _rows(conn, "SELECT * FROM equity_history ORDER BY entered_at DESC LIMIT 30"),
            "signals": signals,
            "positions": _rows(conn, "SELECT * FROM manual_positions ORDER BY updated_at DESC LIMIT 50"),
            "recommendations": _rows(conn, "SELECT * FROM recommendations ORDER BY created_at DESC LIMIT 80"),
            "followupRecommendations": _rows(conn, "SELECT * FROM followup_recommendations ORDER BY candle_date DESC, priority ASC, created_at DESC LIMIT 120"),
            "scanRuns": _rows(conn, "SELECT * FROM scan_runs ORDER BY finished_at DESC LIMIT 20"),
            "auditEvents": _rows(conn, "SELECT * FROM audit_events ORDER BY created_at DESC LIMIT 80"),
        }
