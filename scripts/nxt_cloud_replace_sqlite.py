from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from psycopg.rows import dict_row

from scripts.nxt_cloud_import_sqlite import build_batches, read_source, source_manifest


CONFIRMATION = "CLEAR_SHADOW_AND_REIMPORT"
BUSINESS_TABLES = (
    "notification_outbox",
    "idempotency_keys",
    "followup_recommendations",
    "manual_positions",
    "decisions",
    "trade_plans",
    "signals",
    "scan_run_symbols",
    "scan_runs",
    "legacy_import_records",
)
COUNT_TABLES = (
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
)


def _json_default(value: Any) -> str:
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def _counts(cur) -> dict[str, int]:
    result: dict[str, int] = {}
    for table in COUNT_TABLES:
        cur.execute(f'SELECT count(*) AS count FROM "{table}"')
        result[table] = int(cur.fetchone()["count"])
    return result


def replace_shadow(database_url: str, source: Path, owner_user_id: str, backup_output: Path) -> dict[str, Any]:
    import psycopg

    rows = read_source(source)
    manifest = source_manifest(source, rows)
    batches = build_batches(rows, owner_user_id)
    expected = {
        "scan_runs": len(batches[0][1]),
        "scan_run_symbols": 0,
        "signals": len(batches[1][1]),
        "trade_plans": len(batches[2][1]),
        "decisions": len(batches[3][1]),
        "manual_positions": len(batches[4][1]),
        "followup_recommendations": len(batches[5][1]),
        "notification_outbox": 0,
        "idempotency_keys": 0,
        "legacy_import_records": len(batches[6][1]),
    }
    backup_output.parent.mkdir(parents=True, exist_ok=True)

    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        with conn.transaction(), conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", ("nxt-cloud-shadow-replace",))
            before_counts = _counts(cur)
            cloud_rows: dict[str, list[dict[str, Any]]] = {}
            for table in COUNT_TABLES:
                cur.execute(f'SELECT * FROM "{table}"')
                cloud_rows[table] = list(cur.fetchall())
            backup_payload = {
                "createdAt": datetime.now(timezone.utc).isoformat(),
                "beforeCounts": before_counts,
                "tables": cloud_rows,
            }
            backup_output.write_text(
                json.dumps(backup_payload, ensure_ascii=False, indent=2, sort_keys=True, default=_json_default),
                encoding="utf-8",
            )
            cur.execute("TRUNCATE TABLE " + ", ".join(f'\"{table}\"' for table in BUSINESS_TABLES))
            attempted: dict[str, int] = {}
            for index, (query, values) in enumerate(batches, start=1):
                if values:
                    cur.executemany(query, values)
                attempted[f"batch{index}"] = len(values)
            after_counts = _counts(cur)
            if after_counts != expected:
                raise RuntimeError(f"post-import counts differ: expected={expected}, actual={after_counts}")

    return {
        "status": "REPLACE_COMPLETE",
        "source": str(source.resolve()),
        "sourceSha256": manifest["sourceSha256"],
        "contentSha256": manifest["contentSha256"],
        "sourceCounts": manifest["counts"],
        "beforeCounts": before_counts,
        "attempted": attempted,
        "afterCounts": after_counts,
        "backup": str(backup_output.resolve()),
        "completedAt": datetime.now(timezone.utc).isoformat(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Atomically replace NXT SHADOW business data from a local SQLite snapshot.")
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--owner-user-id", required=True)
    parser.add_argument("--backup-output", type=Path, required=True)
    parser.add_argument("--confirm", required=True)
    args = parser.parse_args()
    if args.confirm != CONFIRMATION:
        parser.error(f"--confirm must equal {CONFIRMATION}")
    result = replace_shadow(args.database_url, args.source, args.owner_user_id, args.backup_output)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
