# NXT Cloud Shadow — P3 local adapter contract

Status: local implementation only. No cloud project, database, secret, scheduler or deployment is created by this phase.

## Runtime roles

The same image uses `python -m app.nxt_cloud.entrypoint` and selects one finite role:

- `ROLE=web`: Gunicorn WSGI service on `0.0.0.0:$PORT`.
- `ROLE=scanner`: one scan, one PostgreSQL advisory lock, persist-first outbox flow, then exit `0` or `1`.

Startup refuses any environment other than `SHADOW`. The scanner accepts only BTCUSDT, BNBUSDT and SOLUSDT through the public Binance USD-M `/fapi/v1/klines` endpoint. Authenticated Binance credentials and signed account/order routes are outside the implementation.

## Web security contract

- `GET /healthz`: public liveness only.
- `GET /readyz`: requires `X-NXT-Health-Token` when configured and reports only readiness.
- `/`, `/api/state`, `/api/signals`, `/api/scans`, `/api/followups`: owner allowlist plus Supabase JWT with `aal2`.
- Write APIs require an `Idempotency-Key`; cookie-authenticated writes additionally require an approved `Origin` and matching double-submit CSRF token.
- Legacy `/scan`, `/equity`, `/decision`, `/track-position` and `/followup-outcome` routes are absent.
- The quantity calculator has no form submission, named inputs, API call, browser storage, leverage or prefilled Equity/Risk value.

## Scanner safety contract

1. Fetch all three symbols.
2. Reject the run before rule evaluation when any symbol is missing, stale, future-dated or invalid.
3. Acquire a PostgreSQL advisory lock and skip an already-completed business date.
4. Evaluate the P2 pure rule engine.
5. Persist scan/signal/plan/follow-up state.
6. Enqueue only `cloud-shadow:*` notification keys.
7. Deliver only messages beginning with `[NXT-CLOUD][SHADOW]` and the testing disclaimer.
8. Exit after the finite run.

## Local verification

```powershell
python -B -m unittest discover -s tests -v
python -B scripts\compare_nxt_rule_golden.py
```

Dependency lock verification may install `requirements-cloud.lock` into an isolated temporary directory. Gunicorn is a POSIX server and must be exercised inside the Linux image; the Windows host uses the WSGI loopback smoke test instead.

## Container commands for a Docker-capable review host

These commands are review instructions, not automatic provisioning:

```powershell
docker build --tag nxt-cloud-shadow:p3 .
docker run --rm --env-file cloud\shadow.env --publish 8080:8080 nxt-cloud-shadow:p3
```

Do not create `cloud\shadow.env` from real secrets inside Git. P4 must supply migrations and a disposable PostgreSQL rehearsal database before `/readyz` can pass.
