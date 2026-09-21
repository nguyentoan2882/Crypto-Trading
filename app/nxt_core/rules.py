from __future__ import annotations

import hashlib
import json

from scripts import backtest_nxt31_utc7_latest as base
from scripts import test_nxt33_long_only_pullback_continuation as cont
from scripts.test_nxt33_ssl14 import enrich_with_ssl_period


ONE_R_DOLLARS = 1000.0
ANTI_REVERSAL_MIN_RUNNER_R = 0.50
TP1_FRACTION = 0.30
PARTIAL_FRACTION = 0.10
PARTIAL_AT_R = 4.0
TAIL_FRACTION = 0.60


def signal_id(signal: dict) -> str:
    return f"NXT35_USDM_BlockShortAfterLosingLong:{signal['symbol']}:{signal['signalDate']}:{signal['side']}:{signal['signalType']}"


def fmt(value: float) -> str:
    if abs(value) >= 1000:
        return f"{value:,.2f}"
    if abs(value) >= 1:
        return f"{value:.4f}"
    return f"{value:.6f}"


def side_values(side: str) -> dict:
    if side == "LONG":
        return {"entry": "BUY", "close": "SELL", "stop": "SELL", "tp": "SELL"}
    return {"entry": "SELL", "close": "BUY", "stop": "BUY", "tp": "BUY"}


def build_orders(signal: dict, one_r_dollars: float = ONE_R_DOLLARS) -> list[dict]:
    vals = side_values(signal["side"])
    qty = one_r_dollars / signal["riskPerUnit"]
    tp1_qty = qty * TP1_FRACTION
    partial_qty = qty * PARTIAL_FRACTION
    tail_qty = qty * TAIL_FRACTION
    partial_price = signal["entryPrice"] + signal["riskPerUnit"] * PARTIAL_AT_R if signal["side"] == "LONG" else signal["entryPrice"] - signal["riskPerUnit"] * PARTIAL_AT_R
    return [
        {
            "step": 1,
            "action": "OPEN_POSITION",
            "date": signal["entryDate"],
            "orderSide": vals["entry"],
            "orderType": "MARKET_OR_LIMIT_AT_OPEN",
            "quantityBase": qty,
            "price": signal["entryPrice"],
            "note": "Open full position at the next Binance daily open after the signal candle closes.",
        },
        {
            "step": 2,
            "action": "PLACE_INITIAL_STOP",
            "date": signal["entryDate"],
            "orderSide": vals["stop"],
            "orderType": "STOP_MARKET reduceOnly",
            "quantityBase": qty,
            "triggerPrice": signal["initialStop"],
            "note": "Protect full position. Stop distance is 1.5 ATR14.",
        },
        {
            "step": 3,
            "action": "PLACE_TP1",
            "date": signal["entryDate"],
            "orderSide": vals["tp"],
            "orderType": "TAKE_PROFIT_MARKET reduceOnly",
            "quantityBase": tp1_qty,
            "triggerPrice": signal["tp1"],
            "note": "Close 30% at TP1. If TP1 fills, move the remaining 70% stop to breakeven.",
        },
        {
            "step": 4,
            "action": "EARLY_BE_7PCT",
            "date": "Next daily candle after post-entry 7% favorable move",
            "orderSide": vals["stop"],
            "orderType": "STOP_MARKET reduceOnly",
            "quantityBase": qty,
            "triggerPrice": signal["entryPrice"],
            "note": "Before TP1, from the first daily candle after entry onward, if LONG High reaches Entry x 1.07 or SHORT Low reaches Entry x 0.93, move the full-position stop to entry from the next daily candle.",
        },
        {
            "step": 5,
            "action": "AFTER_TP1_MOVE_STOP_TO_BREAKEVEN",
            "date": "When TP1 fills",
            "orderSide": vals["stop"],
            "orderType": "STOP_MARKET reduceOnly",
            "quantityBase": tail_qty + partial_qty,
            "triggerPrice": signal["entryPrice"],
            "note": "Cancel initial stop and protect the runner at entry price.",
        },
        {
            "step": 6,
            "action": "PLACE_PARTIAL_TP_AT_4R",
            "date": signal["entryDate"],
            "orderSide": vals["tp"],
            "orderType": "TAKE_PROFIT_MARKET reduceOnly",
            "quantityBase": partial_qty,
            "triggerPrice": partial_price,
            "note": "Close 10% at 4R, leaving 60% as the final tail.",
        },
        {
            "step": 7,
            "action": "TAIL_EXIT_GUARD_DIRECTIONAL",
            "date": "Future daily close",
            "orderSide": vals["close"],
            "orderType": "MARKET reduceOnly",
            "quantityBase": tail_qty,
            "note": "Use EMA50 close for the 60% tail only when BTC was strongly aligned on the signal candle; otherwise exit the tail on an opposite SSL flip.",
        },
    ]


def ema(values: list[float], period: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    if len(values) < period:
        return out
    previous = sum(values[:period]) / period
    out[period - 1] = previous
    alpha = 2 / (period + 1)
    for index in range(period, len(values)):
        previous = values[index] * alpha + previous * (1 - alpha)
        out[index] = previous
    return out


def btc_regime_by_date(candles: list[dict]) -> dict[str, dict]:
    rows = enrich_with_ssl_period(candles, 14)
    ema200 = ema([row["close"] for row in rows], 200)
    result = {}
    for index, row in enumerate(rows):
        indicators_ready = ema200[index] is not None and row.get("ema20") is not None and row.get("ema50") is not None
        result[row["localDate"]] = {
            "bull": indicators_ready and row["close"] > ema200[index] and row["close"] > row["ema50"] and row["ema20"] > row["ema50"],
            "bear": indicators_ready and row["close"] < ema200[index] and row["close"] < row["ema50"] and row["ema20"] < row["ema50"],
        }
    return result


def latest_signal_for_symbol(
    symbol: str,
    candles: list[dict],
    btc_regime: dict[str, dict],
    *,
    detected_at: str,
    one_r_dollars: float = ONE_R_DOLLARS,
) -> dict | None:
    candles = enrich_with_ssl_period(candles, 14)
    pos = None
    last_profitable_runner_exit = None
    last_losing_long_ssl_exit = None
    latest_signal = None

    for i in range(55, len(candles) - 1):
        c, prev, nxt = candles[i], candles[i - 1], candles[i + 1]
        if not c.get("closed"):
            continue

        if pos:
            side = pos["side"]
            ssl_flip = (side == "LONG" and prev["ssl"] == 1 and c["ssl"] == -1) or (
                side == "SHORT" and prev["ssl"] == -1 and c["ssl"] == 1
            )
            can_trigger_early_be = c["localDate"] != pos["entryDate"]
            exit_price = reason = None
            if side == "LONG":
                if c["low"] <= pos["stop"]:
                    exit_price = pos["stop"]
                    reason = "Breakeven stop" if (pos["triggered"] or pos["earlyBeTriggered"]) else "Stop loss"
                else:
                    if not pos["triggered"] and c["high"] >= pos["tp"]:
                        pos["triggered"] = True
                        pos["stop"] = pos["entry"]
                        pos["realizedR"] += TP1_FRACTION * ((pos["tp"] - pos["entry"]) / pos["risk"])
                    if pos["triggered"] and not pos["partialTaken"] and c["high"] >= pos["partialTarget"]:
                        pos["partialTaken"] = True
                        pos["realizedR"] += PARTIAL_FRACTION * PARTIAL_AT_R
                    if can_trigger_early_be and not pos["triggered"] and not pos["earlyBeTriggered"] and c["high"] >= pos["entry"] * 1.07:
                        pos["earlyBeTriggered"] = True
                        pos["stop"] = pos["entry"]
                    if pos["triggered"] and pos["emaTail"] and c["close"] < c["ema50"]:
                        exit_price, reason = c["close"], "Runner exit: close below EMA50"
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
                        pos["stop"] = pos["entry"]
                        pos["realizedR"] += TP1_FRACTION * ((pos["entry"] - pos["tp"]) / pos["risk"])
                    if pos["triggered"] and not pos["partialTaken"] and c["low"] <= pos["partialTarget"]:
                        pos["partialTaken"] = True
                        pos["realizedR"] += PARTIAL_FRACTION * PARTIAL_AT_R
                    if can_trigger_early_be and not pos["triggered"] and not pos["earlyBeTriggered"] and c["low"] <= pos["entry"] * 0.93:
                        pos["earlyBeTriggered"] = True
                        pos["stop"] = pos["entry"]
                    if pos["triggered"] and pos["emaTail"] and c["close"] > c["ema50"]:
                        exit_price, reason = c["close"], "Runner exit: close above EMA50"
                    elif ssl_flip:
                        exit_price = c["close"]
                        reason = "Runner exit: SSL bullish flip"
            if exit_price is not None:
                rem = (TAIL_FRACTION if pos["partialTaken"] else (TAIL_FRACTION + PARTIAL_FRACTION)) if pos["triggered"] else 1.0
                rem_r = (exit_price - pos["entry"]) / pos["risk"] if side == "LONG" else (pos["entry"] - exit_price) / pos["risk"]
                net = pos["realizedR"] + rem * rem_r - base.cost_r(pos["entry"], pos["risk"])
                if net >= ANTI_REVERSAL_MIN_RUNNER_R and str(reason).startswith("Runner exit"):
                    last_profitable_runner_exit = {"index": i, "side": side, "netR": net}
                if side == "LONG" and not pos["triggered"] and reason == "Runner exit: SSL bearish flip" and net < 0:
                    last_losing_long_ssl_exit = {"index": i, "netR": net}
                pos = None
            if pos:
                continue

        if any(c[k] is None for k in ["ema20", "ema50", "atr14", "rsi14", "ssl"]) or prev["ssl"] is None:
            continue
        dist = abs(c["close"] - c["ema50"]) / c["atr14"]
        long_primary = prev["ssl"] == -1 and c["ssl"] == 1 and base.recent_cross(candles, i, "LONG") and dist <= 2 and c["rsi14"] > 50
        short_primary = prev["ssl"] == 1 and c["ssl"] == -1 and base.recent_cross(candles, i, "SHORT") and dist <= 2 and c["rsi14"] < 50
        long_cont = prev["ssl"] == -1 and c["ssl"] == 1 and c["close"] > c["ema20"] > c["ema50"] and cont.touch_reclaim_long(candles, i, cont.RULE["touchLookback"])
        if last_profitable_runner_exit and i - last_profitable_runner_exit["index"] <= 1:
            if (long_primary or long_cont) and last_profitable_runner_exit["side"] == "SHORT":
                long_primary = long_cont = False
            if short_primary and last_profitable_runner_exit["side"] == "LONG":
                short_primary = False
        if last_losing_long_ssl_exit and i - last_losing_long_ssl_exit["index"] <= 1:
            short_primary = False
        if not (long_primary or short_primary or long_cont):
            continue

        side = "LONG" if (long_primary or long_cont) else "SHORT"
        signal_type = "Continuation" if long_cont and not long_primary else "Primary"
        risk = c["atr14"] * 1.5
        entry = nxt["open"]
        latest_signal = {
            "symbol": symbol,
            "side": side,
            "signalType": signal_type,
            "signalDate": c["localDate"],
            "entryDate": nxt["localDate"],
            "entryPrice": entry,
            "initialStop": entry - risk if side == "LONG" else entry + risk,
            "riskPerUnit": risk,
            "tp1": entry + c["atr14"] * 2.5 if side == "LONG" else entry - c["atr14"] * 2.5,
            "atr14": c["atr14"],
            "rsi14": c["rsi14"],
            "ema20": c["ema20"],
            "ema50": c["ema50"],
            "distanceToEma50Atr": dist,
            "latestClosedDate": c["localDate"],
            "detectedAt": detected_at,
            "btcDirectionalGuard": bool((side == "LONG" and btc_regime.get(c["localDate"], {}).get("bull")) or (side == "SHORT" and btc_regime.get(c["localDate"], {}).get("bear"))),
        }
        pos = {
            "side": side,
            "entryDate": latest_signal["entryDate"],
            "entry": entry,
            "stop": latest_signal["initialStop"],
            "risk": risk,
            "tp": latest_signal["tp1"],
            "triggered": False,
            "partialTaken": False,
            "partialTarget": entry + risk * PARTIAL_AT_R if side == "LONG" else entry - risk * PARTIAL_AT_R,
            "emaTail": latest_signal["btcDirectionalGuard"],
            "earlyBeTriggered": False,
            "realizedR": 0.0,
        }

    latest_closed = next((c for c in reversed(candles) if c.get("closed")), None)
    if latest_signal and latest_closed and latest_signal["signalDate"] == latest_closed["localDate"]:
        latest_signal["id"] = signal_id(latest_signal)
        latest_signal["orders"] = build_orders(latest_signal, one_r_dollars)
        return latest_signal
    return None


def _followup_result(
    subject: dict,
    candle_date: str,
    action: str,
    action_label: str,
    priority: int,
    rationale: str,
    evidence: dict,
    state: dict,
    status: str = "Pending",
) -> dict:
    state_payload = {
        "signalId": subject["signal_id"],
        "positionId": subject.get("position_id"),
        "candleDate": candle_date,
        "action": action,
        "state": state,
        "evidence": evidence,
    }
    state_version = hashlib.sha256(json.dumps(state_payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()
    recommendation_id = f"followup:{subject['signal_id']}:{candle_date}:{action}:{state_version[:16]}"
    signal = subject["signal"]
    return {
        "recommendationId": recommendation_id,
        "signalId": subject["signal_id"],
        "positionId": subject.get("position_id"),
        "subjectType": "POSITION" if subject.get("position_id") else "SIGNAL",
        "trackingStatus": "Tracked Position" if subject.get("position_id") else "Accepted - chua Track Position",
        "theoretical": not bool(subject.get("position_id")),
        "symbol": signal["symbol"],
        "side": signal["side"],
        "signalType": signal.get("signalType", ""),
        "candleDate": candle_date,
        "action": action,
        "actionLabel": action_label,
        "priority": priority,
        "status": status,
        "rationale": rationale,
        "evidence": evidence,
        "state": state,
        "stateVersion": state_version,
        "entryPrice": state.get("entry"),
        "currentStop": state.get("stop"),
        "tp1": state.get("tp1"),
        "quantity": state.get("quantity"),
        "recommendationOnly": True,
    }


def evaluate_accepted_signal_followup(
    subject: dict,
    candles: list[dict],
    *,
    evaluation_date: str,
) -> dict:
    """Evaluate one Accepted signal without creating or mutating a position."""
    signal = subject["signal"]
    position = subject.get("position")
    closed = [row for row in candles if row.get("closed")]
    if not closed:
        return _followup_result(
            subject,
            evaluation_date,
            "DATA_STALE",
            "KHONG THE DANH GIA - DATA STALE",
            0,
            "Khong co Binance USD-M D1 candle da dong de danh gia follow-up.",
            {},
            {"entry": signal.get("entryPrice"), "stop": signal.get("initialStop"), "tp1": signal.get("tp1")},
        )

    rows = enrich_with_ssl_period(candles, 14) if any("ssl" not in row for row in closed) else candles
    closed = [row for row in rows if row.get("closed")]
    latest = closed[-1]
    entry_date = str(position.get("entryTime") if position else signal.get("entryDate", ""))[:10]
    entry = float(position.get("entryPrice") if position else signal["entryPrice"])
    stop = float(position.get("currentSl") if position and position.get("currentSl") is not None else signal["initialStop"])
    tp1 = float(position.get("currentTp1") if position and position.get("currentTp1") is not None else signal["tp1"])
    quantity = float(position.get("quantity") or 0) if position else float(subject.get("plan", {}).get("sizing", {}).get("quantityBase") or 0)
    risk = abs(entry - float(signal["initialStop"]))
    state = {
        "entry": entry,
        "stop": stop,
        "tp1": tp1,
        "quantity": quantity,
        "tp1Hit": False,
        "partial4RHit": False,
        "earlyBeTriggered": False,
        "active": True,
    }
    if risk <= 0:
        return _followup_result(
            subject,
            latest["localDate"],
            "NEEDS_REVIEW",
            "NEEDS REVIEW - KIEM TRA ENTRY/SL",
            0,
            "Entry va initial stop khong tao duoc riskPerUnit duong.",
            {},
            state,
        )

    latest_action = None
    last_historical_action = None
    previous = None
    for row in closed:
        if row["localDate"] < entry_date:
            previous = row
            continue
        if not state["active"]:
            break
        side = signal["side"]
        stop_hit = row["low"] <= state["stop"] if side == "LONG" else row["high"] >= state["stop"]
        tp1_hit = row["high"] >= tp1 if side == "LONG" else row["low"] <= tp1
        partial_target = entry + risk * PARTIAL_AT_R if side == "LONG" else entry - risk * PARTIAL_AT_R
        partial_hit = row["high"] >= partial_target if side == "LONG" else row["low"] <= partial_target
        favorable_7pct = row["high"] >= entry * 1.07 if side == "LONG" else row["low"] <= entry * 0.93
        ssl_flip = bool(
            previous
            and previous.get("ssl") is not None
            and row.get("ssl") is not None
            and ((side == "LONG" and previous["ssl"] == 1 and row["ssl"] == -1) or (side == "SHORT" and previous["ssl"] == -1 and row["ssl"] == 1))
        )
        action = None
        if stop_hit:
            action = (
                "BE_STOP" if state["tp1Hit"] or state["earlyBeTriggered"] else "STOP_LOSS",
                "XAC NHAN VI THE DA CHAM BE STOP" if state["tp1Hit"] or state["earlyBeTriggered"] else "XAC NHAN VI THE DA CHAM STOP LOSS",
                1,
                f"Latest D1 range da cham stop {state['stop']}.",
                {"low": row["low"], "high": row["high"], "stop": state["stop"]},
            )
            state["active"] = False
        else:
            if not state["tp1Hit"] and tp1_hit:
                state["tp1Hit"] = True
                state["stop"] = entry
                action = (
                    "TAKE_TP1_30_MOVE_BE",
                    "CHOT TP1 30% VA MOVE SL 70% CON LAI VE BE SAU KHI XAC NHAN",
                    2,
                    f"Latest D1 range da cham TP1 {tp1}.",
                    {"low": row["low"], "high": row["high"], "tp1": tp1, "breakeven": entry},
                )
            elif state["tp1Hit"] and not state["partial4RHit"] and partial_hit:
                state["partial4RHit"] = True
                action = (
                    "TAKE_4R_PARTIAL_10",
                    "CHOT THEM 10% TAI 4R",
                    3,
                    f"Latest D1 range da cham muc 4R {partial_target}.",
                    {"low": row["low"], "high": row["high"], "target4R": partial_target},
                )
            elif row["localDate"] != entry_date and not state["tp1Hit"] and not state["earlyBeTriggered"] and favorable_7pct:
                state["earlyBeTriggered"] = True
                state["stop"] = entry
                action = (
                    "MOVE_STOP_TO_BE",
                    "MOVE STOP VE BREAKEVEN TU NEN D1 KE TIEP",
                    4,
                    "Bien dong thuan chieu 7% truoc TP1 da kich hoat Early-BE.",
                    {"low": row["low"], "high": row["high"], "breakeven": entry},
                )

            if action is None and state["tp1Hit"] and signal.get("btcDirectionalGuard") and row.get("ema50") is not None:
                ema_exit = row["close"] < row["ema50"] if side == "LONG" else row["close"] > row["ema50"]
                if ema_exit:
                    action = (
                        "TAIL_EXIT_EMA50",
                        "THOAT PHAN TAIL THEO EMA50",
                        5,
                        "Guard Directional dang dung EMA50 va latest close da vi pham EMA50.",
                        {"close": row["close"], "ema50": row["ema50"]},
                    )
                    state["active"] = False
            if action is None and ssl_flip:
                action = (
                    "TAIL_EXIT_SSL",
                    "THOAT VI THE CON LAI THEO OPPOSITE SSL FLIP",
                    6,
                    "Latest closed candle xac nhan opposite SSL flip.",
                    {"close": row["close"], "ssl": row.get("ssl"), "previousSsl": previous.get("ssl") if previous else None},
                )
                state["active"] = False

        if row["localDate"] == latest["localDate"] and action:
            latest_action = action
        elif action and action[0] not in set(subject.get("acknowledgedActions", [])):
            last_historical_action = action
        previous = row

    pending = subject.get("pendingFollowup")
    if pending and (latest_action is None or int(pending["priority"]) < int(latest_action[2])):
        original = pending["payload"]
        return _followup_result(
            subject,
            latest["localDate"],
            "PENDING_CONFIRMATION",
            f"ACTION CHUA XAC NHAN: {original.get('actionLabel', pending['action_label'])}",
            int(pending["priority"]),
            f"Recommendation {pending['recommendation_id']} van dang cho nguoi dung xac nhan.",
            {"pendingRecommendationId": pending["recommendation_id"], "originalAction": pending["action"]},
            state,
            status="Reminder",
        )
    if latest_action:
        return _followup_result(subject, latest["localDate"], *latest_action, state=state)
    if last_historical_action:
        action, label, priority, rationale, evidence = last_historical_action
        return _followup_result(
            subject,
            latest["localDate"],
            action,
            f"ACTION CAN XAC NHAN (CATCH-UP): {label}",
            priority,
            f"Monitor phat hien action lich su chua co outcome trong he thong. {rationale}",
            evidence,
            state,
        )
    return _followup_result(
        subject,
        latest["localDate"],
        "NO_ACTION",
        "KHONG CAN THAO TAC",
        99,
        "Latest closed D1 candle khong kich hoat TP1, SL, BE, 4R partial hoac tail exit moi.",
        {"close": latest["close"], "low": latest["low"], "high": latest["high"]},
        state,
        status="Informational",
    )
