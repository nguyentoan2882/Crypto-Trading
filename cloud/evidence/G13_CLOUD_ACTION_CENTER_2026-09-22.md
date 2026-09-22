# G13 Cloud Action Center — 2026-09-22

## Finding

The authenticated cloud dashboard previously rendered only the signal table and
quantity calculator. `followupRecommendations` and the existing protected write
APIs were present, but the page did not render an Action Center.

## Implementation

- Added owner-scoped latest decisions and manual positions to dashboard state.
- Added an Action Center above the signal table.
- Signals without a recorded latest decision expose `Accept`, `Watchlist` and
  `Reject` actions.
- Pending actionable follow-ups expose `Applied`, `Dismissed` and
  `Not applicable` outcomes.
- Browser writes continue to require the existing MFA session, allowed origin,
  CSRF cookie/header pair and a unique idempotency key.
- The signal table now shows the latest decision status.
- Local NXT was not changed.

## Verification and deployment

- Test build: `6536c6d8-d568-4dfc-bd3f-d6a6f54a2da3`.
- Result: `64 passed, 3 subtests passed`.
- Source commit: `56cb766`.
- Image build: `18fb4254-83ef-41ca-9203-75899db1ec81` (`SUCCESS`).
- Image digest:
  `sha256:264369e8a0eb03de79cd15151fb33bfcf5c861ffabb60399bcd33457dbb05254`.
- Cloud Run revision: `nxt-cloud-shadow-00013-b99`, serving `100%` traffic.
- Web and scanner now use image tag `56cb766`.
- Live public checks: `/health` HTTP `200`, `/login` HTTP `200`, unauthenticated
  `/` HTTP `401` as designed.
- Scheduler configuration was not changed.
