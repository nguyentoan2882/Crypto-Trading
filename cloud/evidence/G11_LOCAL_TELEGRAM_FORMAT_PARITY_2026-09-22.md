# G11 local Telegram format parity — 2026-09-22

## Requested outcome

Cloud SHADOW Telegram notifications must retain the same message body format as
the local NXT scanner. The mandatory cloud identity and safety disclaimer remain
as a two-line prefix.

## Implementation

- Added one shared formatter for local and cloud entry-signal messages.
- Added one shared formatter and batching implementation for local and cloud
  accepted-signal follow-ups.
- Preserved local fields, ordering, price formatting, suggested-order sizing,
  warning text, and bold `ACTION` blocks.
- Cloud generation timestamps are rendered in `Asia/Ho_Chi_Minh` time.
- Cloud Telegram delivery now uses `parse_mode=HTML`, matching local delivery.
- Cloud keeps this prefix before the unchanged local body:

  ```text
  [NXT-CLOUD][SHADOW]
  TESTING ONLY — local NXT remains official. Recommendation-only; no order execution.
  ```

## Verification and deployment

- Test build: `4b14a7e3-a1c2-4df9-b372-309755361a41`.
- Result: `63 passed, 3 subtests passed`.
- Source commit: `542a3ce`.
- Image build: `75115bdb-b8ff-4697-9f47-4a505cc290f7` (`SUCCESS`).
- Image digest:
  `sha256:dd8ed855ab8d1832277ddf00bbe289da3747a8a64a023086809fd15956ec2ab4`.
- `nxt-cloud-shadow-scanner` now uses image tag `542a3ce` with
  `NXT_NOTIFICATION_MODE=telegram`.
- The scanner was not executed during this format deployment, so no additional
  Telegram notification was sent.
- Scheduler and production remain unchanged.
