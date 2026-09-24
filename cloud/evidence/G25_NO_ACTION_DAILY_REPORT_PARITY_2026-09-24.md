# G25 - NO_ACTION daily report parity

Date: 2026-09-24

## Corrected business rule

- Action Center contains only follow-ups that require an operator decision;
  `NO_ACTION` and `DATA_STALE` are not pending actions.
- Telegram is a daily status report for every monitored accepted signal/open
  position. `NO_ACTION` must therefore be sent as `KHONG CAN THAO TAC`, including
  the theoretical-position warning when the signal has not been tracked.
- `DATA_STALE` remains audit-only and is not sent as a valid daily assessment.

## Verification and deployment

- Test build: `b447dd70-6699-44b2-bc07-35ba455b890a` - 71 tests passed.
- Regression test verifies `NO_ACTION` produces the bold Telegram action and
  theoretical warning.
- Regression test verifies `DATA_STALE` is persisted but not notified.
- Commit/image tag: `066faff`.
- Image build: `875d0e74-e77c-4dd7-b02a-7cae0ff66c04`.
- Image digest: `sha256:638a29642f979a347586386deffb789af522f09ff715405e2c440c9cee6f3f90`.
- Web revision: `nxt-cloud-shadow-00024-rwm`, serving 100% traffic.
- Authenticated readiness: `{"ready":true}`.
- Scanner job uses image tag `066faff`.
- No scanner execution or Telegram delivery was triggered by this deployment.
