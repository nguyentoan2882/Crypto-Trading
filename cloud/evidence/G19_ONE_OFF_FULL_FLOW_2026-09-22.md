# G19 — One-off full-flow rerun (2026-09-22)

## Authority and scope

- User explicitly approved one duplicate run for 2026-09-22, including Telegram delivery.
- Environment remained `SHADOW`; no exchange credentials, order execution, production cutover, or local NXT changes.
- Force mode was supplied only as an execution override: `NXT_FORCE_RUN_ID=manual-20260922-fullflow1`.

## Implementation and verification

- Commits: `6bda9a5` (audited one-off rerun) and `4a74068` (unique forced scan audit source).
- Cloud test builds: `f7a45f1c-86e5-4425-bef3-b54f7f1fac0c` and `a2522a45-93eb-4e03-bcf8-5536f8ed7f17`.
- Result: 67 tests passed on Python 3.13.7 with the locked cloud dependencies.
- Deployed image digest: `sha256:86205432cf1fc6245887e3826a55e3a3882fa021ae3d2edcd5f58a3d2c129d2e`.
- Web revision: `nxt-cloud-shadow-00019-2ld`.

## Execution result

- An initial execution `nxt-cloud-shadow-scanner-lvvll` failed before outbox creation because the forced audit run reused the normal scan source and hit the existing `(environment, candle_date, rule_version, source)` key. The database transaction rolled back and Telegram was not sent.
- The forced audit source was then namespaced without changing the rule version, tests were rerun, and the same force ID was retried.
- Successful execution: `nxt-cloud-shadow-scanner-t6tnb`.
- Cloud Run status: `COMPLETED`, succeeded tasks `1`, failed tasks `0`.
- Scanner output:
  - candle date: `2026-09-21`
  - new signals: `0`
  - follow-ups evaluated: `4`
  - Telegram messages delivered: `1`
  - run ID: `504b3779-5ffe-41ba-8e92-d0924a726933`
  - input hash: `b961a45b69c39aa2b11433a1cddabaa5c901c81a2f7bcf9003196da0da4716d0`

## Post-run safety check

- The persisted scanner job remains `NXT_NOTIFICATION_MODE=telegram` on Git SHA `4a74068`.
- `NXT_FORCE_RUN_ID` is absent from the persisted job environment; subsequent scheduled executions retain normal completed-run deduplication.
