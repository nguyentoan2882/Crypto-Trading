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
& 'C:\Users\Admin\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' app\nxt_signal_app.py --host 127.0.0.1 --port 8765
```

Open `http://127.0.0.1:8765`, then use `Quet Binance` to scan Binance USD-M perpetual 1D candles. The shared core includes Early-BE 7%, requires an SSL bullish flip for LONG Continuation signals, and blocks a SHORT Primary on the exit candle plus next candle after a losing pre-TP1 LONG SSL bearish-flip exit. The app stores valid signals and suggested order steps in `outputs\nxt_signal_app\signals_history.json`.

The scheduled Telegram scanner uses the same app core, so both Telegram alerts and the local app scan the same BTC/BNB/SOL symbols with the same NXT latest rules and write to the same signal history.
