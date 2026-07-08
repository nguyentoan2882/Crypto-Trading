# NXT Daily Telegram Alerts on Windows

This setup runs the NXT daily scanner on your Windows machine and sends Telegram only when a new entry signal appears.

## 1. Create Telegram bot

1. Open Telegram and message `@BotFather`.
2. Run `/newbot`, then copy the bot token.
3. Send any message to your new bot.
4. Open this URL in a browser, replacing `<TOKEN>`:

```text
https://api.telegram.org/bot<TOKEN>/getUpdates
```

5. Copy the `chat.id` value.

## 2. Create local `.env`

Copy `.env.example` to `.env`, then fill in:

```powershell
NXT_TELEGRAM_BOT_TOKEN=...
NXT_TELEGRAM_CHAT_ID=...
NXT_SYMBOLS=BTCUSDT,BNBUSDT,SOLUSDT
NXT_NOTIFY_NO_SIGNAL=1
NXT_BINANCE_KLINES_URL=https://data-api.binance.vision/api/v3/klines
```

Keep `.env` private. It is already ignored by Git.

## 3. Test manually

From `D:\Workspace\Codex\Crypto trading`:

```powershell
$env:NXT_TELEGRAM_BOT_TOKEN="your token"
$env:NXT_TELEGRAM_CHAT_ID="your chat id"
& "C:\Users\Admin\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" scripts\daily_nxt_signal_scan.py
```

If there is no signal, the script prints a no-signal line and sends Telegram when `NXT_NOTIFY_NO_SIGNAL=1`.

## 4. Schedule daily run

Use Windows Task Scheduler:

1. Create Task.
2. Trigger: Daily at `00:10`.
3. Action: Start a program.
4. Program:

```text
powershell.exe
```

5. Arguments:

```text
-NoProfile -ExecutionPolicy Bypass -Command "Set-Location 'D:\Workspace\Codex\Crypto trading'; & 'C:\Users\Admin\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' scripts\daily_nxt_signal_scan.py"
```

The scanner reads Telegram settings from `.env`, so the token does not need to be placed in the scheduled task command.

If you install Python globally, `python` is fine. On this machine, the verified Python path is:

```text
C:\Users\Admin\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe
```

Binance native daily candles close at `07:00` Vietnam time (`00:00 UTC`), so the scheduled `07:10` scan runs after the TradingView/Binance 1D candle is final.

## Notes

- The scanner uses the shared local app core in `app\nxt_signal_app.py`, so Telegram and the browser app use the same NXT latest BTC/BNB/SOL logic.
- The current shared core uses Binance native 1D candles matching TradingView `BINANCE:<symbol>` 1D, SSL14, Runner A, Early-BE 7% triggered by a favorable High/Low move and effective from the next daily candle, profitable-runner anti-immediate-reversal, and LONG-only pullback continuation requiring an SSL bullish flip.
- Set `NXT_NOTIFY_NO_SIGNAL=0` if you only want Telegram messages when a new entry signal appears.
- Signal history is saved at `outputs\nxt_signal_app\signals_history.json`; this also prevents duplicate Telegram alerts for the same signal.
- Delete that history file only if you intentionally want the scanner/app to be allowed to rediscover and resend old latest signals.
