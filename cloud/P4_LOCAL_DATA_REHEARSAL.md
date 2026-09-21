# NXT Cloud Shadow — P4 local data rehearsal

Status: local-only implementation. These tools do not provision or contact Supabase, GCP, Telegram or Binance.

## Safety boundary

- The SQLite source is opened with `mode=ro` and `PRAGMA query_only=ON`; the importer verifies its SHA-256 is unchanged.
- Import is dry-run unless `--apply` is explicitly supplied.
- All PostgreSQL business rows are constrained to `SHADOW`.
- Re-import uses stable source IDs and `ON CONFLICT DO NOTHING`.
- Records without an equivalent cloud runtime table are retained in `legacy_import_records` with source table/key provenance.
- The rehearsal script accepts localhost only, creates randomly named disposable databases, compares row counts after `pg_dump`/`pg_restore`, then removes both databases.

## Review commands

Read-only inventory of the current local database:

```powershell
python -B scripts\nxt_cloud_import_sqlite.py --source "D:\Workspace\Codex\Investment\runtime\nxt_signal_app\nxt_mvp1.sqlite" --owner-user-id local-rehearsal-owner
```

Full drill on a host with local PostgreSQL and its client tools installed:

```powershell
python -B scripts\rehearse_nxt_cloud_postgres.py --admin-url "postgresql://postgres:LOCAL_PASSWORD@127.0.0.1:5432/postgres" --source "D:\Workspace\Codex\Investment\runtime\nxt_signal_app\nxt_mvp1.sqlite" --owner-user-id local-rehearsal-owner
```

Do not put a password in Git or a committed environment file. The command above is a placeholder review instruction.

## Exit evidence required

P4 can be code-complete without PostgreSQL installed, but P4 exit/G4 readiness requires a real local run proving:

1. migration apply and no-op reapply;
2. first import and no-op re-import;
3. source SQLite checksum unchanged;
4. custom-format backup and clean restore;
5. equal per-table row counts after restore;
6. `/readyz` succeeds against the migrated database.

Until that evidence exists, no Supabase project or cloud deployment is authorized.
