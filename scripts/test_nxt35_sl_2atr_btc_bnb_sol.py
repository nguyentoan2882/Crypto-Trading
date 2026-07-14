from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import audit_nxt34_btc_bnb_sol_funding_adjusted as funding
import backtest_nxt31_utc7_latest as base
import backtest_nxt32_native_1d_latest as native
import test_nxt33_long_only_pullback_continuation as cont
from nxt_tradingview_binance_1d_data import fetch_tradingview_binance_1d
from test_nxt33_ssl14 import enrich_with_ssl_period


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "outputs" / "nxt35_sl_2atr_btc_bnb_sol"
OUT_JSON = OUT_DIR / "NXT35_SL_2ATR_BTC_BNB_SOL_FundingAdjusted.json"
BASELINE_JSON = ROOT / "latest" / "NXT_Latest_NXT35_BTC_BNB_SOL_FundingAdjusted_20K.json"

SYMBOLS = ["BTCUSDT", "BNBUSDT", "SOLUSDT"]
STOP_ATR = 2.0
TP1_ATR = 2.5


def profit_factor(rows: list[dict], key: str) -> float | None:
    gross_profit = sum(t[key] for t in rows if t[key] > 0)
    gross_loss = -sum(t[key] for t in rows if t[key] < 0)
    return gross_profit / gross_loss if gross_loss else None


def stats_for_key(rows: list[dict], key: str) -> dict:
    stats = funding.stats_for_key(rows, key)
    stats["profitFactor"] = profit_factor(rows, key)
    return stats


def backtest_symbol(symbol: str, candles: list[dict]) -> list[dict]:
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
                    if can_trigger_early_be and not pos["triggered"] and not pos["earlyBeTriggered"] and c["high"] >= pos["entry"] * 1.07:
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
                    if can_trigger_early_be and not pos["triggered"] and not pos["earlyBeTriggered"] and c["low"] <= pos["entry"] * 0.93:
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
                    "stopAtr": STOP_ATR,
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
                if net > 0 and reason.startswith("Runner exit"):
                    last_profitable_runner_exit = {"index": i, "side": side}
                n += 1
                pos = None
            if pos:
                continue

        if any(c[k] is None for k in ["ema20", "ema50", "atr14", "rsi14", "ssl"]) or prev["ssl"] is None:
            continue
        dist = abs(c["close"] - c["ema50"]) / c["atr14"]
        long_primary = prev["ssl"] == -1 and c["ssl"] == 1 and base.recent_cross(candles, i, "LONG") and dist <= 2 and c["rsi14"] > 50
        short_primary = prev["ssl"] == 1 and c["ssl"] == -1 and base.recent_cross(candles, i, "SHORT") and dist <= 2 and c["rsi14"] < 50
        continuation_ssl_ok = prev["ssl"] == -1 and c["ssl"] == 1
        long_cont = continuation_ssl_ok and c["close"] > c["ema20"] > c["ema50"] and cont.touch_reclaim_long(candles, i, cont.RULE["touchLookback"])
        if last_profitable_runner_exit and i - last_profitable_runner_exit["index"] <= 1:
            if (long_primary or long_cont) and last_profitable_runner_exit["side"] == "SHORT":
                long_primary = long_cont = False
            if short_primary and last_profitable_runner_exit["side"] == "LONG":
                short_primary = False
        if not (long_primary or short_primary or long_cont):
            continue
        side = "LONG" if (long_primary or long_cont) else "SHORT"
        signal_type = "Continuation" if (long_cont and not long_primary) else "Primary"
        risk = c["atr14"] * STOP_ATR
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
            "tp": entry + c["atr14"] * TP1_ATR if side == "LONG" else entry - c["atr14"] * TP1_ATR,
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
            "notes": "Primary NXT v3.5; SL 2.0 ATR test" if signal_type == "Primary" else "LONG-only pullback/touch EMA20 continuation; SL 2.0 ATR test",
        }
    return trades


def grouped(rows: list[dict], key_fn, value_key: str) -> list[dict]:
    groups = {}
    for row in rows:
        groups.setdefault(key_fn(row), []).append(row)
    out = []
    for key, subset in sorted(groups.items()):
        item = stats_for_key(subset, value_key)
        item["group"] = key
        out.append(item)
    return out


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    all_trades = []
    datasets = {}
    for symbol in SYMBOLS:
        candles = enrich_with_ssl_period(fetch_tradingview_binance_1d(symbol, native.WARMUP_DATE, native.END_DATE), 14)
        datasets[symbol] = {
            "dailyRows": len(candles),
            "firstDay": candles[0]["localDate"],
            "lastDay": candles[-1]["localDate"],
            "source": "Binance spot native 1D (00:00 UTC), matching TradingView BINANCE 1D",
        }
        all_trades.extend(backtest_symbol(symbol, candles))
    all_trades.sort(key=lambda trade: (trade["exitTime"], trade["symbol"], trade["tradeNo"]))

    funding_by_symbol = {
        symbol: funding.fetch_monthly_funding(symbol, native.START_DATE, native.END_DATE)
        for symbol in SYMBOLS
    }
    for trade in all_trades:
        trade.update(funding.funding_for_trade(trade, funding_by_symbol[trade["symbol"]]))
        trade["netRAfterFunding"] = trade["rMultiple"] + trade["fundingR"]

    baseline = json.loads(BASELINE_JSON.read_text(encoding="utf-8"))
    baseline_period = {
        "start": min(t["entryTime"] for t in baseline["trades"]),
        "end": max(t["exitTime"] for t in baseline["trades"]),
    }
    result = {
        "generatedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "systemVersion": "NXT v3.5 BTC/BNB/SOL SL 2.0 ATR test; all other current latest rules unchanged",
        "period": baseline_period,
        "symbols": SYMBOLS,
        "changedRule": "Initial stop and risk unit changed from 1.5 ATR14 to 2.0 ATR14. TP1 remains 2.5 ATR14; BE7, entries, exits, costs, funding and anti-immediate-reversal unchanged.",
        "originalStats": stats_for_key(all_trades, "rMultiple"),
        "fundingAdjustedStats": stats_for_key(all_trades, "netRAfterFunding"),
        "baselineFundingAdjustedStats": baseline["fundingAdjustedStats"],
        "deltaVsBaseline": {
            key: stats_for_key(all_trades, "netRAfterFunding")[key] - baseline["fundingAdjustedStats"][key]
            for key in ["trades", "winRate", "totalR", "avgR", "maxDrawdownR", "profitFactor", "ending20k"]
        },
        "fundingSummary": {
            "totalFundingR": sum(t["fundingR"] for t in all_trades),
            "fundingEvents": sum(t["fundingEvents"] for t in all_trades),
            "fundingPaidR": sum(t["fundingPaidR"] for t in all_trades),
            "fundingReceivedR": sum(t["fundingReceivedR"] for t in all_trades),
        },
        "bySymbol": grouped(all_trades, lambda t: t["symbol"], "netRAfterFunding"),
        "bySide": grouped(all_trades, lambda t: t["side"], "netRAfterFunding"),
        "bySignalType": grouped(all_trades, lambda t: t["signalType"], "netRAfterFunding"),
        "byYear": grouped(all_trades, lambda t: t["exitTime"][:4], "netRAfterFunding"),
        "datasets": datasets,
        "trades": all_trades,
    }
    OUT_JSON.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({
        "outJson": str(OUT_JSON),
        "variant": result["fundingAdjustedStats"],
        "baseline": result["baselineFundingAdjustedStats"],
        "delta": result["deltaVsBaseline"],
        "bySymbol": result["bySymbol"],
        "bySide": result["bySide"],
        "bySignalType": result["bySignalType"],
    }, indent=2))


if __name__ == "__main__":
    main()
