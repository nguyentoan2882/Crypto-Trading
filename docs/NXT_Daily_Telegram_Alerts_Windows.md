# NXT Daily Telegram Alerts on Windows

This setup runs the NXT daily scanner on your Windows machine. It sends new-entry alerts and a daily follow-up for every signal whose latest decision is `Accept`.

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
NXT_NOTIFY_FOLLOWUPS=1
NXT_USDM_KLINES_URL=https://fapi.binance.com/fapi/v1/klines
```

Keep `.env` private. It is already ignored by Git.

## 3. Test manually

From `D:\Workspace\Codex\Investment`:

```powershell
$env:NXT_TELEGRAM_BOT_TOKEN="your token"
$env:NXT_TELEGRAM_CHAT_ID="your chat id"
& "C:\Users\Admin\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" scripts\daily_nxt_signal_scan.py
```

If there is no new entry signal, the script prints a no-signal line and sends it when `NXT_NOTIFY_NO_SIGNAL=1`. Accepted-signal follow-ups remain independent and are sent when `NXT_NOTIFY_FOLLOWUPS=1`.

## 4. Schedule daily run

Use Windows Task Scheduler:

1. Create Task.
2. Trigger: Daily at `07:01` (Vietnam time).
3. Action: Start a program.
4. Program:

```text
powershell.exe
```

5. Arguments:

```text
-NoProfile -ExecutionPolicy Bypass -File "D:\Workspace\Codex\Investment\scripts\run_daily_nxt_signal_scan.ps1"
```

The scanner reads Telegram settings from `.env`, so the token does not need to be placed in the scheduled task command.

If you install Python globally, `python` is fine. On this machine, the verified Python path is:

```text
C:\Users\Admin\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe
```

Binance USD-M daily candles close at `07:00` Vietnam time (`00:00 UTC`). Recovery triggers run at `07:01`, `08:01`, `09:01`, `10:01`, `12:01`, `14:31`, and `16:01`. Each trigger waits `2`, `2`, then `5` minutes between its four attempts. After the first successful full scan of the day, later recovery triggers exit without rescanning.

## Notes

- The scanner uses the shared local app core in `app\nxt_signal_app.py`, so Telegram and the browser app use the same NXT latest BTC/BNB/SOL logic.
- The current shared core uses Binance USD-M perpetual 1D candles, SSL14, Runner A, Early-BE 7% checked from the first daily candle after entry and effective from the next daily candle after trigger, anti-immediate-reversal only after runner exit net R >= 0.50R, LONG-only pullback continuation requiring an SSL bullish flip, and blocks a SHORT Primary on the losing pre-TP1 LONG SSL-exit candle plus its next candle.
- Set `NXT_NOTIFY_NO_SIGNAL=0` to suppress the no-new-entry summary; Accepted-signal follow-ups remain controlled separately.
- Set `NXT_NOTIFY_FOLLOWUPS=0` only when you intentionally want to suppress the Accepted-signal daily follow-up.
- The latest decision must be `Accept`. An Accepted signal without a tracked position is evaluated from its stored Trade Plan and is clearly labelled theoretical; the monitor never creates a position automatically.
- A tracked position uses the user-confirmed entry, quantity, SL, TP1 and lifecycle. Every follow-up shows one prioritized action (SL/BE, TP1, 4R, Early-BE, EMA50/SSL exit) or explicitly shows **ACTION: KHÔNG CẦN THAO TÁC**.
- Telegram uses HTML formatting so the primary action is bold in both entry and follow-up alerts. Dynamic values are escaped before delivery.
- Follow-up recommendations are saved to the local SQLite ledger before Telegram delivery. Retry/catch-up uses a deterministic signal/candle/action/state key to prevent duplicate messages.
- The local app's `Accepted Signal Daily Follow-up` section records `Applied`, `Not Applied`, `Snoozed`, or `Already Closed`; acknowledgement does not cause automatic Binance execution.
- Signal history is saved at `outputs\nxt_signal_app\signals_history.json`; this also prevents duplicate Telegram alerts for the same signal.
- MVP1 SQLite workflow data is saved locally at `runtime\nxt_signal_app\nxt_mvp1.sqlite` and is ignored by Git.
- During a transient USD-M outage, the scanner may use its cache only when that cache contains the latest fully closed UTC daily candle. It fails closed when the cache is stale rather than issuing a recommendation from incomplete data.
- The first retry attempts suppress Telegram error notifications; only the final failed attempt sends one consolidated scan-error message.
- Telegram delivery uses `runtime\nxt_signal_app\telegram_outbox.json`. A signal is queued before delivery, so a temporary Telegram outage does not lose a signal already persisted to JSON/SQLite.
- Delivered notification keys are retained locally, so repeated recovery failures do not send the same daily error repeatedly. A late recovery signal explicitly warns that the planned daily-open entry has already passed.
- Delete that history file only if you intentionally want the scanner/app to be allowed to rediscover and resend old latest signals.
