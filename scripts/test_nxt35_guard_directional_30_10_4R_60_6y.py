from __future__ import annotations

"""NXT v3.5 latest + Rule `Guard directional 30/10@4R/60`.

Entry / SL(1.5ATR) / TP1(2.5ATR=1.6667R) / early-BE 7% / anti-reversal: unchanged.
Partial scale-out:
  - At TP1: close 30% (realized += 0.30 * 1.6667R), move stop to BE.
  - If favorable move reaches 4R: close another 10% (realized += 0.10 * 4R).
  - Remaining 60% = tail runner (stop at BE).
Tail exit (60%):
  - LONG: use symbol-EMA50 close-cross exit ONLY when BTC strong uptrend
          (BTC close>EMA200 & close>EMA50 & EMA20>EMA50); else SSL flip.
  - SHORT: use symbol-EMA50 close-cross exit ONLY when BTC strong downtrend
          (BTC close<EMA200 & close<EMA50 & EMA20<EMA50); else SSL flip.
Offline-safe (cached candles/funding).
"""

import json
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
OUT_DIR = ROOT / "outputs" / "nxt35_guard_directional_30_10_4R_60_6y"
OUT_JSON = OUT_DIR / "NXT35_Guard_Directional_30_10_4R_60_6Y.json"
SYMBOLS = ["BTCUSDT", "BNBUSDT", "SOLUSDT"]

TP1_R = cont.TP1_ATR / 1.5          # 2.5 ATR stop=1.5 ATR -> 1.6667R
R4 = 4.0
F_TP1, F_R4, F_TAIL = 0.30, 0.10, 0.60


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
    files = sorted(audit.FUNDING_CACHE.glob(f"{symbol}_*.json"))
    best = max(files, key=lambda p: p.stat().st_size)
    return json.loads(best.read_text(encoding="utf-8"))


def build_btc_regime(btc_candles):
    closes = [c["close"] for c in btc_candles]
    ema200 = base.ema(closes, 200)
    reg = {}
    for i, c in enumerate(btc_candles):
        e20, e50, e200 = c["ema20"], c["ema50"], ema200[i]
        if None in (e20, e50, e200):
            reg[c["localDate"]] = (False, False)
            continue
        up = c["close"] > e200 and c["close"] > e50 and e20 > e50
        down = c["close"] < e200 and c["close"] < e50 and e20 < e50
        reg[c["localDate"]] = (up, down)
    return reg


def backtest_symbol(symbol, candles, btc_regime):
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
            btc_up, btc_down = btc_regime.get(c["localDate"], (False, False))
            ema50_adverse = c["ema50"] is not None and ((side == "LONG" and c["close"] < c["ema50"]) or (side == "SHORT" and c["close"] > c["ema50"]))
            use_ema50 = (side == "LONG" and btc_up) or (side == "SHORT" and btc_down)
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
                        pos["realizedR"] += F_TP1 * TP1_R
                        pos["remaining"] = F_R4 + F_TAIL
                    if can_trigger_early_be and not pos["triggered"] and not pos["earlyBeTriggered"] and c["high"] >= pos["entry"] * (1 + cont.EARLY_BE_PROFIT_PCT):
                        pos["earlyBeTriggered"] = True
                        pos["earlyBeTime"] = c["localDate"]
                        pos["stop"] = pos["entry"]
                    if pos["triggered"]:
                        if not pos["r4done"] and c["high"] >= pos["entry"] + R4 * pos["risk"]:
                            pos["r4done"] = True
                            pos["realizedR"] += F_R4 * R4
                            pos["remaining"] = F_TAIL
                        if (use_ema50 and ema50_adverse) or (not use_ema50 and ssl_flip):
                            exit_price = c["close"]
                            reason = "Tail exit: EMA50 close" if use_ema50 else "Tail exit: SSL bearish flip"
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
                        pos["realizedR"] += F_TP1 * TP1_R
                        pos["remaining"] = F_R4 + F_TAIL
                    if can_trigger_early_be and not pos["triggered"] and not pos["earlyBeTriggered"] and c["low"] <= pos["entry"] * (1 - cont.EARLY_BE_PROFIT_PCT):
                        pos["earlyBeTriggered"] = True
                        pos["earlyBeTime"] = c["localDate"]
                        pos["stop"] = pos["entry"]
                    if pos["triggered"]:
                        if not pos["r4done"] and c["low"] <= pos["entry"] - R4 * pos["risk"]:
                            pos["r4done"] = True
                            pos["realizedR"] += F_R4 * R4
                            pos["remaining"] = F_TAIL
                        if (use_ema50 and ema50_adverse) or (not use_ema50 and ssl_flip):
                            exit_price = c["close"]
                            reason = "Tail exit: EMA50 close" if use_ema50 else "Tail exit: SSL bullish flip"
                    elif ssl_flip:
                        exit_price = c["close"]
                        reason = "Runner exit: SSL bullish flip"
            if exit_price is not None:
                rem = pos["remaining"] if pos["triggered"] else 1.0
                rem_r = (exit_price - pos["entry"]) / pos["risk"] if side == "LONG" else (pos["entry"] - exit_price) / pos["risk"]
                gross = pos["realizedR"] + rem * rem_r
                cost = base.cost_r(pos["entry"], pos["risk"])
                net = gross - cost
                trades.append({
                    "symbol": symbol, "tradeNo": n, "signalType": pos["signalType"], "side": side,
                    "signalTime": pos["signalDate"], "entryTime": pos["entryDate"], "entryPrice": pos["entry"],
                    "initialStop": pos["initialStop"], "finalStop": pos["stop"], "riskPerUnit": pos["risk"],
                    "tp1": pos["tp"], "tp1Time": pos["tp1Time"], "r4Done": pos["r4done"],
                    "earlyBeTriggered": pos["earlyBeTriggered"], "earlyBeTime": pos["earlyBeTime"],
                    "exitTime": c["localDate"], "exitPrice": exit_price, "exitReason": reason,
                    "grossRMultiple": gross, "costR": cost, "rMultiple": net,
                    "atr14": pos["atr14"], "rsi14": pos["rsi14"], "distanceToEma50Atr": pos["distance"],
                    "ema20": pos["ema20"], "ema50": pos["ema50"], "notes": pos["notes"],
                })
                if reason.startswith(("Runner exit", "Tail exit")) and net >= cont.ANTI_REVERSAL_MIN_RUNNER_R:
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
        if last_runner_exit and i - last_runner_exit["index"] <= 1:
            if (long_primary or long_cont) and last_runner_exit["side"] == "SHORT":
                long_primary = long_cont = False
            if short_primary and last_runner_exit["side"] == "LONG":
                short_primary = False
        if not (long_primary or short_primary or long_cont):
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
            "triggered": False, "r4done": False, "remaining": 1.0,
            "earlyBeTriggered": False, "earlyBeTime": "", "tp1Time": "", "realizedR": 0.0,
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
    btc_regime = build_btc_regime(datasets["BTCUSDT"])

    results = []
    # baseline latest
    bt = []
    for s in SYMBOLS:
        bt.extend(grid.backtest_symbol(s, datasets[s], {"key": "x"}))
    bt.sort(key=lambda t: t["exitTime"])
    fb = grid.add_funding(bt)
    results.append({"variant": {"key": "baseline_latest", "description": "Current latest 50/SSL."},
                    "fundingAdjustedStats": grid.stats(fb, "netRAfterFunding"),
                    "byYear": breakdown(fb, lambda t: t["exitTime"][:4]),
                    "bySide": breakdown(fb, lambda t: t["side"]), "trades": fb})
    # guard variant
    gt = []
    for s in SYMBOLS:
        gt.extend(backtest_symbol(s, datasets[s], btc_regime))
    gt.sort(key=lambda t: t["exitTime"])
    fg = grid.add_funding(gt)
    results.append({"variant": {"key": "guard_directional_30_10_4R_60", "description": "30% at TP1, 10% at 4R, 60% tail with BTC-gated EMA50 exit."},
                    "fundingAdjustedStats": grid.stats(fg, "netRAfterFunding"),
                    "byYear": breakdown(fg, lambda t: t["exitTime"][:4]),
                    "bySide": breakdown(fg, lambda t: t["side"]),
                    "byExitReason": breakdown(fg, lambda t: t["exitReason"]), "trades": fg})

    b = results[0]["fundingAdjustedStats"]
    v = results[1]["fundingAdjustedStats"]
    results[1]["deltaVsBaseline"] = {
        "trades": v["trades"] - b["trades"], "totalR": v["totalR"] - b["totalR"],
        "winRate": v["winRate"] - b["winRate"], "maxDrawdownR": v["maxDrawdownR"] - b["maxDrawdownR"],
        "profitFactor": (v["profitFactor"] or 0) - (b["profitFactor"] or 0),
    }
    payload = {
        "generatedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "system": "NXT v3.5 latest + Guard directional 30/10@4R/60",
        "period": {"start": str(native.START_DATE), "end": str(native.END_DATE)},
        "params": {"tp1R": TP1_R, "r4": R4, "fractions": {"tp1": F_TP1, "r4": F_R4, "tail": F_TAIL}},
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
        print(" bySide:", ["%s n=%d totR=%.1f wr=%.2f" % (x["group"], x["trades"], x["totalR"], x["winRate"]) for x in r["bySide"]])
        if "byExitReason" in r:
            print(" byExit:", ["%s n=%d totR=%.1f" % (x["group"], x["trades"], x["totalR"]) for x in r["byExitReason"]])
    print("\nR4 hit count (guard):", sum(1 for t in results[1]["trades"] if t.get("r4Done")))
    print("Saved:", OUT_JSON)


if __name__ == "__main__":
    main()
