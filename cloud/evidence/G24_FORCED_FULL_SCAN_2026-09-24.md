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

The absence of a Telegram message is the expected business result after the G23
parity correction: the run completed end-to-end, but no new signal or actionable
follow-up existed. Authorization to duplicate a message does not synthesize a
notification when the scanner has no actionable content.
