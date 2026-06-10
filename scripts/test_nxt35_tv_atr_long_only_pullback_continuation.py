from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import backtest_nxt31_utc7_latest as base
import backtest_nxt32_native_1d_latest as native
import test_nxt33_long_only_pullback_continuation as cont
from test_nxt33_ssl14 import enrich_with_ssl_period


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "outputs" / "nxt35_tv_atr_long_only_pullback_continuation"
OUT_JSON = OUT_DIR / "nxt35_tv_atr_long_only_pullback_continuation_results.json"
OUT_XLSX = OUT_DIR / "NXT35_TV_ATR_Long_Only_Pullback_Continuation_6Y_BTC_SOL_SUI_20K.xlsx"
BASELINE_JSON = ROOT / "latest" / "NXT_Latest_NXT34_Native1D_SSL14_RunnerA_LongOnlyPullbackContinuation_NoRiskOff_6Y_BTC_SOL_SUI_20K.json"


def atr_rma(candles: list[dict], period: int = 14) -> list[float | None]:
    tr = []
    for i, c in enumerate(candles):
        if i == 0:
            tr.append(c["high"] - c["low"])
        else:
            pc = candles[i - 1]["close"]
            tr.append(max(c["high"] - c["low"], abs(c["high"] - pc), abs(c["low"] - pc)))
    out: list[float | None] = [None] * len(candles)
    if len(tr) < period:
        return out
    prev = sum(tr[:period]) / period
    out[period - 1] = prev
    for i in range(period, len(tr)):
        prev = (prev * (period - 1) + tr[i]) / period
        out[i] = prev
    return out


def enrich_tv_atr_ssl14(candles: list[dict]) -> list[dict]:
    enriched = enrich_with_ssl_period(candles, 14)
    tv_atr = atr_rma(enriched, 14)
    for i, c in enumerate(enriched):
        c["atr14"] = tv_atr[i]
    return enriched


def trade_key(t: dict) -> tuple:
    return (t["symbol"], t["side"], t["signalTime"], t["entryTime"])


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    baseline = json.loads(BASELINE_JSON.read_text(encoding="utf-8"))
    baseline_rows = baseline["trades"]
    baseline_stats = cont.enriched_stats(baseline_rows)

    all_trades = []
    datasets = {}
    for symbol in native.SYMBOLS:
        candles = enrich_tv_atr_ssl14(native.fetch_native_1d(symbol))
        datasets[symbol] = {
            "dailyRows": len(candles),
            "firstDay": candles[0]["localDate"],
            "lastDay": candles[-1]["localDate"],
            "source": "Binance spot native 1D klines",
        }
        all_trades.extend(cont.backtest_symbol(symbol, candles))
    all_trades.sort(key=lambda x: x["exitTime"])

    baseline_keys = {trade_key(t) for t in baseline_rows}
    continuation = [t for t in all_trades if t["signalType"] == "Continuation"]
    added = [t for t in all_trades if trade_key(t) not in baseline_keys]
    variant_stats = cont.enriched_stats(all_trades)
    continuation_stats = cont.enriched_stats(continuation)
    added_stats = cont.enriched_stats(added)

    result = {
        "generatedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "systemVersion": "NXT v3.5 + TradingView ATR RMA + LONG-only pullback/touch EMA20 continuation",
        "period": baseline["period"],
        "rule": {
            "key": "tv_atr_long_only_pullback_touch_ema20",
            "name": "TradingView ATR RMA + LONG-only pullback/touch EMA20 continuation",
            "touchLookback": 5,
        },
        "baselineStats": baseline_stats,
        "variantStats": variant_stats,
        "continuationStats": continuation_stats,
        "addedStats": added_stats,
        "trades": all_trades,
        "continuationTrades": continuation,
        "addedTrades": added,
        "bySymbol": cont.group_stats(all_trades, lambda t: t["symbol"]),
        "byContinuationSymbol": cont.group_stats(continuation, lambda t: t["symbol"]),
        "byYear": cont.group_stats(all_trades, lambda t: t["exitTime"][:4]),
        "byContinuationYear": cont.group_stats(continuation, lambda t: t["exitTime"][:4]),
        "datasets": datasets,
        "assumptions": [
            "Baseline comparison is prior NXT v3.4 latest using ATR SMA.",
            "This version uses TradingView default ATR14 Wilder RMA smoothing.",
            "Daily candles use Binance native 1D klines.",
            "SSL Channel uses SMA(high,14) and SMA(low,14); state flips bullish when close is above high SMA and bearish when close is below low SMA.",
            "Primary LONG/SHORT rules are unchanged except all ATR-based distance, stop, and target calculations use TradingView ATR RMA.",
            "Continuation is LONG-only.",
            "Continuation LONG requires SSL already bullish, close > EMA20 > EMA50, a low touching EMA20 within the last 5 candles, close > EMA20, and close > previous close.",
            "Continuation does not require RSI, distance-to-EMA50, or EMA50 slope filters.",
            "Only one position per symbol is open at a time; continuation is skipped while an existing trade is open.",
            "Entry remains next daily open after signal close; stop, TP1, Runner A exit, cost model, and anti-immediate-reversal rule are unchanged.",
        ],
    }
    OUT_JSON.write_text(json.dumps(result, indent=2), encoding="utf-8")
    cont.OUT_XLSX = OUT_XLSX
    cont.build_workbook(result)
    print(json.dumps({
        "outJson": str(OUT_JSON),
        "outXlsx": str(OUT_XLSX),
        "variantStats": variant_stats,
        "continuationStats": continuation_stats,
        "dec282021Short": [
            t for t in all_trades
            if t["symbol"] == "BTCUSDT" and t["side"] == "SHORT" and t["signalTime"] == "2021-12-28"
        ],
    }, indent=2))


if __name__ == "__main__":
    main()
