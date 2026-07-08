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
OUT_DIR = ROOT / "outputs" / "nxt35_early_be_10pct_native_1d"
OUT_JSON = OUT_DIR / "NXT35_Early_BE_After_10pct_Profit_Native1D.json"


def group_stats(rows: list[dict]) -> list[dict]:
    result = []
    for symbol in SYMBOLS:
        subset = [row for row in rows if row["symbol"] == symbol]
        item = funding.stats_for_key(subset, "netRAfterFunding")
        item["symbol"] = symbol
        result.append(item)
    return result


def run(early_be_pct: float | None, datasets: dict, funding_by_symbol: dict) -> dict:
    cont.TP1_ATR = 2.5
    cont.EARLY_BE_PROFIT_PCT = early_be_pct
    trades = []
    for symbol in SYMBOLS:
        trades.extend(cont.backtest_symbol(symbol, datasets[symbol]))
    trades.sort(key=lambda t: (t["exitTime"], t["symbol"], t["tradeNo"]))
    for trade in trades:
        trade.update(funding.funding_for_trade(trade, funding_by_symbol[trade["symbol"]]))
        trade["netRAfterFunding"] = trade["rMultiple"] + trade["fundingR"]
    return {
        "stats": funding.stats_for_key(trades, "netRAfterFunding"),
        "bySymbol": group_stats(trades),
        "earlyBeTriggered": sum(bool(t.get("earlyBeTriggered")) for t in trades),
        "earlyBeStopExits": sum(bool(t.get("earlyBeTriggered")) and t["exitReason"] == "Breakeven stop" for t in trades),
        "trades": trades,
    }


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    datasets = {
        symbol: enrich_with_ssl_period(fetch_tradingview_binance_1d(symbol, native.WARMUP_DATE, native.END_DATE), 14)
        for symbol in SYMBOLS
    }
    funding_by_symbol = {
        symbol: funding.fetch_monthly_funding(symbol, native.START_DATE, native.END_DATE)
        for symbol in SYMBOLS
    }
    old_tp1, old_early_be = cont.TP1_ATR, cont.EARLY_BE_PROFIT_PCT
    try:
        baseline = run(None, datasets, funding_by_symbol)
        variant = run(0.10, datasets, funding_by_symbol)
    finally:
        cont.TP1_ATR, cont.EARLY_BE_PROFIT_PCT = old_tp1, old_early_be
    b, v = baseline["stats"], variant["stats"]
    result = {
        "generatedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "rule": {
            "long": "If a post-entry daily high reaches entry * 1.10 before TP1, move full-position stop to entry from the next daily candle.",
            "short": "If a post-entry daily low reaches entry * 0.90 before TP1, move full-position stop to entry from the next daily candle.",
            "intrabarAssumption": "Conservative daily OHLC: the trigger is recognized after the candle; breakeven protection starts on the following candle.",
            "unchanged": "TP1 2.5 ATR closes 50%; initial stop 1.5 ATR; native Binance 1D; all entries, exits, costs, funding and anti-reversal unchanged.",
        },
        "period": {"start": native.START_DATE.isoformat(), "end": (native.END_DATE - native.timedelta(days=1)).isoformat()},
        "baseline": baseline,
        "variant": variant,
        "delta": {
            "trades": v["trades"] - b["trades"],
            "totalR": v["totalR"] - b["totalR"],
            "winRate": v["winRate"] - b["winRate"],
            "maxDrawdownR": v["maxDrawdownR"] - b["maxDrawdownR"],
            "profitFactor": v["profitFactor"] - b["profitFactor"],
        },
    }
    OUT_JSON.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({
        "output": str(OUT_JSON), "baseline": b, "variant": v, "delta": result["delta"],
        "earlyBeTriggered": variant["earlyBeTriggered"], "earlyBeStopExits": variant["earlyBeStopExits"],
        "bySymbol": variant["bySymbol"],
    }, indent=2))


if __name__ == "__main__":
    main()
