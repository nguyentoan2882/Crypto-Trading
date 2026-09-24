# G23 - Follow-up monitor terminal parity

Date: 2026-09-24

## Incident

The 07:01 ICT cloud scan completed successfully but Telegram repeated a historical
`DATA_STALE` recommendation for a BTC signal that local NXT had already removed
from monitoring after `TAIL_EXIT_SSL` was acknowledged as `Applied`.

## Root cause

- The PostgreSQL `accepted_monitor_subjects` view did not exclude signals with an
  acknowledged terminal outcome, unlike the local SQLite query.
- Its pending-follow-up subquery did not exclude `DATA_STALE`, `NO_ACTION`, and
  `NEEDS_REVIEW`.
- The cloud Telegram filter excluded `NO_ACTION` but not `DATA_STALE`.

## Correction

- Migration `0003_monitor_terminal_parity.sql` aligns monitor selection,
  acknowledged-action selection, and pending-follow-up selection with local NXT.
- Cloud scanner persists `DATA_STALE` for audit but does not enqueue it to Telegram.

## Verification

- Test build: `a5ed6726-4fdf-4a34-9cbe-c922270429c0` - 70 tests passed.
- Migration: schema version `3` applied.
- Post-migration monitor subjects: `3`.
- The affected terminal BTC signal is no longer monitored.
- Image build: `658a944e-459d-4c1e-8f23-2c6c4f02a551`.
- Git SHA/image tag: `7a10be5`.
- Image digest: `sha256:cdd0bc1ca6d365b5aef4725dd04f085a7119b5d223b41c6163b8ef437c6c7131`.
- Web revision: `nxt-cloud-shadow-00023-7rk`, serving 100% traffic.
- Web and scanner job both use image tag `7a10be5`.
- Authenticated readiness: `{"ready":true}`.
- No manual scanner execution or Telegram test message was sent.

The first attempt to apply the migration through Cloud Build was rejected because
that build service account cannot access Secret Manager. The migration was then
applied with the already-authorized operator identity without changing IAM.
