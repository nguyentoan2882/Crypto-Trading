from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(SCRIPTS))

import backtest_nxt31_utc7_latest as base
import backtest_nxt32_native_1d_latest as native
import test_nxt33_long_only_pullback_continuation as cont
from test_nxt33_ssl14 import enrich_with_ssl_period
from nxt_usdm_binance_1d_data import fetch_usdm_1d
from app import nxt_mvp_store as store


APP_DIR = ROOT / "outputs" / "nxt_signal_app"
HISTORY_PATH = APP_DIR / "signals_history.json"
SCAN_PATH = APP_DIR / "last_scan.json"
SYSTEM_NAME = "NXT v3.5 Portfolio BTC+BNB+SOL + Guard directional 30/10@4R/60 + Binance USD-M 1D + SSL14 + Early-BE 7%"
SYMBOLS = ["BTCUSDT", "BNBUSDT", "SOLUSDT"]
WARMUP_DATE = native.WARMUP_DATE
ONE_R_DOLLARS = float(os.environ.get("NXT_ONE_R_DOLLARS", "1000"))
ANTI_REVERSAL_MIN_RUNNER_R = 0.50
TP1_FRACTION = 0.30
PARTIAL_FRACTION = 0.10
PARTIAL_AT_R = 4.0
TAIL_FRACTION = 0.60


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def date_label(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, timezone.utc).date().isoformat()


def ms_at_utc_midnight(d: date) -> int:
    return int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp() * 1000)


def http_json(url: str, data: dict | None = None) -> object:
    headers = {"User-Agent": "nxt-signal-app/1.0"}
    encoded = urllib.parse.urlencode(data).encode("utf-8") if data is not None else None
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, data=encoded, headers=headers), timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, ConnectionResetError) as exc:
            last_error = exc
            time.sleep(1 + attempt * 2)
    raise RuntimeError(f"HTTP request failed after retries: {url}") from last_error


def fetch_daily_candles(symbol: str) -> list[dict]:
    return fetch_usdm_1d(symbol, WARMUP_DATE)


def load_json(path: Path, default: object) -> object:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


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


def build_orders(signal: dict) -> list[dict]:
    vals = side_values(signal["side"])
    qty = ONE_R_DOLLARS / signal["riskPerUnit"]
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


def latest_signal_for_symbol(symbol: str, candles: list[dict], btc_regime: dict[str, dict]) -> dict | None:
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
            "detectedAt": utc_now(),
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
        latest_signal["orders"] = build_orders(latest_signal)
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


def evaluate_accepted_signal_followup(subject: dict, candles: list[dict]) -> dict:
    """Evaluate one Accepted signal without creating or mutating a position."""
    signal = subject["signal"]
    position = subject.get("position")
    closed = [row for row in candles if row.get("closed")]
    if not closed:
        return _followup_result(
            subject,
            datetime.now(timezone.utc).date().isoformat(),
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


def evaluate_accepted_followups(candle_sets: dict[str, list[dict]]) -> list[dict]:
    results = []
    for subject in store.accepted_monitor_subjects():
        candles = candle_sets.get(subject["symbol"], [])
        results.append(evaluate_accepted_signal_followup(subject, candles))
    store.persist_followup_recommendations(results)
    return results


def scan_and_persist() -> dict:
    started_at = utc_now()
    history = load_json(HISTORY_PATH, [])
    existing = {item["id"] for item in history if isinstance(item, dict) and "id" in item}
    alerts = []
    checked = []
    errors = []
    candle_sets = {}
    for symbol in SYMBOLS:
        try:
            candles = fetch_daily_candles(symbol)
            candle_sets[symbol] = candles
            checked.append({"symbol": symbol, "candles": len(candles), "latestDate": candles[-1]["localDate"] if candles else ""})
        except Exception as exc:
            errors.append({"symbol": symbol, "error": str(exc)})
    btc_regime = btc_regime_by_date(candle_sets["BTCUSDT"]) if "BTCUSDT" in candle_sets else {}
    for symbol, candles in candle_sets.items():
        try:
            signal = latest_signal_for_symbol(symbol, candles, btc_regime)
            if signal and signal["id"] not in existing:
                alerts.append(signal)
                history.append(signal)
                existing.add(signal["id"])
        except Exception as exc:
            errors.append({"symbol": symbol, "error": str(exc)})

    history.sort(key=lambda item: (item["signalDate"], item["symbol"], item["side"]), reverse=True)
    save_json(HISTORY_PATH, history)
    result = {
        "systemName": SYSTEM_NAME,
        "scannedAt": utc_now(),
        "symbols": SYMBOLS,
        "checked": checked,
        "newSignals": alerts,
        "errors": errors,
        "historyCount": len(history),
    }
    store.persist_scan_result(result, started_at=started_at)
    try:
        result["followUps"] = evaluate_accepted_followups(candle_sets)
    except Exception as exc:
        result["followUps"] = []
        result["errors"].append({"symbol": "MONITOR", "error": f"Accepted-signal follow-up failed: {exc}"})
    save_json(SCAN_PATH, result)
    return result


def read_form(handler: BaseHTTPRequestHandler) -> dict[str, str]:
    length = int(handler.headers.get("Content-Length", "0") or 0)
    raw = handler.rfile.read(length).decode("utf-8") if length else ""
    parsed = urllib.parse.parse_qs(raw)
    return {key: values[0] for key, values in parsed.items() if values}


def money(value: float | int | None) -> str:
    if value is None:
        return "-"
    return f"${float(value):,.2f}"


def render_signal_rows(signals: list[dict]) -> str:
    if not signals:
        return "<tr><td colspan='8' class='muted'>Chua co tin hieu trong SQLite.</td></tr>"
    rows = []
    for row in signals:
        signal = row["payload"]
        plan = row.get("plan", {})
        sizing = plan.get("sizing", {})
        rows.append(
            f"""
            <tr>
              <td><b>{html.escape(row['symbol'])}</b><br><span class="muted">{html.escape(row['signal_date'])}</span></td>
              <td>{html.escape(row['side'])}<br><span class="muted">{html.escape(row['signal_type'])}</span></td>
              <td>{fmt(float(signal['entryPrice']))}<br><span class="muted">SL {fmt(float(signal['initialStop']))}</span></td>
              <td>{fmt(float(signal['tp1']))}</td>
              <td>{html.escape(row.get('plan_status') or 'Needs Review')}<br><span class="muted">Qty {fmt(float(sizing.get('quantityBase', 0))) if sizing else '-'}</span></td>
              <td>{html.escape(row.get('latest_decision') or 'Pending')}</td>
              <td>
                <form method="post" action="/decision" class="inline">
                  <input type="hidden" name="signal_id" value="{html.escape(row['signal_id'])}">
                  <button name="decision" value="Accept" title="Accept signal">Accept</button>
                  <button name="decision" value="Watchlist" class="secondary" title="Watchlist">Watch</button>
                  <button name="decision" value="Reject" class="danger" title="Reject signal">Reject</button>
                </form>
                <form method="post" action="/track-position" class="inline">
                  <input type="hidden" name="signal_id" value="{html.escape(row['signal_id'])}">
                  <input name="quantity" value="{html.escape(str(round(float(sizing.get('quantityBase', 0)), 6))) if sizing else ''}" placeholder="qty">
                  <button class="secondary" title="Track manual position">Track</button>
                </form>
              </td>
              <td class="idcell">{html.escape(row['signal_id'])}</td>
            </tr>
            """
        )
    return "\n".join(rows)


def render_history_cards(history: list[dict]) -> str:
    cards = []
    for signal in history[:20]:
        orders = "".join(
            f"<tr><td>{o['step']}</td><td>{html.escape(o['action'])}</td><td>{html.escape(str(o['orderSide']))}</td>"
            f"<td>{html.escape(str(o['orderType']))}</td><td>{fmt(float(o.get('quantityBase', 0))) if o.get('quantityBase') else ''}</td>"
            f"<td>{fmt(float(o.get('price') or o.get('triggerPrice'))) if (o.get('price') or o.get('triggerPrice')) else ''}</td>"
            f"<td>{html.escape(o['note'])}</td></tr>"
            for o in signal.get("orders", [])
        )
        cards.append(
            f"""
            <section class="signal">
              <div class="signal-head">
                <div>
                  <h2>{html.escape(signal['symbol'])} {html.escape(signal['side'])}</h2>
                  <p>{html.escape(signal['signalType'])} | Signal {html.escape(signal['signalDate'])} | Entry {html.escape(signal['entryDate'])}</p>
                </div>
                <span>{html.escape(signal['id'])}</span>
              </div>
              <div class="metrics">
                <b>Entry {fmt(signal['entryPrice'])}</b>
                <b>Stop {fmt(signal['initialStop'])}</b>
                <b>TP1 {fmt(signal['tp1'])}</b>
                <b>ATR {fmt(signal['atr14'])}</b>
                <b>RSI {signal['rsi14']:.2f}</b>
              </div>
              <div class="orders">
                <table>
                  <thead><tr><th>#</th><th>Action</th><th>Side</th><th>Type</th><th>Qty</th><th>Price</th><th>Note</th></tr></thead>
                  <tbody>{orders}</tbody>
                </table>
              </div>
            </section>
            """
        )
    return "\n".join(cards) if cards else "<div class='empty'>Chua co tin hieu nao duoc luu trong JSON history.</div>"


def render_positions(positions: list[dict], recommendations: list[dict]) -> str:
    if not positions:
        return "<tr><td colspan='7' class='muted'>Chua co vi the thu cong nao dang duoc track.</td></tr>"
    latest_rec = {}
    for rec in recommendations:
        latest_rec.setdefault(rec["position_id"], rec)
    rows = []
    for pos in positions:
        rec = latest_rec.get(pos["position_id"])
        rows.append(
            f"""
            <tr>
              <td><b>{html.escape(pos['symbol'])}</b><br><span class="muted">{html.escape(pos['position_id'])}</span></td>
              <td>{html.escape(pos['side'])}</td>
              <td>{fmt(float(pos['entry_price']))}</td>
              <td>{fmt(float(pos['quantity']))}</td>
              <td>{html.escape(pos['lifecycle'])}</td>
              <td>{html.escape(rec['action']) if rec else '-'}</td>
              <td>{html.escape(rec['rationale']) if rec else '-'}</td>
            </tr>
            """
        )
    return "\n".join(rows)


def render_followups(items: list[dict]) -> str:
    if not items:
        return "<tr><td colspan='7' class='muted'>Chua co Accepted-signal follow-up recommendation.</td></tr>"
    rows = []
    for item in items:
        payload = json.loads(item.get("payload_json") or "{}")
        tracking = payload.get("trackingStatus", item.get("subject_type", ""))
        action = item.get("action_label") or item.get("action", "")
        outcome = item.get("outcome") or item.get("status", "")
        actions = ""
        if item.get("status") == "Pending":
            buttons = []
            for value, label in (("Applied", "Applied"), ("Not Applied", "Not Applied"), ("Snoozed", "Snooze"), ("Already Closed", "Closed")):
                buttons.append(
                    f'<button name="outcome" value="{html.escape(value)}" class="secondary">{html.escape(label)}</button>'
                )
            actions = (
                '<form method="post" action="/followup-outcome" class="inline">'
                f'<input type="hidden" name="recommendation_id" value="{html.escape(item["recommendation_id"])}">'
                + "".join(buttons)
                + "</form>"
            )
        rows.append(
            f"""
            <tr>
              <td><b>{html.escape(str(payload.get('symbol', '-')))}</b><br><span class="muted">{html.escape(str(item['candle_date']))}</span></td>
              <td>{html.escape(str(tracking))}</td>
              <td><b>{html.escape(str(action))}</b></td>
              <td>{html.escape(str(item.get('rationale', '')))}</td>
              <td>{html.escape(str(outcome))}</td>
              <td>{html.escape(str(item.get('notified_at') or '-'))}</td>
              <td>{actions}</td>
            </tr>
            """
        )
    return "\n".join(rows)


def legacy_page() -> str:
    last_scan = load_json(SCAN_PATH, {})
    history = load_json(HISTORY_PATH, [])
    store.import_legacy_history(history, SYSTEM_NAME)
    state = store.dashboard_state()
    equity = state.get("currentEquity")
    settings = state.get("settings", {})
    new_count = len(last_scan.get("newSignals", [])) if isinstance(last_scan, dict) else 0
    scanned_at = last_scan.get("scannedAt", "Never") if isinstance(last_scan, dict) else "Never"
    return f"""<!doctype html>
<html lang="vi">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>NXT Signal App</title>
  <style>
    :root {{ color-scheme: light; --ink:#17202a; --muted:#667085; --line:#d7dde5; --bg:#f6f8fa; --panel:#ffffff; --accent:#0f766e; --danger:#b42318; }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; font-family: Arial, sans-serif; background: var(--bg); color: var(--ink); }}
    header {{ background: #ffffff; border-bottom: 1px solid var(--line); padding: 18px 28px; position: sticky; top: 0; z-index: 2; }}
    h1 {{ margin: 0 0 6px; font-size: 22px; }}
    p {{ margin: 0; color: var(--muted); }}
    main {{ max-width: 1220px; margin: 0 auto; padding: 22px; }}
    .toolbar {{ display: flex; gap: 12px; align-items: center; justify-content: space-between; margin-bottom: 18px; flex-wrap: wrap; }}
    .status {{ display: flex; gap: 10px; flex-wrap: wrap; color: var(--muted); }}
    .pill {{ background: #e8f3f1; color: #0f5f58; padding: 7px 10px; border-radius: 4px; font-weight: 700; }}
    button {{ background: var(--accent); color: #fff; border: 0; border-radius: 4px; padding: 10px 14px; font-weight: 700; cursor: pointer; }}
    button.secondary {{ background:#475467; }} button.danger {{ background:var(--danger); }}
    input, select {{ border:1px solid var(--line); border-radius:4px; padding:9px; min-width:90px; }}
    .grid {{ display:grid; grid-template-columns: 1fr 1fr; gap:16px; margin-bottom:16px; }}
    .panel {{ background:#fff; border:1px solid var(--line); border-radius:6px; padding:16px; }}
    .panel h2 {{ margin-bottom:12px; }}
    .form-row {{ display:flex; gap:8px; flex-wrap:wrap; align-items:end; }}
    .kv {{ display:grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap:8px; }}
    .kv div {{ background:#f8fafc; border:1px solid var(--line); border-radius:4px; padding:10px; }}
    .kv span, .muted {{ color:var(--muted); font-size:12px; }}
    .inline {{ display:flex; gap:6px; flex-wrap:wrap; margin:4px 0; }}
    .inline button {{ padding:7px 9px; }} .inline input {{ padding:7px; width:92px; min-width:92px; }}
    .idcell {{ max-width:280px; overflow-wrap:anywhere; color:var(--muted); font-size:12px; }}
    .signal {{ background: var(--panel); border: 1px solid var(--line); border-radius: 6px; padding: 16px; margin-bottom: 16px; }}
    .signal-head {{ display: flex; justify-content: space-between; gap: 12px; align-items: start; }}
    h2 {{ margin: 0 0 4px; font-size: 18px; }}
    .signal-head span {{ color: var(--muted); font-size: 12px; overflow-wrap: anywhere; text-align: right; }}
    .metrics {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap: 8px; margin: 14px 0; }}
    .metrics b {{ background: #f1f5f9; padding: 9px; border-radius: 4px; font-size: 13px; }}
    .orders {{ width: 100%; overflow-x: auto; }}
    table {{ width: 100%; min-width: 980px; border-collapse: collapse; font-size: 13px; }}
    th, td {{ border-top: 1px solid var(--line); padding: 8px; text-align: left; vertical-align: top; }}
    th {{ color: #344054; background: #f8fafc; }}
    .empty {{ background: #fff; border: 1px solid var(--line); padding: 28px; border-radius: 6px; color: var(--muted); }}
    @media (max-width: 900px) {{ .grid {{ grid-template-columns:1fr; }} }}
    @media (max-width: 760px) {{ header {{ padding: 14px; }} main {{ padding: 14px; }} .signal-head {{ display:block; }} }}
  </style>
</head>
<body>
  <header>
    <h1>NXT Signal App</h1>
    <p>{html.escape(SYSTEM_NAME)}</p>
  </header>
  <main>
    <div class="toolbar">
      <form method="post" action="/scan"><button type="submit">Quet Binance</button></form>
      <div class="status">
        <span class="pill">BTC / BNB / SOL</span>
        <span>Lan quet gan nhat: {html.escape(scanned_at)}</span>
        <span>Tin hieu moi: {new_count}</span>
        <span>Lich su: {len(history)}</span>
      </div>
    </div>
    <div class="grid">
      <section class="panel">
        <h2>Equity & Risk</h2>
        <div class="kv">
          <div><span>Current Equity</span><br><b>{money(equity.get('new_equity') if equity else None)}</b></div>
          <div><span>Risk per trade</span><br><b>{html.escape(str(settings.get('risk_pct', '-')))}%</b></div>
          <div><span>Leverage ref</span><br><b>{html.escape(str(settings.get('leverage', '-')))}x</b></div>
          <div><span>Portfolio cap</span><br><b>{html.escape(str(settings.get('portfolio_cap_pct', '-')))}%</b></div>
        </div>
        <form method="post" action="/equity" class="form-row" style="margin-top:12px">
          <input name="equity" placeholder="Equity USD" value="{html.escape(str(equity.get('new_equity'))) if equity else ''}">
          <input name="risk_pct" placeholder="Risk %" value="{html.escape(str(settings.get('risk_pct', 2)))}">
          <input name="leverage" placeholder="Leverage" value="{html.escape(str(settings.get('leverage', 1)))}">
          <input name="portfolio_cap_pct" placeholder="Cap %" value="{html.escape(str(settings.get('portfolio_cap_pct', 0)))}">
          <input name="reason" placeholder="Reason" value="Manual update">
          <button>Save</button>
        </form>
      </section>
      <section class="panel">
        <h2>MVP1 Boundaries</h2>
        <div class="kv">
          <div><span>Mode</span><br><b>Recommendation-only</b></div>
          <div><span>Exchange access</span><br><b>Public USD-M 1D</b></div>
          <div><span>Storage</span><br><b>SQLite WAL + JSON history</b></div>
          <div><span>Rule lock</span><br><b>NXT v3.5 legacy entry</b></div>
        </div>
      </section>
    </div>
    <section class="panel">
      <h2>Signals, Decisions & Sizing</h2>
      <div class="orders">
        <table>
          <thead><tr><th>Symbol</th><th>Side</th><th>Entry / Stop</th><th>TP1</th><th>Plan</th><th>Decision</th><th>Action</th><th>Signal ID</th></tr></thead>
          <tbody>{render_signal_rows(state['signals'])}</tbody>
        </table>
      </div>
    </section>
    <section class="panel">
      <h2>Manual Positions & Recommendations</h2>
      <div class="orders">
        <table>
          <thead><tr><th>Position</th><th>Side</th><th>Entry</th><th>Qty</th><th>Status</th><th>Recommendation</th><th>Rationale</th></tr></thead>
          <tbody>{render_positions(state['positions'], state['recommendations'])}</tbody>
        </table>
      </div>
    </section>
    <section class="panel">
      <h2>Accepted Signal Daily Follow-up</h2>
      <div class="orders">
        <table>
          <thead><tr><th>Signal</th><th>Tracking</th><th>Action</th><th>Rationale</th><th>Status</th><th>Notified</th><th>Confirm</th></tr></thead>
          <tbody>{render_followups(state['followupRecommendations'])}</tbody>
        </table>
      </div>
    </section>
    <h2 style="margin:18px 0 10px">JSON Signal History</h2>
    {render_history_cards(history)}
  </main>
</body>
</html>"""


def render_dashboard_signals(signals: list[dict]) -> str:
    if not signals:
        return "<tr><td colspan='7' class='empty-cell'>Chưa có tín hiệu được lưu.</td></tr>"
    rows = []
    for row in signals[:5]:
        signal = row["payload"]
        plan = row.get("plan", {})
        sizing = plan.get("sizing", {})
        side = row["side"]
        side_class = "long" if side == "LONG" else "short"
        decision = row.get("latest_decision") or "Pending"
        decision_class = decision.lower().replace(" ", "-")
        partial_4r = float(signal["entryPrice"]) + float(signal["riskPerUnit"]) * 4
        if side == "SHORT":
            partial_4r = float(signal["entryPrice"]) - float(signal["riskPerUnit"]) * 4
        rows.append(
            f"""<tr>
              <td><b>{html.escape(row['symbol'])}</b><br><span class="table-note">D1 · {html.escape(row['signal_date'])}</span></td>
              <td><span class="side {side_class}">{html.escape(side)}</span><br><span class="table-note">{html.escape(row['signal_type'])}</span></td>
              <td><b>{fmt(float(signal['entryPrice']))}</b><br><span class="table-note">Stop {fmt(float(signal['initialStop']))}</span></td>
              <td>{fmt(float(signal['tp1']))}<br><span class="table-note">4R {fmt(partial_4r)}</span></td>
              <td><span class="plan-status">{html.escape(row.get('plan_status') or 'Needs Review')}</span><br><span class="table-note">Qty {fmt(float(sizing.get('quantityBase', 0))) if sizing else '-'}</span></td>
              <td><span class="decision {decision_class}">{html.escape(decision)}</span></td>
              <td>
                <button type="button" class="quantity-button signal-quantity-button" data-symbol="{html.escape(row['symbol'])}" data-entry="{float(signal['entryPrice'])}" data-stop="{float(signal['initialStop'])}">Tính quantity</button>
                <form method="post" action="/decision" class="inline">
                  <input type="hidden" name="signal_id" value="{html.escape(row['signal_id'])}">
                  <button name="decision" value="Accept">Accept</button>
                  <button name="decision" value="Watchlist" class="quiet">Watch</button>
                  <button name="decision" value="Reject" class="quiet danger-text">Reject</button>
                </form>
                <form method="post" action="/track-position" class="inline track-form">
                  <input type="hidden" name="signal_id" value="{html.escape(row['signal_id'])}">
                  <input name="quantity" value="{html.escape(str(round(float(sizing.get('quantityBase', 0)), 6))) if sizing else ''}" placeholder="qty">
                  <button class="quiet">Track position</button>
                </form>
              </td>
            </tr>"""
        )
    return "\n".join(rows)


def render_dashboard_positions(positions: list[dict], recommendations: list[dict]) -> str:
    if not positions:
        return "<tr><td colspan='6' class='empty-cell'>Chưa có vị thế nào được người dùng xác nhận để theo dõi.</td></tr>"
    latest_by_position = {}
    for recommendation in recommendations:
        latest_by_position.setdefault(recommendation["position_id"], recommendation)
    rows = []
    for position in positions:
        recommendation = latest_by_position.get(position["position_id"])
        side_class = "long" if position["side"] == "LONG" else "short"
        action = recommendation["action"] if recommendation else "Chưa có action"
        rationale = recommendation["rationale"] if recommendation else "Sẽ đánh giá sau nến D1 đóng"
        rows.append(
            f"""<tr>
              <td><b>{html.escape(position['symbol'])}</b><br><span class="table-note">User confirmed</span></td>
              <td><span class="side {side_class}">{html.escape(position['side'])}</span></td>
              <td>{fmt(float(position['entry_price']))}</td>
              <td>{fmt(float(position['quantity']))}</td>
              <td><span class="lifecycle">{html.escape(position['lifecycle'])}</span></td>
              <td><b>{html.escape(action)}</b><br><span class="table-note">{html.escape(rationale)}</span></td>
            </tr>"""
        )
    return "\n".join(rows)


def render_dashboard_actions(items: list[dict]) -> str:
    actionable_items = [
        item
        for item in items
        if item.get("action") not in {"DATA_STALE", "NO_ACTION"}
    ]
    if not actionable_items:
        return "<div class='empty-action'>Không có action nào đang chờ xác nhận.</div>"
    cards = []
    for item in actionable_items[:5]:
        payload = json.loads(item.get("payload_json") or "{}")
        tracking = payload.get("trackingStatus", item.get("subject_type", ""))
        action = item.get("action_label") or item.get("action", "")
        outcome = item.get("outcome") or item.get("status", "")
        controls = ""
        if item.get("status") == "Pending":
            buttons = "".join(
                f'<button name="outcome" value="{html.escape(value)}">{html.escape(label)}</button>'
                for value, label in (("Applied", "Applied"), ("Not Applied", "Not applied"), ("Snoozed", "Snooze"), ("Already Closed", "Closed"))
            )
            controls = (
                '<form method="post" action="/followup-outcome" class="action-buttons">'
                f'<input type="hidden" name="recommendation_id" value="{html.escape(item["recommendation_id"])}">{buttons}</form>'
            )
        urgent = " urgent" if int(item.get("priority", 99)) <= 3 else ""
        cards.append(
            f"""<article class="action-card{urgent}">
              <div class="action-meta"><b>{html.escape(str(payload.get('symbol', '-')))}</b><span>{html.escape(str(tracking))}</span><span>{html.escape(str(item['candle_date']))}</span></div>
              <h3>{html.escape(str(action))}</h3>
              <p>{html.escape(str(item.get('rationale', '')))}</p>
              <div class="action-footer"><span class="outcome">{html.escape(str(outcome))}</span>{controls}</div>
            </article>"""
        )
    return "\n".join(cards)


def render_recent_runs(runs: list[dict]) -> str:
    if not runs:
        return "<p>Chưa có run nào.</p>"
    return "\n".join(
        f"""<div class="run"><div><b>{html.escape(str(run.get('status', '-')))}</b><small>{html.escape(str(run.get('finished_at', '-')))}</small></div><span class="status-chip">{html.escape(str(run.get('candle_date') or 'D1'))}</span></div>"""
        for run in runs[:5]
    )


def add_quantity_calculator(payload: str, equity: dict | None, settings: dict) -> str:
    equity_value = html.escape(str(equity.get("new_equity"))) if equity else ""
    risk_value = html.escape(str(settings.get("risk_pct", 2)))
    leverage_value = html.escape(str(settings.get("leverage", 1)))
    styles = """
<style>
.quantity-button{background:#fff;color:#087f75;border-color:#9bc8c3;margin-left:auto}.qty-dialog{width:min(680px,calc(100vw - 28px));border:0;border-radius:10px;padding:0;box-shadow:0 24px 70px rgba(23,33,43,.28)}.qty-dialog::backdrop{background:rgba(23,33,43,.55)}.qty-head{display:flex;align-items:start;justify-content:space-between;gap:16px;padding:20px 22px;border-bottom:1px solid var(--line)}.qty-head p{margin-top:5px;font-size:12px}.qty-close{background:#fff;color:#52616b;border-color:var(--line);padding:6px 9px}.qty-body{padding:20px 22px}.qty-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}.qty-field label{display:block;color:var(--muted);font-size:12px;margin-bottom:5px}.qty-field input{font-variant-numeric:tabular-nums}.qty-error{min-height:20px;color:var(--danger);font-size:12px;margin:10px 0}.qty-results{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;margin-top:16px}.qty-result{background:#f4f7f8;border:1px solid var(--line);border-radius:6px;padding:11px}.qty-result span{display:block;color:var(--muted);font-size:11px}.qty-result b{display:block;margin-top:5px;font-size:16px;overflow-wrap:anywhere}.qty-note{margin-top:14px;font-size:12px}@media(max-width:620px){.qty-grid,.qty-results{grid-template-columns:1fr}.quantity-button{margin-left:0}}
</style>
"""
    button = ""
    modal = f"""
<dialog class="qty-dialog" id="quantity-calculator">
  <div class="qty-head"><div><h2>Tính Quantity theo tín hiệu</h2><p id="qty-signal-note">Entry và stop được lấy từ tín hiệu đang xem. Calculator không lưu DB và không gửi lệnh.</p></div><button type="button" class="qty-close" id="close-quantity-calculator" aria-label="Đóng">×</button></div>
  <div class="qty-body">
    <div class="qty-grid">
      <div class="qty-field"><label for="qty-equity">Equity USD</label><input id="qty-equity" type="number" min="0" step="any" value="{equity_value}" placeholder="20000"></div>
      <div class="qty-field"><label>Risk profile</label><b>{risk_value}% / trade</b><input id="qty-risk-pct" type="hidden" value="{risk_value}"></div>
      <div class="qty-field"><label>Signal</label><b id="qty-signal">-</b></div>
      <div class="qty-field"><label>Entry price</label><b id="qty-entry-label">-</b><input id="qty-entry" type="hidden"></div>
      <div class="qty-field"><label>Stop price</label><b id="qty-stop-label">-</b><input id="qty-stop" type="hidden"></div>
      <input id="qty-leverage" type="hidden" value="{leverage_value}"><input id="qty-step" type="hidden" value="0">
    </div>
    <div class="qty-error" id="qty-error"></div><button type="button" id="calculate-quantity">Tính quantity</button>
    <div class="qty-results"><div class="qty-result"><span>Risk USD</span><b id="qty-risk-usd">-</b></div><div class="qty-result"><span>Risk / unit</span><b id="qty-risk-unit">-</b></div><div class="qty-result"><span>Quantity</span><b id="qty-result">-</b></div><div class="qty-result"><span>Notional</span><b id="qty-notional">-</b></div><div class="qty-result"><span>Margin tham chiếu</span><b id="qty-margin">-</b></div><div class="qty-result"><span>TP1 / 4R / Tail</span><b id="qty-split">-</b></div></div>
    <p class="qty-note">Quantity = Risk USD / |Entry - Stop|. Quantity step nếu có sẽ làm tròn xuống để không vượt risk.</p>
  </div>
</dialog>
<script>
(()=>{{const d=document.getElementById('quantity-calculator'),num=id=>Number(document.getElementById(id).value),show=(id,value)=>document.getElementById(id).textContent=value,fmt=(value,digits=8)=>Number(value).toLocaleString('en-US',{{maximumFractionDigits:digits}}),calculate=()=>{{const equity=num('qty-equity'),riskPct=num('qty-risk-pct'),entry=num('qty-entry'),stop=num('qty-stop'),leverage=num('qty-leverage'),error=document.getElementById('qty-error');error.textContent='';if(!(equity>0)||!(riskPct>0)||!(entry>0)||!(stop>0)||!(leverage>0)){{error.textContent='Nhập Equity USD lớn hơn 0.';return}}const riskPerUnit=Math.abs(entry-stop);if(!(riskPerUnit>0)){{error.textContent='Entry và Stop phải khác nhau.';return}}const riskUsd=equity*riskPct/100,qty=riskUsd/riskPerUnit,notional=qty*entry,margin=notional/leverage;show('qty-risk-usd','$'+fmt(riskUsd,2));show('qty-risk-unit',fmt(riskPerUnit));show('qty-result',fmt(qty));show('qty-notional','$'+fmt(notional,2));show('qty-margin','$'+fmt(margin,2));show('qty-split',fmt(qty*.30)+' / '+fmt(qty*.10)+' / '+fmt(qty*.60));}};document.querySelectorAll('.signal-quantity-button').forEach(button=>button.addEventListener('click',()=>{{const entry=button.dataset.entry,stop=button.dataset.stop,symbol=button.dataset.symbol;document.getElementById('qty-entry').value=entry;document.getElementById('qty-stop').value=stop;show('qty-signal',symbol);show('qty-entry-label',fmt(entry));show('qty-stop-label',fmt(stop));document.getElementById('qty-error').textContent='';d.showModal();if(num('qty-equity')>0)calculate();}}));document.getElementById('close-quantity-calculator').addEventListener('click',()=>d.close());d.addEventListener('click',event=>{{if(event.target===d)d.close()}});document.getElementById('calculate-quantity').addEventListener('click',calculate);}})();
</script>
"""
    payload = payload.replace("</style></head>", f"</style>{styles}</head>", 1)
    payload = payload.replace('<form method="post" action="/scan">', f'{button}<form method="post" action="/scan">', 1)
    return payload.replace("</body></html>", f"{modal}</body></html>", 1)


def page() -> str:
    last_scan = load_json(SCAN_PATH, {})
    history = load_json(HISTORY_PATH, [])
    store.import_legacy_history(history, SYSTEM_NAME)
    state = store.dashboard_state()
    equity = state.get("currentEquity")
    settings = state.get("settings", {})
    new_count = len(last_scan.get("newSignals", [])) if isinstance(last_scan, dict) else 0
    scanned_at = last_scan.get("scannedAt", "Never") if isinstance(last_scan, dict) else "Never"
    latest_run = state["scanRuns"][0] if state.get("scanRuns") else {}
    pending = [
        item
        for item in state["followupRecommendations"]
        if item.get("status") in {"Pending", "Reminder"}
        and item.get("action") not in {"DATA_STALE", "NO_ACTION"}
    ]
    active = [item for item in state["positions"] if item.get("lifecycle") not in {"Closed", "Stopped", "Rejected", "Expired"}]
    payload = f"""<!doctype html>
<html lang="vi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>NXT | Trading Desk</title>
<style>
:root{{--ink:#17212b;--muted:#637083;--line:#dce2e8;--bg:#f5f7f8;--panel:#fff;--accent:#087f75;--blue:#2563a9;--danger:#b54736;--amber:#a35f05;--sidebar:#202a31}}*{{box-sizing:border-box}}body{{margin:0;font-family:Arial,sans-serif;background:var(--bg);color:var(--ink);font-size:14px}}.shell{{min-height:100vh;display:grid;grid-template-columns:232px minmax(0,1fr)}}.sidebar{{background:var(--sidebar);color:#fff;padding:24px 16px;display:flex;flex-direction:column;gap:28px}}.brand{{padding:0 8px}}.brand strong{{display:block;font-size:22px}}.brand span{{display:block;margin-top:5px;color:#aebcc3;font-size:12px;line-height:1.45}}nav{{display:grid;gap:4px}}nav a{{color:#b9c4ca;text-decoration:none;padding:10px 12px;border-radius:5px;font-weight:700}}nav a:first-child{{background:#35454d;color:#fff}}nav a:hover{{background:#2b3940;color:#fff}}.sidebar-note{{margin-top:auto;border-top:1px solid #3b4950;padding:16px 8px 0;color:#afbac0;font-size:12px;line-height:1.55}}.content{{min-width:0}}header{{background:#fff;border-bottom:1px solid var(--line);padding:18px 34px;display:flex;align-items:center;justify-content:space-between;gap:16px}}.header-title{{display:flex;align-items:center;gap:11px}}.header-title h1{{margin:0;font-size:18px}}.header-title span{{color:var(--muted);font-size:12px}}.live{{width:8px;height:8px;border-radius:50%;background:#35a678;display:inline-block}}main{{max-width:1480px;margin:0 auto;padding:28px 34px 44px}}button{{background:var(--accent);color:#fff;border:1px solid var(--accent);border-radius:5px;padding:9px 12px;font-weight:700;cursor:pointer}}button:hover{{filter:brightness(.94)}}button.quiet{{color:#39515d;background:#fff;border-color:#c8d2d9}}button.danger-text{{color:var(--danger)}}.scan-button::before{{content:'↻';font-size:17px;margin-right:7px}}.eyebrow{{text-transform:uppercase;font-size:11px;font-weight:700;color:var(--muted);margin-bottom:5px}}h2{{margin:0;font-size:18px}}h3{{margin:0;font-size:14px}}p{{margin:0;color:var(--muted);line-height:1.5}}.page-heading{{display:flex;justify-content:space-between;gap:16px;align-items:end;margin-bottom:20px}}.page-heading h2{{font-size:26px}}.page-heading p{{margin-top:6px}}.summary-grid{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin-bottom:24px}}.metric{{background:var(--panel);border:1px solid var(--line);border-radius:6px;padding:16px;min-height:106px}}.metric-label{{color:var(--muted);font-size:12px}}.metric-value{{margin-top:10px;font-size:24px;font-weight:700}}.metric-detail{{margin-top:7px;color:var(--muted);font-size:12px}}.metric.good .metric-value{{color:#087f75}}.metric.alert .metric-value{{color:var(--amber)}}.dashboard-grid{{display:grid;grid-template-columns:minmax(0,1.8fr) minmax(300px,.95fr);gap:16px;align-items:start}}.stack{{display:grid;gap:16px}}.panel{{background:#fff;border:1px solid var(--line);border-radius:6px;padding:18px;min-width:0}}.panel-heading{{display:flex;align-items:start;justify-content:space-between;gap:12px;margin-bottom:15px}}.panel-heading p{{margin-top:4px;font-size:12px}}.actions{{display:grid;gap:10px;max-height:430px;overflow-y:auto;padding-right:6px;scrollbar-gutter:stable}}.signals-scroll{{max-height:430px;overflow-y:auto;scrollbar-gutter:stable}}.action-card{{border:1px solid var(--line);border-left:4px solid #aab7bf;border-radius:5px;padding:13px 14px;min-width:0}}.action-card.urgent{{border-left-color:var(--amber);background:#fffdf8}}.action-meta{{display:flex;flex-wrap:wrap;gap:7px;color:var(--muted);font-size:12px}}.action-meta b{{color:var(--ink)}}.action-card h3{{margin:9px 0 5px;overflow-wrap:anywhere}}.action-card p{{overflow-wrap:anywhere}}.action-footer{{display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:10px;margin-top:11px}}.outcome{{color:var(--blue);font-size:12px;font-weight:700}}.action-buttons{{display:flex;flex:1 1 260px;flex-wrap:wrap;gap:5px;justify-content:flex-end}}.action-buttons button{{padding:6px 8px;background:#fff;color:#39515d;border-color:#c8d2d9;font-size:12px}}.empty-action{{color:var(--muted);padding:16px 0}}.form-section{{border-top:1px solid var(--line);margin-top:15px;padding-top:15px}}.form-row{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}}.form-row button{{grid-column:span 2}}input{{border:1px solid #c8d2d9;border-radius:5px;padding:9px;width:100%;color:var(--ink)}}.settings{{display:grid}}.setting{{padding:11px 0;border-top:1px solid var(--line);display:flex;justify-content:space-between;gap:10px}}.setting:first-child{{border-top:0;padding-top:0}}.setting span{{color:var(--muted);font-size:12px}}.orders{{overflow-x:auto}}table{{width:100%;min-width:830px;border-collapse:collapse;font-size:13px}}th,td{{border-top:1px solid var(--line);padding:12px 10px;text-align:left;vertical-align:top}}th{{color:var(--muted);font-weight:700;font-size:11px;text-transform:uppercase}}.table-note{{display:inline-block;margin-top:3px;color:var(--muted);font-size:11px}}.empty-cell{{color:var(--muted);padding:22px 10px}}.side,.decision,.plan-status,.lifecycle{{display:inline-block;padding:4px 7px;border-radius:4px;font-size:11px;font-weight:700}}.side.long,.decision.accept{{color:#087f75;background:#e6f5f1}}.side.short,.decision.reject{{color:#b54736;background:#faece9}}.decision.watchlist,.decision.pending{{color:#7b5a12;background:#fbf3dc}}.plan-status,.lifecycle{{color:#39515d;background:#eef3f5}}.inline{{display:flex;gap:5px;flex-wrap:wrap}}.inline button{{padding:6px 8px;font-size:12px}}.track-form{{margin-top:6px}}.track-form input{{width:86px;padding:6px;font-size:12px}}.history-grid{{display:grid;grid-template-columns:1fr 1fr;gap:16px}}.run-list{{display:grid}}.run{{padding:11px 0;border-top:1px solid var(--line);display:flex;justify-content:space-between;gap:10px}}.run:first-child{{border-top:0;padding-top:0}}.run small{{color:var(--muted);display:block;margin-top:3px}}.status-chip{{color:#087f75;background:#e6f5f1;padding:4px 6px;height:max-content;border-radius:4px;font-size:11px;font-weight:700}}.utility-link{{color:var(--blue);text-decoration:none;font-weight:700;font-size:12px}}@media(max-width:1100px){{.summary-grid{{grid-template-columns:repeat(2,minmax(0,1fr))}}.dashboard-grid{{grid-template-columns:1fr}}}}@media(max-width:760px){{.shell{{display:block}}.sidebar{{display:none}}header{{padding:14px 16px}}main{{padding:22px 16px 34px}}.page-heading{{align-items:start;flex-direction:column}}.summary-grid,.history-grid{{grid-template-columns:1fr}}.page-heading h2{{font-size:22px}}.action-buttons{{justify-content:flex-start}}}}
</style></head><body><div class="shell"><aside class="sidebar"><div class="brand"><strong>NXT</strong><span>Trading decision desk<br>BTC · BNB · SOL</span></div><nav><a href="#overview">Tổng quan</a><a href="#actions">Action center</a><a href="#signals">Tín hiệu</a><a href="#positions">Vị thế</a><a href="#history">Lịch sử</a></nav><div class="sidebar-note">NXT v3.5<br>Public Binance USD-M 1D<br><br>Chỉ khuyến nghị. Không kết nối tài khoản hoặc gửi lệnh.</div></aside><div class="content"><header><div class="header-title"><span class="live"></span><div><h1>Trading desk</h1><span>{html.escape(SYSTEM_NAME)}</span></div></div><form method="post" action="/scan"><button class="scan-button">Quét dữ liệu mới</button></form></header><main id="overview"><div class="page-heading"><div><div class="eyebrow">Daily operating view</div><h2>Trạng thái hôm nay</h2><p>Đánh giá sau nến USD-M 1D đóng. Mọi action cần được xác nhận thủ công.</p></div><a class="utility-link" href="/api/state">Mở dữ liệu hệ thống</a></div><section class="summary-grid"><article class="metric good"><div class="metric-label">Lần quét gần nhất</div><div class="metric-value">{html.escape(latest_run.get('status', 'Chưa có scan'))}</div><div class="metric-detail">{html.escape(scanned_at)}</div></article><article class="metric {'alert' if pending else ''}"><div class="metric-label">Action chờ xác nhận</div><div class="metric-value">{len(pending)}</div><div class="metric-detail">Ưu tiên xử lý action có nhãn màu cam</div></article><article class="metric"><div class="metric-label">Vị thế đang theo dõi</div><div class="metric-value">{len(active)}</div><div class="metric-detail">Nguồn trạng thái: người dùng xác nhận</div></article><article class="metric"><div class="metric-label">Tín hiệu trong lịch sử</div><div class="metric-value">{len(state['signals'])}</div><div class="metric-detail">Tín hiệu mới từ scan gần nhất: {new_count}</div></article></section><div class="dashboard-grid"><div class="stack"><section class="panel" id="actions"><div class="panel-heading"><div><h2>Action center</h2><p>Follow-up cho tín hiệu đã Accept và vị thế đang theo dõi.</p></div><span class="status-chip">{len(pending)} pending</span></div><div class="actions">{render_dashboard_actions(state['followupRecommendations'])}</div></section><section class="panel" id="signals"><div class="panel-heading"><div><h2>Tín hiệu và quyết định</h2><p>Accept chỉ ghi nhận quyết định. Chọn Track position sau khi bạn đã vào lệnh bên ngoài hệ thống.</p></div><span class="status-chip">{len(state['signals'])} signals</span></div><div class="orders signals-scroll"><table><thead><tr><th>Symbol</th><th>Side</th><th>Entry / Stop</th><th>Targets</th><th>Sizing plan</th><th>Decision</th><th>Thao tác</th></tr></thead><tbody>{render_dashboard_signals(state['signals'])}</tbody></table></div></section><section class="panel" id="positions"><div class="panel-heading"><div><h2>Vị thế theo dõi thủ công</h2><p>Hệ thống không suy đoán fill hoặc tự thay đổi trạng thái vị thế.</p></div></div><div class="orders"><table><thead><tr><th>Position</th><th>Side</th><th>Entry</th><th>Quantity</th><th>Lifecycle</th><th>Khuyến nghị mới nhất</th></tr></thead><tbody>{render_dashboard_positions(state['positions'], state['recommendations'])}</tbody></table></div></section></div><aside class="stack"><section class="panel"><div class="panel-heading"><div><h2>Equity & risk</h2><p>Current equity chỉ dùng để tính sizing tham khảo.</p></div></div><div class="settings"><div class="setting"><span>Current equity</span><b>{money(equity.get('new_equity') if equity else None)}</b></div><div class="setting"><span>Risk per trade</span><b>{html.escape(str(settings.get('risk_pct', '-')))}%</b></div><div class="setting"><span>Leverage tham chiếu</span><b>{html.escape(str(settings.get('leverage', '-')))}x</b></div><div class="setting"><span>Portfolio risk cap</span><b>{html.escape(str(settings.get('portfolio_cap_pct', '-')))}%</b></div><div class="setting"><span>Reference equity</span><b>$10,000.00</b></div></div><form method="post" action="/equity" class="form-section form-row"><input name="equity" placeholder="Equity USD" value="{html.escape(str(equity.get('new_equity'))) if equity else ''}"><input name="risk_pct" placeholder="Risk %" value="{html.escape(str(settings.get('risk_pct', 2)))}"><input name="leverage" placeholder="Leverage" value="{html.escape(str(settings.get('leverage', 1)))}"><input name="portfolio_cap_pct" placeholder="Portfolio cap %" value="{html.escape(str(settings.get('portfolio_cap_pct', 0)))}"><input name="reason" placeholder="Lý do cập nhật" value="Manual update"><input name="note" placeholder="Ghi chú (tuỳ chọn)"><button>Lưu equity mới</button></form></section><section class="panel"><div class="panel-heading"><div><h2>Biên an toàn MVP1</h2></div></div><div class="settings"><div class="setting"><span>Market data</span><b>Public USD-M</b></div><div class="setting"><span>Execution</span><b>Disabled</b></div><div class="setting"><span>Schedule</span><b>07:01 ICT</b></div><div class="setting"><span>Rule version</span><b>NXT v3.5</b></div></div></section></aside></div><section class="history-grid" id="history" style="margin-top:16px"><article class="panel"><div class="panel-heading"><div><h2>Nhật ký quét</h2><p>Run gần nhất và trạng thái vận hành.</p></div></div><div class="run-list">{render_recent_runs(state['scanRuns'])}</div></article><article class="panel"><div class="panel-heading"><div><h2>Lịch sử & audit</h2><p>Dữ liệu được lưu local, append-only cho các nghiệp vụ chính.</p></div></div><div class="settings"><div class="setting"><span>Equity records</span><b>{len(state['equityHistory'])}</b></div><div class="setting"><span>Audit events</span><b>{len(state['auditEvents'])}</b></div><div class="setting"><span>Signal history JSON</span><b>{len(history)}</b></div></div><div style="margin-top:16px"><a class="utility-link" href="/api/history">Xem lịch sử signal JSON</a></div></article></section></main></div></div></body></html>"""

    return add_quantity_calculator(payload, equity, settings)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/api/state":
            self.send_json(store.dashboard_state())
            return
        if self.path == "/api/history":
            self.send_json(load_json(HISTORY_PATH, []))
            return
        if self.path == "/api/last-scan":
            self.send_json(load_json(SCAN_PATH, {}))
            return
        self.send_html(page())

    def do_POST(self) -> None:
        if self.path == "/scan":
            scan_and_persist()
            self.redirect("/")
            return
        try:
            form = read_form(self)
            if self.path == "/equity":
                store.append_equity(
                    float(form.get("equity", "0")),
                    float(form.get("risk_pct", "0")),
                    float(form.get("leverage", "1") or 1),
                    float(form.get("portfolio_cap_pct", "0") or 0),
                    form.get("reason", "Manual update"),
                    form.get("note", ""),
                )
                self.redirect("/")
                return
            if self.path == "/decision":
                store.record_decision(form["signal_id"], form["decision"], form.get("note", ""))
                self.redirect("/")
                return
            if self.path == "/track-position":
                qty = form.get("quantity", "").strip()
                store.track_position(form["signal_id"], float(qty) if qty else None)
                self.redirect("/")
                return
            if self.path == "/followup-outcome":
                store.record_followup_outcome(form["recommendation_id"], form["outcome"])
                self.redirect("/")
                return
        except Exception as exc:
            self.send_error(400, str(exc))
            return
        self.send_error(404)

    def redirect(self, target: str) -> None:
        self.send_response(303)
        self.send_header("Location", target)
        self.end_headers()

    def send_html(self, payload: str) -> None:
        data = payload.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def send_json(self, payload: object) -> None:
        data = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt_text: str, *args: object) -> None:
        print(f"{self.address_string()} - {fmt_text % args}")


def run_server(host: str, port: int) -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    store.init_db()
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"NXT Signal App running at http://{host}:{port}")
    server.serve_forever()


def main() -> int:
    parser = argparse.ArgumentParser(description="NXT latest signal app for Binance BTC/BNB/SOL.")
    parser.add_argument("--scan-once", action="store_true", help="Scan Binance once, persist new signals, and exit.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=6789)
    args = parser.parse_args()
    if args.scan_once:
        print(json.dumps(scan_and_persist(), indent=2))
        return 0
    run_server(args.host, args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
