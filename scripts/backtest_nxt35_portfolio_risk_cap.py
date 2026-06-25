from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "latest" / "NXT_Latest_NXT35_BTC_BNB_SOL_FundingAdjusted_20K.json"
OUT_DIR = ROOT / "outputs" / "nxt35_portfolio_risk_cap_variants"
OUT_JSON = OUT_DIR / "NXT35_BTC_BNB_SOL_6Y_RiskCap_3_5_6_8pct.json"

STARTING_EQUITY = 20_000.0
SCENARIOS = [
    ("Cap 3%", 0.03, {"BTCUSDT": 0.015, "BNBUSDT": 0.0075, "SOLUSDT": 0.0075}),
    ("Cap 5%", 0.05, {"BTCUSDT": 0.025, "BNBUSDT": 0.0125, "SOLUSDT": 0.0125}),
    ("Cap 6%", 0.06, {"BTCUSDT": 0.03, "BNBUSDT": 0.015, "SOLUSDT": 0.015}),
    ("Cap 8%", 0.08, {"BTCUSDT": 0.04, "BNBUSDT": 0.02, "SOLUSDT": 0.02}),
]


def key(index: int, trade: dict) -> str:
    return f"{index}:{trade['symbol']}:{trade['entryTime']}:{trade['exitTime']}"


def simulate(trades: list[dict], portfolio_cap: float, symbol_limits: dict[str, float]) -> dict:
    events = defaultdict(lambda: {"entries": [], "tp1": [], "exits": []})
    for index, trade in enumerate(trades):
        events[trade["entryTime"]]["entries"].append((index, trade))
        events[trade["exitTime"]]["exits"].append((index, trade))
        if trade.get("tp1Time"):
            events[trade["tp1Time"]]["tp1"].append((index, trade))

    equity = STARTING_EQUITY
    peak = equity
    max_dd = 0.0
    max_dd_pct = 0.0
    open_risk: dict[str, float] = {}
    records: dict[str, dict] = {}
    exit_rows: list[dict] = []
    sequence = 1

    for event_date in sorted(events):
        same_day = {
            index for index, trade in events[event_date]["entries"]
            if trade["exitTime"] == event_date
        }

        # Closed positions release risk and realize P&L before new entries.
        for index, trade in sorted(events[event_date]["exits"], key=lambda x: (x[1]["symbol"], x[1]["tradeNo"])):
            if index in same_day:
                continue
            identity = key(index, trade)
            risk_amount = records[identity]["allocatedRisk"]
            pnl = risk_amount * float(trade["netRAfterFunding"])
            equity += pnl
            peak = max(peak, equity)
            dd = equity - peak
            dd_pct = dd / peak if peak else 0.0
            max_dd = min(max_dd, dd)
            max_dd_pct = min(max_dd_pct, dd_pct)
            open_risk.pop(identity, None)
            records[identity].update(
                {
                    "exitSequence": sequence,
                    "pnl": pnl,
                    "equityAfterExit": equity,
                    "drawdown": dd,
                    "drawdownPct": dd_pct,
                }
            )
            exit_rows.append(records[identity])
            sequence += 1

        # Conservative D1 assumption: entries do not reuse TP1 risk released on the same date.
        for index, trade in sorted(events[event_date]["entries"], key=lambda x: (x[1]["symbol"], x[1]["tradeNo"])):
            identity = key(index, trade)
            requested = equity * symbol_limits[trade["symbol"]]
            current_open = sum(open_risk.values())
            capacity = max(0.0, equity * portfolio_cap - current_open)
            allocated = min(requested, capacity)
            allocation_pct = allocated / equity if equity else 0.0
            rec = {
                "identity": identity,
                "symbol": trade["symbol"],
                "tradeNo": trade["tradeNo"],
                "signalType": trade["signalType"],
                "side": trade["side"],
                "signalTime": trade["signalTime"],
                "entryTime": trade["entryTime"],
                "tp1Time": trade.get("tp1Time", ""),
                "exitTime": trade["exitTime"],
                "entryPrice": trade["entryPrice"],
                "initialStop": trade["initialStop"],
                "tp1": trade["tp1"],
                "exitPrice": trade["exitPrice"],
                "exitReason": trade["exitReason"],
                "netRAfterFunding": float(trade["netRAfterFunding"]),
                "symbolLimitPct": symbol_limits[trade["symbol"]],
                "equityAtEntry": equity,
                "requestedRisk": requested,
                "openRiskBefore": current_open,
                "capacityBefore": capacity,
                "allocatedRisk": allocated,
                "allocatedRiskPct": allocation_pct,
                "openRiskAfter": current_open + allocated,
                "openRiskAfterPct": (current_open + allocated) / equity if equity else 0.0,
                "wasCapped": allocated + 1e-9 < requested,
                "wasSkipped": allocated <= 1e-9,
            }
            records[identity] = rec
            open_risk[identity] = allocated

        # TP1 removes the remaining initial loss exposure; P&L stays unrealized until exit.
        for index, trade in events[event_date]["tp1"]:
            open_risk.pop(key(index, trade), None)

        for index, trade in sorted(events[event_date]["exits"], key=lambda x: (x[1]["symbol"], x[1]["tradeNo"])):
            if index not in same_day:
                continue
            identity = key(index, trade)
            risk_amount = records[identity]["allocatedRisk"]
            pnl = risk_amount * float(trade["netRAfterFunding"])
            equity += pnl
            peak = max(peak, equity)
            dd = equity - peak
            dd_pct = dd / peak if peak else 0.0
            max_dd = min(max_dd, dd)
            max_dd_pct = min(max_dd_pct, dd_pct)
            open_risk.pop(identity, None)
            records[identity].update(
                {
                    "exitSequence": sequence,
                    "pnl": pnl,
                    "equityAfterExit": equity,
                    "drawdown": dd,
                    "drawdownPct": dd_pct,
                }
            )
            exit_rows.append(records[identity])
            sequence += 1

    yearly = []
    for year in sorted({r["exitTime"][:4] for r in exit_rows}):
        rows = [r for r in exit_rows if r["exitTime"].startswith(year)]
        yearly.append(
            {
                "year": year,
                "trades": len(rows),
                "pnl": sum(r["pnl"] for r in rows),
                "endingEquity": rows[-1]["equityAfterExit"],
                "cappedEntries": sum(r["wasCapped"] for r in rows),
                "skippedEntries": sum(r["wasSkipped"] for r in rows),
            }
        )

    return {
        "startingEquity": STARTING_EQUITY,
        "endingEquity": equity,
        "netProfit": equity - STARTING_EQUITY,
        "returnPct": equity / STARTING_EQUITY - 1,
        "maxDrawdownDollars": max_dd,
        "maxDrawdownPct": max_dd_pct,
        "trades": len(exit_rows),
        "cappedEntries": sum(r["wasCapped"] for r in exit_rows),
        "skippedEntries": sum(r["wasSkipped"] for r in exit_rows),
        "minAllocatedRiskPct": min(r["allocatedRiskPct"] for r in exit_rows),
        "maxOpenRiskPctAtEntry": max(r["openRiskAfterPct"] for r in exit_rows),
        "yearly": yearly,
        "tradeDetail": exit_rows,
    }


def main() -> None:
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    trades = sorted(source["trades"], key=lambda t: (t["entryTime"], t["exitTime"], t["symbol"], t["tradeNo"]))
    scenario_results = {}
    for name, cap, limits in SCENARIOS:
        scenario_results[name] = {
            "portfolioCapPct": cap,
            "symbolLimitsPct": limits,
            **simulate(trades, cap, limits),
        }
    result = {
        "system": "NXT v3.5 BTC/BNB/SOL 6Y funding-adjusted with portfolio risk cap",
        "period": {"start": min(t["entryTime"] for t in trades), "end": max(t["exitTime"] for t in trades)},
        "riskRules": {
            "allocationRatio": "BTC:BNB:SOL = 2:1:1",
            "equityBasis": "Realized equity at entry",
            "tp1RiskRelease": "Initial risk is released after TP1; same-day entries cannot reuse it.",
        },
        "source": str(SOURCE),
        "scenarios": scenario_results,
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(result, indent=2), encoding="utf-8")
    for name, scenario in scenario_results.items():
        print(name, json.dumps({k: v for k, v in scenario.items() if k not in {"tradeDetail", "yearly", "symbolLimitsPct"}}, indent=2))
    print(OUT_JSON)


if __name__ == "__main__":
    main()
