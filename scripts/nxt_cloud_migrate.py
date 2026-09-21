from __future__ import annotations

import argparse
import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MIGRATIONS = ROOT / "cloud" / "migrations"


def migration_files(directory: Path) -> list[tuple[int, Path, str]]:
    found: list[tuple[int, Path, str]] = []
    for path in sorted(directory.glob("[0-9][0-9][0-9][0-9]_*.sql")):
        version = int(path.name.split("_", 1)[0])
        found.append((version, path, hashlib.sha256(path.read_bytes()).hexdigest()))
    versions = [item[0] for item in found]
    if not found or versions != list(range(1, len(found) + 1)):
        raise ValueError("migration versions must be contiguous and start at 0001")
    return found


def apply_migrations(database_url: str, directory: Path = DEFAULT_MIGRATIONS) -> list[int]:
    if not database_url:
        raise ValueError("DATABASE_URL is required")
    import psycopg

    applied_now: list[int] = []
    with psycopg.connect(database_url) as conn:
        with conn.transaction(), conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", ("nxt-cloud-schema-migrations",))
            cur.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations ("
                "version integer PRIMARY KEY, name text NOT NULL, checksum text NOT NULL, "
                "applied_at timestamptz NOT NULL DEFAULT now())"
            )
            cur.execute("SELECT version, checksum FROM schema_migrations ORDER BY version")
            applied = dict(cur.fetchall())
            for version, path, checksum in migration_files(directory):
                if version in applied:
                    if applied[version] != checksum:
                        raise RuntimeError(f"applied migration checksum changed: {path.name}")
                    continue
                cur.execute(path.read_text(encoding="utf-8"))
                cur.execute(
                    "INSERT INTO schema_migrations(version, name, checksum) VALUES (%s, %s, %s)",
                    (version, path.name, checksum),
                )
                applied_now.append(version)
    return applied_now


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply immutable NXT cloud-shadow PostgreSQL migrations.")
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--migrations", type=Path, default=DEFAULT_MIGRATIONS)
    args = parser.parse_args()
    versions = apply_migrations(args.database_url, args.migrations)
    print("applied=" + (",".join(map(str, versions)) if versions else "none"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
