# G18 — Dashboard ICT timestamps

Date: 2026-09-22

## Scope

- Action Center follow-up cards show the closed D1 candle date and record creation time.
- New-signal Action Center cards show the signal date and detection time.
- The signal table has a dedicated `Signal / phát hiện` column.
- Timestamps are converted to `Asia/Ho_Chi_Minh` and labeled `ICT`; date-only D1 values remain dates.
- The change is display-only. Rule evaluation, persistence, scanner schedule, Telegram and local NXT are unchanged.

## Verification

- Local timestamp-format assertion: PASS (`2026-09-21T01:02:03Z` -> `2026-09-21 08:02 ICT`).
- Cloud Build test: `ae085559-b817-4323-bd7e-54cc2f811d52` — SUCCESS.
- Result: `65 passed, 3 subtests passed`.
- Source commit: `6f699cf` (`feat: show dashboard timestamps in ICT`).
- Image build: `d4ecb254-f055-4b43-8f94-2cb9f20a86ef` — SUCCESS.
- Image digest: `sha256:66882100741c9893a056f254b3b424acca3c7a71316a484c852de55fd4b52dc6`.
- Cloud Run revision: `nxt-cloud-shadow-00017-g4l`, 100% traffic.
- Live `/health`: HTTP 200; unauthenticated `/`: HTTP 401.
- Scanner job aligned to image/Git SHA `6f699cf`; no scanner execution was triggered by this deployment.
