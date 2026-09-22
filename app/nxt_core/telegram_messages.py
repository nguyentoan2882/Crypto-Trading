from __future__ import annotations

import html
from datetime import datetime


SYSTEM_NAME = "NXT v3.5 Portfolio BTC+BNB+SOL + Guard directional 30/10@4R/60 + Binance USD-M 1D + SSL14 + Early-BE 7%"


def format_price(value: float) -> str:
    if abs(value) >= 1000:
        return f"{value:,.2f}"
    if abs(value) >= 1:
        return f"{value:.4f}"
    return f"{value:.6f}"


def build_entry_message(alerts: list[dict], generated_at: datetime | None = None) -> str:
    generated_at = generated_at or datetime.now()
    lines = [
        f"{SYSTEM_NAME}: entry signal",
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


def build_followup_message(items: list[dict], generated_at: datetime | None = None) -> str:
    generated_at = generated_at or datetime.now()
    lines = [
        f"{html.escape(SYSTEM_NAME)}: Accepted signal daily follow-up",
        f"Generated: {generated_at.strftime('%Y-%m-%d %H:%M:%S')}",
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


def build_followup_message_batches(
    items: list[dict],
    max_length: int = 3900,
    generated_at: datetime | None = None,
) -> list[tuple[str, list[str]]]:
    generated_at = generated_at or datetime.now()
    ordered = sorted(items, key=lambda row: (int(row.get("priority", 99)), row.get("symbol", ""), row.get("signalId", "")))
    batches: list[tuple[str, list[str]]] = []
    current: list[dict] = []
    for item in ordered:
        candidate = current + [item]
        message = build_followup_message(candidate, generated_at)
        if current and len(message) > max_length:
            batches.append((build_followup_message(current, generated_at), [str(row["recommendationId"]) for row in current]))
            current = [item]
        else:
            current = candidate
    if current:
        batches.append((build_followup_message(current, generated_at), [str(row["recommendationId"]) for row in current]))
    return batches
