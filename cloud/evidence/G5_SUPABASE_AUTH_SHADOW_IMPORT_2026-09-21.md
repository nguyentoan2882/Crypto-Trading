# NXT Cloud Shadow — G5 Auth, MFA and SHADOW import evidence

Date: 2026-09-21  
Decision authority: G5 approved by the user  
Decision state: **G5 COMPLETE — AUTH/MFA AND SHADOW IMPORT VERIFIED**

## Authorized scope

G5 authorized Supabase Auth/MFA configuration and import of the existing NXT
SQLite data into the Supabase `SHADOW` environment. It did not authorize Cloud
Run deployment or Telegram delivery.

## Auth and MFA verification

- The invited owner completed Supabase Auth sign-in.
- TOTP MFA is enabled for the project.
- The owner enrolled and verified a TOTP factor.
- The local enrollment flow reported
  `MFA_COMPLETE — assurance level: aal2` after challenge verification.
- The Supabase Auth redirect allow list contains
  `http://127.0.0.1:8767/p5_mfa_enroll.html` for the temporary local password
  recovery flow.
- No Auth password, TOTP secret, OTP, database password, access token or service
  key was written to the repository.

## SHADOW import verification

Source SQLite SHA-256:
`4fdbe43d20b6fc5a0d6aef16ea7a1706a7a8b2240e797a252db392261b6da78e`

Normalized content SHA-256:
`c7f04be87a70201a7e1d0ff1a7bf09bbecf73cdb90d45eb5b08d2913ffefddef`

Observed owner-scoped `SHADOW` row counts after the first import:

| Table | Rows |
|---|---:|
| `scan_runs` | 127 |
| `signals` | 8 |
| `trade_plans` | 8 |
| `decisions` | 11 |
| `manual_positions` | 0 |
| `followup_recommendations` | 27 |
| `legacy_import_records` | 228 |

The same import was executed a second time. Before and after counts were
identical, the source checksum was unchanged, and the result reported
`idempotent: true` and `status: IMPORT_COMPLETE`.

## Implementation and regression checks

- The importer supports hidden interactive password input and percent-encodes
  database credentials when building a TLS-required PostgreSQL URL.
- The importer can emit a transactional, advisory-locked, idempotent SQL file
  without storing the database password.
- `python -m unittest discover -s tests -v`: **56 tests passed**.
- The temporary import form, generated SQL, recovery/enrollment page and import
  result remain under ignored `outputs/`; they contain no committed secrets.

## Remaining boundary

No Cloud Run service, GCP scheduler, registry, secret injection, production
cutover, Telegram delivery or Binance-authenticated write was created or
enabled. Those actions remain outside G5 and require their next explicit gate.
