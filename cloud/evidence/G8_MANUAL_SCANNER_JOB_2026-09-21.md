# NXT Cloud Shadow — G8 manual scanner job evidence

Date: 2026-09-21  
Decision authority: G8 approved by the user  
Decision state: **G8 COMPLETE — MANUAL SHADOW SCANNER VERIFIED**

## Authorized scope

G8 authorized one Cloud Run scanner job that can be invoked manually in
`SHADOW`. It explicitly did not authorize Cloud Scheduler, Telegram delivery,
Binance-authenticated access, production mode or Git push.

## Job configuration

- Google Cloud project: `nxt-cloud-shadow`
- Region: `asia-southeast1`
- Cloud Run job: `nxt-cloud-shadow-scanner`
- Runtime service account:
  `nxt-cloud-runtime@nxt-cloud-shadow.iam.gserviceaccount.com`
- Image tag:
  `asia-southeast1-docker.pkg.dev/nxt-cloud-shadow/nxt-cloud/nxt-cloud-shadow:f824f99`
- Image digest:
  `sha256:1a19001ba26d2dc4cd2890768b04e4e831ba3c1c86f8607c7d04e8a0f5173475`
- Successful Cloud Build ID: `30c619d4-494a-4cba-a4c2-81da011cd081`
- Tasks/parallelism: 1/1
- Maximum retries: 0
- Timeout: 600 seconds
- Resources: 1 CPU, 512 MiB
- Secret injection: `DATABASE_URL` from `nxt-database-url:latest`
- Notification mode: `disabled`
- Telegram environment variables: none

The scanner is restricted to the approved public Binance USD-M daily-klines
endpoint and BTCUSDT, BNBUSDT and SOLUSDT. Authenticated Binance credentials and
signed order/account routes remain forbidden.

## Implementation safeguards

- `NXT_NOTIFICATION_MODE=disabled` uses an explicit no-delivery adapter. It
  neither writes notification-outbox rows nor calls Telegram.
- Scanner-only workbook dependencies are included in the immutable container
  while web startup remains lazy and isolated from scanner imports.
- PostgreSQL monitor rows are normalized to the shared rule-engine contract.
- The PostgreSQL connection pool is closed explicitly when a finite job exits.
- Final local regression: `python -m unittest discover -s tests -q` — **61
  tests passed**.

## Manual execution evidence

The first execution, `nxt-cloud-shadow-scanner-rvb8z`, failed with exit code 1
before scan persistence because a PostgreSQL `pendingFollowup` payload had not
been normalized to the shared rule-engine envelope. Maximum retries was zero.
The adapter and job owner configuration were corrected before rerun.

Successful execution: `nxt-cloud-shadow-scanner-8qxzq`

| Field | Observed value |
|---|---|
| Status | `COMPLETED` |
| Candle date | `2026-09-20` |
| Symbols passing the all-symbol gate | BTCUSDT, BNBUSDT, SOLUSDT |
| New signals | 0 |
| Follow-ups evaluated | 4 |
| Delivered notifications | 0 |
| Notification mode | `disabled` |
| Input hash | `17a793a1a62a9af3c10ceae0d5d2e3191fc6a038b413929954452e0ea827124b` |

The successful execution exited 0. A second post-success manual execution,
`nxt-cloud-shadow-scanner-l8wg7`, returned `SKIPPED_COMPLETED` for the same
`2026-09-20` candle date, proving the database-backed completed-run idempotency
guard.

## Boundary verification

- Cloud Scheduler API remains disabled; no schedule was created.
- Telegram is not configured and no notification was delivered.
- No Binance API key, signed route or order execution exists.
- Environment remains `SHADOW`; local NXT remains official.
- No Git push was performed.

The job remains manual-only pending a separately approved scheduling gate.
