# G21 — Action Center status/outcome parity (2026-09-23)

## Scope

- Count both `Pending` and `Reminder` follow-ups as pending operator actions, matching local NXT.
- Continue excluding `DATA_STALE` and `NO_ACTION` from Action Center.
- Render the five most recent actionable follow-ups even when already acknowledged, matching local history visibility.
- Store follow-up `status` and `outcome` separately; an operator outcome changes status to `Acknowledged`.

## Schema and data

- Applied migration `0002_followup_outcome_parity.sql`.
- Schema version verified at `2`.
- Existing outcomes were backfilled from `legacy_import_records`.
- Verified normalized cloud state:
  - pending operator actions: `2`
  - actionable follow-ups including history: `7`
  - acknowledged `Applied`: `4`
  - acknowledged `Already Closed`: `1`
  - reminder `PENDING_CONFIRMATION`: `2`

## Verification and deployment

- Commit: `927f1a6`.
- Test build: `362f9b12-3b32-4ca8-a63e-767861308b08` — 69 tests passed.
- Image build: `5f6685f2-d38f-49ca-86cd-e3569fa1b1e6`.
- Image digest: `sha256:bb9eadf0bad5e90aa1467737e4eb2482c6f08c6a1540ae69de47216a2f7bea8f`.
- Web revision after schema metadata update: `nxt-cloud-shadow-00021-d2m`, 100% traffic.
- Scanner job uses Git SHA `927f1a6`.
- Authenticated readiness returned `{"ready": true}`.
- No scanner execution or Telegram delivery was triggered by this change.
