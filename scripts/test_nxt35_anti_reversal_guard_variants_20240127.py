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
OUT_DIR = ROOT / "outputs" / "nxt35_anti_reversal_guard_variants_20240127"
OUT_JSON = OUT_DIR / "NXT35_Anti_Reversal_Guard_Variants_20240127.json"
BASELINE_JSON = ROOT / "latest" / "NXT_Latest_NXT35_BTC_BNB_SOL_FundingAdjusted_20K.json"
SYMBOLS = ["BTCUSDT", "BNBUSDT", "SOLUSDT"]

VARIANTS = [
    {
        "name": "current",
        "description": "Current latest: block same candle and next candle after any profitable runner SSL-flip exit.",
        "mode": "current",
    },
    {
        "name": "allow_same_candle_block_next_only",
        "description": "Allow opposite entry on the exit candle; block only the next candle.",
        "mode": "block_next_only",
    },
    {
        "name": "block_if_prior_runner_ge_0_25R",
        "description": "Current same+next block, but only if the prior runner exit net R >= 0.25R.",
        "mode": "min_prior_r",
        "minPriorR": 0.25,
    },
    {
        "name": "block_if_prior_runner_ge_0_50R",
        "description": "Current same+next block, but only if the prior runner exit net R >= 0.50R.",
        "mode": "min_prior_r",
        "minPriorR": 0.50,
    },
    {
        "name": "block_if_prior_runner_ge_1_00R",
        "description": "Current same+next block, but only if the prior runner exit net R >= 1.00R.",
        "mode": "min_prior_r",
        "minPriorR": 1.00,
    },
    {
        "name": "block_only_if_prior_tp1",
        "description": "Current same+next block, but only if the prior runner trade had TP1 filled.",
        "mode": "prior_tp1",
    },
    {
        "name": "allow_if_primary_and_continuation",
        "description": "Current same+next block except allow an opposite signal if it qualifies as both Primary and Continuation.",
        "mode": "primary_and_cont_override",
    },
    {
        "name": "no_guard",
        "description": "Disable anti-immediate-reversal completely.",
        "mode": "no_guard",
    },
]


def profit_factor(rows: list[dict], key: str) -> float | None:
    gp = sum(t[key] for t in rows if t[key] > 0)
    gl = -sum(t[key] for t in rows if t[key] < 0)
    return gp / gl if gl else None


def stats_for_key(rows: list[dict], key: str) -> dict:
    stats = funding.stats_for_key(rows, key)
    stats["profitFactor"] = profit_factor(rows, key)
    return stats


def should_block(variant: dict, last_exit: dict | None, i: int, side: str, signal_flags: dict) -> bool:
    if not last_exit or last_exit["side"] == side:
        return False
    mode = variant["mode"]
    if mode == "no_guard":
        return False
    delta = i - last_exit["index"]
    if mode == "block_next_only":
        return delta == 1
    if delta not in (0, 1):
        return False
    if mode == "min_prior_r":
        return last_exit["netR"] >= variant["minPriorR"]
    if mode == "prior_tp1":
        return bool(last_exit["tp1Hit"])
    if mode == "primary_and_cont_override":
        if side == "LONG" and signal_flags["longPrimary"] and signal_flags["longCont"]:
            return False
        if side == "SHORT" and signal_flags["shortPrimary"] and signal_flags["shortCont"]:
            return False
    return True


def backtest_symbol(symbol: str, candles: list[dict], variant: dict) -> list[dict]:
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
                trade = {
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
                    "notes": variant["name"],
                }
                trades.append(trade)
                if net > 0 and reason.startswith("Runner exit"):
                    last_profitable_runner_exit = {
                        "index": i,
                        "side": side,
                        "netR": net,
                        "tp1Hit": bool(pos["tp1Time"]),
                        "exitDate": c["localDate"],
                    }
                n += 1
                pos = None
            if pos:
                continue

        if any(c[k] is None for k in ["ema20", "ema50", "atr14", "rsi14", "ssl"]) or prev["ssl"] is None:
            continue
        dist = abs(c["close"] - c["ema50"]) / c["atr14"]
        long_primary = prev["ssl"] == -1 and c["ssl"] == 1 and base.recent_cross(candles, i, "LONG") and dist <= 2 and c["rsi14"] > 50
        short_primary = prev["ssl"] == 1 and c["ssl"] == -1 and base.recent_cross(candles, i, "SHORT") and dist <= 2 and c["rsi14"] < 50
        long_cont = (prev["ssl"] == -1 and c["ssl"] == 1) and c["close"] > c["ema20"] > c["ema50"] and cont.touch_reclaim_long(candles, i, cont.RULE["touchLookback"])
        short_cont = False
        flags = {
            "longPrimary": long_primary,
            "longCont": long_cont,
            "shortPrimary": short_primary,
            "shortCont": short_cont,
        }
        if (long_primary or long_cont) and should_block(variant, last_profitable_runner_exit, i, "LONG", flags):
            long_primary = long_cont = False
        if short_primary and should_block(variant, last_profitable_runner_exit, i, "SHORT", flags):
            short_primary = False
        if not (long_primary or short_primary or long_cont):
            continue
        side = "LONG" if (long_primary or long_cont) else "SHORT"
        signal_type = "Continuation" if (long_cont and not long_primary) else "Primary"
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
            "tp": entry + c["atr14"] * 2.5 if side == "LONG" else entry - c["atr14"] * 2.5,
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


def add_funding(trades: list[dict], funding_by_symbol: dict[str, list[dict]]) -> None:
    for trade in trades:
        trade.update(funding.funding_for_trade(trade, funding_by_symbol[trade["symbol"]]))
        trade["netRAfterFunding"] = trade["rMultiple"] + trade["fundingR"]


def trade_key(trade: dict) -> tuple:
    return trade["symbol"], trade["side"], trade["signalTime"], trade["entryTime"]


def run_variant(variant: dict, datasets: dict, funding_by_symbol: dict[str, list[dict]]) -> dict:
    trades = []
    for symbol in SYMBOLS:
        trades.extend(backtest_symbol(symbol, datasets[symbol], variant))
    trades.sort(key=lambda t: (t["exitTime"], t["symbol"], t["tradeNo"]))
    add_funding(trades, funding_by_symbol)
    stats = stats_for_key(trades, "netRAfterFunding")
    target = [
        t for t in trades
        if t["symbol"] == "BTCUSDT"
        and t["side"] == "LONG"
        and t["signalTime"] == "2024-01-27"
    ]
    return {
        "variant": variant,
        "stats": stats,
        "targetTrades": target,
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
    baseline_latest = json.loads(BASELINE_JSON.read_text(encoding="utf-8"))
    runs = [run_variant(variant, datasets, funding_by_symbol) for variant in VARIANTS]
    current = runs[0]
    current_keys = {trade_key(t) for t in current["trades"]}
    for run in runs:
        keys = {trade_key(t) for t in run["trades"]}
        run["deltaVsCurrentRun"] = {
            key: run["stats"][key] - current["stats"][key]
            for key in ["trades", "winRate", "totalR", "avgR", "maxDrawdownR", "profitFactor", "ending20k"]
        }
        run["tradeDiffCounts"] = {
            "added": len(keys - current_keys),
            "removed": len(current_keys - keys),
        }
    payload = {
        "generatedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "system": "NXT v3.5 anti-immediate-reversal guard variants for BTC/BNB/SOL",
        "baselineLatestFundingAdjustedStats": baseline_latest["fundingAdjustedStats"],
        "runs": runs,
    }
    OUT_JSON.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps({
        "outJson": str(OUT_JSON),
        "latestBaseline": baseline_latest["fundingAdjustedStats"],
        "summary": [
            {
                "name": run["variant"]["name"],
                "description": run["variant"]["description"],
                "stats": run["stats"],
                "deltaVsCurrent": run["deltaVsCurrentRun"],
                "targetCount": len(run["targetTrades"]),
                "targetTrades": [
                    {
                        "entryTime": t["entryTime"],
                        "exitTime": t["exitTime"],
                        "exitReason": t["exitReason"],
                        "netRAfterFunding": t["netRAfterFunding"],
                    }
                    for t in run["targetTrades"]
                ],
                "tradeDiffCounts": run["tradeDiffCounts"],
            }
            for run in runs
        ],
    }, indent=2))


if __name__ == "__main__":
    main()
