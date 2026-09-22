# G16 — Action Center local-rule parity

Date: 2026-09-22

## Scope

- Cloud Action Center now applies the local dashboard follow-up visibility rule.
- `DATA_STALE` and `NO_ACTION` remain in PostgreSQL history/API for audit but are not presented as operator actions.
- Only pending actionable follow-ups are shown, with the local dashboard limit of five follow-up cards.
- Existing new-signal decision cards remain available in Cloud Action Center.
- No local NXT files, local runtime, scanner schedule, Telegram policy or execution boundary were changed.

## Verification

- Test build: `8eed964b-e33d-4979-8dea-12c3b5649c17` — SUCCESS.
- Result: `65 passed, 3 subtests passed`.
- Source commit: `4dcd5a9` (`fix: align cloud action center with local rules`).
- Image build: `b6f6a869-33ec-4210-b17a-31f7ec69c753` — SUCCESS.
- Image: `asia-southeast1-docker.pkg.dev/nxt-cloud-shadow/nxt-cloud/nxt-cloud-shadow:4dcd5a9`.
- Digest: `sha256:6697ec1519f0f19ac492c13984f956b965ac714e0e66a96655b5f516b74b5523`.
- Cloud Run revision: `nxt-cloud-shadow-00016-6xb`, 100% traffic.
- Live `/health`: HTTP 200.
- Live unauthenticated `/`: HTTP 401.
- Scanner job aligned to image/Git SHA `4dcd5a9` without executing a new scan.
