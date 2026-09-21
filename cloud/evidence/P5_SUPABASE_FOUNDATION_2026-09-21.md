# NXT Cloud Shadow — P5 Supabase foundation evidence

Date: 2026-09-21  
Decision authority: G4 approved by the user  
Decision state: **P5 SUPABASE FOUNDATION CREATED — SCHEMA VERIFIED**

## Provisioned boundary

- Supabase organization: `NXT Cloud Shadow`
- Plan: Free (`$0/month` at creation)
- Project: `nxt-cloud-shadow`
- Project reference: `bpeumngkdjjyrsumpkwh`
- Region: Southeast Asia (Singapore), `ap-southeast-1`
- Compute shown after provisioning: Nano
- Project health shown after provisioning: Healthy

No GCP resource, runtime deployment, scheduler, Telegram delivery, Binance write,
or local-production change was performed in this step.

## Security baseline

- Data API enabled.
- Automatic exposure of new tables disabled.
- Automatic RLS enabled for new public-schema tables.
- Migration `cloud/migrations/0001_shadow_schema.sql` applied through the
  Supabase SQL Editor.
- The migration defines no client-facing policies; browser-facing Supabase
  roles therefore receive no direct application-table access.
- No database password, API key, access token, or connection string was written
  to this repository.

## Verification result

The following read-only catalogue check was executed after migration:

```sql
SELECT
  count(*) FILTER (WHERE c.relkind = 'r') AS app_tables,
  count(*) FILTER (WHERE c.relkind = 'r' AND c.relrowsecurity) AS rls_enabled_tables,
  count(*) FILTER (WHERE c.relkind = 'v') AS app_views
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public'
  AND c.relname IN (
    'scan_runs','scan_run_symbols','signals','trade_plans','decisions',
    'manual_positions','followup_recommendations','notification_outbox',
    'idempotency_keys','legacy_import_records','accepted_monitor_subjects'
  );
```

Observed result:

| app_tables | rls_enabled_tables | app_views |
|---:|---:|---:|
| 10 | 10 | 1 |

Supabase reported `Success. No rows returned.` for the migration and returned
the single verification row above.

## Remaining boundary

This evidence does not authorize or claim completion of cloud data import,
Supabase Auth configuration, GCP/Cloud Run provisioning, secret injection,
runtime deployment, scheduling, Telegram delivery, or production cutover.
Those remain subject to their next reviewed gate.
