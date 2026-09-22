# G14 quantity calculator notional — 2026-09-22

- Added `Notional USD` to the per-signal quantity popup.
- Formula: `notional = raw quantity × entry`.
- Display uses USD formatting with two decimal places.
- Risk USD, risk per unit, raw quantity and the 30% / 10% / 60% split are
  unchanged.
- The calculator remains browser-memory-only: no form submission, network
  request, local/session storage or leverage input was added.
- Regression build `783397a9-dc1c-48ac-bc2a-50a06f23ddc2` passed `64` tests
  and `3` subtests.
- Source commit: `ff74c47`.
- Image build: `82dcc578-1b77-4d71-a89d-d1b67f1b7be7` (`SUCCESS`).
- Image digest:
  `sha256:48c8e87027619afd076162529298896bfceccfcafaed6af0b0d1018308f8333e`.
- Cloud Run revision `nxt-cloud-shadow-00014-xvp` serves `100%` of traffic.
- Local NXT and Cloud Scheduler configuration were not changed.
