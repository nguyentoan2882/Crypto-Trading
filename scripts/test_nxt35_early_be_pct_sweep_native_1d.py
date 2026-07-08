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
import test_nxt35_early_be_10pct_native_1d as single_test
from nxt_tradingview_binance_1d_data import fetch_tradingview_binance_1d
from test_nxt33_ssl14 import enrich_with_ssl_period


SYMBOLS = ["BTCUSDT", "BNBUSDT", "SOLUSDT"]
THRESHOLDS = [value / 100 for value in range(5, 21)]
OUT_DIR = ROOT / "outputs" / "nxt35_early_be_pct_sweep_native_1d"
OUT_JSON = OUT_DIR / "NXT35_Early_BE_5pct_to_20pct_Native1D.json"


def compact(result: dict, threshold: float | None, baseline: dict) -> dict:
    stats = result["stats"]
    base_stats = baseline["stats"]
    return {
        "thresholdPct": None if threshold is None else threshold * 100,
        "trades": stats["trades"],
        "winRate": stats["winRate"],
        "totalR": stats["totalR"],
        "avgR": stats["avgR"],
        "maxDrawdownR": stats["maxDrawdownR"],
        "profitFactor": stats["profitFactor"],
        "ending20k": stats["ending20k"],
        "deltaTotalRVsBaseline": stats["totalR"] - base_stats["totalR"],
        "earlyBeTriggered": result["earlyBeTriggered"],
        "earlyBeStopExits": result["earlyBeStopExits"],
        "bySymbol": result["bySymbol"],
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
        baseline = single_test.run(None, datasets, funding_by_symbol)
        variants = [single_test.run(value, datasets, funding_by_symbol) for value in THRESHOLDS]
    finally:
        cont.TP1_ATR, cont.EARLY_BE_PROFIT_PCT = old_tp1, old_early_be
    summary = [compact(baseline, None, baseline)] + [
        compact(result, threshold, baseline) for threshold, result in zip(THRESHOLDS, variants)
    ]
    payload = {
        "generatedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "test": "NXT v3.5 native 1D early breakeven percentage sweep",
        "assumption": "After a post-entry daily High/Low reaches the threshold before TP1, the full-position stop moves to entry starting with the next daily candle.",
        "fixed": "TP1 2.5 ATR, initial stop 1.5 ATR, close 50% at TP1, funding and all current NXT rules unchanged.",
        "period": {"start": native.START_DATE.isoformat(), "end": (native.END_DATE - native.timedelta(days=1)).isoformat()},
        "summary": summary,
    }
    OUT_JSON.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(OUT_JSON), "summary": summary}, indent=2))


if __name__ == "__main__":
    main()
