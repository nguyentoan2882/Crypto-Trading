from __future__ import annotations

import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import audit_nxt34_btc_bnb_sol_funding_adjusted as funding
import backtest_nxt31_utc7_latest as base
import backtest_nxt35_latest_to_today as latest
import test_nxt33_long_only_pullback_continuation as cont
from test_nxt33_ssl14 import enrich_with_ssl_period


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "outputs" / "nxt35_runner_exit_variants"
OUT_JSON = OUT_DIR / "NXT35_Runner_Exit_Variants.json"
SYMBOLS = ["BTCUSDT", "BNBUSDT", "SOLUSDT"]
LATEST_JSON = ROOT / "latest" / "NXT_Latest_NXT35_USDM_BlockShortAfterLosingLong_FundingAdjusted_20K.json"

VARIANTS = [
    {
        "key": "baseline_ssl_flip",
        "description": "Current latest: stop/TP1/Early-BE, then exit remaining position on opposite SSL flip.",
        "mode": "ssl",
    },
    {
        "key": "ema20_close",
        "description": "Exit remaining open position when daily close crosses against EMA20 instead of waiting for SSL flip.",
        "mode": "ema_close",
        "ema": "ema20",
    },
    {
        "key": "ema50_close",
        "description": "Exit remaining open position when daily close crosses against EMA50 instead of waiting for SSL flip.",
        "mode": "ema_close",
        "ema": "ema50",
    },
    {
        "key": "atr_trail_2_0",
        "description": "Replace SSL runner exit with a 2.0 ATR trailing stop using daily high/low and ATR14.",
        "mode": "atr_trail",
        "atr_mult": 2.0,
    },
    {
        "key": "atr_trail_3_0",
        "description": "Replace SSL runner exit with a 3.0 ATR trailing stop using daily high/low and ATR14.",
        "mode": "atr_trail",
        "atr_mult": 3.0,
    },
    {
        "key": "runner_only_ema20_close",
        "description": "Before TP1 keep SSL exit; after TP1 exit runner when daily close crosses against EMA20.",
        "mode": "ema_close",
        "ema": "ema20",
        "runner_only": True,
    },
    {
        "key": "runner_only_ema50_close",
        "description": "Before TP1 keep SSL exit; after TP1 exit runner when daily close crosses against EMA50.",
        "mode": "ema_close",
        "ema": "ema50",
        "runner_only": True,
    },
    {
        "key": "runner_only_atr_trail_2_0",
        "description": "Before TP1 keep SSL exit; after TP1 use a 2.0 ATR trailing stop for the runner.",
        "mode": "atr_trail",
        "atr_mult": 2.0,
        "runner_only": True,
    },
    {
        "key": "runner_only_atr_trail_3_0",
        "description": "Before TP1 keep SSL exit; after TP1 use a 3.0 ATR trailing stop for the runner.",
        "mode": "atr_trail",
        "atr_mult": 3.0,
        "runner_only": True,
    },
    {
        "key": "conditional_ema50_btc_above_ema200",
        "description": "Before TP1 keep SSL exit; after TP1 use EMA50 runner only if BTC signal candle closes above EMA200, else keep SSL runner.",
        "mode": "conditional_ema50",
        "condition": "btc_above_ema200",
        "runner_only": True,
    },
    {
        "key": "conditional_ema50_with_btc_trend",
        "description": "Before TP1 keep SSL exit; after TP1 use EMA50 runner only when trade direction aligns with BTC EMA20/EMA50 trend structure, else keep SSL runner.",
        "mode": "conditional_ema50",
        "condition": "with_btc_trend",
        "runner_only": True,
    },
    {
        "key": "conditional_ema50_above_ema200_or_with_trend",
        "description": "Before TP1 keep SSL exit; after TP1 use EMA50 runner if BTC is above EMA200 or trade direction aligns with BTC EMA20/EMA50 trend structure, else keep SSL runner.",
        "mode": "conditional_ema50",
        "condition": "btc_above_ema200_or_with_btc_trend",
        "runner_only": True,
    },
    {
        "key": "runner_scaleout_3r_4r_5r_equal",
        "description": "After TP1, split the 50% runner equally across 3R, 4R and 5R targets; any unfinished runner still exits by SSL flip or stop.",
        "mode": "scaleout_r_targets",
        "r_targets": [3.0, 4.0, 5.0],
        "runner_only": True,
    },
    *[
        {
            "key": f"hybrid_partial_{str(level).replace('.', '_')}r_then_cond_ema50",
            "description": f"After TP1, close 25% original position at {level:.1f}R, then keep final 25% on conditional EMA50 when BTC > EMA200, else SSL runner.",
            "mode": "hybrid_partial_then_conditional_ema50",
            "partial_r": level,
            "partial_fraction": 0.25,
            "condition": "btc_above_ema200",
            "runner_only": True,
        }
        for level in [3.0, 3.5, 4.0, 4.5, 5.0]
    ],
    *[
        {
            "key": f"hybrid_partial_{int(frac * 100)}pct_at_{str(level).replace('.', '_')}r_then_cond_ema50",
            "description": f"After TP1, close {frac:.0%} original position at {level:.1f}R, then keep the rest on conditional EMA50 when BTC > EMA200, else SSL runner.",
            "mode": "hybrid_partial_then_conditional_ema50",
            "partial_r": level,
            "partial_fraction": frac,
            "condition": "btc_above_ema200",
            "runner_only": True,
        }
        for frac in [0.10, 0.15, 0.20]
        for level in [3.5, 4.0, 4.5]
    ],
    *[
        {
            "key": (
                f"alloc_tp1_{int(tp1 * 100)}pct_"
                f"partial_{int(partial * 100)}pct_at_{str(level).replace('.', '_')}r_"
                "cond_ema50"
            ),
            "description": (
                f"Allocation grid: close {tp1:.0%} at TP1, "
                f"{partial:.0%} at {level:.1f}R after TP1, "
                "and leave the rest as conditional EMA50/SSL tail."
            ),
            "mode": "hybrid_partial_then_conditional_ema50",
            "tp1_fraction": tp1,
            "partial_r": level,
            "partial_fraction": partial,
            "condition": "btc_above_ema200",
            "runner_only": True,
            "allocation_grid": True,
        }
        for tp1 in [0.30, 0.40, 0.50, 0.60]
        for partial in [0.00, 0.10, 0.15, 0.20]
        for level in ([4.0] if partial == 0.0 else [3.5, 4.0, 4.5])
        if tp1 + partial <= 0.90
    ],
    *[
        {
            "key": (
                f"guard_{condition}_tp1_{int(tp1 * 100)}pct_"
                f"partial_{int(partial * 100)}pct_at_4_0r_cond_ema50"
            ),
            "description": (
                f"Guarded allocation: close {tp1:.0%} at TP1, "
                f"{partial:.0%} at 4.0R, and use EMA50 tail only when "
                f"BTC condition '{condition}' is true; otherwise use SSL tail."
            ),
            "mode": "hybrid_partial_then_conditional_ema50",
            "tp1_fraction": tp1,
            "partial_r": 4.0,
            "partial_fraction": partial,
            "condition": condition,
            "runner_only": True,
            "allocation_grid": True,
            "regime_guard_grid": True,
        }
        for condition in [
            "long_only_btc_bull_above_ema200",
            "directional_strong_btc_trend",
            "btc_above_ema200_and_bull_structure",
        ]
        for tp1, partial in [(0.30, 0.10), (0.40, 0.10), (0.30, 0.00), (0.40, 0.00)]
    ],
    {
        "key": "tp2_4atr_after_tp1",
        "description": "After TP1, close the remaining 50% at TP2 = 4.0 ATR from entry; pre-TP1 exit remains SSL/stop.",
        "mode": "tp2_after_tp1",
        "tp2_atr": 4.0,
    },
    {
        "key": "tp2_5atr_after_tp1",
        "description": "After TP1, close the remaining 50% at TP2 = 5.0 ATR from entry; pre-TP1 exit remains SSL/stop.",
        "mode": "tp2_after_tp1",
        "tp2_atr": 5.0,
    },
]


def close_position(symbol: str, trade_no: int, pos: dict, candle: dict, exit_price: float, reason: str) -> dict:
    side = pos["side"]
    rem = pos.get("remainingFraction", 0.5 if pos["triggered"] else 1.0)
    rem_r = (exit_price - pos["entry"]) / pos["risk"] if side == "LONG" else (pos["entry"] - exit_price) / pos["risk"]
    gross = pos["realizedR"] + rem * rem_r
    cost = base.cost_r(pos["entry"], pos["risk"])
    net = gross - cost
    return {
        "symbol": symbol,
        "tradeNo": trade_no,
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
        "partialTime": pos.get("hybridPartialTime", ""),
        "earlyBeTriggered": pos["earlyBeTriggered"],
        "earlyBeTime": pos["earlyBeTime"],
        "exitTime": candle["localDate"],
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
    }


def update_atr_trail(pos: dict, candle: dict, variant: dict) -> None:
    mult = float(variant["atr_mult"])
    if pos["side"] == "LONG":
        pos["bestHigh"] = max(pos.get("bestHigh", pos["entry"]), candle["high"])
        trail = pos["bestHigh"] - mult * candle["atr14"]
        pos["stop"] = max(pos["stop"], trail)
    else:
        pos["bestLow"] = min(pos.get("bestLow", pos["entry"]), candle["low"])
        trail = pos["bestLow"] + mult * candle["atr14"]
        pos["stop"] = min(pos["stop"], trail)


def ema(values: list[float], period: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    if len(values) < period:
        return out
    prev = sum(values[:period]) / period
    out[period - 1] = prev
    alpha = 2 / (period + 1)
    for i in range(period, len(values)):
        prev = values[i] * alpha + prev * (1 - alpha)
        out[i] = prev
    return out


def add_btc_regime(candles: list[dict]) -> dict[str, dict]:
    ema200 = ema([row["close"] for row in candles], 200)
    by_date = {}
    for i, candle in enumerate(candles):
        row = dict(candle)
        row["ema200"] = ema200[i]
        if row.get("ema50") is not None and row.get("ema20") is not None:
            row["btcBullStructure"] = row["close"] > row["ema50"] and row["ema20"] > row["ema50"]
            row["btcBearStructure"] = row["close"] < row["ema50"] and row["ema20"] < row["ema50"]
        else:
            row["btcBullStructure"] = False
            row["btcBearStructure"] = False
        row["btcAboveEma200"] = row.get("ema200") is not None and row["close"] > row["ema200"]
        row["btcBelowEma200"] = row.get("ema200") is not None and row["close"] < row["ema200"]
        by_date[row["localDate"]] = row
    return by_date


def should_use_conditional_ema50(side: str, btc: dict | None, condition: str) -> bool:
    if btc is None:
        return False
    above = bool(btc.get("btcAboveEma200"))
    below = bool(btc.get("btcBelowEma200"))
    with_trend = (side == "LONG" and btc.get("btcBullStructure")) or (side == "SHORT" and btc.get("btcBearStructure"))
    bull_above_ema200 = above and bool(btc.get("btcBullStructure"))
    bear_below_ema200 = below and bool(btc.get("btcBearStructure"))
    if condition == "btc_above_ema200":
        return above
    if condition == "with_btc_trend":
        return bool(with_trend)
    if condition == "btc_above_ema200_or_with_btc_trend":
        return above or bool(with_trend)
    if condition == "btc_above_ema200_and_bull_structure":
        return bool(bull_above_ema200)
    if condition == "long_only_btc_bull_above_ema200":
        return side == "LONG" and bool(bull_above_ema200)
    if condition == "directional_strong_btc_trend":
        return (side == "LONG" and bool(bull_above_ema200)) or (side == "SHORT" and bool(bear_below_ema200))
    raise ValueError(f"Unknown conditional EMA50 condition {condition}")


def variant_exit(pos: dict, candle: dict, prev: dict, variant: dict) -> tuple[float | None, str | None]:
    side = pos["side"]
    mode = pos.get("runnerExitMode", variant["mode"])
    ssl_flip = (side == "LONG" and prev["ssl"] == 1 and candle["ssl"] == -1) or (side == "SHORT" and prev["ssl"] == -1 and candle["ssl"] == 1)
    if variant.get("runner_only") and not pos["triggered"]:
        if ssl_flip:
            reason = "Runner exit: SSL bearish flip before TP1" if side == "LONG" else "Runner exit: SSL bullish flip before TP1"
            return candle["close"], reason
        return None, None
    if mode == "ssl":
        if ssl_flip:
            reason = "Runner exit: SSL bearish flip" if side == "LONG" else "Runner exit: SSL bullish flip"
            return candle["close"], reason
    elif mode == "ema_close":
        ema_key = pos.get("runnerEma", variant.get("ema", "ema50"))
        ema = candle[ema_key]
        if side == "LONG" and candle["close"] < ema:
            return candle["close"], f"Runner exit: close below {ema_key.upper()}"
        if side == "SHORT" and candle["close"] > ema:
            return candle["close"], f"Runner exit: close above {ema_key.upper()}"
    elif mode == "atr_trail":
        update_atr_trail(pos, candle, variant)
        if side == "LONG" and candle["low"] <= pos["stop"]:
            return pos["stop"], f"Runner exit: {variant['atr_mult']:.1f} ATR trail"
        if side == "SHORT" and candle["high"] >= pos["stop"]:
            return pos["stop"], f"Runner exit: {variant['atr_mult']:.1f} ATR trail"
    elif mode == "tp2_after_tp1":
        if pos["triggered"]:
            tp2 = pos["entry"] + candle["atr14"] * variant["tp2_atr"] if side == "LONG" else pos["entry"] - candle["atr14"] * variant["tp2_atr"]
            if side == "LONG" and candle["high"] >= tp2:
                return tp2, f"Runner exit: TP2 {variant['tp2_atr']:.1f} ATR"
            if side == "SHORT" and candle["low"] <= tp2:
                return tp2, f"Runner exit: TP2 {variant['tp2_atr']:.1f} ATR"
        elif ssl_flip:
            reason = "Runner exit: SSL bearish flip before TP1" if side == "LONG" else "Runner exit: SSL bullish flip before TP1"
            return candle["close"], reason
    elif mode == "scaleout_r_targets":
        if pos["triggered"]:
            targets = variant["r_targets"]
            slice_fraction = pos.get("runnerInitialFraction", 0.5) / len(targets)
            for target_r in targets:
                if target_r in pos["scaleTargetsHit"]:
                    continue
                target_price = pos["entry"] + target_r * pos["risk"] if side == "LONG" else pos["entry"] - target_r * pos["risk"]
                hit = candle["high"] >= target_price if side == "LONG" else candle["low"] <= target_price
                if not hit:
                    continue
                pos["scaleTargetsHit"].append(target_r)
                pos["realizedR"] += slice_fraction * target_r
                pos["remainingFraction"] = max(0.0, pos["remainingFraction"] - slice_fraction)
                if pos["remainingFraction"] <= 1e-9:
                    return target_price, f"Runner exit: scale-out complete at {target_r:.1f}R"
        if ssl_flip:
            reason = "Runner exit: SSL bearish flip after scale-out" if side == "LONG" else "Runner exit: SSL bullish flip after scale-out"
            return candle["close"], reason
    elif mode == "hybrid_partial_then_conditional_ema50":
        if pos["triggered"] and not pos.get("hybridPartialHit"):
            target_r = float(variant["partial_r"])
            target_price = pos["entry"] + target_r * pos["risk"] if side == "LONG" else pos["entry"] - target_r * pos["risk"]
            hit = candle["high"] >= target_price if side == "LONG" else candle["low"] <= target_price
            if hit:
                frac = min(float(variant["partial_fraction"]), pos["remainingFraction"])
                pos["hybridPartialHit"] = True
                pos["hybridPartialTime"] = candle["localDate"]
                pos["realizedR"] += frac * target_r
                pos["remainingFraction"] = max(0.0, pos["remainingFraction"] - frac)
        if pos["triggered"]:
            if pos.get("conditionalEma50Active"):
                ema_key = "ema50"
                ema_value = candle[ema_key]
                if side == "LONG" and candle["close"] < ema_value:
                    return candle["close"], f"Runner exit: hybrid close below {ema_key.upper()}"
                if side == "SHORT" and candle["close"] > ema_value:
                    return candle["close"], f"Runner exit: hybrid close above {ema_key.upper()}"
            elif ssl_flip:
                reason = "Runner exit: hybrid SSL bearish flip" if side == "LONG" else "Runner exit: hybrid SSL bullish flip"
                return candle["close"], reason
    return None, None


def backtest_symbol(symbol: str, candles: list[dict], end_date: date, variant: dict, btc_by_date: dict[str, dict] | None = None) -> tuple[list[dict], dict | None]:
    trades, pos, n = [], None, 1
    last_runner_exit = None
    for i in range(55, len(candles) - 1):
        c, prev, nxt = candles[i], candles[i - 1], candles[i + 1]
        next_date = date.fromisoformat(nxt["localDate"])
        if next_date < latest.START_DATE or next_date > end_date:
            continue

        if pos:
            side = pos["side"]
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
                        tp1_fraction = pos["tp1Fraction"]
                        pos["realizedR"] += tp1_fraction * ((pos["tp"] - pos["entry"]) / pos["risk"])
                        pos["remainingFraction"] = 1.0 - tp1_fraction
                        pos["runnerInitialFraction"] = pos["remainingFraction"]
                    if c["localDate"] != pos["entryDate"] and not pos["triggered"] and not pos["earlyBeTriggered"] and c["high"] >= pos["entry"] * (1 + cont.EARLY_BE_PROFIT_PCT):
                        pos["earlyBeTriggered"] = True
                        pos["earlyBeTime"] = c["localDate"]
                        pos["stop"] = pos["entry"]
                    exit_price, reason = variant_exit(pos, c, prev, variant)
            else:
                if c["high"] >= pos["stop"]:
                    exit_price = pos["stop"]
                    reason = "Breakeven stop" if (pos["triggered"] or pos["earlyBeTriggered"]) else "Stop loss"
                else:
                    if not pos["triggered"] and c["low"] <= pos["tp"]:
                        pos["triggered"] = True
                        pos["tp1Time"] = c["localDate"]
                        pos["stop"] = pos["entry"]
                        tp1_fraction = pos["tp1Fraction"]
                        pos["realizedR"] += tp1_fraction * ((pos["entry"] - pos["tp"]) / pos["risk"])
                        pos["remainingFraction"] = 1.0 - tp1_fraction
                        pos["runnerInitialFraction"] = pos["remainingFraction"]
                    if c["localDate"] != pos["entryDate"] and not pos["triggered"] and not pos["earlyBeTriggered"] and c["low"] <= pos["entry"] * (1 - cont.EARLY_BE_PROFIT_PCT):
                        pos["earlyBeTriggered"] = True
                        pos["earlyBeTime"] = c["localDate"]
                        pos["stop"] = pos["entry"]
                    exit_price, reason = variant_exit(pos, c, prev, variant)

            if exit_price is not None:
                trade = close_position(symbol, n, pos, c, exit_price, reason)
                trade["runnerVariant"] = variant["key"]
                trades.append(trade)
                if reason.startswith("Runner exit"):
                    block_short_after_losing_long = side == "LONG" and trade["rMultiple"] < 0
                    profitable_runner = trade["rMultiple"] >= cont.ANTI_REVERSAL_MIN_RUNNER_R
                    if block_short_after_losing_long or profitable_runner:
                        last_runner_exit = {"index": i, "side": side, "netR": trade["rMultiple"]}
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
        runner_exit_mode = variant["mode"]
        runner_ema = variant.get("ema")
        if variant["mode"] == "conditional_ema50":
            use_ema50 = should_use_conditional_ema50(side, (btc_by_date or {}).get(c["localDate"]), variant["condition"])
            runner_exit_mode = "ema_close" if use_ema50 else "ssl"
            runner_ema = "ema50" if use_ema50 else None
        conditional_ema50_active = False
        if variant["mode"] == "hybrid_partial_then_conditional_ema50":
            conditional_ema50_active = should_use_conditional_ema50(side, (btc_by_date or {}).get(c["localDate"]), variant["condition"])
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
            "remainingFraction": 1.0,
            "earlyBeTriggered": False,
            "earlyBeTime": "",
            "tp1Time": "",
            "realizedR": 0.0,
            "tp1Fraction": float(variant.get("tp1_fraction", 0.5)),
            "runnerInitialFraction": 1.0,
            "atr14": c["atr14"],
            "rsi14": c["rsi14"],
            "distance": dist,
            "ema20": c["ema20"],
            "ema50": c["ema50"],
            "bestHigh": entry,
            "bestLow": entry,
            "runnerExitMode": runner_exit_mode,
            "runnerEma": runner_ema,
            "runnerExitCondition": variant.get("condition", ""),
            "conditionalEma50Active": conditional_ema50_active,
            "hybridPartialHit": False,
            "hybridPartialTime": "",
            "scaleTargetsHit": [],
            "notes": "Primary NXT v3.5" if signal_type == "Primary" else cont.RULE["name"],
        }

    open_position = None
    if pos is not None:
        last = candles[-1]
        mark_r = (last["close"] - pos["entry"]) / pos["risk"] if pos["side"] == "LONG" else (pos["entry"] - last["close"]) / pos["risk"]
        open_position = {
            "symbol": symbol,
            "tradeNo": n,
            "runnerVariant": variant["key"],
            "side": pos["side"],
            "signalType": pos["signalType"],
            "signalTime": pos["signalDate"],
            "entryTime": pos["entryDate"],
            "entryPrice": pos["entry"],
            "currentMarkDate": last["localDate"],
            "currentMarkPrice": last["close"],
            "grossOpenR": pos["realizedR"] + (0.5 if pos["triggered"] else 1.0) * mark_r,
            "tp1Time": pos["tp1Time"],
            "currentStop": pos["stop"],
        }
    return trades, open_position


def add_funding(trades: list[dict], start: date, end: date) -> list[dict]:
    funding_by_symbol = {symbol: funding.fetch_monthly_funding(symbol, start, end) for symbol in SYMBOLS}
    out = []
    for trade in trades:
        row = dict(trade)
        row.update(funding.funding_for_trade(row, funding_by_symbol[row["symbol"]]))
        row["netRAfterFunding"] = row["rMultiple"] + row["fundingR"]
        out.append(row)
    return out


def stats(rows: list[dict], key: str) -> dict:
    return cont.enriched_stats([dict(row, rMultiple=row[key]) for row in rows])


def group_stats(rows: list[dict], group_key: str) -> list[dict]:
    groups: dict[str, list[dict]] = {}
    for row in rows:
        groups.setdefault(row[group_key][:4] if group_key.endswith("Time") else row[group_key], []).append(row)
    out = []
    for key, subset in sorted(groups.items()):
        st = stats(subset, "netRAfterFunding")
        st["group"] = key
        out.append(st)
    return out


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    latest_payload = json.loads(LATEST_JSON.read_text(encoding="utf-8"))
    end_date = date.fromisoformat(latest_payload["period"]["lastDataDate"])
    requested_end = date.fromisoformat(latest_payload["period"].get("requestedEnd", latest_payload["period"]["lastDataDate"]))

    datasets = {}
    for symbol in SYMBOLS:
        candles = enrich_with_ssl_period(latest.fetch_usdm_1d(symbol, requested_end), 14)
        candles = [row for row in candles if date.fromisoformat(row["localDate"]) <= end_date]
        datasets[symbol] = candles
    btc_by_date = add_btc_regime(datasets["BTCUSDT"])

    results = []
    for variant in VARIANTS:
        all_trades = []
        open_positions = []
        for symbol in SYMBOLS:
            trades, open_pos = backtest_symbol(symbol, datasets[symbol], end_date, variant, btc_by_date)
            all_trades.extend(trades)
            if open_pos:
                open_positions.append(open_pos)
        all_trades.sort(key=lambda t: (t["exitTime"], t["entryTime"], t["symbol"], t["tradeNo"]))
        funded = add_funding(all_trades, latest.START_DATE, end_date)
        original = stats(funded, "rMultiple")
        adjusted = stats(funded, "netRAfterFunding")
        curve = funding.equity_curve(funded, "netRAfterFunding")
        adjusted["maxDrawdownDollars"] = min((row["drawdown"] for row in curve), default=0.0)
        cap = funding.portfolio_cap_curve(
            funded,
            {"BTCUSDT": 0.02, "BNBUSDT": 0.02, "SOLUSDT": 0.02},
            "netRAfterFunding",
        )
        results.append(
            {
                "variant": variant,
                "originalStats": original,
                "fundingAdjustedStats": adjusted,
                "portfolioCap6Equal": {k: v for k, v in cap.items() if k != "trades"},
                "fundingSummary": {
                    "totalFundingR": sum(t["fundingR"] for t in funded),
                    "fundingEvents": sum(t["fundingEvents"] for t in funded),
                },
                "byYear": group_stats(funded, "exitTime"),
                "bySymbol": group_stats(funded, "symbol"),
                "openPositions": open_positions,
                "trades": funded,
            }
        )

    baseline = next(row for row in results if row["variant"]["key"] == "baseline_ssl_flip")
    base_stats = baseline["fundingAdjustedStats"]
    base_cap = baseline["portfolioCap6Equal"]
    for row in results:
        st = row["fundingAdjustedStats"]
        cap = row["portfolioCap6Equal"]
        row["deltaVsBaselineFundingAdjusted"] = {
            "trades": st["trades"] - base_stats["trades"],
            "totalR": st["totalR"] - base_stats["totalR"],
            "winRate": st["winRate"] - base_stats["winRate"],
            "maxDrawdownR": st["maxDrawdownR"] - base_stats["maxDrawdownR"],
            "profitFactor": (st["profitFactor"] or 0) - (base_stats["profitFactor"] or 0),
            "ending20k": st["ending20k"] - base_stats["ending20k"],
            "cap6EqualEnding": cap["endingEquity"] - base_cap["endingEquity"],
            "cap6EqualMaxDdPct": cap["maxDrawdownPct"] - base_cap["maxDrawdownPct"],
        }

    payload = {
        "generatedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "system": "NXT v3.5 USD-M latest, runner-exit variant experiment only",
        "period": latest_payload["period"],
        "symbols": SYMBOLS,
        "assumptions": [
            "Entry, stop, TP1, Early-BE, continuation, funding, and promoted block-short-after-losing-long rule are kept unchanged.",
            "Only the final runner/SSL exit logic is changed per variant.",
            "Experiment output only; latest artifacts are not changed.",
        ],
        "results": results,
    }
    OUT_JSON.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    summary = []
    for row in sorted(results, key=lambda r: r["fundingAdjustedStats"]["totalR"], reverse=True):
        st = row["fundingAdjustedStats"]
        d = row["deltaVsBaselineFundingAdjusted"]
        summary.append(
            {
                "variant": row["variant"]["key"],
                "trades": st["trades"],
                "totalR": st["totalR"],
                "deltaR": d["totalR"],
                "maxDdR": st["maxDrawdownR"],
                "profitFactor": st["profitFactor"],
                "cap6Ending": row["portfolioCap6Equal"]["endingEquity"],
                "openPositions": len(row["openPositions"]),
            }
        )
    print(json.dumps({"outJson": str(OUT_JSON), "summary": summary}, indent=2))


if __name__ == "__main__":
    main()
