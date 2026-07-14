from __future__ import annotations

import argparse
import html
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import backtest_nxt31_utc7_latest as base
import backtest_nxt32_native_1d_latest as native
import test_nxt33_long_only_pullback_continuation as cont
from test_nxt33_ssl14 import enrich_with_ssl_period
from nxt_tradingview_binance_1d_data import fetch_tradingview_binance_1d


APP_DIR = ROOT / "outputs" / "nxt_signal_app"
HISTORY_PATH = APP_DIR / "signals_history.json"
SCAN_PATH = APP_DIR / "last_scan.json"
SYSTEM_NAME = "NXT v3.5 Portfolio BTC+BNB+SOL + TradingView BINANCE native 1D + SSL14 + Runner A + Early-BE 7% + Anti-Immediate-Reversal >=0.50R + LONG-only Pullback Continuation on SSL Bullish Flip"
SYMBOLS = ["BTCUSDT", "BNBUSDT", "SOLUSDT"]
WARMUP_DATE = native.WARMUP_DATE
ONE_R_DOLLARS = float(os.environ.get("NXT_ONE_R_DOLLARS", "1000"))
ANTI_REVERSAL_MIN_RUNNER_R = 0.50


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def date_label(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, timezone.utc).date().isoformat()


def ms_at_utc_midnight(d: date) -> int:
    return int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp() * 1000)


def http_json(url: str, data: dict | None = None) -> object:
    headers = {"User-Agent": "nxt-signal-app/1.0"}
    encoded = urllib.parse.urlencode(data).encode("utf-8") if data is not None else None
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, data=encoded, headers=headers), timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, ConnectionResetError) as exc:
            last_error = exc
            time.sleep(1 + attempt * 2)
    raise RuntimeError(f"HTTP request failed after retries: {url}") from last_error


def fetch_daily_candles(symbol: str) -> list[dict]:
    return fetch_tradingview_binance_1d(symbol, WARMUP_DATE)


def load_json(path: Path, default: object) -> object:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def signal_id(signal: dict) -> str:
    return f"{signal['symbol']}:{signal['signalDate']}:{signal['side']}:{signal['signalType']}"


def fmt(value: float) -> str:
    if abs(value) >= 1000:
        return f"{value:,.2f}"
    if abs(value) >= 1:
        return f"{value:.4f}"
    return f"{value:.6f}"


def side_values(side: str) -> dict:
    if side == "LONG":
        return {"entry": "BUY", "close": "SELL", "stop": "SELL", "tp": "SELL"}
    return {"entry": "SELL", "close": "BUY", "stop": "BUY", "tp": "BUY"}


def build_orders(signal: dict) -> list[dict]:
    vals = side_values(signal["side"])
    qty = ONE_R_DOLLARS / signal["riskPerUnit"]
    half_qty = qty * 0.5
    return [
        {
            "step": 1,
            "action": "OPEN_POSITION",
            "date": signal["entryDate"],
            "orderSide": vals["entry"],
            "orderType": "MARKET_OR_LIMIT_AT_OPEN",
            "quantityBase": qty,
            "price": signal["entryPrice"],
            "note": "Open full position at the next Binance daily open after the signal candle closes.",
        },
        {
            "step": 2,
            "action": "PLACE_INITIAL_STOP",
            "date": signal["entryDate"],
            "orderSide": vals["stop"],
            "orderType": "STOP_MARKET reduceOnly",
            "quantityBase": qty,
            "triggerPrice": signal["initialStop"],
            "note": "Protect full position. Stop distance is 1.5 ATR14.",
        },
        {
            "step": 3,
            "action": "PLACE_TP1",
            "date": signal["entryDate"],
            "orderSide": vals["tp"],
            "orderType": "TAKE_PROFIT_MARKET reduceOnly",
            "quantityBase": half_qty,
            "triggerPrice": signal["tp1"],
            "note": "Close 50% at TP1. If TP1 fills, move remaining stop to breakeven.",
        },
        {
            "step": 4,
            "action": "EARLY_BE_7PCT",
            "date": "Next daily candle after post-entry 7% favorable move",
            "orderSide": vals["stop"],
            "orderType": "STOP_MARKET reduceOnly",
            "quantityBase": qty,
            "triggerPrice": signal["entryPrice"],
            "note": "Before TP1, from the first daily candle after entry onward, if LONG High reaches Entry x 1.07 or SHORT Low reaches Entry x 0.93, move the full-position stop to entry from the next daily candle.",
        },
        {
            "step": 5,
            "action": "AFTER_TP1_MOVE_STOP_TO_BREAKEVEN",
            "date": "When TP1 fills",
            "orderSide": vals["stop"],
            "orderType": "STOP_MARKET reduceOnly",
            "quantityBase": half_qty,
            "triggerPrice": signal["entryPrice"],
            "note": "Cancel initial stop and protect the runner at entry price.",
        },
        {
            "step": 6,
            "action": "RUNNER_EXIT_ON_OPPOSITE_SSL_FLIP",
            "date": "Future daily close",
            "orderSide": vals["close"],
            "orderType": "MARKET reduceOnly",
            "quantityBase": half_qty,
            "note": "Close the remaining runner when NXT detects an opposite SSL flip.",
        },
    ]


def latest_signal_for_symbol(symbol: str, candles: list[dict]) -> dict | None:
    candles = enrich_with_ssl_period(candles, 14)
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
            can_trigger_early_be = c["localDate"] != pos["entryDate"]
            exit_price = reason = None
            if side == "LONG":
                if c["low"] <= pos["stop"]:
                    exit_price = pos["stop"]
                    reason = "Breakeven stop" if (pos["triggered"] or pos["earlyBeTriggered"]) else "Stop loss"
                else:
                    if not pos["triggered"] and c["high"] >= pos["tp"]:
                        pos["triggered"] = True
                        pos["stop"] = pos["entry"]
                        pos["realizedR"] += 0.5 * ((pos["tp"] - pos["entry"]) / pos["risk"])
                    if can_trigger_early_be and not pos["triggered"] and not pos["earlyBeTriggered"] and c["high"] >= pos["entry"] * 1.07:
                        pos["earlyBeTriggered"] = True
                        pos["stop"] = pos["entry"]
                    if ssl_flip:
                        exit_price = c["close"]
                        reason = "Runner exit: SSL bearish flip"
            else:
                if c["high"] >= pos["stop"]:
                    exit_price = pos["stop"]
                    reason = "Breakeven stop" if (pos["triggered"] or pos["earlyBeTriggered"]) else "Stop loss"
                else:
                    if not pos["triggered"] and c["low"] <= pos["tp"]:
                        pos["triggered"] = True
                        pos["stop"] = pos["entry"]
                        pos["realizedR"] += 0.5 * ((pos["entry"] - pos["tp"]) / pos["risk"])
                    if can_trigger_early_be and not pos["triggered"] and not pos["earlyBeTriggered"] and c["low"] <= pos["entry"] * 0.93:
                        pos["earlyBeTriggered"] = True
                        pos["stop"] = pos["entry"]
                    if ssl_flip:
                        exit_price = c["close"]
                        reason = "Runner exit: SSL bullish flip"
            if exit_price is not None:
                rem = 0.5 if pos["triggered"] else 1.0
                rem_r = (exit_price - pos["entry"]) / pos["risk"] if side == "LONG" else (pos["entry"] - exit_price) / pos["risk"]
                net = pos["realizedR"] + rem * rem_r - base.cost_r(pos["entry"], pos["risk"])
                if net >= ANTI_REVERSAL_MIN_RUNNER_R and str(reason).startswith("Runner exit"):
                    last_profitable_runner_exit = {"index": i, "side": side, "netR": net}
                pos = None
            if pos:
                continue

        if any(c[k] is None for k in ["ema20", "ema50", "atr14", "rsi14", "ssl"]) or prev["ssl"] is None:
            continue
        dist = abs(c["close"] - c["ema50"]) / c["atr14"]
        long_primary = prev["ssl"] == -1 and c["ssl"] == 1 and base.recent_cross(candles, i, "LONG") and dist <= 2 and c["rsi14"] > 50
        short_primary = prev["ssl"] == 1 and c["ssl"] == -1 and base.recent_cross(candles, i, "SHORT") and dist <= 2 and c["rsi14"] < 50
        long_cont = prev["ssl"] == -1 and c["ssl"] == 1 and c["close"] > c["ema20"] > c["ema50"] and cont.touch_reclaim_long(candles, i, cont.RULE["touchLookback"])
        if last_profitable_runner_exit and i - last_profitable_runner_exit["index"] <= 1:
            if (long_primary or long_cont) and last_profitable_runner_exit["side"] == "SHORT":
                long_primary = long_cont = False
            if short_primary and last_profitable_runner_exit["side"] == "LONG":
                short_primary = False
        if not (long_primary or short_primary or long_cont):
            continue

        side = "LONG" if (long_primary or long_cont) else "SHORT"
        signal_type = "Continuation" if long_cont and not long_primary else "Primary"
        risk = c["atr14"] * 1.5
        entry = nxt["open"]
        latest_signal = {
            "symbol": symbol,
            "side": side,
            "signalType": signal_type,
            "signalDate": c["localDate"],
            "entryDate": nxt["localDate"],
            "entryPrice": entry,
            "initialStop": entry - risk if side == "LONG" else entry + risk,
            "riskPerUnit": risk,
            "tp1": entry + c["atr14"] * 2.5 if side == "LONG" else entry - c["atr14"] * 2.5,
            "atr14": c["atr14"],
            "rsi14": c["rsi14"],
            "ema20": c["ema20"],
            "ema50": c["ema50"],
            "distanceToEma50Atr": dist,
            "latestClosedDate": c["localDate"],
            "detectedAt": utc_now(),
        }
        pos = {
            "side": side,
            "entryDate": latest_signal["entryDate"],
            "entry": entry,
            "stop": latest_signal["initialStop"],
            "risk": risk,
            "tp": latest_signal["tp1"],
            "triggered": False,
            "earlyBeTriggered": False,
            "realizedR": 0.0,
        }

    latest_closed = next((c for c in reversed(candles) if c.get("closed")), None)
    if latest_signal and latest_closed and latest_signal["signalDate"] == latest_closed["localDate"]:
        latest_signal["id"] = signal_id(latest_signal)
        latest_signal["orders"] = build_orders(latest_signal)
        return latest_signal
    return None


def scan_and_persist() -> dict:
    history = load_json(HISTORY_PATH, [])
    existing = {item["id"] for item in history if isinstance(item, dict) and "id" in item}
    alerts = []
    checked = []
    errors = []
    for symbol in SYMBOLS:
        try:
            candles = fetch_daily_candles(symbol)
            checked.append({"symbol": symbol, "candles": len(candles), "latestDate": candles[-1]["localDate"] if candles else ""})
            signal = latest_signal_for_symbol(symbol, candles)
            if signal and signal["id"] not in existing:
                alerts.append(signal)
                history.append(signal)
                existing.add(signal["id"])
        except Exception as exc:
            errors.append({"symbol": symbol, "error": str(exc)})

    history.sort(key=lambda item: (item["signalDate"], item["symbol"], item["side"]), reverse=True)
    save_json(HISTORY_PATH, history)
    result = {
        "systemName": SYSTEM_NAME,
        "scannedAt": utc_now(),
        "symbols": SYMBOLS,
        "checked": checked,
        "newSignals": alerts,
        "errors": errors,
        "historyCount": len(history),
    }
    save_json(SCAN_PATH, result)
    return result


def page() -> str:
    last_scan = load_json(SCAN_PATH, {})
    history = load_json(HISTORY_PATH, [])
    cards = []
    for signal in history[:80]:
        orders = "".join(
            f"<tr><td>{o['step']}</td><td>{html.escape(o['action'])}</td><td>{html.escape(str(o['orderSide']))}</td>"
            f"<td>{html.escape(str(o['orderType']))}</td><td>{fmt(float(o.get('quantityBase', 0))) if o.get('quantityBase') else ''}</td>"
            f"<td>{fmt(float(o.get('price') or o.get('triggerPrice'))) if (o.get('price') or o.get('triggerPrice')) else ''}</td>"
            f"<td>{html.escape(o['note'])}</td></tr>"
            for o in signal.get("orders", [])
        )
        cards.append(
            f"""
            <section class="signal">
              <div class="signal-head">
                <div>
                  <h2>{html.escape(signal['symbol'])} {html.escape(signal['side'])}</h2>
                  <p>{html.escape(signal['signalType'])} | Signal {html.escape(signal['signalDate'])} | Entry {html.escape(signal['entryDate'])}</p>
                </div>
                <span>{html.escape(signal['id'])}</span>
              </div>
              <div class="metrics">
                <b>Entry {fmt(signal['entryPrice'])}</b>
                <b>Stop {fmt(signal['initialStop'])}</b>
                <b>TP1 {fmt(signal['tp1'])}</b>
                <b>ATR {fmt(signal['atr14'])}</b>
                <b>RSI {signal['rsi14']:.2f}</b>
              </div>
              <div class="orders">
                <table>
                  <thead><tr><th>#</th><th>Action</th><th>Side</th><th>Type</th><th>Qty</th><th>Price</th><th>Note</th></tr></thead>
                  <tbody>{orders}</tbody>
                </table>
              </div>
            </section>
            """
        )
    body = "\n".join(cards) if cards else "<div class='empty'>Chua co tin hieu nao duoc luu.</div>"
    new_count = len(last_scan.get("newSignals", [])) if isinstance(last_scan, dict) else 0
    scanned_at = last_scan.get("scannedAt", "Never") if isinstance(last_scan, dict) else "Never"
    return f"""<!doctype html>
<html lang="vi">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>NXT Signal App</title>
  <style>
    :root {{ color-scheme: light; --ink:#17202a; --muted:#667085; --line:#d7dde5; --bg:#f6f8fa; --panel:#ffffff; --accent:#0f766e; }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; font-family: Arial, sans-serif; background: var(--bg); color: var(--ink); }}
    header {{ background: #ffffff; border-bottom: 1px solid var(--line); padding: 18px 28px; position: sticky; top: 0; z-index: 2; }}
    h1 {{ margin: 0 0 6px; font-size: 22px; }}
    p {{ margin: 0; color: var(--muted); }}
    main {{ max-width: 1220px; margin: 0 auto; padding: 22px; }}
    .toolbar {{ display: flex; gap: 12px; align-items: center; justify-content: space-between; margin-bottom: 18px; flex-wrap: wrap; }}
    .status {{ display: flex; gap: 10px; flex-wrap: wrap; color: var(--muted); }}
    .pill {{ background: #e8f3f1; color: #0f5f58; padding: 7px 10px; border-radius: 4px; font-weight: 700; }}
    button {{ background: var(--accent); color: #fff; border: 0; border-radius: 4px; padding: 10px 14px; font-weight: 700; cursor: pointer; }}
    .signal {{ background: var(--panel); border: 1px solid var(--line); border-radius: 6px; padding: 16px; margin-bottom: 16px; }}
    .signal-head {{ display: flex; justify-content: space-between; gap: 12px; align-items: start; }}
    h2 {{ margin: 0 0 4px; font-size: 18px; }}
    .signal-head span {{ color: var(--muted); font-size: 12px; overflow-wrap: anywhere; text-align: right; }}
    .metrics {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap: 8px; margin: 14px 0; }}
    .metrics b {{ background: #f1f5f9; padding: 9px; border-radius: 4px; font-size: 13px; }}
    .orders {{ width: 100%; overflow-x: auto; }}
    table {{ width: 100%; min-width: 980px; border-collapse: collapse; font-size: 13px; }}
    th, td {{ border-top: 1px solid var(--line); padding: 8px; text-align: left; vertical-align: top; }}
    th {{ color: #344054; background: #f8fafc; }}
    .empty {{ background: #fff; border: 1px solid var(--line); padding: 28px; border-radius: 6px; color: var(--muted); }}
    @media (max-width: 760px) {{ header {{ padding: 14px; }} main {{ padding: 14px; }} .signal-head {{ display:block; }} }}
  </style>
</head>
<body>
  <header>
    <h1>NXT Signal App</h1>
    <p>{html.escape(SYSTEM_NAME)}</p>
  </header>
  <main>
    <div class="toolbar">
      <form method="post" action="/scan"><button type="submit">Quet Binance</button></form>
      <div class="status">
        <span class="pill">BTC / BNB / SOL</span>
        <span>Lan quet gan nhat: {html.escape(scanned_at)}</span>
        <span>Tin hieu moi: {new_count}</span>
        <span>Lich su: {len(history)}</span>
      </div>
    </div>
    {body}
  </main>
</body>
</html>"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/api/history":
            self.send_json(load_json(HISTORY_PATH, []))
            return
        if self.path == "/api/last-scan":
            self.send_json(load_json(SCAN_PATH, {}))
            return
        self.send_html(page())

    def do_POST(self) -> None:
        if self.path == "/scan":
            scan_and_persist()
            self.send_response(303)
            self.send_header("Location", "/")
            self.end_headers()
            return
        self.send_error(404)

    def send_html(self, payload: str) -> None:
        data = payload.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def send_json(self, payload: object) -> None:
        data = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt_text: str, *args: object) -> None:
        print(f"{self.address_string()} - {fmt_text % args}")


def run_server(host: str, port: int) -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"NXT Signal App running at http://{host}:{port}")
    server.serve_forever()


def main() -> int:
    parser = argparse.ArgumentParser(description="NXT latest signal app for Binance BTC/BNB/SOL.")
    parser.add_argument("--scan-once", action="store_true", help="Scan Binance once, persist new signals, and exit.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    if args.scan_once:
        print(json.dumps(scan_and_persist(), indent=2))
        return 0
    run_server(args.host, args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
