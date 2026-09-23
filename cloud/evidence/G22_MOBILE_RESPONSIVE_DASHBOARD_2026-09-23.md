# G22 - Mobile responsive dashboard

Date: 2026-09-23

## Scope

- Make the authenticated Cloud Shadow dashboard fit a 400 px mobile viewport.
- Preserve desktop table presentation above 760 px.
- Do not execute the scanner or send Telegram notifications.

## Change

- Added viewport scaling and global horizontal-overflow protection.
- Converted the signal table into labelled row cards at widths up to 760 px.
- Made panels, action cards, action buttons, banner text, and quantity dialog responsive.
- Added HTML contract assertions for the mobile breakpoint and table labels.

## Verification

- Python compile: passed.
- Cloud Build test ID: `e2b433ea-ab45-4a2a-ac28-9f8aadce7884`.
- Tests: `69/69` passed on Python 3.13 Linux.
- Image build ID: `756037a5-0973-4bfa-87b8-751fb9dd9331`.
- Git SHA/image tag: `0dfb05e`.
- Image digest: `sha256:ae1dee183f4efde9e34a08752f7db6fc62b43e349a5d11cdbd30f39a30329440`.
- Cloud Run revision: `nxt-cloud-shadow-00022-j5s`, serving 100% traffic.
- Authenticated readiness: `{"ready":true}`.
- Scanner job updated to the same image but was not executed.
