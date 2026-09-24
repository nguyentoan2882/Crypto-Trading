# G24 - Forced full cloud scan

Date: 2026-09-24

## Authorization

The operator authorized one full Cloud SHADOW scan and explicitly accepted a
duplicate Telegram delivery if the run produced a notification.

## Execution

- Execution: `nxt-cloud-shadow-scanner-5vggj`.
- Force-run ID: `manual-20260924-fullflow-1`.
- Start: `2026-09-24T07:36:43.518186Z`.
- Completion: `2026-09-24T07:37:06.969511Z`.
- Infrastructure result: completed successfully; `succeededCount=1`.
- Application status: `COMPLETED`; container exit code `0`.
- Candle date: `2026-09-23`.
- Input hash: `0b37f5b234178e064ea767e09f72daead752dbc04edbff73a8b80c66cad7ef33`.
- Run ID: `ed915c2a-1bad-4194-9532-316017ae91da`.
- New signals: `0`.
- Evaluated follow-ups: `3`.

## Notification result

- BNBUSDT: `NO_ACTION` / `Informational`.
- BTCUSDT: `NO_ACTION` / `Informational`.
- SOLUSDT: `NO_ACTION` / `Informational`.
- Actionable notification batches: `0`.
- Force-run outbox rows: `0`.
- Telegram messages delivered: `0`.

## Superseded interpretation

The run facts above remain valid, but the original interpretation of
`delivered=0` was rejected by the operator. A daily follow-up is a status report:
an open/monitored subject with `NO_ACTION` must still be reported as `KHONG CAN
THAO TAC`, matching local NXT. G25 corrects the cloud notification filter while
continuing to suppress `DATA_STALE`.
