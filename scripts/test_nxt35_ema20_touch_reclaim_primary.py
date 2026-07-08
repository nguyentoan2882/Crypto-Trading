from __future__ import annotations

import json
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

import audit_nxt34_btc_bnb_sol_funding_adjusted as funding_audit
import backtest_nxt31_utc7_latest as base
import backtest_nxt32_native_1d_latest as native
import test_nxt33_long_only_pullback_continuation as cont
from nxt_tradingview_binance_1d_data import fetch_tradingview_binance_1d
from test_nxt33_ssl14 import enrich_with_ssl_period


MODE = os.environ.get("NXT_EMA20_CROSS_MODE", "touch_reclaim_3bar")
if MODE == "open_close_same_bar":
    OUT_DIR = ROOT / "outputs" / "nxt35_ema20_open_close_same_bar"
    OUT_JSON = OUT_DIR / "NXT35_EMA20_Open_Close_Same_Bar.json"
else:
    OUT_DIR = ROOT / "outputs" / "nxt35_ema20_touch_reclaim_primary"
    OUT_JSON = OUT_DIR / "NXT35_EMA20_Touch_Reclaim_Within_3_Bars.json"
BASELINE_JSON = ROOT / "latest" / "NXT_Latest_NXT35_BTC_BNB_SOL_FundingAdjusted_20K.json"
SYMBOLS = ["BTCUSDT", "BNBUSDT", "SOLUSDT"]
WARMUP_DATE = native.WARMUP_DATE
START_DATE = native.START_DATE
END_DATE = native.END_DATE


def recent_touch_reclaim(candles: list[dict], index: int, side: str, lookback: int = 3) -> bool:
    start = max(0, index - lookback + 1)
    if side == "LONG":
        return any(
            candles[i]["low"] <= candles[i]["ema20"]
            and candles[i]["close"] > candles[i]["ema20"]
            for i in range(start, index + 1)
        )
    return any(
        candles[i]["high"] >= candles[i]["ema20"]
        and candles[i]["close"] < candles[i]["ema20"]
        for i in range(start, index + 1)
    )


def open_close_same_bar(candles: list[dict], index: int, side: str, lookback: int = 3) -> bool:
    start = max(0, index - lookback + 1)
    if side == "LONG":
        return any(
            candles[i]["open"] <= candles[i]["ema20"]
            and candles[i]["close"] > candles[i]["ema20"]
            for i in range(start, index + 1)
        )
    return any(
        candles[i]["open"] >= candles[i]["ema20"]
        and candles[i]["close"] < candles[i]["ema20"]
        for i in range(start, index + 1)
    )


def group_stats(rows: list[dict], field: str) -> list[dict]:
    groups: dict[str, list[dict]] = {}
    for row in rows:
        groups.setdefault(str(row[field]), []).append(row)
    result = []
    for group, subset in sorted(groups.items()):
        stats = funding_audit.stats_for_key(subset, "netRAfterFunding")
        stats["group"] = group
        result.append(stats)
    return result


def key(trade: dict) -> tuple[str, str, str, str]:
    return trade["symbol"], trade["side"], trade["signalTime"], trade["entryTime"]


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    baseline = json.loads(BASELINE_JSON.read_text(encoding="utf-8"))

    original_recent_cross = base.recent_cross
    candidate_cross = open_close_same_bar if MODE == "open_close_same_bar" else recent_touch_reclaim
    base.recent_cross = candidate_cross
    try:
        trades = []
        datasets = {}
        for symbol in SYMBOLS:
            candles = enrich_with_ssl_period(
                fetch_tradingview_binance_1d(symbol, WARMUP_DATE, END_DATE),
                14,
            )
            datasets[symbol] = {
                "dailyRows": len(candles),
                "firstDay": candles[0]["localDate"],
                "lastDay": candles[-1]["localDate"],
            }
            trades.extend(cont.backtest_symbol(symbol, candles))
    finally:
        base.recent_cross = original_recent_cross

    trades.sort(key=lambda trade: (trade["exitTime"], trade["symbol"], trade["tradeNo"]))
    start = min(date.fromisoformat(t["entryTime"]) for t in trades)
    end = max(date.fromisoformat(t["exitTime"]) for t in trades)
    funding_by_symbol = {
        symbol: funding_audit.fetch_monthly_funding(symbol, start, end)
        for symbol in SYMBOLS
    }
    for trade in trades:
        trade.update(funding_audit.funding_for_trade(trade, funding_by_symbol[trade["symbol"]]))
        trade["netRAfterFunding"] = trade["rMultiple"] + trade["fundingR"]
        trade["exitYear"] = trade["exitTime"][:4]

    for trade in baseline["trades"]:
        trade["exitYear"] = trade["exitTime"][:4]

    variant_keys = {key(t) for t in trades}
    baseline_keys = {key(t) for t in baseline["trades"]}
    new_trades = [t for t in trades if key(t) not in baseline_keys]
    removed_trades = [t for t in baseline["trades"] if key(t) not in variant_keys]
    sol_june29 = [
        t for t in trades
        if t["symbol"] == "SOLUSDT" and t["signalTime"] == "2026-06-29"
    ]

    variant_original = cont.enriched_stats(trades)
    variant_adjusted = funding_audit.stats_for_key(trades, "netRAfterFunding")
    result = {
        "generatedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "testName": "NXT v3.5 Primary EMA20 Open/Close Same-Bar Cross" if MODE == "open_close_same_bar" else "NXT v3.5 Primary EMA20 Touch/Reclaim Within 3 Bars",
        "rule": {
            "long": "Within the current and previous 2 candles: open <= EMA20 and close > EMA20." if MODE == "open_close_same_bar" else "Within the current and previous 2 candles: low <= EMA20 and close > EMA20.",
            "short": "Within the current and previous 2 candles: open >= EMA20 and close < EMA20." if MODE == "open_close_same_bar" else "Within the current and previous 2 candles: high >= EMA20 and close < EMA20.",
            "unchanged": "UTC+7 candles, SSL14, RSI, EMA50 distance, continuation, exits, costs, anti-reversal, and funding.",
        },
        "period": {"start": START_DATE.isoformat(), "end": (END_DATE - base.timedelta(days=1)).isoformat()},
        "datasets": datasets,
        "baseline": {
            "originalStats": baseline["originalStats"],
            "fundingAdjustedStats": baseline["fundingAdjustedStats"],
        },
        "variant": {
            "originalStats": variant_original,
            "fundingAdjustedStats": variant_adjusted,
            "fundingR": sum(t["fundingR"] for t in trades),
        },
        "delta": {
            "trades": variant_adjusted["trades"] - baseline["fundingAdjustedStats"]["trades"],
            "totalR": variant_adjusted["totalR"] - baseline["fundingAdjustedStats"]["totalR"],
            "maxDrawdownR": variant_adjusted["maxDrawdownR"] - baseline["fundingAdjustedStats"]["maxDrawdownR"],
            "profitFactor": variant_adjusted["profitFactor"] - baseline["fundingAdjustedStats"]["profitFactor"],
            "winRate": variant_adjusted["winRate"] - baseline["fundingAdjustedStats"]["winRate"],
        },
        "bySymbol": group_stats(trades, "symbol"),
        "baselineBySymbol": group_stats(baseline["trades"], "symbol"),
        "byYear": group_stats(trades, "exitYear"),
        "baselineByYear": group_stats(baseline["trades"], "exitYear"),
        "bySignalType": group_stats(trades, "signalType"),
        "newTradeStats": funding_audit.stats_for_key(new_trades, "netRAfterFunding"),
        "removedTradeStats": funding_audit.stats_for_key(removed_trades, "netRAfterFunding"),
        "newTrades": new_trades,
        "removedTrades": removed_trades,
        "solSignal20260629": sol_june29,
        "trades": trades,
    }
    OUT_JSON.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({
        "output": str(OUT_JSON),
        "baseline": result["baseline"]["fundingAdjustedStats"],
        "variant": result["variant"]["fundingAdjustedStats"],
        "delta": result["delta"],
        "newTrades": len(new_trades),
        "removedTrades": len(removed_trades),
        "solSignal20260629": sol_june29,
    }, indent=2))


if __name__ == "__main__":
    main()
