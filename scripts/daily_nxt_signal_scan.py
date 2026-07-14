from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import nxt_signal_app as core


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


def env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def format_price(value: float) -> str:
    if abs(value) >= 1000:
        return f"{value:,.2f}"
    if abs(value) >= 1:
        return f"{value:.4f}"
    return f"{value:.6f}"


def build_message(alerts: list[dict]) -> str:
    lines = [
        f"{core.SYSTEM_NAME}: entry signal",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
    ]
    for signal in alerts:
        lines.extend(
            [
                f"{signal['symbol']} {signal['side']} ({signal['signalType']})",
                f"Signal date: {signal['signalDate']}",
                f"Entry date/open: {signal['entryDate']} @ {format_price(signal['entryPrice'])}",
                f"Stop: {format_price(signal['initialStop'])}",
                f"TP1: {format_price(signal['tp1'])}",
                f"ATR14: {format_price(signal['atr14'])} | RSI14: {signal['rsi14']:.2f} | EMA50 distance: {signal['distanceToEma50Atr']:.2f} ATR",
                "Suggested orders:",
            ]
        )
        for order in signal.get("orders", []):
            price = order.get("price") or order.get("triggerPrice")
            price_text = f" @ {format_price(price)}" if price else ""
            qty_text = f" qty {format_price(order['quantityBase'])}" if order.get("quantityBase") else ""
            lines.append(f"- {order['step']}. {order['action']}: {order['orderSide']} {order['orderType']}{qty_text}{price_text}")
        lines.append("")
    return "\n".join(lines).strip()


def build_error_message(result: dict) -> str:
    lines = [
        f"{core.SYSTEM_NAME}: scan error",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
    ]
    for err in result.get("errors", []):
        lines.append(f"- {err['symbol']}: {err['error']}")
    checked_symbols = ", ".join(item["symbol"] for item in result.get("checked", []))
    if checked_symbols:
        lines.extend(["", f"Checked before failure: {checked_symbols}"])
    return "\n".join(lines).strip()


def send_telegram(message: str) -> None:
    token = os.environ.get("NXT_TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("NXT_TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print(message)
        print("\nTelegram was not sent because NXT_TELEGRAM_BOT_TOKEN or NXT_TELEGRAM_CHAT_ID is missing.")
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    core.http_json(url, {"chat_id": chat_id, "text": message, "disable_web_page_preview": "true"})


def main() -> int:
    load_local_env()
    result = core.scan_and_persist()
    alerts = result.get("newSignals", [])
    if alerts:
        message = build_message(alerts)
        print(message)
        send_telegram(message)
        return 0

    checked_symbols = ", ".join(item["symbol"] for item in result.get("checked", [])) or ", ".join(core.SYMBOLS)
    message = f"{core.SYSTEM_NAME}: no new entry signal. Checked {checked_symbols} at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}."
    print(message)
    if result.get("errors"):
        for err in result["errors"]:
            print(f"{err['symbol']}: {err['error']}", file=sys.stderr)
        if env_bool("NXT_NOTIFY_ERRORS", True):
            send_telegram(build_error_message(result))
    if env_bool("NXT_NOTIFY_NO_SIGNAL"):
        send_telegram(message)
    return 1 if result.get("errors") else 0


if __name__ == "__main__":
    raise SystemExit(main())
