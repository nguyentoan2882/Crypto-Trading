from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import backtest_nxt31_utc7_latest as base
import backtest_nxt32_native_1d_latest as native
import test_nxt33_long_only_pullback_continuation as cont
from audit_nxt34_btc_bnb_sol_funding_adjusted import fetch_monthly_funding, funding_for_trade
from nxt_tradingview_binance_1d_data import fetch_tradingview_binance_1d
from test_nxt33_ssl14 import enrich_with_ssl_period


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "outputs" / "nxt35_primary_distance_sweep"
OUT_JSON = OUT_DIR / "NXT35_Primary_Distance_To_EMA50_Sweep.json"
SYMBOLS = ["BTCUSDT", "BNBUSDT", "SOLUSDT"]
DISTANCE_THRESHOLDS = [2.0, 2.1, 2.2, 2.3, 2.4, 2.5]


def profit_factor(rows: list[dict], key: str) -> float | None:
    gross_profit = sum(t[key] for t in rows if t[key] > 0)
    gross_loss = -sum(t[key] for t in rows if t[key] < 0)
    return gross_profit / gross_loss if gross_loss else None


def stats(rows: list[dict], key: str) -> dict:
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    values = [t[key] for t in rows]
    for value in values:
        equity += value
        peak = max(peak, equity)
        max_dd = min(max_dd, equity - peak)
    wins = sum(1 for value in values if value > 0)
    total = sum(values)
    return {
        "trades": len(values),
        "wins": wins,
        "losses": len(values) - wins,
        "winRate": wins / len(values) if values else 0.0,
        "totalR": total,
        "avgR": total / len(values) if values else 0.0,
        "maxDrawdownR": max_dd,
        "bestR": max(values) if values else None,
        "worstR": min(values) if values else None,
        "profitFactor": profit_factor(rows, key),
        "ending20k": 20000 + total * 1000,
    }


def add_funding(trades: list[dict]) -> list[dict]:
    funding_by_symbol = {
        symbol: fetch_monthly_funding(symbol, native.START_DATE, native.END_DATE)
        for symbol in SYMBOLS
    }
    out = []
    for trade in trades:
        row = dict(trade)
        funding = funding_for_trade(row, funding_by_symbol[row["symbol"]])
        row.update(funding)
        row["netRAfterFunding"] = row["rMultiple"] + row["fundingR"]
        out.append(row)
    return out


def backtest_symbol(symbol: str, candles: list[dict], primary_distance_cap: float) -> list[dict]:
    trades, pos, n = [], None, 1
    last_profitable_runner_exit = None
    for i in range(55, len(candles) - 1):
        c, prev, nxt = candles[i], candles[i - 1], candles[i + 1]
        next_date = base.date.fromisoformat(nxt["localDate"])
        if next_date < native.START_DATE or next_date >= native.END_DATE:
            continue
        if pos:
            side = pos["side"]
            ssl_flip = (side == "LONG" and prev["ssl"] == 1 and c["ssl"] == -1) or (side == "SHORT" and prev["ssl"] == -1 and c["ssl"] == 1)
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
                    if ssl_flip:
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
                    if ssl_flip:
                        exit_price = c["close"]
                        reason = "Runner exit: SSL bullish flip"
            if exit_price is not None:
                rem = 0.5 if pos["triggered"] else 1.0
                rem_r = (exit_price - pos["entry"]) / pos["risk"] if side == "LONG" else (pos["entry"] - exit_price) / pos["risk"]
                gross = pos["realizedR"] + rem * rem_r
                cost = base.cost_r(pos["entry"], pos["risk"])
                net = gross - cost
                trades.append({
                    "symbol": symbol,
                    "tradeNo": n,
                    "signalType": pos["signalType"],
                    "side": side,
                    "signalTime": pos["signalDate"],
                    "entryTime": pos["entryDate"],
                    "entryPrice": pos["entry"],
                    "initialStop": pos["initialStop"],
                    "finalStop": pos["stop"],
                    "riskPerUnit": pos["risk"],
                    "tp1": pos["tp"],
                    "tp1Time": pos["tp1Time"],
                    "earlyBeTriggered": pos["earlyBeTriggered"],
                    "earlyBeTime": pos["earlyBeTime"],
                    "exitTime": c["localDate"],
                    "exitPrice": exit_price,
                    "exitReason": reason,
                    "grossRMultiple": gross,
                    "costR": cost,
                    "rMultiple": net,
                    "atr14": pos["atr14"],
                    "rsi14": pos["rsi14"],
                    "distanceToEma50Atr": pos["distance"],
                    "ema20": pos["ema20"],
                    "ema50": pos["ema50"],
                    "notes": pos["notes"],
                })
                if net >= cont.ANTI_REVERSAL_MIN_RUNNER_R and reason.startswith("Runner exit"):
                    last_profitable_runner_exit = {"index": i, "side": side, "netR": net}
                n += 1
                pos = None
            if pos:
                continue

        if any(c[k] is None for k in ["ema20", "ema50", "atr14", "rsi14", "ssl"]) or prev["ssl"] is None:
            continue
        dist = abs(c["close"] - c["ema50"]) / c["atr14"]
        long_primary = prev["ssl"] == -1 and c["ssl"] == 1 and base.recent_cross(candles, i, "LONG") and dist <= primary_distance_cap and c["rsi14"] > 50
        short_primary = prev["ssl"] == 1 and c["ssl"] == -1 and base.recent_cross(candles, i, "SHORT") and dist <= primary_distance_cap and c["rsi14"] < 50
        long_cont = prev["ssl"] == -1 and c["ssl"] == 1 and c["close"] > c["ema20"] > c["ema50"] and cont.touch_reclaim_long(candles, i, cont.RULE["touchLookback"])
        short_cont = False
        if last_profitable_runner_exit and i - last_profitable_runner_exit["index"] <= 1:
            if (long_primary or long_cont) and last_profitable_runner_exit["side"] == "SHORT":
                long_primary = long_cont = False
            if short_primary and last_profitable_runner_exit["side"] == "LONG":
                short_primary = False
        if not (long_primary or short_primary or long_cont or short_cont):
            continue
        side = "LONG" if (long_primary or long_cont) else "SHORT"
        signal_type = "Continuation" if long_cont and not long_primary else "Primary"
        risk = c["atr14"] * 1.5
        entry = nxt["open"]
        pos = {
            "side": side,
            "signalType": signal_type,
            "signalDate": c["localDate"],
            "entryDate": nxt["localDate"],
            "entry": entry,
            "initialStop": entry - risk if side == "LONG" else entry + risk,
            "stop": entry - risk if side == "LONG" else entry + risk,
            "risk": risk,
            "tp": entry + c["atr14"] * cont.TP1_ATR if side == "LONG" else entry - c["atr14"] * cont.TP1_ATR,
            "triggered": False,
            "earlyBeTriggered": False,
            "earlyBeTime": "",
            "tp1Time": "",
            "realizedR": 0.0,
            "atr14": c["atr14"],
            "rsi14": c["rsi14"],
            "distance": dist,
            "ema20": c["ema20"],
            "ema50": c["ema50"],
            "notes": "Primary NXT v3.5" if signal_type == "Primary" else cont.RULE["name"],
        }
    return trades


def run_variant(cap: float, datasets: dict[str, list[dict]]) -> dict:
    trades = []
    for symbol in SYMBOLS:
        trades.extend(backtest_symbol(symbol, datasets[symbol], cap))
    trades.sort(key=lambda trade: trade["exitTime"])
    funded = add_funding(trades)
    watch = [
        t for t in funded
        if t["symbol"] == "BTCUSDT" and "2025-02-20" <= t["signalTime"] <= "2025-03-05"
    ]
    return {
        "primaryDistanceToEma50Atr": cap,
        "originalStats": stats(funded, "rMultiple"),
        "fundingAdjustedStats": stats(funded, "netRAfterFunding"),
        "btc20250220To20250305": watch,
    }


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    datasets = {
        symbol: enrich_with_ssl_period(fetch_tradingview_binance_1d(symbol, native.WARMUP_DATE, native.END_DATE), 14)
        for symbol in SYMBOLS
    }
    results = [run_variant(cap, datasets) for cap in DISTANCE_THRESHOLDS]
    baseline = results[0]["fundingAdjustedStats"]
    for result in results:
        st = result["fundingAdjustedStats"]
        result["deltaVs2_0FundingAdjusted"] = {
            "trades": st["trades"] - baseline["trades"],
            "totalR": st["totalR"] - baseline["totalR"],
            "maxDrawdownR": st["maxDrawdownR"] - baseline["maxDrawdownR"],
            "profitFactor": (st["profitFactor"] or 0) - (baseline["profitFactor"] or 0),
        }
    payload = {
        "generatedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "system": "NXT v3.5 primary distance-to-EMA50 ATR sweep",
        "note": "Only Primary LONG/SHORT distanceToEma50Atr gate changes. Continuation rules and all other latest rules are unchanged.",
        "results": results,
    }
    OUT_JSON.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps([
        {
            "cap": r["primaryDistanceToEma50Atr"],
            "fundingAdjustedStats": r["fundingAdjustedStats"],
            "delta": r["deltaVs2_0FundingAdjusted"],
            "btcWatch": [
                {
                    "side": t["side"],
                    "signalTime": t["signalTime"],
                    "entryTime": t["entryTime"],
                    "exitTime": t["exitTime"],
                    "netRAfterFunding": t["netRAfterFunding"],
                    "distanceToEma50Atr": t["distanceToEma50Atr"],
                }
                for t in r["btc20250220To20250305"]
            ],
        }
        for r in results
    ], indent=2))


if __name__ == "__main__":
    main()
