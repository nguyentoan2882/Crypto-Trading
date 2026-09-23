# G20 — Full local-to-cloud data replacement (2026-09-23)

## Authority and scope

- User explicitly requested clearing all NXT cloud data and migrating the complete local dataset through 2026-09-23.
- Cleared scope: all NXT SHADOW business tables, including scan-symbol details, notification outbox, idempotency keys, and legacy imports.
- Preserved infrastructure: Supabase Auth users, database schema/migrations, secrets, Cloud Run services/jobs, and Cloud Scheduler definitions.
- Local NXT remained unchanged; migration used a point-in-time SQLite backup.

## Controls

- All three scanner schedules were paused before replacement and resumed only after independent verification.
- Local snapshot: `outputs/nxt_cloud_replace_20260923/local_nxt_snapshot.sqlite`.
- Local snapshot SHA-256: `114A5A9010599459856D4358E4542755E1EA9EAC0F47E0E3FCC443B010655DD3`.
- Pre-replacement cloud backup: `outputs/nxt_cloud_replace_20260923/cloud_before_replace.json`.
- Cloud backup SHA-256: `A4E749C966DDECCDC50A632E7756209F649EF9B0AB69F0ED91B1F9473188B9A0`.
- Backup, clear, import, and count validation ran under one PostgreSQL transaction and advisory lock.

## Source inventory

| Local table | Rows | Latest relevant date |
|---|---:|---|
| scan_runs | 129 | 2026-09-22 |
| signals | 8 | 2026-09-18 |
| trade_plans | 8 | — |
| decisions | 11 | 2026-09-20T23:57:25Z |
| manual_positions | 0 | — |
| followup_recommendations | 33 | 2026-09-22 |
| audit_events | 54 | 2026-09-23T00:01:05Z |
| settings / equity_history / recommendations | 0 | — |

## Cloud before and after

| Table | Before | After |
|---|---:|---:|
| scan_runs | 131 | 129 |
| scan_run_symbols | 12 | 0 |
| signals | 8 | 8 |
| trade_plans | 8 | 8 |
| decisions | 11 | 11 |
| manual_positions | 0 | 0 |
| followup_recommendations | 36 | 33 |
| notification_outbox | 3 | 0 |
| idempotency_keys | 1 | 0 |
| legacy_import_records | 228 | 243 |

All 243 local rows, including local-only audit data, are retained in `legacy_import_records`; supported runtime entities are also normalized into their cloud tables. Independent verification found four accepted monitor subjects.

## Post-operation verification

- Replacement status: `REPLACE_COMPLETE` at `2026-09-23T07:25:32.891278Z`.
- Content hash: `8f0b33bd4f1150f1c84b4e7425792ade6283e2bdaff0bb7cec4655ed4b73ca23`.
- Cloud `/health`: HTTP 200; `/login`: HTTP 200.
- Scheduler jobs `nxt-cloud-shadow-scan-0701`, `nxt-cloud-shadow-scan-0801`, and `nxt-cloud-shadow-scan-1201` are `ENABLED` in `Asia/Ho_Chi_Minh`.
- No scanner execution or Telegram message was triggered as part of the migration.
