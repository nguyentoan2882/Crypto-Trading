from __future__ import annotations

import json
import html
import os
import sys
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import nxt_signal_app as core


OUTBOX_PATH = ROOT / "runtime" / "nxt_signal_app" / "telegram_outbox.json"
DELIVERY_STATE_PATH = ROOT / "runtime" / "nxt_signal_app" / "telegram_delivery_state.json"
DAILY_SCAN_STATE_PATH = ROOT / "runtime" / "nxt_signal_app" / "daily_scan_state.json"


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
    generated_at = datetime.now()
    lines = [
        f"{core.SYSTEM_NAME}: entry signal",
        f"Generated: {generated_at.strftime('%Y-%m-%d %H:%M:%S')}",
        "",
    ]
    if generated_at.hour >= 8 and any(signal.get("entryDate") == generated_at.date().isoformat() for signal in alerts):
        lines.extend(
            [
                "WARNING: delayed recovery scan; the planned daily-open entry has already passed.",
                "Reassess current price and risk manually. Do not treat the historical open as an executable quote.",
                "",
            ]
        )
    for signal in alerts:
        lines.extend(
            [
                f"{html.escape(str(signal['symbol']))} {html.escape(str(signal['side']))} ({html.escape(str(signal['signalType']))})",
                f"Signal date: {signal['signalDate']}",
                f"Entry date/open: {signal['entryDate']} @ {format_price(signal['entryPrice'])}",
                f"Stop: {format_price(signal['initialStop'])}",
                f"TP1: {format_price(signal['tp1'])}",
                f"ATR14: {format_price(signal['atr14'])} | RSI14: {signal['rsi14']:.2f} | EMA50 distance: {signal['distanceToEma50Atr']:.2f} ATR",
                "<b>ACTION CAN LUU Y: REVIEW TIN HIEU VA QUYET DINH ACCEPT / REJECT / WATCHLIST</b>",
                "Recommendation Only - he thong khong dat lenh.",
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


def build_followup_message(items: list[dict]) -> str:
    lines = [
        f"{html.escape(core.SYSTEM_NAME)}: Accepted signal daily follow-up",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
    ]
    for item in sorted(items, key=lambda row: (int(row.get("priority", 99)), row.get("symbol", ""))):
        lines.extend(
            [
                f"{html.escape(str(item['symbol']))} {html.escape(str(item['side']))} ({html.escape(str(item.get('signalType', '')))})",
                f"Status: {html.escape(str(item['trackingStatus']))}",
                f"Latest closed candle: {html.escape(str(item['candleDate']))}",
                f"<b>ACTION: {html.escape(str(item['actionLabel']))}</b>",
                f"Reason: {html.escape(str(item['rationale']))}",
            ]
        )
        if item.get("theoretical"):
            lines.append("WARNING: danh gia theoretical theo accepted Trade Plan; chua xac nhan user da vao lenh.")
            lines.append("Neu da giao dich ben ngoai, hay Track Position va xac nhan actual entry/quantity/SL.")
        else:
            lines.append("Vui long thao tac ben ngoai he thong va xac nhan outcome trong NXT neu co action.")
        lines.append("")
    return "\n".join(lines).strip()


def build_followup_message_batches(items: list[dict], max_length: int = 3900) -> list[tuple[str, list[str]]]:
    ordered = sorted(items, key=lambda row: (int(row.get("priority", 99)), row.get("symbol", ""), row.get("signalId", "")))
    batches: list[tuple[str, list[str]]] = []
    current: list[dict] = []
    for item in ordered:
        candidate = current + [item]
        message = build_followup_message(candidate)
        if current and len(message) > max_length:
            batches.append((build_followup_message(current), [str(row["recommendationId"]) for row in current]))
            current = [item]
        else:
            current = candidate
    if current:
        batches.append((build_followup_message(current), [str(row["recommendationId"]) for row in current]))
    return batches


def build_error_message(result: dict) -> str:
    lines = [
        f"{core.SYSTEM_NAME}: scan error",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
    ]
    for err in result.get("errors", []):
        lines.append(f"- {html.escape(str(err['symbol']))}: {html.escape(str(err['error']))}")
    checked_symbols = ", ".join(item["symbol"] for item in result.get("checked", []))
    if checked_symbols:
        lines.extend(["", f"Checked before failure: {checked_symbols}"])
    return "\n".join(lines).strip()


def send_telegram(message: str) -> None:
    token = os.environ.get("NXT_TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("NXT_TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        raise RuntimeError("NXT_TELEGRAM_BOT_TOKEN or NXT_TELEGRAM_CHAT_ID is missing.")
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    core.http_json(url, {"chat_id": chat_id, "text": message, "parse_mode": "HTML", "disable_web_page_preview": "true"})


def load_outbox() -> list[dict]:
    if not OUTBOX_PATH.exists():
        return []
    payload = json.loads(OUTBOX_PATH.read_text(encoding="utf-8"))
    return payload if isinstance(payload, list) else []


def save_outbox(items: list[dict]) -> None:
    OUTBOX_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = OUTBOX_PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps(items, indent=2), encoding="utf-8")
    temporary.replace(OUTBOX_PATH)


def load_json_object(path: Path) -> dict:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def save_json_object(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    temporary.replace(path)


def delivered_keys() -> dict[str, str]:
    keys = load_json_object(DELIVERY_STATE_PATH).get("keys", {})
    return keys if isinstance(keys, dict) else {}


def mark_delivered(key: str) -> None:
    keys = delivered_keys()
    keys[key] = datetime.now().isoformat(timespec="seconds")
    if len(keys) > 500:
        keys = dict(list(keys.items())[-500:])
    save_json_object(DELIVERY_STATE_PATH, {"keys": keys})


def queue_telegram(kind: str, key: str, message: str, recommendation_ids: list[str] | None = None) -> None:
    if key in delivered_keys():
        return
    items = load_outbox()
    if any(item.get("key") == key for item in items):
        return
    items.append(
        {
            "key": key,
            "kind": kind,
            "message": message,
            "recommendationIds": recommendation_ids or [],
            "createdAt": datetime.now().isoformat(timespec="seconds"),
        }
    )
    save_outbox(items)


def has_pending(kind: str) -> bool:
    return any(item.get("kind") == kind for item in load_outbox())


def flush_outbox() -> int:
    items = load_outbox()
    sent = 0
    while items:
        key = str(items[0]["key"])
        if key in delivered_keys():
            items.pop(0)
            save_outbox(items)
            continue
        item = items[0]
        send_telegram(str(item["message"]))
        if item.get("kind") == "followup":
            core.store.mark_followups_notified([str(value) for value in item.get("recommendationIds", [])])
        mark_delivered(key)
        items.pop(0)
        save_outbox(items)
        sent += 1
    return sent


def local_day() -> str:
    return datetime.now().date().isoformat()


def daily_scan_succeeded_today() -> bool:
    state = load_json_object(DAILY_SCAN_STATE_PATH)
    return state.get("successDate") == local_day()


def mark_daily_scan_success(result: dict) -> None:
    save_json_object(
        DAILY_SCAN_STATE_PATH,
        {
            "successDate": local_day(),
            "scannedAt": result.get("scannedAt"),
            "checkedSymbols": [item.get("symbol") for item in result.get("checked", [])],
        },
    )


def main() -> int:
    load_local_env()
    if env_bool("NXT_SKIP_IF_DAILY_SUCCESS") and daily_scan_succeeded_today():
        print(f"Daily scan already succeeded on {local_day()}; recovery run skipped.")
        try:
            flush_outbox()
        except Exception as exc:
            print(f"Telegram delivery failed; queued messages were retained: {exc}", file=sys.stderr)
            return 1
        return 0

    result = core.scan_and_persist()
    alerts = result.get("newSignals", [])
    followups = result.get("followUps", [])
    errors = result.get("errors", [])
    checked = result.get("checked", [])

    if not errors and len(checked) == len(core.SYMBOLS):
        mark_daily_scan_success(result)

    if alerts:
        message = build_message(alerts)
        print(message)
        signal_key = "signal:" + "|".join(sorted(str(signal["id"]) for signal in alerts))
        queue_telegram("signal", signal_key, message)

    if followups and env_bool("NXT_NOTIFY_FOLLOWUPS", True):
        for followup_message, followup_ids in build_followup_message_batches(followups):
            print(followup_message)
            followup_key = "followup:" + "|".join(sorted(followup_ids))
            queue_telegram("followup", followup_key, followup_message, followup_ids)

    checked_symbols = ", ".join(item["symbol"] for item in result.get("checked", [])) or ", ".join(core.SYMBOLS)
    if errors:
        for err in errors:
            print(f"{err['symbol']}: {err['error']}", file=sys.stderr)
        if env_bool("NXT_NOTIFY_ERRORS", True):
            error_message = build_error_message(result)
            queue_telegram("scan-error", f"scan-error:{local_day()}", error_message)
    elif not alerts:
        message = f"{core.SYSTEM_NAME}: no new entry signal. Checked {checked_symbols} at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}."
        print(message)
        if env_bool("NXT_NOTIFY_NO_SIGNAL") and not has_pending("signal"):
            queue_telegram("no-signal", f"no-signal:{local_day()}", message)

    try:
        sent = flush_outbox()
        if sent:
            print(f"Telegram outbox delivered: {sent} message(s).")
    except Exception as exc:
        print(f"Telegram delivery failed; queued messages were retained: {exc}", file=sys.stderr)
        return 1

    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
