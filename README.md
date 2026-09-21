# Crypto trading

Workspace for crypto trading strategy documents, backtest scripts, and generated result workbooks.

## Contents

- `scripts/`: backtest, optimization, and workbook verification scripts.
- `*.docx`: strategy documents used as source rules.
- `*.xlsx`: small source/reference workbooks kept in the repository.
- `outputs/`: generated backtest results. This folder is ignored by Git because it can be regenerated and may become large.

## Setup on another computer

1. Clone the repository.
2. Install Node.js.
3. Restore any dependencies needed by the scripts.
4. Run the relevant script from `scripts/`.

Example:

```powershell
node scripts/backtest_htf_pullback.mjs
```

## NXT Signal App

Run the local app for the current NXT latest BTC/BNB/SOL scanner:

```powershell
& 'C:\Users\Admin\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' app\nxt_signal_app.py --host 127.0.0.1 --port 6789
```

Open `http://127.0.0.1:6789`, then use `Quet Binance` to scan Binance USD-M perpetual 1D candles. The shared core includes Early-BE 7%, requires an SSL bullish flip for LONG Continuation signals, and blocks a SHORT Primary on the exit candle plus next candle after a losing pre-TP1 LONG SSL bearish-flip exit. The app stores valid signals and suggested order steps in `outputs\nxt_signal_app\signals_history.json`.

To keep the local app running after Windows sign-in, register its separate startup task once:

```powershell
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\register_nxt_signal_app_task.ps1
```

The daily Telegram task remains a scan-and-exit job; sharing the scanner core does not make it the web-server process.

The scheduled Telegram scanner uses the same app core, so both Telegram alerts and the local app scan the same BTC/BNB/SOL symbols with the same NXT latest rules and write to the same signal history. After each closed-D1 scan it also evaluates every latest `Accept`: untracked signals receive a clearly theoretical follow-up, tracked positions use user-confirmed values, and Telegram bolds the required action or explicit `KHÔNG CẦN THAO TÁC`.

Cloud-shadow development is isolated under `app/nxt_cloud/`. Its local-only P3 runtime and security contract is documented in `cloud/P3_LOCAL_CLOUD_ADAPTERS.md`; the P4 schema, copy-only importer and disposable backup/restore rehearsal are documented in `cloud/P4_LOCAL_DATA_REHEARSAL.md`. Neither phase replaces or modifies the Windows runtime.
