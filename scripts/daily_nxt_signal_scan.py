from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

import backtest_nxt31_utc7_latest as base


ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = ROOT / "outputs" / "daily_nxt_signal_state.json"
WARMUP_DATE = date(2019, 11, 1)
SYSTEM_NAME = "NXT v3.3 Native 1D Anti-Reversal Runner A"


def load_local_env() -> None:
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_local_env()
BINANCE_API = os.environ.get("NXT_BINANCE_KLINES_URL", "https://data-api.binance.vision/api/v3/klines")


def env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def ms_at_utc_midnight(d: date) -> int:
    return int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp() * 1000)


def date_label(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, timezone.utc).date().isoformat()


def http_json(url: str, data: dict | None = None) -> object:
    encoded = None
    if data is not None:
        encoded = urllib.parse.urlencode(data).encode("utf-8")
    headers = {"User-Agent": "nxt-daily-signal-scan/1.0"}
    last_error: Exception | None = None
    for attempt in range(3):
        request = urllib.request.Request(url, data=encoded, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, ConnectionResetError) as exc:
            last_error = exc
            time.sleep(2 + attempt * 3)
    raise RuntimeError(f"HTTP request failed after retries: {url}") from last_error


def fetch_native_1d(symbol: str) -> list[dict]:
    rows: list[dict] = []
    start_ms = ms_at_utc_midnight(WARMUP_DATE)
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    while True:
        query = urllib.parse.urlencode(
            {
                "symbol": symbol,
                "interval": "1d",
                "startTime": start_ms,
                "limit": 1000,
            }
        )
        batch = http_json(f"{BINANCE_API}?{query}")
        if not isinstance(batch, list) or not batch:
            break
        for row in batch:
            open_time = int(row[0])
            close_time = int(row[6])
            if open_time > now_ms:
                continue
            rows.append(
                {
                    "time": open_time,
                    "open": float(row[1]),
                    "high": float(row[2]),
                    "low": float(row[3]),
                    "close": float(row[4]),
                    "volume": float(row[5]),
                    "closeTime": close_time,
                    "takerBuyBaseVolume": float(row[9]),
                    "localDate": date_label(open_time),
                    "closed": close_time <= now_ms,
                }
            )
        next_start = int(batch[-1][0]) + 24 * 60 * 60 * 1000
        if next_start <= start_ms or next_start > now_ms:
            break
        start_ms = next_start
    return sorted({r["time"]: r for r in rows}.values(), key=lambda r: r["time"])


def load_state() -> dict:
    if not STATE_PATH.exists():
        return {"sentSignals": []}
    return json.loads(STATE_PATH.read_text(encoding="utf-8"))


def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")


def format_price(value: float) -> str:
    if value >= 1000:
        return f"{value:,.2f}"
    if value >= 1:
        return f"{value:.4f}"
    return f"{value:.6f}"


def scan_symbol(symbol: str, candles: list[dict]) -> dict | None:
    candles = base.enrich(candles)
    pos = None
    last_profitable_runner_exit = None
    latest_signal = None

    for i in range(55, len(candles) - 1):
        c, prev, nxt = candles[i], candles[i - 1], candles[i + 1]
        if not c.get("closed"):
            continue

        if pos:
            side = pos["side"]
            ssl_flip = (side == "LONG" and prev["ssl"] == 1 and c["ssl"] == -1) or (
                side == "SHORT" and prev["ssl"] == -1 and c["ssl"] == 1
            )
            exit_price = reason = None
            if side == "LONG":
                if c["low"] <= pos["stop"]:
                    exit_price = pos["stop"]
                    reason = "Breakeven stop" if pos["triggered"] else "Stop loss"
                else:
                    if not pos["triggered"] and c["high"] >= pos["tp"]:
                        pos["triggered"] = True
                        pos["stop"] = pos["entry"]
                        pos["realizedR"] += 0.5 * ((pos["tp"] - pos["entry"]) / pos["risk"])
                    if ssl_flip:
                        exit_price = c["close"]
                        reason = "Runner exit: SSL bearish flip"
            else:
                if c["high"] >= pos["stop"]:
                    exit_price = pos["stop"]
                    reason = "Breakeven stop" if pos["triggered"] else "Stop loss"
                else:
                    if not pos["triggered"] and c["low"] <= pos["tp"]:
                        pos["triggered"] = True
                        pos["stop"] = pos["entry"]
                        pos["realizedR"] += 0.5 * ((pos["entry"] - pos["tp"]) / pos["risk"])
                    if ssl_flip:
                        exit_price = c["close"]
                        reason = "Runner exit: SSL bullish flip"
            if exit_price is not None:
                rem = 0.5 if pos["triggered"] else 1.0
                rem_r = (exit_price - pos["entry"]) / pos["risk"] if side == "LONG" else (pos["entry"] - exit_price) / pos["risk"]
                net = pos["realizedR"] + rem * rem_r - base.cost_r(pos["entry"], pos["risk"])
                if net > 0 and str(reason).startswith("Runner exit"):
                    last_profitable_runner_exit = {"index": i, "side": side}
                pos = None
            if pos:
                continue

        if any(c[k] is None for k in ["ema20", "ema50", "atr14", "rsi14", "ssl"]) or prev["ssl"] is None:
            continue
        dist = abs(c["close"] - c["ema50"]) / c["atr14"]
        long_ok = prev["ssl"] == -1 and c["ssl"] == 1 and base.recent_cross(candles, i, "LONG") and dist <= 2 and c["rsi14"] > 50
        short_ok = prev["ssl"] == 1 and c["ssl"] == -1 and base.recent_cross(candles, i, "SHORT") and dist <= 2 and c["rsi14"] < 50
        if last_profitable_runner_exit and i - last_profitable_runner_exit["index"] <= 1:
            if long_ok and last_profitable_runner_exit["side"] == "SHORT":
                long_ok = False
            if short_ok and last_profitable_runner_exit["side"] == "LONG":
                short_ok = False
        if not (long_ok or short_ok):
            continue

        side = "LONG" if long_ok else "SHORT"
        risk = c["atr14"] * 1.5
        entry = nxt["open"]
        signal = {
            "id": f"{symbol}:{c['localDate']}:{side}",
            "symbol": symbol,
            "side": side,
            "signalDate": c["localDate"],
            "entryDate": nxt["localDate"],
            "entryPrice": entry,
            "initialStop": entry - risk if side == "LONG" else entry + risk,
            "riskPerUnit": risk,
            "tp1": entry + c["atr14"] * 2.5 if side == "LONG" else entry - c["atr14"] * 2.5,
            "atr14": c["atr14"],
            "rsi14": c["rsi14"],
            "distanceToEma50Atr": dist,
            "latestClosedDate": c["localDate"],
        }
        latest_signal = signal
        pos = {
            "side": side,
            "entry": entry,
            "stop": signal["initialStop"],
            "risk": risk,
            "tp": signal["tp1"],
            "triggered": False,
            "realizedR": 0.0,
        }

    latest_closed = next((c for c in reversed(candles) if c.get("closed")), None)
    if latest_signal and latest_closed and latest_signal["signalDate"] == latest_closed["localDate"]:
        return latest_signal
    return None


def build_message(alerts: list[dict]) -> str:
    lines = [
        f"{SYSTEM_NAME}: entry signal",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
    ]
    for a in alerts:
        lines.extend(
            [
                f"{a['symbol']} {a['side']}",
                f"Signal date: {a['signalDate']}",
                f"Entry date/open: {a['entryDate']} @ {format_price(a['entryPrice'])}",
                f"Stop: {format_price(a['initialStop'])}",
                f"TP1: {format_price(a['tp1'])}",
                f"ATR14: {format_price(a['atr14'])} | RSI14: {a['rsi14']:.2f} | EMA50 distance: {a['distanceToEma50Atr']:.2f} ATR",
                "",
            ]
        )
    return "\n".join(lines).strip()


def send_telegram(message: str) -> None:
    token = os.environ.get("NXT_TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("NXT_TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print(message)
        print("\nTelegram was not sent because NXT_TELEGRAM_BOT_TOKEN or NXT_TELEGRAM_CHAT_ID is missing.")
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    http_json(url, {"chat_id": chat_id, "text": message, "disable_web_page_preview": "true"})


def main() -> int:
    symbols = [s.strip().upper() for s in os.environ.get("NXT_SYMBOLS", "BTCUSDT,SOLUSDT,SUIUSDT").split(",") if s.strip()]
    state = load_state()
    sent = set(state.get("sentSignals", []))
    alerts = []

    for symbol in symbols:
        candles = fetch_native_1d(symbol)
        if len(candles) < 80:
            print(f"{symbol}: not enough candles fetched ({len(candles)}).", file=sys.stderr)
            continue
        signal = scan_symbol(symbol, candles)
        if signal and signal["id"] not in sent:
            alerts.append(signal)

    if alerts:
        send_telegram(build_message(alerts))
        sent.update(a["id"] for a in alerts)
        state["sentSignals"] = sorted(sent)
        state["lastRun"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        save_state(state)
        return 0

    message = f"{SYSTEM_NAME}: no new entry signal. Checked {', '.join(symbols)} at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}."
    print(message)
    if env_bool("NXT_NOTIFY_NO_SIGNAL"):
        send_telegram(message)
    state["lastRun"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    save_state(state)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
