from __future__ import annotations

"""Dedicated 6y run: promote candidate rule
`block_short_after_losing_long_runner_exit` vs baseline latest.

Reuses the variant engine from test_nxt35_post_bull_chop_filters_20240402.
Offline-safe: falls back to cached Binance 1D candles / funding when network
is unavailable.
"""

import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import backtest_nxt32_native_1d_latest as native
import nxt_tradingview_binance_1d_data as tvdata
import audit_nxt34_btc_bnb_sol_funding_adjusted as audit
import test_nxt35_post_bull_chop_filters_20240402 as grid
from test_nxt33_ssl14 import enrich_with_ssl_period

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "outputs" / "nxt35_block_short_after_losing_long_runner_6y"
OUT_JSON = OUT_DIR / "NXT35_Block_SHORT_After_Losing_LONG_Runner_6Y.json"
SYMBOLS = ["BTCUSDT", "BNBUSDT", "SOLUSDT"]

VARIANTS = [
    {"key": "baseline_latest", "description": "Current latest."},
    {
        "key": "block_short_after_losing_long_runner_exit",
        "description": "Block same/next-candle SHORT after a LONG position exits via SSL bearish flip with net R < 0.",
        "block_short_after_losing_long_runner_exit": True,
    },
]


def cached_candles(symbol: str, start_date, end_date) -> list[dict]:
    """Cache-only replica of fetch_tradingview_binance_1d output format."""
    rows = sorted(tvdata._load_cache(symbol).values(), key=lambda r: int(r["time"]))
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    result = []
    for row in rows:
        bar_date = datetime.fromtimestamp(int(row["time"]) / 1000, timezone.utc).date()
        if bar_date < start_date or (end_date is not None and bar_date > end_date):
            continue
        item = dict(row)
        item.setdefault("closeTime", int(item["time"]) + tvdata.DAY_MS - 1)
        item.setdefault("takerBuyBaseVolume", 0.0)
        item["localDate"] = bar_date.isoformat()
        item["closed"] = int(item["closeTime"]) <= now_ms
        result.append(item)
    return result


def cached_funding(symbol: str, start, end) -> list[dict]:
    """Use exact cache file if present, else widest cached range for symbol."""
    try:
        return audit.fetch_monthly_funding(symbol, start, end)
    except Exception:
        pass
    files = sorted(audit.FUNDING_CACHE.glob(f"{symbol}_*.json"))
    if not files:
        raise RuntimeError(f"No cached funding for {symbol}")
    best = max(files, key=lambda p: p.stat().st_size)
    return json.loads(best.read_text(encoding="utf-8"))


import os


def get_candles(symbol: str):
    if os.environ.get("NXT_OFFLINE") == "1":
        print(f"[offline] using cached candles for {symbol}")
        return cached_candles(symbol, native.WARMUP_DATE, native.END_DATE)
    try:
        return tvdata.fetch_tradingview_binance_1d(symbol, native.WARMUP_DATE, native.END_DATE)
    except Exception:
        print(f"[offline] using cached candles for {symbol}")
        return cached_candles(symbol, native.WARMUP_DATE, native.END_DATE)


def breakdown(trades: list[dict], keyfn, key="netRAfterFunding") -> list[dict]:
    groups = defaultdict(list)
    for t in trades:
        groups[keyfn(t)].append(t)
    out = []
    for g in sorted(groups):
        st = grid.stats(groups[g], key)
        st["group"] = g
        out.append(st)
    return out


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # offline-safe funding
    original_fetch = audit.fetch_monthly_funding
    audit.fetch_monthly_funding = cached_funding  # type: ignore
    grid.fetch_monthly_funding = cached_funding  # type: ignore

    datasets = {s: enrich_with_ssl_period(get_candles(s), 14) for s in SYMBOLS}
    for s in SYMBOLS:
        print(f"{s}: {len(datasets[s])} candles {datasets[s][0]['localDate']} -> {datasets[s][-1]['localDate']}")

    results = []
    for variant in VARIANTS:
        trades = []
        for s in SYMBOLS:
            trades.extend(grid.backtest_symbol(s, datasets[s], variant))
        trades.sort(key=lambda t: t["exitTime"])
        funded = grid.add_funding(trades)
        results.append({
            "variant": variant,
            "originalStats": grid.stats(funded, "rMultiple"),
            "fundingAdjustedStats": grid.stats(funded, "netRAfterFunding"),
            "byYear": breakdown(funded, lambda t: t["exitTime"][:4]),
            "bySide": breakdown(funded, lambda t: t["side"]),
            "bySymbol": breakdown(funded, lambda t: t["symbol"]),
            "trades": funded,
        })

    audit.fetch_monthly_funding = original_fetch  # restore

    base_t = {(t["symbol"], t["entryTime"], t["side"]) for t in results[0]["trades"]}
    var_t = {(t["symbol"], t["entryTime"], t["side"]) for t in results[1]["trades"]}
    removed = sorted(base_t - var_t)
    added = sorted(var_t - base_t)

    b, v = results[0]["fundingAdjustedStats"], results[1]["fundingAdjustedStats"]
    results[1]["deltaVsBaselineFundingAdjusted"] = {
        "trades": v["trades"] - b["trades"],
        "totalR": v["totalR"] - b["totalR"],
        "winRate": v["winRate"] - b["winRate"],
        "maxDrawdownR": v["maxDrawdownR"] - b["maxDrawdownR"],
        "profitFactor": (v["profitFactor"] or 0) - (b["profitFactor"] or 0),
    }
    payload = {
        "generatedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "system": "NXT v3.5 latest + block SHORT after losing LONG runner exit (6y dedicated run)",
        "period": {"start": str(native.START_DATE), "end": str(native.END_DATE)},
        "removedEntries": [{"symbol": s, "entryTime": e, "side": sd} for s, e, sd in removed],
        "addedEntries": [{"symbol": s, "entryTime": e, "side": sd} for s, e, sd in added],
        "results": results,
    }
    OUT_JSON.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    for r in results:
        st = r["fundingAdjustedStats"]
        print("\n== %s" % r["variant"]["key"])
        print("trades=%d wr=%.4f totalR=%.2f PF=%.3f maxDD=%.2f end20k=%.0f" % (
            st["trades"], st["winRate"], st["totalR"], st["profitFactor"], st["maxDrawdownR"], st["ending20k"]))
        for row in r["byYear"]:
            print("  %s n=%3d totR=%7.2f wr=%.3f" % (row["group"], row["trades"], row["totalR"], row["winRate"]))
    print("\nRemoved entries (blocked):", len(removed))
    for s_, e_, sd_ in removed:
        print("  -", s_, e_[:10], sd_)
    print("Added entries (chain effects):", len(added))
    for s_, e_, sd_ in added:
        print("  +", s_, e_[:10], sd_)
    print("\nSaved:", OUT_JSON)


if __name__ == "__main__":
    main()
