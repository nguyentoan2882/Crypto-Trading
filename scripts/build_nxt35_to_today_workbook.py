from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import audit_nxt34_btc_bnb_sol_funding_adjusted as audit


ROOT = Path(__file__).resolve().parents[1]
SOURCE_JSON = ROOT / "outputs" / "nxt35_latest_to_today" / "NXT35_Latest_To_Today.json"
OUT_XLSX = ROOT / "outputs" / "nxt35_latest_to_today" / "NXT35_Latest_To_Today_FundingAdjusted_20K.xlsx"


def funding_by_symbol(trades: list[dict], symbols: list[str]) -> list[dict]:
    rows = []
    for symbol in symbols:
        subset = [trade for trade in trades if trade["symbol"] == symbol]
        rows.append(
            {
                "symbol": symbol,
                "originalR": sum(trade["rMultiple"] for trade in subset),
                "fundingR": sum(trade["fundingR"] for trade in subset),
                "adjustedR": sum(trade["netRAfterFunding"] for trade in subset),
                "fundingEvents": sum(trade["fundingEvents"] for trade in subset),
            }
        )
    return rows


def main() -> None:
    result = json.loads(SOURCE_JSON.read_text(encoding="utf-8"))
    result["fundingBySymbol"] = funding_by_symbol(result["trades"], result["symbols"])
    result["equityCurveFundingAdjusted"] = audit.equity_curve(result["trades"], "netRAfterFunding")
    result["portfolioCap6BtcHeavy"] = audit.portfolio_cap_curve(
        result["trades"],
        {"BTCUSDT": 0.03, "BNBUSDT": 0.015, "SOLUSDT": 0.015},
        "netRAfterFunding",
    )

    original_out_xlsx = audit.OUT_XLSX
    audit.OUT_XLSX = OUT_XLSX
    try:
        audit.build_workbook(result)
    finally:
        audit.OUT_XLSX = original_out_xlsx

    env = os.environ.copy()
    env["NXT_LATEST_JSON"] = str(SOURCE_JSON)
    env["NXT_LATEST_FUNDING_XLSX"] = str(OUT_XLSX)
    subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "build_order_level_trade_plan.py")],
        cwd=str(ROOT),
        env=env,
        check=True,
    )

    print(
        json.dumps(
            {
                "sourceJson": str(SOURCE_JSON),
                "workbook": str(OUT_XLSX),
                "trades": result["fundingAdjustedStats"]["trades"],
                "lastDataDate": result["period"]["lastDataDate"],
                "openPositions": len(result.get("openPositions", [])),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
