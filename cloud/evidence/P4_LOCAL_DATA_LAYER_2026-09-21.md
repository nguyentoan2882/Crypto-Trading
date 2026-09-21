# P4 Local Data Layer Evidence

Date: 2026-09-21
Branch: `codex/nxt-cloud-shadow`
G3 authority parent: `2ced77b`
Decision state: **P4 CODE COMPLETE — REAL POSTGRESQL REHEARSAL PENDING**

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
| Local production health after verification | PASS; HTTP 200, 8 signals, latest scan `Completed` |
| `git diff --check` and Python compile | PASS |

## Host limitation

This host has no Docker/Podman/nerdctl, PostgreSQL server, `psql`, `pg_dump` or `pg_restore`, and no installed WSL distribution. Therefore the migration SQL, import/re-import and backup/restore harness could not be executed against a real PostgreSQL engine here.

That limitation blocks P4 exit/G4 readiness. It does not justify creating a Supabase project: the pending verification is explicitly local and disposable.

## Artifact hashes

| Path | SHA-256 |
| --- | --- |
| `cloud/migrations/0001_shadow_schema.sql` | `AE88A2F386AA5C1A0E6507A3F5A2DF3D3E1EBD3C5AE2FB5B96037471E68FD1D2` |
| `scripts/nxt_cloud_migrate.py` | `386E7480A849147590E8E6873FF7F359782793419E3A6B77F68BC7C7E641224D` |
| `scripts/nxt_cloud_import_sqlite.py` | `9DA8F336D75EC49549B7CAD1B72B47A4039A79BDA919D7D0EC2DE75634660958` |
| `scripts/rehearse_nxt_cloud_postgres.py` | `94893EFCF2BDBC89ADA12D18F8DB9A6AE53D4F9CB3C40EA41F26A1F7711DA190` |
| `app/nxt_cloud/postgres.py` | `94187671BD78DD7120D344F6EB5B862214B1AAA596C3C70C75FEB10B3537171A` |

## Next authority boundary

Do not approve or start P5/cloud provisioning yet. First run the documented disposable PostgreSQL rehearsal on a Docker/PostgreSQL-capable local host, attach the output, verify `/readyz`, and close P4. G4 would then authorize only the separately reviewed P5 cloud-foundation scope.
