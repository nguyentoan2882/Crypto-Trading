from __future__ import annotations

import json
import sys
import csv
import io
import time
import urllib.error
import urllib.request
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import audit_nxt34_btc_bnb_sol_funding_adjusted as funding
import backtest_nxt31_utc7_latest as base
import backtest_nxt32_native_1d_latest as native
import test_nxt33_long_only_pullback_continuation as cont
from test_nxt33_ssl14 import enrich_with_ssl_period


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "outputs" / "nxt35_latest_to_today"
OUT_JSON = OUT_DIR / "NXT35_Latest_To_Today.json"
LATEST_FUNDING_JSON = ROOT / "latest" / "NXT_Latest_NXT35_USDM_BlockShortAfterLosingLong_FundingAdjusted_20K.json"
USDM_CACHE = ROOT / "data_cache" / "binance_usdm_futures_1d"

SYMBOLS = ["BTCUSDT", "BNBUSDT", "SOLUSDT"]
START_DATE = native.START_DATE
WARMUP_DATE = native.WARMUP_DATE
RUN_DATE = date.today()
STARTING_EQUITY = 20_000.0
ONE_R_DOLLARS = 1_000.0


def month_iter(start: date, end: date):
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        yield y, m
        m += 1
        if m == 13:
            y += 1
            m = 1


def normalize_ms(value: str) -> int:
    number = int(float(value))
    return number // 1000 if number > 10_000_000_000_000 else number


def read_usdm_zip(url: str) -> list[dict]:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "nxt-latest-to-today/1.0"})
        with urllib.request.urlopen(req, timeout=30) as response:
            payload = response.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return []
        raise
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        names = [name for name in archive.namelist() if name.endswith(".csv")]
        if not names:
            return []
        with archive.open(names[0]) as raw:
            reader = csv.reader(io.TextIOWrapper(raw, encoding="utf-8"))
            rows = []
            for row in reader:
                if not row or row[0] in {"open_time", "Open time"}:
                    continue
                rows.append(
                    {
                        "time": normalize_ms(row[0]),
                        "open": float(row[1]),
                        "high": float(row[2]),
                        "low": float(row[3]),
                        "close": float(row[4]),
                        "volume": float(row[5]),
                    }
                )
            return rows


def fetch_usdm_1d(symbol: str, requested_end: date) -> list[dict]:
    USDM_CACHE.mkdir(parents=True, exist_ok=True)
    cache_path = USDM_CACHE / f"{symbol}_1d_{WARMUP_DATE}_{requested_end}.json"
    if cache_path.exists():
        raw = json.loads(cache_path.read_text(encoding="utf-8"))
    else:
        raw = []
        for year, month in month_iter(WARMUP_DATE, requested_end):
            url = (
                "https://data.binance.vision/data/futures/um/monthly/klines/"
                f"{symbol}/1d/{symbol}-1d-{year}-{month:02d}.zip"
            )
            batch = read_usdm_zip(url)
            raw.extend(batch)
            if batch:
                print(symbol, year, f"{month:02d}", len(batch), "monthly")
            time.sleep(0.02)

        # Monthly archives for the current month can lag. Pull daily files too so
        # reruns can extend as close to today's available closed candle as possible.
        month_start = requested_end.replace(day=1)
        day = max(month_start, WARMUP_DATE)
        while day <= requested_end:
            url = (
                "https://data.binance.vision/data/futures/um/daily/klines/"
                f"{symbol}/1d/{symbol}-1d-{day.isoformat()}.zip"
            )
            batch = read_usdm_zip(url)
            raw.extend(batch)
            if batch:
                print(symbol, day.isoformat(), len(batch), "daily")
            day += timedelta(days=1)
            time.sleep(0.02)

        raw = sorted({int(row["time"]): row for row in raw}.values(), key=lambda row: int(row["time"]))
        cache_path.write_text(json.dumps(raw), encoding="utf-8")

    candles = []
    for row in raw:
        day = datetime.fromtimestamp(int(row["time"]) / 1000, timezone.utc).date()
        if WARMUP_DATE <= day <= requested_end:
            item = dict(row)
            item["localDate"] = day.isoformat()
            candles.append(item)
    return candles


def close_position(symbol: str, trade_no: int, pos: dict, candle: dict, exit_price: float, reason: str) -> dict:
    side = pos["side"]
    rem = 0.5 if pos["triggered"] else 1.0
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


def backtest_symbol_to_date(symbol: str, candles: list[dict], end_date: date) -> tuple[list[dict], dict | None]:
    trades, pos, n = [], None, 1
    last_runner_exit = None
    for i in range(55, len(candles) - 1):
        c, prev, nxt = candles[i], candles[i - 1], candles[i + 1]
        next_date = base.date.fromisoformat(nxt["localDate"])
        if next_date < START_DATE or next_date > end_date:
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
                trade = close_position(symbol, n, pos, c, exit_price, reason)
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
        continuation_ssl_ok = prev["ssl"] == -1 and c["ssl"] == 1
        long_cont = continuation_ssl_ok and c["close"] > c["ema20"] > c["ema50"] and cont.touch_reclaim_long(candles, i, cont.RULE["touchLookback"])
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

    open_position = None
    if pos is not None:
        last = candles[-1]
        mark_r = (last["close"] - pos["entry"]) / pos["risk"] if pos["side"] == "LONG" else (pos["entry"] - last["close"]) / pos["risk"]
        open_position = {
            "symbol": symbol,
            "tradeNo": n,
            "signalType": pos["signalType"],
            "side": pos["side"],
            "signalTime": pos["signalDate"],
            "entryTime": pos["entryDate"],
            "entryPrice": pos["entry"],
            "currentMarkDate": last["localDate"],
            "currentMarkPrice": last["close"],
            "initialStop": pos["initialStop"],
            "currentStop": pos["stop"],
            "riskPerUnit": pos["risk"],
            "tp1": pos["tp"],
            "tp1Time": pos["tp1Time"],
            "earlyBeTriggered": pos["earlyBeTriggered"],
            "earlyBeTime": pos["earlyBeTime"],
            "grossOpenR": pos["realizedR"] + (0.5 if pos["triggered"] else 1.0) * mark_r,
            "notes": pos["notes"],
        }
    return trades, open_position


def stats_for_key(trades: list[dict], key: str) -> dict:
    return cont.enriched_stats([dict(t, rMultiple=t[key]) for t in trades])


def apply_funding(trades: list[dict], start: date, end: date) -> list[dict]:
    funding_by_symbol = {
        symbol: funding.fetch_monthly_funding(symbol, start, end)
        for symbol in SYMBOLS
    }
    out = []
    for trade in trades:
        row = dict(trade)
        f = funding.funding_for_trade(row, funding_by_symbol[row["symbol"]])
        row.update(f)
        row["netRAfterFunding"] = row["rMultiple"] + row["fundingR"]
        out.append(row)
    return out


def group_stats(rows: list[dict], key_fn, r_key: str) -> list[dict]:
    groups: dict[str, list[dict]] = {}
    for row in rows:
        groups.setdefault(key_fn(row), []).append(row)
    out = []
    for key, subset in sorted(groups.items()):
        st = stats_for_key(subset, r_key)
        st["group"] = key
        out.append(st)
    return out


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    baseline = json.loads(LATEST_FUNDING_JSON.read_text(encoding="utf-8"))
    all_trades = []
    open_positions = []
    datasets = {}
    for symbol in SYMBOLS:
        candles = enrich_with_ssl_period(fetch_usdm_1d(symbol, RUN_DATE), 14)
        datasets[symbol] = {
            "dailyRows": len(candles),
            "firstDay": candles[0]["localDate"],
            "lastDay": candles[-1]["localDate"],
            "source": "Binance USD-M perpetual contract 1D klines (00:00 UTC)",
        }
        trades, open_pos = backtest_symbol_to_date(symbol, candles, RUN_DATE)
        all_trades.extend(trades)
        if open_pos:
            open_positions.append(open_pos)
    all_trades.sort(key=lambda trade: (trade["exitTime"], trade["entryTime"], trade["symbol"], trade["tradeNo"]))
    funded = apply_funding(all_trades, START_DATE, RUN_DATE)
    original_stats = stats_for_key(funded, "rMultiple")
    adjusted_stats = stats_for_key(funded, "netRAfterFunding")
    adjusted_curve = funding.equity_curve(funded, "netRAfterFunding")
    adjusted_stats["maxDrawdownDollars"] = min((row["drawdown"] for row in adjusted_curve), default=0.0)
    cap_equal = funding.portfolio_cap_curve(
        funded,
        {"BTCUSDT": 0.02, "BNBUSDT": 0.02, "SOLUSDT": 0.02},
        "netRAfterFunding",
    )
    result = {
        "generatedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "runDate": RUN_DATE.isoformat(),
        "sourceRules": str(LATEST_FUNDING_JSON),
        "method": "NXT latest USD-M promoted rules rerun to current local date. Closed-trade stats include only completed trades; any open position is reported separately as mark-to-market.",
        "period": {
            "start": START_DATE.isoformat(),
            "requestedEnd": RUN_DATE.isoformat(),
            "lastDataDate": max(q["lastDay"] for q in datasets.values()),
        },
        "symbols": SYMBOLS,
        "baselineLatestFundingAdjustedStats": baseline["fundingAdjustedStats"],
        "baselineLatestPortfolioCap6Equal": baseline["portfolioCap6Equal"],
        "originalStats": original_stats,
        "fundingAdjustedStats": adjusted_stats,
        "fundingSummary": {
            "totalFundingR": sum(t["fundingR"] for t in funded),
            "fundingEvents": sum(t["fundingEvents"] for t in funded),
            "fundingPaidR": sum(t["fundingPaidR"] for t in funded),
            "fundingReceivedR": sum(t["fundingReceivedR"] for t in funded),
        },
        "portfolioCap6Equal": cap_equal,
        "deltaVsPublishedLatest": {
            "trades": adjusted_stats["trades"] - baseline["fundingAdjustedStats"]["trades"],
            "totalR": adjusted_stats["totalR"] - baseline["fundingAdjustedStats"]["totalR"],
            "maxDrawdownR": adjusted_stats["maxDrawdownR"] - baseline["fundingAdjustedStats"]["maxDrawdownR"],
            "profitFactor": adjusted_stats["profitFactor"] - baseline["fundingAdjustedStats"]["profitFactor"],
            "ending20k": adjusted_stats["ending20k"] - baseline["fundingAdjustedStats"]["ending20k"],
            "cap6EqualEnding": cap_equal["endingEquity"] - baseline["portfolioCap6Equal"]["endingEquity"],
        },
        "bySymbol": group_stats(funded, lambda t: t["symbol"], "netRAfterFunding"),
        "byYear": group_stats(funded, lambda t: t["exitTime"][:4], "netRAfterFunding"),
        "openPositions": open_positions,
        "datasets": datasets,
        "trades": funded,
    }
    OUT_JSON.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({
        "outJson": str(OUT_JSON),
        "runDate": result["runDate"],
        "lastDataDate": result["period"]["lastDataDate"],
        "closedTrades": adjusted_stats["trades"],
        "baselineTrades": baseline["fundingAdjustedStats"]["trades"],
        "totalR": adjusted_stats["totalR"],
        "deltaR": result["deltaVsPublishedLatest"]["totalR"],
        "maxDdR": adjusted_stats["maxDrawdownR"],
        "profitFactor": adjusted_stats["profitFactor"],
        "ending20k": adjusted_stats["ending20k"],
        "cap6EqualEnding": cap_equal["endingEquity"],
        "openPositions": open_positions,
    }, indent=2))


if __name__ == "__main__":
    main()
