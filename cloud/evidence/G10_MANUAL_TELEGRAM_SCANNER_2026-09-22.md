# G10 manual Telegram scanner evidence — 2026-09-22

## Approval and boundary

- The owner confirmed receipt of the Telegram connectivity message and approved
  continuing with one manual SHADOW scanner execution.
- Cloud Scheduler, production/cutover, exchange credentials, and order execution
  remained out of scope.

## Execution

- Cloud Run job: `nxt-cloud-shadow-scanner`.
- Execution: `nxt-cloud-shadow-scanner-v72x6`.
- Image digest:
  `sha256:858a90a40a2de7e100ee7e3e9f2bc7e026a5ec974d278a67b6cd2a9389922584`.
- Service account:
  `nxt-cloud-runtime@nxt-cloud-shadow.iam.gserviceaccount.com`.
- Retry policy: `maxRetries=0`.
- Cloud Run result: successful, task count `1/1`, container exit code `0`.

## Scanner result

```json
{
  "status": "COMPLETED",
  "candleDate": "2026-09-21",
  "newSignals": 0,
  "followUps": 4,
  "delivered": 1,
  "notificationMode": "telegram",
  "inputHash": "2a9c5ded8c1be02fb567a745894caf1808b0ace418dd2717beb71486c902b930",
  "runId": "21c7b721-ef11-49d3-9167-6e2f962a0dc8"
}
```

The delivered Telegram item was produced by the SHADOW notification outbox. No
new signal was created in this run; the message related to the four evaluated
follow-ups. All cloud messages retain the `[NXT-CLOUD][SHADOW]` warning and are
recommendation-only.

## State after execution

- The scanner remains a manual Cloud Run job.
- Cloud Scheduler was not enabled or created.
- No production resource was changed.
- No Binance credential or order-submission capability exists in this image.
- No Git remote was changed or pushed.
