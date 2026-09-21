# P3 Local Cloud Adapters Evidence

Date: 2026-09-21
Branch: `codex/nxt-cloud-shadow`
G2 implementation parent: `5c4b285`
Decision state: **P3 CODE COMPLETE — CONTAINER/REAL-POSTGRES VERIFICATION PENDING**

## Delivered scope

- Production WSGI adapter designed for Gunicorn on `0.0.0.0:$PORT`.
- Public `/healthz`, limited `/readyz`, authenticated dashboard and paginated API reads.
- Supabase JWKS JWT verifier restricted to asymmetric `ES256`/`RS256`, issuer, audience, expiry and `aal2` MFA.
- Owner user/email allowlist, Origin control, double-submit CSRF for cookie writes and mandatory idempotency keys.
- PostgreSQL repository with parameterized SQL, short transactions, advisory locks, business-key conflicts and durable outbox methods.
- Ephemeral per-signal quantity calculator with blank Equity/Risk inputs, locked Entry/Stop and no leverage, form, API call or browser storage.
- Finite scanner with an all-symbol/date/OHLC fail-closed gate, PostgreSQL lock, completed-run skip and persist-before-notify ordering.
- Mandatory `cloud-shadow:*` delivery namespace and `[NXT-CLOUD][SHADOW]` plus testing disclaimer on every Telegram message.
- One image/two roles entrypoint, exact dependency pins, non-root container user and pinned official Python base-image index digest.

No cloud project, database, secret, scheduler, registry, image, service or job was created. No Git push was performed.

## Verification results

| Check | Result |
| --- | --- |
| Full unit/security/adapter suite | 50 passed, 0 failed |
| P2 golden signal parity | PASS; expected and actual hash `28e7e4c98f71fed9fbc74a417331cd25743fe491c49b4b7e515bfe7807d1fab0` |
| P2 golden follow-up parity | PASS; expected and actual hash `c015cd4692954a4a14efaa7468a0fa364c8d7f303afc31b10debcc691dd2cf18` |
| Real WSGI loopback request | PASS; `GET /healthz` returned HTTP 200 |
| Dependency lock installation | PASS in isolated temporary directory |
| Portable runtime imports | PASS for PyJWT 2.14.0, Psycopg 3.3.6, Psycopg Pool 3.3.2 and Cryptography 50.0.1 |
| Local RS256 JWT validation | PASS with an in-memory temporary key |
| Partial/stale/invalid market-data rejection | PASS; no business persistence |
| Lock/completed-run idempotent skip | PASS |
| Signed Binance endpoint/header scan | PASS; none present |
| Local production health after verification | HTTP 200; 8 signals; latest scan Completed |
| `git diff --check` and Python compile | PASS |

## Host limitations and unclosed verification

1. Docker, Podman and nerdctl are not installed on this Windows host. The Linux container was therefore **not built or executed**. Gunicorn correctly cannot run natively on Windows because it requires POSIX `fcntl`; the WSGI application itself passed a real loopback HTTP test.
2. There is no disposable PostgreSQL server or P4 schema yet. Repository tests cover DB-API integration shape, parameterization, validation and transaction/advisory-lock ordering, but not real PostgreSQL execution.
3. `/readyz` is expected to remain false until P4 supplies and applies the reviewed schema migration.

These items prohibit declaring P3 deploy-ready. They do not require or authorize cloud provisioning. P4 should create SQL migrations and a disposable local rehearsal/restore path; a Docker-capable review host must later build and smoke the exact image before any G3/G4 claim.

## Artifact hashes

| Path | SHA-256 |
| --- | --- |
| `Dockerfile` | `A57BE8B2F71C411BC47761ABD76F677C8689B11DE05EAABCAFB16767867DEFAA` |
| `requirements-cloud.lock` | `D765C52D8D31B38D6A858D93F53D401CF092F62AF16EA44A47496D6BBF808E90` |
| `app/nxt_cloud/web.py` | `7A01952A78CF134CE471AD22298E9BCB021C7602ECB3451926C8F367AE3957DA` |
| `app/nxt_cloud/postgres.py` | `35801A2E9E1D62C17C945DCD77C8E5DFD3E22B7E0D99B5082306DB1499DC050C` |
| `app/nxt_cloud/scanner.py` | `6455F73BA512DAB761D45FED561950A63CCC63D042D7B7C7C07E775F4970DF66` |
| `app/nxt_cloud/auth.py` | `CD109CFB4AB86639F48382222D8F682B5AB098D552EDEA43E49314B9FAF288BB` |
| `app/nxt_cloud/outbox.py` | `FAE6D67A6C9F4E574A1CDD97A93FA2B554F3DA824011215B86D61DA7721048D5` |
| `tests/test_nxt_cloud_adapters.py` | `4B0EE65498D87DBA1949357DBD2453078988A2A097C20E9D5F380CD175527352` |

## Next authority boundary

Proceeding to P4 would authorize only local SQL migrations, copy-only migration tooling, disposable rehearsal, idempotency checks and backup/restore drill. It would still not authorize cloud resources, deployment, real secrets, Telegram delivery, Git push or changes to local production.
