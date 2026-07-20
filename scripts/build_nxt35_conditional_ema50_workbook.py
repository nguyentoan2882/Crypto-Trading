from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import audit_nxt34_btc_bnb_sol_funding_adjusted as audit


ROOT = Path(__file__).resolve().parents[1]
SOURCE_JSON = ROOT / "outputs" / "nxt35_runner_exit_variants" / "NXT35_Runner_Exit_Variants.json"
OUT_DIR = ROOT / "outputs" / "nxt35_runner_exit_variants"
VARIANT_KEY = "conditional_ema50_btc_above_ema200"
OUT_JSON = OUT_DIR / "NXT35_Conditional_EMA50_BTC_Above_EMA200.json"
OUT_XLSX = OUT_DIR / "NXT35_Conditional_EMA50_BTC_Above_EMA200_FundingAdjusted_20K.xlsx"


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
    source = json.loads(SOURCE_JSON.read_text(encoding="utf-8"))
    variant = next(row for row in source["results"] if row["variant"]["key"] == VARIANT_KEY)
    trades = sorted(
        [dict(trade) for trade in variant["trades"]],
        key=lambda t: (t["exitTime"], t["entryTime"], t["symbol"], t["tradeNo"]),
    )
    symbols = source["symbols"]
    result = {
        "generatedAt": source["generatedAt"],
        "systemVersion": "NXT v3.5 USD-M + conditional EMA50 runner when BTC > EMA200",
        "candidateStatus": "Experiment only; not promoted to latest.",
        "dataSource": "Binance USD-M perpetual 1D klines; Binance USD-M historical funding.",
        "period": source["period"],
        "symbols": symbols,
        "variant": variant["variant"],
        "ruleChange": (
            "Before TP1 keep latest SSL exit. After TP1, if BTC signal candle close > BTC EMA200, "
            "exit runner on coin daily close crossing against EMA50; otherwise keep latest SSL runner exit."
        ),
        "originalStats": variant["originalStats"],
        "fundingAdjustedStats": variant["fundingAdjustedStats"],
        "fundingSummary": variant["fundingSummary"],
        "fundingBySymbol": funding_by_symbol(trades, symbols),
        "trades": trades,
        "openPositions": variant.get("openPositions", []),
        "equityCurveFundingAdjusted": audit.equity_curve(trades, "netRAfterFunding"),
        "portfolioCap6Equal": audit.portfolio_cap_curve(
            trades,
            {"BTCUSDT": 0.02, "BNBUSDT": 0.02, "SOLUSDT": 0.02},
            "netRAfterFunding",
        ),
        "portfolioCap6BtcHeavy": audit.portfolio_cap_curve(
            trades,
            {"BTCUSDT": 0.03, "BNBUSDT": 0.015, "SOLUSDT": 0.015},
            "netRAfterFunding",
        ),
        "byYear": variant["byYear"],
        "bySymbol": variant["bySymbol"],
        "deltaVsBaselineFundingAdjusted": variant["deltaVsBaselineFundingAdjusted"],
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(result, indent=2), encoding="utf-8")

    original_out_xlsx = audit.OUT_XLSX
    audit.OUT_XLSX = OUT_XLSX
    try:
        audit.build_workbook(result)
    finally:
        audit.OUT_XLSX = original_out_xlsx

    env = os.environ.copy()
    env["NXT_LATEST_JSON"] = str(OUT_JSON)
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
                "variant": VARIANT_KEY,
                "outJson": str(OUT_JSON),
                "outXlsx": str(OUT_XLSX),
                "trades": result["fundingAdjustedStats"]["trades"],
                "totalR": result["fundingAdjustedStats"]["totalR"],
                "maxDrawdownR": result["fundingAdjustedStats"]["maxDrawdownR"],
                "profitFactor": result["fundingAdjustedStats"]["profitFactor"],
                "cap6EqualEnding": result["portfolioCap6Equal"]["endingEquity"],
                "openPositions": len(result["openPositions"]),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
