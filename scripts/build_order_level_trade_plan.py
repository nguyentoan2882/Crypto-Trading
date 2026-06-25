from __future__ import annotations

import json
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter


ROOT = Path(__file__).resolve().parents[1]
LATEST_JSON = ROOT / "latest" / "NXT_Latest_NXT35_BTC_BNB_SOL_FundingAdjusted_20K.json"
LATEST_XLSX = ROOT / "latest" / "NXT_Latest_NXT35_BTC_BNB_SOL_FundingAdjusted_20K.xlsx"
ONE_R_DOLLARS = 1_000
SHEET_NAME = "Order Plan"


def side_values(side: str) -> dict:
    if side == "LONG":
        return {
            "entrySide": "BUY",
            "closeSide": "SELL",
            "stopOrderSide": "SELL",
            "takeProfitSide": "SELL",
            "positionSide": "LONG",
            "stopDirection": "below entry",
            "tpDirection": "above entry",
        }
    return {
        "entrySide": "SELL",
        "closeSide": "BUY",
        "stopOrderSide": "BUY",
        "takeProfitSide": "BUY",
        "positionSide": "SHORT",
        "stopDirection": "above entry",
        "tpDirection": "below entry",
    }


def qty_for_trade(trade: dict) -> float:
    return ONE_R_DOLLARS / trade["riskPerUnit"]


def order_rows_for_trade(global_no: int, trade: dict) -> list[list]:
    vals = side_values(trade["side"])
    qty = qty_for_trade(trade)
    half_qty = qty * 0.5
    symbol = trade["symbol"]
    key = f"{symbol}-{trade['tradeNo']:03d}-{trade['signalTime']}"
    common = [
        global_no,
        key,
        symbol,
        trade["tradeNo"],
        trade["signalType"],
        trade["side"],
        vals["positionSide"],
        trade["signalTime"],
    ]
    rows = []
    rows.append(common + [
        1,
        trade["entryTime"],
        "OPEN_POSITION",
        vals["entrySide"],
        "MARKET_OR_LIMIT_AT_OPEN",
        "OPEN",
        qty,
        1.0,
        trade["entryPrice"],
        "",
        "",
        "Open full position at next daily open after signal close.",
        "Submit only if signal remains valid at daily close; use isolated/cross setting per account policy.",
    ])
    rows.append(common + [
        2,
        trade["entryTime"],
        "PLACE_INITIAL_STOP",
        vals["stopOrderSide"],
        "STOP_MARKET reduceOnly",
        "PROTECT",
        qty,
        1.0,
        "",
        trade["initialStop"],
        "",
        f"Protect full position; stop is 1.5 ATR {vals['stopDirection']}.",
        "Must be reduceOnly. Cancel/replace after TP1 if TP1 fills.",
    ])
    rows.append(common + [
        3,
        trade["entryTime"],
        "PLACE_TP1",
        vals["takeProfitSide"],
        "TAKE_PROFIT_MARKET reduceOnly",
        "PARTIAL_CLOSE",
        half_qty,
        0.5,
        "",
        trade["tp1"],
        "",
        f"Close 50% at TP1; target is 2.5 ATR {vals['tpDirection']}.",
        "If TP1 is not hit, this order remains pending until final exit/stop.",
    ])
    if trade.get("tp1Time"):
        rows.append(common + [
            4,
            trade["tp1Time"],
            "TP1_FILLED_CLOSE_50",
            vals["closeSide"],
            "FILLED_TP1 reduceOnly",
            "PARTIAL_CLOSE",
            half_qty,
            0.5,
            trade["tp1"],
            "",
            "",
            "TP1 filled; 50% position closed.",
            "Realized gross +0.8333R before trading cost/funding for this half.",
        ])
        rows.append(common + [
            5,
            trade["tp1Time"],
            "MOVE_STOP_TO_BREAKEVEN",
            vals["stopOrderSide"],
            "STOP_MARKET reduceOnly",
            "PROTECT_RUNNER",
            half_qty,
            0.5,
            "",
            trade["entryPrice"],
            "",
            "Cancel initial stop and replace with breakeven stop for remaining 50%.",
            "This is the runner risk-control step after TP1.",
        ])
        final_order_no = 6
        final_qty = half_qty
        final_fraction = 0.5
    else:
        final_order_no = 4
        final_qty = qty
        final_fraction = 1.0

    final_action = "STOP_LOSS_OR_RUNNER_EXIT"
    if trade["exitReason"] == "Stop loss":
        final_action = "STOP_LOSS_CLOSE"
    elif trade["exitReason"] == "Breakeven stop":
        final_action = "BREAKEVEN_STOP_CLOSE_RUNNER"
    elif trade["exitReason"].startswith("Runner exit"):
        final_action = "RUNNER_EXIT_ON_SSL_FLIP"

    rows.append(common + [
        final_order_no,
        trade["exitTime"],
        final_action,
        vals["closeSide"],
        "MARKET_OR_STOP reduceOnly",
        "FINAL_CLOSE",
        final_qty,
        final_fraction,
        trade["exitPrice"],
        trade["finalStop"] if "stop" in trade["exitReason"].lower() else "",
        "",
        trade["exitReason"],
        f"Trade net after trading cost and funding: {trade['netRAfterFunding']:.4f}R.",
    ])
    return rows


def style_sheet(ws) -> None:
    ws.freeze_panes = "A5"
    for cell in ws[4]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="1F4E79")
    widths = {
        "A": 8, "B": 28, "C": 12, "D": 8, "E": 14, "F": 10, "G": 12, "H": 12,
        "I": 8, "J": 12, "K": 26, "L": 10, "M": 24, "N": 16, "O": 14,
        "P": 12, "Q": 14, "R": 14, "S": 12, "T": 44, "U": 52,
    }
    for col in range(1, ws.max_column + 1):
        letter = get_column_letter(col)
        ws.column_dimensions[letter].width = widths.get(letter, 16)
    ws.auto_filter.ref = ws.dimensions


def main() -> None:
    latest = json.loads(LATEST_JSON.read_text(encoding="utf-8"))
    wb = load_workbook(LATEST_XLSX)
    if SHEET_NAME in wb.sheetnames:
        del wb[SHEET_NAME]
    ws = wb.create_sheet(SHEET_NAME, 1)
    ws["A1"] = "Binance Futures Order-Level Plan"
    ws["A2"] = "Assumption: futures position uses 1R = $1,000 risk. Quantity = 1000 / riskPerUnit. TP1 closes 50%; runner keeps 50% until SSL exit or stop."
    headers = [
        "Trade #", "Trade Key", "Symbol", "Symbol Trade #", "Signal Type", "Trade Side", "Position Side",
        "Signal Date", "Order #", "Action Date", "Action", "Order Side", "Order Type", "Purpose",
        "Qty Base", "Position Fraction", "Price", "Trigger/Stop", "Leverage Note", "Rule / Reason", "Control Note",
    ]
    for col, value in enumerate(headers, 1):
        ws.cell(4, col).value = value
    row_no = 5
    for i, trade in enumerate(latest["trades"], 1):
        for row in order_rows_for_trade(i, trade):
            for col, value in enumerate(row, 1):
                ws.cell(row_no, col).value = value
            row_no += 1
    style_sheet(ws)
    wb.save(LATEST_XLSX)
    print(json.dumps({
        "workbook": str(LATEST_XLSX),
        "sheet": SHEET_NAME,
        "trades": len(latest["trades"]),
        "orderRows": row_no - 5,
    }, indent=2))


if __name__ == "__main__":
    main()
