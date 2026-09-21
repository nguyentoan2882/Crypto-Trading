# NXT Cloud Shadow — G7 authenticated browser UAT evidence

Date: 2026-09-21  
Decision authority: authenticated UAT gate approved by the user  
Decision state: **G7 COMPLETE — OWNER MFA LOGIN AND SHADOW DASHBOARD VERIFIED**

## Authorized scope

This gate authorized browser-based owner login with Supabase password plus TOTP
MFA and read-only verification of the deployed Cloud Run dashboard. It did not
authorize scheduled scanning, Telegram delivery, Binance-authenticated writes,
production cutover or a Git push.

## Deployed UAT revision

- Cloud Run service: `nxt-cloud-shadow`
- Region: `asia-southeast1`
- Revision: `nxt-cloud-shadow-00012-sd8`
- Traffic: 100%
- Application Git SHA and image tag: `8eeacd3`
- Image digest:
  `sha256:2cb20ea341ae3684a050de272ccc07bcddfd6f1d965532ce94495aede24dcd40`
- Cloud Build ID: `0d3792d9-72e5-46ee-85d1-14da435e9a58`
- UAT URL:
  `https://nxt-cloud-shadow-692928112671.asia-southeast1.run.app/`

## Authentication result

The owner completed the browser flow using the existing verified Supabase TOTP
factor:

1. Email and password established an `aal1` Supabase session.
2. A fresh TOTP challenge was created immediately before verification.
3. The current six-digit Authenticator code upgraded the token to `aal2`.
4. Cloud Run independently verified the JWT issuer, audience, signature, owner
   allow-list and `aal2` claim.
5. Cloud Run issued a one-hour `Secure`, `HttpOnly`, `SameSite=Strict`,
   `__Host-` session cookie and opened the dashboard.

The user's password, TOTP secret, six-digit code and access token were not shown
to the operator, written to logs or committed to the repository.

Cloud Run request logs for the successful session show:

| UTC timestamp | Request | Result |
|---|---|---:|
| `2026-09-21T15:53:10.948437Z` | `POST /auth/session` | HTTP 200 |
| `2026-09-21T15:53:11.421408Z` | `GET /` | HTTP 200 |

An unauthenticated dashboard request remained HTTP 401 before login.

## Dashboard verification

- The page displayed the mandatory `[NXT-CLOUD][SHADOW]` and testing-only
  warning.
- The page displayed the eight owner-scoped signals previously reconciled in
  the G5 SHADOW import.
- BTCUSDT, BNBUSDT and SOLUSDT rows rendered with side, entry and stop values.
- Each signal exposed the in-memory `Tính quantity` control.
- No write action, scan, order execution, Telegram delivery or local-production
  change was performed during this UAT.

## Defects resolved during UAT

- The MFA challenge is now created immediately before verification, reducing
  the window for Supabase challenge/verify IP mismatch.
- The browser-login origin allow-list was corrected to the exact Cloud Run URL
  used for UAT.
- Final local regression: `python -m unittest discover -s tests -q` — **58
  tests passed**.

## Remaining boundary

The service remains `SHADOW`; local NXT remains official. Cloud Scheduler,
Cloud Run scanner job, Telegram, Binance-authenticated access, production
cutover and Git push remain disabled or absent and require separate explicit
approval.
