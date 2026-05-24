from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(r"D:\Workspace\Codex\Crypto trading")
DATA = ROOT / "data_cache" / "binance_spot_1d"
BASE = ROOT / "outputs" / "nxt_v31_runner_ab_6y" / "nxt_v31_runner_ab_6y_results.json"
OUT_DIR = ROOT / "outputs" / "nxt31_continuation_module_6y"
OUT_JSON = OUT_DIR / "nxt31_continuation_module_6y_results.json"

SYMBOLS = ["BTCUSDT", "SOLUSDT", "SUIUSDT"]
START = int(datetime(2020, 5, 17, tzinfo=timezone.utc).timestamp() * 1000)
END = int(datetime(2026, 5, 17, tzinfo=timezone.utc).timestamp() * 1000)
ROUND_TRIP = 2 * (0.0006 + 0.0005)


def iso(ms):
    return datetime.fromtimestamp(ms / 1000, timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sma(values, period):
    out, total = [None] * len(values), 0.0
    for i, v in enumerate(values):
        total += v
        if i >= period:
            total -= values[i - period]
        if i >= period - 1:
            out[i] = total / period
    return out


def ema(values, period):
    out, total = [None] * len(values), 0.0
    k = 2 / (period + 1)
    for i, v in enumerate(values):
        if i < period:
            total += v
        if i == period - 1:
            out[i] = total / period
        elif i >= period:
            out[i] = v * k + out[i - 1] * (1 - k)
    return out


def rma(values, period):
    out, total = [None] * len(values), 0.0
    for i, v in enumerate(values):
        if i < period:
            total += v
        if i == period - 1:
            out[i] = total / period
        elif i >= period:
            out[i] = (out[i - 1] * (period - 1) + v) / period
    return out


def rsi(values, period=14):
    out = [None] * len(values)
    avg_gain = avg_loss = 0.0
    for i in range(1, len(values)):
        ch = values[i] - values[i - 1]
        gain, loss = max(ch, 0), max(-ch, 0)
        if i <= period:
            avg_gain += gain
            avg_loss += loss
            if i == period:
                avg_gain /= period
                avg_loss /= period
                out[i] = 100 if avg_loss == 0 else 100 - 100 / (1 + avg_gain / avg_loss)
        else:
            avg_gain = (avg_gain * (period - 1) + gain) / period
            avg_loss = (avg_loss * (period - 1) + loss) / period
            out[i] = 100 if avg_loss == 0 else 100 - 100 / (1 + avg_gain / avg_loss)
    return out


def atr_sma(candles, period=14):
    tr = []
    for i, c in enumerate(candles):
        if i == 0:
            tr.append(c["high"] - c["low"])
        else:
            pc = candles[i - 1]["close"]
            tr.append(max(c["high"] - c["low"], abs(c["high"] - pc), abs(c["low"] - pc)))
    return sma(tr, period)


def enrich(candles):
    closes = [c["close"] for c in candles]
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]
    ema20 = ema(closes, 20)
    ema50 = ema(closes, 50)
    ema100 = ema(closes, 100)
    ema200 = ema(closes, 200)
    atr14 = atr_sma(candles, 14)
    rsi14 = rsi(closes, 14)
    hs = sma(highs, 10)
    ls = sma(lows, 10)
    ssl, state = [], 0
    for i, c in enumerate(candles):
        if hs[i] is None or ls[i] is None:
            ssl.append(None)
            continue
        if c["close"] > hs[i]:
            state = 1
        elif c["close"] < ls[i]:
            state = -1
        ssl.append(state)
    for i, c in enumerate(candles):
        slope5 = ema50[i] - ema50[i - 5] if i >= 5 and ema50[i] is not None and ema50[i - 5] is not None else None
        c.update({"ema20": ema20[i], "ema50": ema50[i], "ema100": ema100[i], "ema200": ema200[i], "ema50Slope5": slope5, "atr14": atr14[i], "rsi14": rsi14[i], "ssl": ssl[i]})
    return candles


def crossed_up(cs, i):
    return cs[i - 1]["close"] <= cs[i - 1]["ema20"] and cs[i]["close"] > cs[i]["ema20"]


def crossed_down(cs, i):
    return cs[i - 1]["close"] >= cs[i - 1]["ema20"] and cs[i]["close"] < cs[i]["ema20"]


def recent_cross(cs, i, side, lookback=3):
    start = max(1, i - lookback + 1)
    fn = crossed_up if side == "LONG" else crossed_down
    return any(fn(cs, j) for j in range(start, i + 1))


def cost_r(entry, risk):
    return entry * ROUND_TRIP / risk


CONTINUATION_VARIANTS = [
    {
        "key": "cont_ssl_reentry_dist25",
        "name": "SSL re-entry after failed distance, dist<=2.5",
        "maxDist": 2.5,
        "longRsi": 55,
        "shortRsi": 45,
        "requireStack": False,
        "requireSlope": False,
        "barsAfterFlip": 3,
    },
    {
        "key": "cont_ssl_reentry_dist28",
        "name": "SSL re-entry after failed distance, dist<=2.8",
        "maxDist": 2.8,
        "longRsi": 55,
        "shortRsi": 45,
        "requireStack": False,
        "requireSlope": False,
        "barsAfterFlip": 3,
    },
    {
        "key": "cont_stack_slope_dist28",
        "name": "Continuation stack+slope, dist<=2.8",
        "maxDist": 2.8,
        "longRsi": 55,
        "shortRsi": 45,
        "requireStack": True,
        "requireSlope": True,
        "barsAfterFlip": 5,
    },
    {
        "key": "cont_strong_stack_dist30",
        "name": "Strong continuation RSI60/40 stack, dist<=3.0",
        "maxDist": 3.0,
        "longRsi": 60,
        "shortRsi": 40,
        "requireStack": True,
        "requireSlope": True,
        "barsAfterFlip": 8,
    },
    {
        "key": "cont_long_only_dist30",
        "name": "LONG-only strong continuation, dist<=3.0",
        "maxDist": 3.0,
        "longRsi": 60,
        "shortRsi": 0,
        "requireStack": True,
        "requireSlope": True,
        "barsAfterFlip": 8,
        "longOnly": True,
    },
]


def continuation_signal(cs, i, cfg):
    c = cs[i]
    if any(c[k] is None for k in ["ema20", "ema50", "atr14", "rsi14", "ssl"]):
        return None
    dist = abs(c["close"] - c["ema50"]) / c["atr14"]
    if dist > cfg["maxDist"]:
        return None

    recent_bull_flip = False
    recent_bear_flip = False
    from_i = max(1, i - cfg["barsAfterFlip"])
    for j in range(from_i, i + 1):
        recent_bull_flip = recent_bull_flip or (cs[j - 1]["ssl"] == -1 and cs[j]["ssl"] == 1)
        recent_bear_flip = recent_bear_flip or (cs[j - 1]["ssl"] == 1 and cs[j]["ssl"] == -1)

    long_stack = c["close"] > c["ema20"] > c["ema50"] and (not cfg["requireStack"] or (c["ema100"] is not None and c["ema50"] > c["ema100"]))
    short_stack = c["close"] < c["ema20"] < c["ema50"] and (not cfg["requireStack"] or (c["ema100"] is not None and c["ema50"] < c["ema100"]))
    long_slope = not cfg["requireSlope"] or (c["ema50Slope5"] is not None and c["ema50Slope5"] > 0)
    short_slope = not cfg["requireSlope"] or (c["ema50Slope5"] is not None and c["ema50Slope5"] < 0)
    long_ok = recent_bull_flip and long_stack and long_slope and c["rsi14"] > cfg["longRsi"] and c["close"] > c["open"]
    short_ok = (not cfg.get("longOnly")) and recent_bear_flip and short_stack and short_slope and c["rsi14"] < cfg["shortRsi"] and c["close"] < c["open"]
    if long_ok:
        return "LONG"
    if short_ok:
        return "SHORT"
    return None


def backtest_continuation(symbol, candles, cfg):
    trades, position, n = [], None, 1
    for i in range(55, len(candles) - 1):
        c, nxt = candles[i], candles[i + 1]
        if nxt["time"] < START or nxt["time"] >= END:
            continue
        if position:
            prev = candles[i - 1]
            side = position["side"]
            ssl_flip = (side == "LONG" and prev["ssl"] == 1 and c["ssl"] == -1) or (side == "SHORT" and prev["ssl"] == -1 and c["ssl"] == 1)
            exit_price = reason = None
            if side == "LONG":
                if c["low"] <= position["stop"]:
                    exit_price, reason = position["stop"], "Stop loss"
                elif (not position["triggered"]) and c["high"] >= position["tp"]:
                    position["triggered"] = True
                    position["triggerTime"] = c["time"]
                    position["stop"] = position["entry"]
                    position["realized"] = 0.5 * ((position["tp"] - position["entry"]) / position["risk"])
                elif position["triggered"] and ssl_flip:
                    exit_price, reason = c["close"], "Runner exit SSL flip"
            else:
                if c["high"] >= position["stop"]:
                    exit_price, reason = position["stop"], "Stop loss"
                elif (not position["triggered"]) and c["low"] <= position["tp"]:
                    position["triggered"] = True
                    position["triggerTime"] = c["time"]
                    position["stop"] = position["entry"]
                    position["realized"] = 0.5 * ((position["entry"] - position["tp"]) / position["risk"])
                elif position["triggered"] and ssl_flip:
                    exit_price, reason = c["close"], "Runner exit SSL flip"
            if exit_price is not None:
                rem = 0.5 if position["triggered"] else 1.0
                rem_r = (exit_price - position["entry"]) / position["risk"] if side == "LONG" else (position["entry"] - exit_price) / position["risk"]
                gross = position["realized"] + rem * rem_r
                net = gross - cost_r(position["entry"], position["risk"])
                trades.append({**position, "tradeNo": n, "exitTime": iso(c["time"]), "exitPrice": exit_price, "exitReason": reason, "grossRMultiple": gross, "costR": cost_r(position["entry"], position["risk"]), "rMultiple": net, "tp1Time": iso(position["triggerTime"]) if position["triggerTime"] else ""})
                n += 1
                position = None
            if position:
                continue

        side = continuation_signal(candles, i, cfg)
        if not side:
            continue
        risk = c["atr14"] * 1.5
        entry = nxt["open"]
        position = {
            "symbol": symbol,
            "side": side,
            "signalType": "Continuation",
            "signalTime": iso(c["time"]),
            "entryTime": iso(nxt["time"]),
            "entry": entry,
            "entryPrice": entry,
            "initialStop": entry - risk if side == "LONG" else entry + risk,
            "stop": entry - risk if side == "LONG" else entry + risk,
            "finalStop": entry - risk if side == "LONG" else entry + risk,
            "risk": risk,
            "riskPerUnit": risk,
            "tp": entry + c["atr14"] * 2.5 if side == "LONG" else entry - c["atr14"] * 2.5,
            "tp1": entry + c["atr14"] * 2.5 if side == "LONG" else entry - c["atr14"] * 2.5,
            "triggered": False,
            "triggerTime": None,
            "realized": 0.0,
            "atr14": c["atr14"],
            "rsi14": c["rsi14"],
            "distanceToEma50Atr": abs(c["close"] - c["ema50"]) / c["atr14"],
            "notes": cfg["name"],
        }
    return trades


def load_primary_trades():
    data = json.loads(BASE.read_text(encoding="utf-8"))
    return next(v for v in data["variants"] if v["key"] == "runner_a_50_50_ssl")["trades"]


def overlaps(primary, cont):
    p_ranges = []
    for t in primary:
        p_ranges.append((t["symbol"], datetime.fromisoformat(t["entryTime"].replace("Z", "+00:00")), datetime.fromisoformat(t["exitTime"].replace("Z", "+00:00"))))
    out = []
    for t in cont:
        entry = datetime.fromisoformat(t["entryTime"].replace("Z", "+00:00"))
        if any(sym == t["symbol"] and start <= entry <= end for sym, start, end in p_ranges):
            continue
        out.append(t)
    return out


def max_dd(trades, key="rMultiple"):
    cum = peak = dd = 0.0
    for t in sorted(trades, key=lambda x: x["exitTime"]):
        cum += t[key]
        peak = max(peak, cum)
        dd = min(dd, cum - peak)
    return dd


def stats(trades):
    rows = sorted(trades, key=lambda x: x["exitTime"])
    total = sum(t["rMultiple"] for t in rows)
    wins = sum(1 for t in rows if t["rMultiple"] > 0)
    cont = [t for t in rows if t.get("signalType") == "Continuation"]
    return {
        "trades": len(rows),
        "wins": wins,
        "losses": len(rows) - wins,
        "winRate": wins / len(rows) if rows else 0,
        "totalR": total,
        "avgR": total / len(rows) if rows else 0,
        "maxDrawdownR": max_dd(rows),
        "continuationTrades": len(cont),
        "continuationR": sum(t["rMultiple"] for t in cont),
        "capturesDec2020": any(t["symbol"] == "BTCUSDT" and t["signalTime"].startswith("2020-12-13") for t in cont),
    }


def riskoff(trades, threshold=-4.0, scale=0.4):
    rows = []
    cum = peak = 0.0
    for t in sorted(trades, key=lambda x: x["exitTime"]):
        row = dict(t)
        mult = scale if cum - peak <= threshold else 1.0
        row["riskOffR"] = row["rMultiple"] * mult
        row["sizeMultiplier"] = mult
        cum += row["riskOffR"]
        peak = max(peak, cum)
        rows.append(row)
    return rows


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    candles = {s: enrich(json.loads((DATA / f"{s}.json").read_text(encoding="utf-8"))) for s in SYMBOLS}
    primary = sorted(load_primary_trades(), key=lambda x: x["exitTime"])
    variants = {}
    for cfg in CONTINUATION_VARIANTS:
        cont = []
        for symbol in SYMBOLS:
            cont.extend(backtest_continuation(symbol, candles[symbol], cfg))
        cont = overlaps(primary, cont)
        combined = sorted([*primary, *cont], key=lambda x: x["exitTime"])
        ro = riskoff(combined)
        variants[cfg["key"]] = {
            "name": cfg["name"],
            "config": cfg,
            "statsBeforeRiskOff": stats(combined),
            "statsAfterRiskOff": {
                **stats([{**t, "rMultiple": t.get("riskOffR", t["rMultiple"])} for t in ro]),
                "riskOffTrades": sum(1 for t in ro if t.get("sizeMultiplier", 1) < 1),
            },
            "continuationTrades": sorted(cont, key=lambda x: x["exitTime"]),
        }
    result = {
        "generatedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "baseline": "NXT v3.1 Runner A unchanged; continuation module adds non-overlapping continuation entries.",
        "primaryStats": stats(primary),
        "primaryRiskOffStats": {
            **stats([{**t, "rMultiple": t.get("riskOffR", t["rMultiple"])} for t in riskoff(primary)]),
            "riskOffTrades": sum(1 for t in riskoff(primary) if t.get("sizeMultiplier", 1) < 1),
        },
        "variants": variants,
        "rankingAfterRiskOff": sorted(({"key": k, "name": v["name"], **v["statsAfterRiskOff"]} for k, v in variants.items()), key=lambda x: x["totalR"], reverse=True),
    }
    OUT_JSON.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({"outJson": str(OUT_JSON), "primary": result["primaryRiskOffStats"], "rankingAfterRiskOff": result["rankingAfterRiskOff"]}, indent=2))


if __name__ == "__main__":
    main()
