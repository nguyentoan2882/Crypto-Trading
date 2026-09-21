# NXT Cloud Shadow — G6 Cloud Run deployment evidence

Date: 2026-09-21  
Decision authority: G6 approved by the user  
Decision state: **G6 COMPLETE — CLOUD RUN SHADOW DEPLOYED AND VERIFIED**

## Authorized scope

G6 authorized provisioning the Google Cloud `SHADOW` runtime and deploying the
NXT Cloud backend to Cloud Run. It did not authorize Telegram delivery,
scheduled execution, Binance-authenticated writes, production cutover or a Git
push.

## Provisioned resources

- Google Cloud project: `nxt-cloud-shadow` (`692928112671`)
- Billing: linked and enabled after the user completed Google Cloud activation
- Region: `asia-southeast1`
- Enabled APIs: Cloud Run, Cloud Build, Artifact Registry and Secret Manager
- Artifact Registry Docker repository: `nxt-cloud`
- Runtime service account:
  `nxt-cloud-runtime@nxt-cloud-shadow.iam.gserviceaccount.com`
- Secret Manager entries: `nxt-database-url` and `nxt-health-token`
- Secret access is granted to the dedicated runtime service account

No secret value, database password, token, OTP or connection URL is recorded in
this evidence or committed to the repository.

## Deployed revision

- Cloud Run service: `nxt-cloud-shadow`
- Revision: `nxt-cloud-shadow-00007-b2j`
- Traffic: 100% to the revision above
- Application Git SHA: `a356e6c`
- Container image:
  `asia-southeast1-docker.pkg.dev/nxt-cloud-shadow/nxt-cloud/nxt-cloud-shadow:a356e6c`
- Image digest:
  `sha256:94690afb213fbf1affd8866a066cd9584618404c02c212395d43ecc4e4da855a`
- Successful Cloud Build ID: `d65aeaf8-b156-473a-8999-a491c7faef16`
- Service URL: `https://nxt-cloud-shadow-tqt6zxjnca-as.a.run.app`

Runtime limits are 1 CPU, 512 MiB memory, concurrency 20, request timeout 30
seconds, minimum instances 0 and maximum instances 1. The service permits
public Cloud Run invocation, while application endpoints remain protected by
Supabase JWT validation, owner allow-listing and `aal2` MFA enforcement.

## Database readiness

The P5 schema had been applied manually through the Supabase SQL Editor, so the
business schema existed without the migration runner's history table. A
one-time bootstrap verified all 10 expected tables and RLS before creating only
the missing `schema_migrations` metadata and recording migration version 1.

- Bootstrap build ID: `58b14b32-62df-4ba5-9f55-c9e89c45ac8b`
- Recorded migration checksum:
  `ae88a2f386aa5c1a0e6507a3f5a2df3d3e1ebd3c5ae2fb5b96037471e68fd1d2`
- Result: `MIGRATION_HISTORY_BOOTSTRAP_OK version=1`

## Verification result

Post-deployment smoke checks against revision `nxt-cloud-shadow-00007-b2j`:

| Check | Expected | Observed |
|---|---|---|
| `GET /health` | Public liveness | HTTP 200, `alive: true`, environment `SHADOW` |
| `GET /ready` with health token | Database readiness | HTTP 200, `ready: true` |
| Unauthenticated `GET /` | Reject missing user JWT | HTTP 401 |

The external aliases `/health` and `/ready` are used because Cloud Run reserves
some URL paths ending in `z`; `/healthz` and `/readyz` remain available for
internal and backward-compatible routing.

Final regression check: `python -m unittest discover -s tests -q` — **57 tests
passed**.

## Remaining boundary

- No Cloud Scheduler schedule or Cloud Run job was created.
- Telegram is not configured or enabled.
- No Binance-authenticated credential or write path is enabled.
- No production cutover was performed; the deployment remains `SHADOW`.
- No Git push was performed.
- Authenticated browser/dashboard UAT remains a subsequent controlled gate.
