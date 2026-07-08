from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

import audit_nxt34_btc_bnb_sol_funding_adjusted as funding
import backtest_nxt32_native_1d_latest as native
import test_nxt33_long_only_pullback_continuation as cont
from nxt_tradingview_binance_1d_data import fetch_tradingview_binance_1d
from test_nxt33_ssl14 import enrich_with_ssl_period


SYMBOLS = ["BTCUSDT", "BNBUSDT", "SOLUSDT"]
MULTIPLIERS = [2.0, 2.1, 2.2, 2.3, 2.4, 2.5]
OUT_DIR = ROOT / "outputs" / "nxt35_tp1_atr_sweep_native_1d"
OUT_JSON = OUT_DIR / "NXT35_TP1_ATR_2.0_to_2.5_Native1D.json"


def stats_by_symbol(rows: list[dict]) -> list[dict]:
    result = []
    for symbol in SYMBOLS:
        subset = [row for row in rows if row["symbol"] == symbol]
        item = funding.stats_for_key(subset, "netRAfterFunding")
        item["symbol"] = symbol
        result.append(item)
    return result


def run_variant(multiplier: float, datasets: dict[str, list[dict]], funding_by_symbol: dict) -> dict:
    cont.TP1_ATR = multiplier
    trades = []
    for symbol in SYMBOLS:
        trades.extend(cont.backtest_symbol(symbol, datasets[symbol]))
    trades.sort(key=lambda trade: (trade["exitTime"], trade["symbol"], trade["tradeNo"]))
    for trade in trades:
        trade.update(funding.funding_for_trade(trade, funding_by_symbol[trade["symbol"]]))
        trade["netRAfterFunding"] = trade["rMultiple"] + trade["fundingR"]
    return {
        "tp1Atr": multiplier,
        "tp1R": multiplier / 1.5,
        "originalStats": cont.enriched_stats(trades),
        "fundingAdjustedStats": funding.stats_for_key(trades, "netRAfterFunding"),
        "bySymbol": stats_by_symbol(trades),
        "fundingR": sum(t["fundingR"] for t in trades),
        "trades": trades,
    }


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    datasets = {
        symbol: enrich_with_ssl_period(
            fetch_tradingview_binance_1d(symbol, native.WARMUP_DATE, native.END_DATE),
            14,
        )
        for symbol in SYMBOLS
    }
    funding_by_symbol = {
        symbol: funding.fetch_monthly_funding(symbol, native.START_DATE, native.END_DATE)
        for symbol in SYMBOLS
    }
    original_tp1 = cont.TP1_ATR
    try:
        variants = [run_variant(multiplier, datasets, funding_by_symbol) for multiplier in MULTIPLIERS]
    finally:
        cont.TP1_ATR = original_tp1
    baseline = next(item for item in variants if item["tp1Atr"] == 2.5)
    baseline_stats = baseline["fundingAdjustedStats"]
    summary = []
    for item in variants:
        stats = item["fundingAdjustedStats"]
        summary.append({
            "tp1Atr": item["tp1Atr"],
            "tp1R": item["tp1R"],
            "trades": stats["trades"],
            "winRate": stats["winRate"],
            "totalR": stats["totalR"],
            "avgR": stats["avgR"],
            "maxDrawdownR": stats["maxDrawdownR"],
            "profitFactor": stats["profitFactor"],
            "ending20k": stats["ending20k"],
            "deltaTotalRVs2_5": stats["totalR"] - baseline_stats["totalR"],
            "deltaDdVs2_5": stats["maxDrawdownR"] - baseline_stats["maxDrawdownR"],
        })
    result = {
        "generatedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "test": "NXT v3.5 native Binance 1D TP1 ATR sweep",
        "fixedRules": "Stop 1.5 ATR; close 50% at TP1; runner to breakeven then opposite SSL exit; current cross, continuation, costs, anti-reversal and funding unchanged.",
        "period": {"start": native.START_DATE.isoformat(), "end": (native.END_DATE - native.timedelta(days=1)).isoformat()},
        "summary": summary,
        "variants": variants,
    }
    OUT_JSON.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(OUT_JSON), "summary": summary}, indent=2))


if __name__ == "__main__":
    main()
