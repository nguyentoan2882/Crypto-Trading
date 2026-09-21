from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from collections.abc import Iterable
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


CORE_TABLES = (
    "scan_runs",
    "signals",
    "trade_plans",
    "decisions",
    "manual_positions",
    "followup_recommendations",
)
ALL_LOCAL_TABLES = (
    "settings",
    "equity_history",
    *CORE_TABLES,
    "recommendations",
    "audit_events",
)
RULE_VERSION_FALLBACK = "NXT v3.5 GuardDirectional_30_10At4R_60 legacy-entry-rule"


def _json_value(value: Any, fallback: Any) -> Any:
    if value in (None, ""):
        return fallback
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback


def _json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _date_or_none(value: Any) -> str | None:
    text = str(value or "").strip()
    return text[:10] if len(text) >= 10 else None


def read_source(path: Path) -> dict[str, list[dict[str, Any]]]:
    resolved = path.resolve(strict=True)
    uri = resolved.as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only = ON")
        conn.execute("BEGIN")  # Keep all table reads on one consistent SQLite snapshot.
        existing = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        return {
            table: [dict(row) for row in conn.execute(f'SELECT * FROM "{table}"')]
            for table in ALL_LOCAL_TABLES
            if table in existing
        }


def source_manifest(path: Path, rows: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    counts = {table: len(items) for table, items in sorted(rows.items())}
    canonical = hashlib.sha256(_json_text(rows).encode("utf-8")).hexdigest()
    return {"sourceSha256": digest, "contentSha256": canonical, "counts": counts}


def _legacy_rows(rows: dict[str, list[dict[str, Any]]], owner: str) -> Iterable[tuple[Any, ...]]:
    for table, items in sorted(rows.items()):
        for index, row in enumerate(items):
            source_key = next(
                (str(row[key]) for key in ("key", "id", "run_id", "signal_id", "plan_id", "decision_id", "position_id", "recommendation_id", "event_id") if row.get(key) is not None),
                str(index),
            )
            yield (owner, table, source_key, _json_text(row))


def build_batches(rows: dict[str, list[dict[str, Any]]], owner: str) -> list[tuple[str, list[tuple[Any, ...]]]]:
    signal_rows = [row for row in rows.get("signals", []) if _date_or_none(row.get("signal_date"))]
    signal_ids = {str(row["signal_id"]) for row in signal_rows}
    position_ids = {str(row["position_id"]) for row in rows.get("manual_positions", [])}
    run_ids = {str(row["run_id"]) for row in rows.get("scan_runs", [])}
    batches: list[tuple[str, list[tuple[Any, ...]]]] = []

    batches.append((
        "INSERT INTO scan_runs(run_id,environment,owner_user_id,candle_date,status,source,input_hash,rule_version,started_at,finished_at,errors_json) "
        "VALUES (%s,'SHADOW',%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb) ON CONFLICT DO NOTHING",
        [(
            str(row["run_id"]), owner, _date_or_none(row.get("candle_date")), str(row.get("status") or "Imported"),
            "LOCAL_SQLITE_IMPORT:" + str(row["run_id"]), hashlib.sha256(_json_text(row).encode()).hexdigest(),
            str(row.get("system_name") or RULE_VERSION_FALLBACK), row.get("started_at"), row.get("finished_at"),
            _json_text(_json_value(row.get("errors_json"), [])),
        ) for row in rows.get("scan_runs", [])],
    ))
    batches.append((
        "INSERT INTO signals(signal_id,environment,owner_user_id,run_id,symbol,side,signal_type,signal_date,rule_version,payload,created_at) "
        "VALUES (%s,'SHADOW',%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s) ON CONFLICT DO NOTHING",
        [(
            str(row["signal_id"]), owner, str(row["run_id"]) if row.get("run_id") in run_ids else None,
            str(row.get("symbol") or ""), str(row.get("side") or ""), str(row.get("signal_type") or ""),
            _date_or_none(row.get("signal_date")), RULE_VERSION_FALLBACK,
            _json_text(_json_value(row.get("payload_json"), {})), row.get("created_at"),
        ) for row in signal_rows],
    ))
    batches.append((
        "INSERT INTO trade_plans(plan_id,environment,owner_user_id,signal_id,rule_version,status,payload,created_at) "
        "VALUES (%s,'SHADOW',%s,%s,%s,%s,%s::jsonb,%s) ON CONFLICT DO NOTHING",
        [(
            str(row["plan_id"]), owner, str(row["signal_id"]), RULE_VERSION_FALLBACK,
            str(row.get("status") or "LEGACY_AUDIT"), _json_text(_json_value(row.get("payload_json"), {})), row.get("created_at"),
        ) for row in rows.get("trade_plans", []) if str(row.get("signal_id")) in signal_ids],
    ))
    batches.append((
        "INSERT INTO decisions(decision_id,environment,owner_user_id,signal_id,decision,note,created_at) "
        "VALUES (%s,'SHADOW',%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
        [(
            str(row["decision_id"]), owner, str(row["signal_id"]), str(row["decision"]),
            str(row.get("note") or ""), row.get("created_at"),
        ) for row in rows.get("decisions", []) if str(row.get("signal_id")) in signal_ids and row.get("decision") in {"Accept", "Reject", "Watchlist"}],
    ))
    batches.append((
        "INSERT INTO manual_positions(position_id,environment,owner_user_id,signal_id,entry_price,quantity,lifecycle,payload,created_at,updated_at) "
        "VALUES (%s,'SHADOW',%s,%s,%s,%s,%s,%s::jsonb,%s,%s) ON CONFLICT DO NOTHING",
        [(
            str(row["position_id"]), owner, str(row["signal_id"]) if str(row.get("signal_id")) in signal_ids else None,
            row.get("entry_price"), row.get("quantity"), str(row.get("lifecycle") or "OPEN"),
            _json_text(_json_value(row.get("payload_json"), {})), row.get("created_at"), row.get("updated_at") or row.get("created_at"),
        ) for row in rows.get("manual_positions", []) if float(row.get("entry_price") or 0) > 0 and float(row.get("quantity") or 0) > 0],
    ))
    batches.append((
        "INSERT INTO followup_recommendations(recommendation_id,environment,owner_user_id,signal_id,position_id,candle_date,action,priority,status,payload,created_at,outcome_at) "
        "VALUES (%s,'SHADOW',%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s) ON CONFLICT DO NOTHING",
        [(
            str(row["recommendation_id"]), owner, str(row["signal_id"]),
            str(row["position_id"]) if str(row.get("position_id")) in position_ids else None,
            _date_or_none(row.get("candle_date")), str(row.get("action") or "NO_ACTION"), int(row.get("priority") or 0),
            str(row.get("status") or "Pending"), _json_text(_json_value(row.get("payload_json"), {})),
            row.get("created_at"), row.get("outcome_at"),
        ) for row in rows.get("followup_recommendations", []) if str(row.get("signal_id")) in signal_ids and _date_or_none(row.get("candle_date"))],
    ))
    batches.append((
        "INSERT INTO legacy_import_records(environment,owner_user_id,source_table,source_key,payload) "
        "VALUES ('SHADOW',%s,%s,%s,%s::jsonb) ON CONFLICT DO NOTHING",
        list(_legacy_rows(rows, owner)),
    ))
    return batches


def apply_batches(database_url: str, batches: list[tuple[str, list[tuple[Any, ...]]]]) -> dict[str, int]:
    import psycopg

    counts: dict[str, int] = {}
    with psycopg.connect(database_url) as conn, conn.transaction(), conn.cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", ("nxt-cloud-sqlite-import",))
        for index, (query, values) in enumerate(batches, start=1):
            if values:
                cur.executemany(query, values)
            counts[f"batch{index}"] = len(values)
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description="Copy local NXT SQLite data into a SHADOW PostgreSQL database.")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--owner-user-id", required=True)
    parser.add_argument("--database-url")
    parser.add_argument("--apply", action="store_true", help="Write to PostgreSQL; otherwise perform a read-only dry run.")
    args = parser.parse_args()
    before = hashlib.sha256(args.source.read_bytes()).hexdigest()
    rows = read_source(args.source)
    manifest = source_manifest(args.source, rows)
    batches = build_batches(rows, args.owner_user_id)
    manifest["targetRows"] = sum(len(values) for _, values in batches[:-1])
    if args.apply:
        if not args.database_url:
            parser.error("--database-url is required with --apply")
        manifest["attempted"] = apply_batches(args.database_url, batches)
    after = hashlib.sha256(args.source.read_bytes()).hexdigest()
    if before != after:
        raise RuntimeError("source SQLite file changed during copy-only import")
    manifest["mode"] = "APPLY" if args.apply else "DRY_RUN"
    manifest["sourceUnchanged"] = True
    manifest["generatedAt"] = datetime.now(timezone.utc).isoformat()
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
