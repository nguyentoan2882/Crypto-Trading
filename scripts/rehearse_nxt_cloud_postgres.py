from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import psycopg
from psycopg import sql

from scripts.nxt_cloud_import_sqlite import apply_batches, build_batches, read_source
from scripts.nxt_cloud_migrate import apply_migrations


EXPECTED_TABLES = (
    "schema_migrations",
    "scan_runs",
    "signals",
    "trade_plans",
    "decisions",
    "manual_positions",
    "followup_recommendations",
    "notification_outbox",
    "idempotency_keys",
    "legacy_import_records",
)


def _local_admin_url(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme not in {"postgres", "postgresql"} or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("P4 rehearsal requires a localhost PostgreSQL admin URL")
    return value


def _database_url(admin_url: str, database: str) -> str:
    parsed = urlsplit(admin_url)
    return urlunsplit((parsed.scheme, parsed.netloc, "/" + database, parsed.query, parsed.fragment))


def _database_counts(database_url: str) -> dict[str, int]:
    with psycopg.connect(database_url) as conn, conn.cursor() as cur:
        result = {}
        for table in EXPECTED_TABLES:
            cur.execute(sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(table)))
            result[table] = int(cur.fetchone()[0])
        return result


def rehearse(admin_url: str, source: Path | None, owner: str) -> dict[str, object]:
    admin_url = _local_admin_url(admin_url)
    pg_dump = shutil.which("pg_dump")
    pg_restore = shutil.which("pg_restore")
    if not pg_dump or not pg_restore:
        raise RuntimeError("pg_dump and pg_restore must be installed and on PATH")
    suffix = uuid.uuid4().hex[:12]
    source_db = f"nxt_rehearsal_{suffix}"
    restore_db = f"nxt_restore_{suffix}"
    source_url = _database_url(admin_url, source_db)
    restore_url = _database_url(admin_url, restore_db)
    created: list[str] = []
    try:
        with psycopg.connect(admin_url, autocommit=True) as conn, conn.cursor() as cur:
            for name in (source_db, restore_db):
                cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
                created.append(name)
        apply_migrations(source_url)
        if source:
            apply_batches(source_url, build_batches(read_source(source), owner))
        before = _database_counts(source_url)
        with tempfile.TemporaryDirectory(prefix="nxt-p4-rehearsal-") as temp_dir:
            dump_path = Path(temp_dir) / "shadow.dump"
            subprocess.run([pg_dump, "--format=custom", "--file", str(dump_path), source_url], check=True)
            subprocess.run([pg_restore, "--exit-on-error", "--no-owner", "--dbname", restore_url, str(dump_path)], check=True)
        after = _database_counts(restore_url)
        if before != after:
            raise RuntimeError(f"restore row counts differ: before={before}, after={after}")
        return {"status": "PASS", "sourceDatabase": source_db, "restoreDatabase": restore_db, "counts": before}
    finally:
        if created:
            with psycopg.connect(admin_url, autocommit=True) as conn, conn.cursor() as cur:
                for name in reversed(created):
                    cur.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s", (name,))
                    cur.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(name)))


def main() -> int:
    parser = argparse.ArgumentParser(description="Create disposable local PostgreSQL databases and verify migrate/import/backup/restore.")
    parser.add_argument("--admin-url", required=True, help="Local PostgreSQL URL for an admin database, normally postgres.")
    parser.add_argument("--source", type=Path)
    parser.add_argument("--owner-user-id", default="local-rehearsal-owner")
    args = parser.parse_args()
    print(json.dumps(rehearse(args.admin_url, args.source, args.owner_user_id), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
