# G15 — Password-only Cloud Auth

Date: 2026-09-22

## Approval and scope

- Owner explicitly requested disabling the application MFA requirement: email and Supabase Auth password are sufficient.
- The existing Supabase TOTP factor was not deleted. The Cloud NXT login flow simply no longer challenges or verifies it.
- Scope remains SHADOW/recommendation-only. Local NXT and exchange execution behavior were not changed.

## Controls retained

- Supabase JWT signature, issuer, audience, expiry and subject validation.
- Owner user ID/email allow-list.
- Only authenticated assurance levels `aal1` and `aal2` are accepted; missing or unauthenticated assurance levels are rejected.
- Short-lived Secure, HttpOnly, SameSite=Strict session cookie.
- Origin allow-list, CSRF token and idempotency controls for browser writes.

## Verification

- Cloud Build test: `7cc7d6af-7569-410d-ba9c-4951c361bfd5` — SUCCESS.
- Test result: `64 passed, 3 subtests passed`.
- Source commit: `9ad11d7` (`feat: allow password-only cloud login`).
- Image build: `69180d52-c28b-4c2a-b3ac-cf594dc01e9d` — SUCCESS.
- Image: `asia-southeast1-docker.pkg.dev/nxt-cloud-shadow/nxt-cloud/nxt-cloud-shadow:9ad11d7`.
- Digest: `sha256:2e9ba8517f50880db93181706cddef40434c84e4b4141f3c1a9ac4231097b8ef`.
- Cloud Run revision: `nxt-cloud-shadow-00015-wtr`, 100% traffic.
- Live checks: `/health` = 200, `/login` = 200, unauthenticated `/` = 401.
- Live login page contains the Supabase password field and contains no TOTP/factor challenge flow.
- Scanner job was aligned to image/Git SHA `9ad11d7`; its scheduler and runtime policy were otherwise unchanged.

An earlier image push attempt (`24bc4060-2dd0-4908-8a69-f3f9bb969345`) failed because it targeted a non-existent Artifact Registry repository. It did not alter Cloud Run. The successful build above used the repository already configured on the service.
