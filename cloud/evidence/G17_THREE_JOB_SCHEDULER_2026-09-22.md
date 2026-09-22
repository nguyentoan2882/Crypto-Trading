# G17 — Three-job scanner schedule

Date: 2026-09-22

## Approved change

The owner selected the recommended three-job schedule. Four redundant recovery
schedules were deleted; Cloud Run web, scanner configuration, Telegram behavior,
Supabase data and local NXT were not changed.

## Active schedules

| Scheduler job | Cron | Time zone | Role |
|---|---|---|---|
| `nxt-cloud-shadow-scan-0701` | `1 7 * * *` | `Asia/Ho_Chi_Minh` | Primary scan after Binance D1 close |
| `nxt-cloud-shadow-scan-0801` | `1 8 * * *` | `Asia/Ho_Chi_Minh` | Fast recovery |
| `nxt-cloud-shadow-scan-1201` | `1 12 * * *` | `Asia/Ho_Chi_Minh` | Final same-day recovery |

All three jobs are `ENABLED` and call the same idempotent Cloud Run job
`nxt-cloud-shadow-scanner` in `asia-southeast1`.

## Deleted schedules

- `nxt-cloud-shadow-scan-0901`
- `nxt-cloud-shadow-scan-1001`
- `nxt-cloud-shadow-scan-1431`
- `nxt-cloud-shadow-scan-1601`

The change reduces scheduled invocations from approximately 210 to 90 per
30-day month and reduces this application to three Scheduler jobs, matching the
documented free monthly job allowance when it is available on the billing
account.
