# G12 scheduled SHADOW scanner activation — 2026-09-22

## Approved operating mode

The owner selected option 1: automatically run the existing cloud SHADOW
scanner while leaving local NXT unchanged. This is not a PROD data/schema
cutover. Cloud messages continue to identify themselves as
`[NXT-CLOUD][SHADOW]`.

## Enabled services and identity

- Enabled API: `cloudscheduler.googleapis.com`.
- Created dedicated service account:
  `nxt-cloud-scheduler@nxt-cloud-shadow.iam.gserviceaccount.com`.
- Granted that identity `roles/run.invoker` only on Cloud Run job
  `nxt-cloud-shadow-scanner`.
- Scanner runtime identity remains
  `nxt-cloud-runtime@nxt-cloud-shadow.iam.gserviceaccount.com`.

## Enabled schedules

All jobs use location `asia-southeast1`, timezone `Asia/Ho_Chi_Minh`, HTTP
`POST`, OAuth with the dedicated scheduler identity, and target only the Cloud
Run scanner job.

| Scheduler job | Daily ICT time |
|---|---:|
| `nxt-cloud-shadow-scan-0701` | 07:01 |
| `nxt-cloud-shadow-scan-0801` | 08:01 |
| `nxt-cloud-shadow-scan-0901` | 09:01 |
| `nxt-cloud-shadow-scan-1001` | 10:01 |
| `nxt-cloud-shadow-scan-1201` | 12:01 |
| `nxt-cloud-shadow-scan-1431` | 14:31 |
| `nxt-cloud-shadow-scan-1601` | 16:01 |

Verification returned `7` configured jobs and `7` jobs in `ENABLED` state.

## End-to-end invocation test

- Manually triggered scheduler job `nxt-cloud-shadow-scan-0701`.
- Scheduler created Cloud Run execution `nxt-cloud-shadow-scanner-hznnj`.
- Execution completed successfully.
- Scanner result: `SKIPPED_COMPLETED` for candle `2026-09-21`.
- No Telegram item was delivered by the test because that candle already had a
  completed scan.

## Boundaries retained

- Local NXT files, process, Windows tasks and Telegram settings were not changed.
- Cloud remains SHADOW and recommendation-only.
- No Binance credentials or order-execution capability were added.
- No PROD schema, resource or cutover was created.
- No Git remote was changed or pushed.
