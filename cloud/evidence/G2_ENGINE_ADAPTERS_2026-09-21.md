# G2 Engine and Adapter Evidence

Date: 2026-09-21
Branch: `codex/nxt-cloud-shadow`
Baseline parent: `58e974772843b9896c8431fca27b7274e5652f03`
Decision state: **READY FOR G2 REVIEW — NOT APPROVED**

## Implemented P2 scope

- Extracted signal generation, order construction and accepted-signal follow-up evaluation into `app/nxt_core/rules.py`.
- Kept time and fixed-risk configuration outside the pure boundary and passed them explicitly.
- Preserved the legacy `app/nxt_signal_app.py` entrypoints through compatibility wrappers.
- Added structural ports for market data, repository and notifier adapters.
- Added canonical normalization and SHA-256 comparison helpers.
- Added a versioned golden fixture captured before extraction.
- Added an executable golden comparison command and regression tests.

No PostgreSQL, Cloud Run, Supabase, auth, container, cloud credential or cloud resource was created in P2.

## Golden inputs and results

Fixture SHA-256: `1084AFE739A8010E99DDB8B90B2FC9D7B8F8404FCD68B8008738C4CF1D300AF4`

The signal case locks the three tracked USD-M cache files by SHA-256 and evaluates them at the fixed cutoff `2026-07-14T01:00:00Z`. It produces one SOLUSDT SHORT Primary signal and explicit null results for BTCUSDT and BNBUSDT. The follow-up case locks a full `TAKE_TP1_30_MOVE_BE` recommendation payload.

| Comparison | Expected hash | Actual hash | Result |
| --- | --- | --- | --- |
| Normalized signal output | `28e7e4c98f71fed9fbc74a417331cd25743fe491c49b4b7e515bfe7807d1fab0` | `28e7e4c98f71fed9fbc74a417331cd25743fe491c49b4b7e515bfe7807d1fab0` | PASS |
| Full follow-up output | `c015cd4692954a4a14efaa7468a0fa364c8d7f303afc31b10debcc691dd2cf18` | `c015cd4692954a4a14efaa7468a0fa364c8d7f303afc31b10debcc691dd2cf18` | PASS |

Comparator command:

```powershell
python -B scripts\compare_nxt_rule_golden.py
```

Comparator result: `passed=true`; all BTCUSDT, BNBUSDT and SOLUSDT input hash and row-count checks passed.

## Verification evidence

- Full unit suite: **29 passed, 0 failed**.
- Existing follow-up suite still covers stop priority, TP1/BE, 4R, SSL/EMA exits, pending/catch-up behavior and tracked/theoretical separation.
- Fixed-input determinism test: PASS.
- Rule source contains no SQLite, HTTP client, store import or file-write call: PASS.
- Market-data, repository and notifier structural port tests: PASS.
- Quantity calculator has no form submission, `fetch`, XHR, `localStorage`, `sessionStorage` or named inputs: PASS.
- Legacy dashboard entrypoint render smoke: PASS.
- `git diff --check`: PASS.
- Local production `/api/state`: HTTP 200 after P2 verification.

## Artifact hashes

| Path | SHA-256 |
| --- | --- |
| `app/nxt_core/rules.py` | `64F15D8784806ED50C321D53B8A8CCC3238881688D8B47C5506B37AC3275D0E0` |
| `app/nxt_core/ports.py` | `CEF26EB8FFD6A6BFAEAA0639D806BFDBCC16FF4F5598C8BD56B7A04DDE9EBC9F` |
| `app/nxt_core/comparison.py` | `CD4388CB94F5B07065142AFE652E0F581BC85B47CDB783171C2E816228E620DE` |
| `tests/fixtures/nxt_rule_golden_v1.json` | `1084AFE739A8010E99DDB8B90B2FC9D7B8F8404FCD68B8008738C4CF1D300AF4` |

## G2 decision boundary

P2 evidence supports G2 review for the engine boundary. Approval of G2 would authorize P3 local cloud adapters only. It would not authorize provisioning, deployment, push, ACTIVE/PROD status, or any change to local production.
