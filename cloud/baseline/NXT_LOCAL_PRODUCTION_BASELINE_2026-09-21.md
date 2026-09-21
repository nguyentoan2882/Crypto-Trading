# NXT Local Production Baseline

## Baseline identity

- Capture time UTC: `2026-09-21T04:29:59Z`
- Local production checkout: `D:\Workspace\Codex\Investment`
- Independent cloud worktree: `C:\Users\Admin\.codex\worktrees\c19a\Investment`
- Cloud branch: `codex/nxt-cloud-shadow`
- Common starting commit: `ac5db0663c81f0bf798f937318ad1badd16b0458`
- Approved scope: G0, P0-P1 only; no cloud resources
- Local production authority: local remains the official source throughout P0-P1

This baseline is a read-only capture of the running local NXT source and runtime contract. Local production was not checked out, committed, restarted or reconfigured. Text files copied into the worktree have identical normalized content to local production except for the explicitly documented test-only correction below.

## Live runtime evidence

- `127.0.0.1:6789` was LISTENING after the snapshot operation.
- GET `http://127.0.0.1:6789/api/state` returned HTTP 200 after the snapshot operation.
- Observed state after capture: 8 signals; latest displayed scan status `Completed`; latest displayed finish time `2026-09-21T00:01:05Z`.
- No POST endpoint or scanner command was invoked during capture.

## Windows Scheduled Tasks

Read-only query was run with elevated access. No task was changed.

### NXT Daily Telegram Signal Scan

- State at capture: Ready.
- Last run: `2026-09-21T10:01:01+07:00`; result `0`.
- Next run at capture: `2026-09-21T12:01:01+07:00`.
- Action: `powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "D:\Workspace\Codex\Investment\scripts\run_daily_nxt_signal_scan.ps1"`.
- Enabled daily triggers: 07:01, 08:01, 09:01, 10:01, 12:01, 14:31 and 16:01 ICT.
- `StartWhenAvailable=true`.
- Execution time limit: 30 minutes.
- Multiple instance policy value: `2` (`IgnoreNew` in Task Scheduler schema).

### NXT Signal App Local Server

- State at capture: Running.
- Last task start: `2026-09-18T10:07:07+07:00`.
- Last task result: `267009` (`0x41301`, task currently running).
- Trigger: enabled at user logon.
- Action: `powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "D:\Workspace\Codex\Investment\scripts\run_nxt_signal_app.ps1"`.
- Restart policy: 3 attempts, 1-minute interval.
- Execution time limit: 3650 days.
- Multiple instance policy value: `2` (`IgnoreNew`).

## Runtime source snapshot

The following source files were copied from local production to the independent worktree. The SHA-256 values are the original local production byte hashes. EOL/EOF normalization in the Git worktree can change a raw file hash; normalized text comparisons passed for all copied runtime files and unchanged tests.

| Path | Local production SHA-256 |
| --- | --- |
| `.env.example` | `22F710CEF4EB0D486B3761A7C4B47DD3E14A3F46C3B95F60420E3836A63C5ED6` |
| `.gitignore` | `0CFDE658A8BD7EE4C071D147A90C4C5D4B28F6F8398A6D2C931B2ACFA8F88E3C` |
| `README.md` | `8D11075E28019EBD48870DC4A3CB1A919283E6B2B16B614DFD9C2538727E22C1` |
| `app/nxt_signal_app.py` | `E3E0AC607BF24A129444FF2C6381F996CE9FBDDC8B218739C31D4E25B401F18C` |
| `app/nxt_mvp_store.py` | `4CE820BE6EBF7CBBCBAF4BAB85320D89156E245C79FE598E2E2E30199D705A09` |
| `docs/NXT_Daily_Telegram_Alerts_Windows.md` | `A0578588203412A6782AF3A034D093B8ECDF78A6A197C5DDF24BC32CAD89CC62` |
| `scripts/daily_nxt_signal_scan.py` | `F35C152B1B40005B59F47E4C2DFB8367F4BBF51AB8686101A9729BF1A8DB5331` |
| `scripts/nxt_usdm_binance_1d_data.py` | `9823A3A2AEA92D0D78C998AF8018E7D903FCDA4ECBEC2637491F0D6B199CD054` |
| `scripts/run_daily_nxt_signal_scan.ps1` | `143E8C56378AF575355B415C8FF1F893D6BB1E838C0F8A4FC33B342C7CACBA7D` |
| `scripts/register_nxt_signal_app_task.ps1` | `5CB6FC4CE5A6BB1DD5E0769B1777DEC1D3EE1AB2CC65897BB1B1CB23E92A3FD9` |
| `scripts/run_nxt_signal_app.ps1` | `E85F4AAF5D44C28CEBC08126FD8F28A9BEE8E0FF34F45A047765456DC032D36F` |
| `tests/test_daily_nxt_signal_scan.py` | `39F0BAC7E93B4C98A9CE7172838770D5B74B67BC2DE90629051CA8B5392C91A5` |
| `tests/test_nxt_followup_monitor.py` | `14562091CB069CF52FDEDF12CB7056E42FE5B926D6B8858DDB11279ACDE267FB` |
| `tests/test_nxt_quantity_sizing.py` | `E54ABC136F20B618BB0554FDEFBBC1D650F304E54D4078C7EB1FBD876E05B228` |

## Explicit test-only baseline correction

`tests/test_nxt_quantity_sizing.py` was corrected only in the cloud worktree after capture:

- Renamed the stale standalone-popup test to the current per-signal-popup behavior.
- Replaced the stale global button assertion with `.signal-quantity-button` binding assertions.
- Updated risk/leverage inputs from stale visible-number expectations to current hidden inputs.
- Replaced the stale `Math.floor` assertion with the current `qty=riskUsd/riskPerUnit` formula assertion.

No application behavior or local production test file was changed. Corrected worktree file SHA-256: `361604CF4B8D2EEFB45E2E2CA9084D1918D77B6914920B5A99009110488BC200`.

## Promoted latest and design evidence

These artifacts were not copied or modified as part of P0-P1; the worktree already has the tracked promoted latest artifacts. The hashes below lock the local evidence reviewed for the baseline.

| Path | Bytes | Local production SHA-256 |
| --- | ---: | --- |
| `latest/NXT_Latest_Summary.md` | 1,125 | `D4F7B3293C9035644F4CB8727AB1E594F529F675BAE1FC8D027BBE2A61F2E713` |
| `latest/NXT_Latest_NXT35_USDM_GuardDirectional_30_10At4R_60_FundingAdjusted_20K.json` | 441,585 | `2B18FA527433727D0BA58B9F6EED0004AE7976C93AA38D2BE15C62C2EC4F8FB6` |
| `latest/NXT_Latest_NXT35_USDM_GuardDirectional_30_10At4R_60_FundingAdjusted_20K.xlsx` | 303,178 | `D79DF2C72BC6390E4F80A8A9F16F62822349FF70A8C4EB831B7480C64EAFBB29` |
| `docs/BRD_NXT_Automated_Signal_Trading_System_v0.5.docx` | 63,867 | `96B775D567A302BAA7C31FF9127CBC95E822A9F970C0E1BC451B0EC49BFB3664` |
| `docs/HLD_NXT_Automated_Signal_Trading_System_v0.4.docx` | 147,603 | `0E682CB17EBAB9C6E4DFC76DAC600DD364F3CBEF8BB595212D9B923C9DAE24B5` |

## Excluded from Git baseline

- `.env` and all credentials/secrets.
- SQLite database, WAL and SHM files.
- Telegram outbox/delivery state and daily scan runtime state.
- Runtime signals/last-scan JSON and logs.
- Live Binance candle cache changes.
- Generated DOCX files that are not required by the runtime; their evidence hashes are recorded above.
- Unrelated strategy experiments and analysis scripts in the dirty local checkout.

## Verification result

- Test command: bundled Python with `-B -m unittest discover -s tests -v`.
- Result after the test-only correction: **22 tests passed, 0 failed**.
- `-B` prevented Python bytecode writes.
- Test Telegram delivery used mocks/in-memory callbacks; no real Telegram message was sent by the test suite.
- No cloud resource was created.

## P1 exit status

P1 baseline is ready for Git review and commit when the staged diff confirms:

1. only the listed source/config/tests and this manifest are included;
2. no secret/runtime/cache/log file is included;
3. `git diff --check` passes;
4. the 22-test suite remains green;
5. local NXT still returns HTTP 200 on port 6789.
