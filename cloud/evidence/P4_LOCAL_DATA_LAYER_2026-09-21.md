# P4 Local Data Layer Evidence

Date: 2026-09-21
Branch: `codex/nxt-cloud-shadow`
G3 authority parent: `2ced77b`
Decision state: **P4 COMPLETE — READY FOR G4 REVIEW**

## Delivered scope

- Immutable, checksummed PostgreSQL migration runner with an advisory lock and no-op reapply behavior.
- SHADOW-only PostgreSQL schema for scanner, dashboard, decisions, manual positions, follow-ups, durable outbox and idempotency keys.
- Row-level security enabled on every business table with no browser-client policy; the monitor view uses security-invoker behavior.
- Copy-only SQLite importer: read-only URI, query-only mode, one consistent read transaction and before/after source checksum guard.
- Stable-ID, `ON CONFLICT DO NOTHING` imports and a provenance table that retains all local records, including data not mapped into runtime tables.
- Localhost-only disposable rehearsal harness for migrate, import, custom-format `pg_dump`, restore, per-table reconciliation and cleanup.
- PostgreSQL adapter correction so imported/generated follow-ups inherit the signal owner and remain visible through owner-scoped queries.

No cloud project, database, secret, scheduler, registry, image, service or job was created. No Telegram delivery or Git push was performed. The local production database was not written.

## Verification results

| Check | Result |
| --- | --- |
| Full unit/security/adapter suite | PASS; 54 tests, 0 failures |
| P4-specific migration/import tests | PASS; 4 tests, 0 failures |
| P2 golden signal parity | PASS; `28e7e4c98f71fed9fbc74a417331cd25743fe491c49b4b7e515bfe7807d1fab0` |
| P2 golden follow-up parity | PASS; `c015cd4692954a4a14efaa7468a0fa364c8d7f303afc31b10debcc691dd2cf18` |
| Production SQLite dry-run | PASS; source unchanged |
| Production SQLite SHA-256 during dry-run | `4fdbe43d20b6fc5a0d6aef16ea7a1706a7a8b2240e797a252db392261b6da78e` |
| Source inventory | 127 scans, 8 signals, 8 plans, 11 decisions, 27 follow-ups, 47 audit events; 181 mapped target rows |
| Real PostgreSQL engine | PASS on PostgreSQL 15.18, disposable localhost cluster |
| Migration idempotency | PASS; first apply `[1]`, second apply `[]` |
| Import idempotency | PASS; all per-table counts unchanged after second import |
| Provenance retention | PASS; 228/228 local rows retained in `legacy_import_records` |
| Backup/restore | PASS; custom-format `pg_dump`/`pg_restore`, all 11 checked table counts equal |
| Real readiness | PASS; `/readyz` returned HTTP `200 OK` with `{"ready":true}` |
| Local production health after verification | PASS; HTTP 200, 8 signals, latest scan `Completed` |
| `git diff --check` and Python compile | PASS |

## Rehearsal isolation

The current PostgreSQL 15.19 download was blocked upstream with HTTP 403, so the supported PostgreSQL 15.18 Windows installer was used after its SHA-256 matched `8D1AC971810B819D861AC6BC47CEAA87A23251C9194F66255EC4AC208D15D688`.

The successful run used a separate user-owned cluster bound only to `127.0.0.1:55432`. It created random `nxt_rehearsal_*` and `nxt_restore_*` databases, dropped both in `finally`, removed the password file and stopped the cluster. The production SQLite file remained read-only and unchanged.

## Artifact hashes

| Path | SHA-256 |
| --- | --- |
| `cloud/migrations/0001_shadow_schema.sql` | `AE88A2F386AA5C1A0E6507A3F5A2DF3D3E1EBD3C5AE2FB5B96037471E68FD1D2` |
| `scripts/nxt_cloud_migrate.py` | `386E7480A849147590E8E6873FF7F359782793419E3A6B77F68BC7C7E641224D` |
| `scripts/nxt_cloud_import_sqlite.py` | `C9B3CC4B4512671D11BFC405A96C1CDB32DC823ECC90E026574B15FA2245D0ED` |
| `scripts/rehearse_nxt_cloud_postgres.py` | `0B97EDB7AC5453C55846194FA42E9038CE6E86A4C8F67FC377EC7B47D66B5C8D` |
| `app/nxt_cloud/postgres.py` | `94187671BD78DD7120D344F6EB5B862214B1AAA596C3C70C75FEB10B3537171A` |

## Next authority boundary

This evidence supports G4 review. Until G4 is explicitly approved, do not create a Supabase/GCP project, secret, registry, service, scheduler or deployment. G4 would authorize only the separately reviewed P5 cloud-foundation scope.
