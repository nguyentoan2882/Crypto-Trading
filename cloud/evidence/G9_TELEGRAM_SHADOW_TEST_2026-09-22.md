# G9 Telegram SHADOW connectivity evidence — 2026-09-22

## Approved scope

- The owner explicitly approved reusing the existing local Telegram bot for the
  cloud SHADOW test.
- This gate does not authorize Cloud Scheduler, production/cutover, exchange
  credentials, or order execution.

## Secret handling

- Created Secret Manager secrets `nxt-telegram-bot-token` and
  `nxt-telegram-chat-id`, each with one enabled version.
- Granted `roles/secretmanager.secretAccessor` on only those secrets to
  `nxt-cloud-runtime@nxt-cloud-shadow.iam.gserviceaccount.com`.
- Secret values were never printed or committed.

## Image and test

- Source commit: `bbd8914` (`fix: guard cloud telegram test with empty outbox`).
- Cloud Build: `a2062ac7-13b2-4c86-8dbc-d4a4bf01ade7` (`SUCCESS`).
- Image: `asia-southeast1-docker.pkg.dev/nxt-cloud-shadow/nxt-cloud/nxt-cloud-shadow:bbd8914`.
- Digest: `sha256:858a90a40a2de7e100ee7e3e9f2bc7e026a5ec974d278a67b6cd2a9389922584`.
- The test executable refused to send unless the SHADOW outbox contained zero
  `PENDING`/`FAILED` messages.
- The first execution, `nxt-cloud-shadow-telegram-test-z6qft`, failed before
  application import and therefore before any Telegram call; the entrypoint was
  corrected from a file path to a Python module.
- The corrected execution, `nxt-cloud-shadow-telegram-test-bq565`, completed
  successfully. Its only message was an explicit connectivity test prefixed
  `[NXT-CLOUD][SHADOW]` and stated that it was not a signal, order, or schedule.
- The temporary connectivity-test job was deleted after the successful run.

## Scanner state after test

- Job: `nxt-cloud-shadow-scanner`.
- Image tag: `bbd8914`.
- `NXT_NOTIFICATION_MODE=telegram`.
- Bot token and chat ID are mounted by Secret Manager references; raw values are
  not present in the job configuration.
- The main scanner was not executed during this gate, so no signal scan or
  signal notification was triggered.
- Cloud Scheduler API remains disabled.
- No production resource or Git remote was changed.

## Verification

- The pre-change suite passed `62/62` tests for the Telegram connectivity
  implementation.
- The added outbox guard passed Python compilation and the Cloud Run integration
  execution above, including live database and Telegram API access.
