from __future__ import annotations

"""Latest NXT v3.5 unchanged EXCEPT runner exit:
after TP1, the runner exits when the daily close crosses back through EMA50
(LONG: close < EMA50; SHORT: close > EMA50). Pre-TP1 logic untouched
(SSL-flip exit, 1.5 ATR stop, early-BE 7%). Variants:
  - baseline_latest
  - runner_ema50_replace: post-TP1 SSL flip ignored, EMA50 cross only
  - runner_ema50_or_ssl:  post-TP1 exit on whichever comes first
Offline-safe (cached candles/funding).
"""

import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import backtest_nxt31_utc7_latest as base
import backtest_nxt32_native_1d_latest as native
import nxt_tradingview_binance_1d_data as tvdata
import audit_nxt34_btc_bnb_sol_funding_adjusted as audit
import test_nxt33_long_only_pullback_continuation as cont
import test_nxt35_post_bull_chop_filters_20240402 as grid
from test_nxt33_ssl14 import enrich_with_ssl_period

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "outputs" / "nxt35_runner_exit_ema50_cross_6y"
OUT_JSON = OUT_DIR / "NXT35_Runner_Exit_EMA50_Cross_6Y.json"
SYMBOLS = ["BTCUSDT", "BNBUSDT", "SOLUSDT"]

VARIANTS = [
    {"key": "baseline_latest", "description": "Current latest."},
    {"key": "runner_ema50_replace", "description": "Post-TP1 runner exits ONLY on adverse daily close vs EMA50.", "mode": "replace"},
    {"key": "runner_ema50_or_ssl", "description": "Post-TP1 runner exits on SSL flip OR adverse close vs EMA50, whichever first.", "mode": "or"},
]


def cached_candles(symbol, start_date, end_date):
    rows = sorted(tvdata._load_cache(symbol).values(), key=lambda r: int(r["time"]))
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    out = []
    for row in rows:
        bar_date = datetime.fromtimestamp(int(row["time"]) / 1000, timezone.utc).date()
        if bar_date < start_date or (end_date is not None and bar_date > end_date):
            continue
        item = dict(row)
        item.setdefault("closeTime", int(item["time"]) + tvdata.DAY_MS - 1)
        item.setdefault("takerBuyBaseVolume", 0.0)
        item["localDate"] = bar_date.isoformat()
        item["closed"] = int(item["closeTime"]) <= now_ms
        out.append(item)
    return out


def cached_funding(symbol, start, end):
    try:
        files = sorted(audit.FUNDING_CACHE.glob(f"{symbol}_*.json"))
        best = max(files, key=lambda p: p.stat().st_size)
        return json.loads(best.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError(f"No cached funding for {symbol}") from exc


def backtest_symbol(symbol, candles, variant):
    if variant["key"] == "baseline_latest":
        return grid.backtest_symbol(symbol, candles, {"key": "x_baseline_copy"})
    mode = variant["mode"]
    trades, pos, n = [], None, 1
    last_runner_exit = None
    for i in range(55, len(candles) - 1):
        c, prev, nxt = candles[i], candles[i - 1], candles[i + 1]
        next_date = base.date.fromisoformat(nxt["localDate"])
        if next_date < native.START_DATE or next_date >= native.END_DATE:
            continue
        if pos:
            side = pos["side"]
            ssl_flip = (side == "LONG" and prev["ssl"] == 1 and c["ssl"] == -1) or (side == "SHORT" and prev["ssl"] == -1 and c["ssl"] == 1)
            ema50_adverse = c["ema50"] is not None and ((side == "LONG" and c["close"] < c["ema50"]) or (side == "SHORT" and c["close"] > c["ema50"]))
            can_trigger_early_be = c["localDate"] != pos["entryDate"]
            exit_price = reason = None
            if side == "LONG":
                if c["low"] <= pos["stop"]:
                    exit_price = pos["stop"]
                    reason = "Breakeven stop" if (pos["triggered"] or pos["earlyBeTriggered"]) else "Stop loss"
                else:
                    if not pos["triggered"] and c["high"] >= pos["tp"]:
                        pos["triggered"] = True
                        pos["tp1Time"] = c["localDate"]
                        pos["stop"] = pos["entry"]
                        pos["realizedR"] += 0.5 * ((pos["tp"] - pos["entry"]) / pos["risk"])
                    if can_trigger_early_be and not pos["triggered"] and not pos["earlyBeTriggered"] and c["high"] >= pos["entry"] * (1 + cont.EARLY_BE_PROFIT_PCT):
                        pos["earlyBeTriggered"] = True
                        pos["earlyBeTime"] = c["localDate"]
                        pos["stop"] = pos["entry"]
                    if pos["triggered"]:
                        if mode == "replace":
                            if ema50_adverse:
                                exit_price = c["close"]
                                reason = "Runner exit: close below EMA50"
                        else:
                            if ssl_flip or ema50_adverse:
                                exit_price = c["close"]
                                reason = "Runner exit: close below EMA50" if ema50_adverse else "Runner exit: SSL bearish flip"
                    elif ssl_flip:
                        exit_price = c["close"]
                        reason = "Runner exit: SSL bearish flip"
            else:
                if c["high"] >= pos["stop"]:
                    exit_price = pos["stop"]
                    reason = "Breakeven stop" if (pos["triggered"] or pos["earlyBeTriggered"]) else "Stop loss"
                else:
                    if not pos["triggered"] and c["low"] <= pos["tp"]:
                        pos["triggered"] = True
                        pos["tp1Time"] = c["localDate"]
                        pos["stop"] = pos["entry"]
                        pos["realizedR"] += 0.5 * ((pos["entry"] - pos["tp"]) / pos["risk"])
                    if can_trigger_early_be and not pos["triggered"] and not pos["earlyBeTriggered"] and c["low"] <= pos["entry"] * (1 - cont.EARLY_BE_PROFIT_PCT):
                        pos["earlyBeTriggered"] = True
                        pos["earlyBeTime"] = c["localDate"]
                        pos["stop"] = pos["entry"]
                    if pos["triggered"]:
                        if mode == "replace":
                            if ema50_adverse:
                                exit_price = c["close"]
                                reason = "Runner exit: close above EMA50"
                        else:
                            if ssl_flip or ema50_adverse:
                                exit_price = c["close"]
                                reason = "Runner exit: close above EMA50" if ema50_adverse else "Runner exit: SSL bullish flip"
                    elif ssl_flip:
                        exit_price = c["close"]
                        reason = "Runner exit: SSL bullish flip"
            if exit_price is not None:
                rem = 0.5 if pos["triggered"] else 1.0
                rem_r = (exit_price - pos["entry"]) / pos["risk"] if side == "LONG" else (pos["entry"] - exit_price) / pos["risk"]
                gross = pos["realizedR"] + rem * rem_r
                cost = base.cost_r(pos["entry"], pos["risk"])
                net = gross - cost
                trades.append({
                    "symbol": symbol, "tradeNo": n, "signalType": pos["signalType"], "side": side,
                    "signalTime": pos["signalDate"], "entryTime": pos["entryDate"], "entryPrice": pos["entry"],
                    "initialStop": pos["initialStop"], "finalStop": pos["stop"], "riskPerUnit": pos["risk"],
                    "tp1": pos["tp"], "tp1Time": pos["tp1Time"], "earlyBeTriggered": pos["earlyBeTriggered"],
                    "earlyBeTime": pos["earlyBeTime"], "exitTime": c["localDate"], "exitPrice": exit_price,
                    "exitReason": reason, "grossRMultiple": gross, "costR": cost, "rMultiple": net,
                    "atr14": pos["atr14"], "rsi14": pos["rsi14"], "distanceToEma50Atr": pos["distance"],
                    "ema20": pos["ema20"], "ema50": pos["ema50"], "notes": pos["notes"],
                })
                if reason.startswith("Runner exit") and net >= cont.ANTI_REVERSAL_MIN_RUNNER_R:
                    last_runner_exit = {"index": i, "side": side, "netR": net}
                n += 1
                pos = None
            if pos:
                continue

        if any(c[k] is None for k in ["ema20", "ema50", "atr14", "rsi14", "ssl"]) or prev["ssl"] is None:
            continue
        dist = abs(c["close"] - c["ema50"]) / c["atr14"]
        long_primary = prev["ssl"] == -1 and c["ssl"] == 1 and base.recent_cross(candles, i, "LONG") and dist <= 2 and c["rsi14"] > 50
        short_primary = prev["ssl"] == 1 and c["ssl"] == -1 and base.recent_cross(candles, i, "SHORT") and dist <= 2 and c["rsi14"] < 50
        long_cont = prev["ssl"] == -1 and c["ssl"] == 1 and c["close"] > c["ema20"] > c["ema50"] and cont.touch_reclaim_long(candles, i, cont.RULE["touchLookback"])
        short_cont = False
        if last_runner_exit and i - last_runner_exit["index"] <= 1:
            if (long_primary or long_cont) and last_runner_exit["side"] == "SHORT":
                long_primary = long_cont = False
            if short_primary and last_runner_exit["side"] == "LONG":
                short_primary = False
        if not (long_primary or short_primary or long_cont or short_cont):
            continue
        side = "LONG" if (long_primary or long_cont) else "SHORT"
        signal_type = "Continuation" if long_cont and not long_primary else "Primary"
        risk = c["atr14"] * 1.5
        entry = nxt["open"]
        pos = {
            "side": side, "signalType": signal_type, "signalDate": c["localDate"], "entryDate": nxt["localDate"],
            "entry": entry, "initialStop": entry - risk if side == "LONG" else entry + risk,
            "stop": entry - risk if side == "LONG" else entry + risk, "risk": risk,
            "tp": entry + c["atr14"] * cont.TP1_ATR if side == "LONG" else entry - c["atr14"] * cont.TP1_ATR,
            "triggered": False, "earlyBeTriggered": False, "earlyBeTime": "", "tp1Time": "", "realizedR": 0.0,
            "atr14": c["atr14"], "rsi14": c["rsi14"], "distance": dist, "ema20": c["ema20"], "ema50": c["ema50"],
            "notes": "Primary NXT v3.5" if signal_type == "Primary" else cont.RULE["name"],
        }
    return trades


def breakdown(trades, keyfn, key="netRAfterFunding"):
    groups = defaultdict(list)
    for t in trades:
        groups[keyfn(t)].append(t)
    out = []
    for g in sorted(groups):
        st = grid.stats(groups[g], key)
        st["group"] = g
        out.append(st)
    return out


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    audit.fetch_monthly_funding = cached_funding
    grid.fetch_monthly_funding = cached_funding

    datasets = {s: enrich_with_ssl_period(cached_candles(s, native.WARMUP_DATE, native.END_DATE), 14) for s in SYMBOLS}
    results = []
    for variant in VARIANTS:
        trades = []
        for s in SYMBOLS:
            trades.extend(backtest_symbol(s, datasets[s], variant))
        trades.sort(key=lambda t: t["exitTime"])
        funded = grid.add_funding(trades)
        results.append({
            "variant": variant,
            "fundingAdjustedStats": grid.stats(funded, "netRAfterFunding"),
            "byYear": breakdown(funded, lambda t: t["exitTime"][:4]),
            "bySide": breakdown(funded, lambda t: t["side"]),
            "byExitReason": breakdown(funded, lambda t: t["exitReason"]),
            "trades": funded,
        })

    b = results[0]["fundingAdjustedStats"]
    for r in results[1:]:
        v = r["fundingAdjustedStats"]
        r["deltaVsBaseline"] = {
            "trades": v["trades"] - b["trades"], "totalR": v["totalR"] - b["totalR"],
            "winRate": v["winRate"] - b["winRate"], "maxDrawdownR": v["maxDrawdownR"] - b["maxDrawdownR"],
            "profitFactor": (v["profitFactor"] or 0) - (b["profitFactor"] or 0),
        }
    payload = {
        "generatedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "system": "NXT v3.5 latest, runner exit via adverse daily close vs EMA50 (post-TP1 only)",
        "period": {"start": str(native.START_DATE), "end": str(native.END_DATE)},
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
        print(" bySide:", ["%s n=%d totR=%.1f" % (x["group"], x["trades"], x["totalR"]) for x in r["bySide"]])
        print(" byExit:", ["%s n=%d totR=%.1f" % (x["group"], x["trades"], x["totalR"]) for x in r["byExitReason"]])
    print("\nSaved:", OUT_JSON)


if __name__ == "__main__":
    main()
