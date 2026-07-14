from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import audit_nxt34_btc_bnb_sol_funding_adjusted as funding
import backtest_nxt31_utc7_latest as base
import backtest_nxt32_native_1d_latest as native
import promote_nxt34_btc_bnb_sol_latest as latest_runner
import test_nxt33_long_only_pullback_continuation as cont
from test_nxt33_ssl14 import enrich_with_ssl_period


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "outputs" / "nxt35_no_short_primary"
OUT_JSON = OUT_DIR / "NXT35_No_SHORT_Primary.json"
LATEST_FUNDING_JSON = ROOT / "latest" / "NXT_Latest_NXT35_BTC_BNB_SOL_FundingAdjusted_20K.json"
LATEST_SOURCE_JSON = ROOT / "latest" / "NXT_Latest_NXT35_BTC_BNB_SOL_LongOnlyPullbackContinuation_20K.json"

SYMBOLS = ["BTCUSDT", "BNBUSDT", "SOLUSDT"]


def backtest_symbol_no_short(symbol: str, candles: list[dict]) -> list[dict]:
    trades, pos, n = [], None, 1
    last_profitable_runner_exit = None
    for i in range(55, len(candles) - 1):
        c, prev, nxt = candles[i], candles[i - 1], candles[i + 1]
        next_date = base.date.fromisoformat(nxt["localDate"])
        if next_date < native.START_DATE or next_date >= native.END_DATE:
            continue
        if pos:
            side = pos["side"]
            ssl_flip = side == "LONG" and prev["ssl"] == 1 and c["ssl"] == -1
            can_trigger_early_be = c["localDate"] != pos["entryDate"]
            exit_price = reason = None
            if c["low"] <= pos["stop"]:
                exit_price = pos["stop"]
                reason = "Breakeven stop" if (pos["triggered"] or pos["earlyBeTriggered"]) else "Stop loss"
            else:
                if not pos["triggered"] and c["high"] >= pos["tp"]:
                    pos["triggered"] = True
                    pos["tp1Time"] = c["localDate"]
                    pos["stop"] = pos["entry"]
                    pos["realizedR"] += 0.5 * ((pos["tp"] - pos["entry"]) / pos["risk"])
                if (
                    can_trigger_early_be
                    and not pos["triggered"]
                    and not pos["earlyBeTriggered"]
                    and cont.EARLY_BE_PROFIT_PCT is not None
                    and c["high"] >= pos["entry"] * (1 + cont.EARLY_BE_PROFIT_PCT)
                ):
                    pos["earlyBeTriggered"] = True
                    pos["earlyBeTime"] = c["localDate"]
                    pos["stop"] = pos["entry"]
                if ssl_flip:
                    exit_price = c["close"]
                    reason = "Runner exit: SSL bearish flip"
            if exit_price is not None:
                rem = 0.5 if pos["triggered"] else 1.0
                rem_r = (exit_price - pos["entry"]) / pos["risk"]
                gross = pos["realizedR"] + rem * rem_r
                cost = base.cost_r(pos["entry"], pos["risk"])
                net = gross - cost
                trades.append(
                    {
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
                    }
                )
                if net >= cont.ANTI_REVERSAL_MIN_RUNNER_R and reason.startswith("Runner exit"):
                    last_profitable_runner_exit = {"index": i, "side": side, "netR": net}
                n += 1
                pos = None
            if pos:
                continue

        if any(c[k] is None for k in ["ema20", "ema50", "atr14", "rsi14", "ssl"]) or prev["ssl"] is None:
            continue
        dist = abs(c["close"] - c["ema50"]) / c["atr14"]
        long_primary = prev["ssl"] == -1 and c["ssl"] == 1 and base.recent_cross(candles, i, "LONG") and dist <= 2 and c["rsi14"] > 50
        continuation_ssl_ok = prev["ssl"] == -1 and c["ssl"] == 1
        long_cont = continuation_ssl_ok and c["close"] > c["ema20"] > c["ema50"] and cont.touch_reclaim_long(candles, i, cont.RULE["touchLookback"])
        if last_profitable_runner_exit and i - last_profitable_runner_exit["index"] <= 1:
            if (long_primary or long_cont) and last_profitable_runner_exit["side"] == "SHORT":
                long_primary = long_cont = False
        if not (long_primary or long_cont):
            continue
        signal_type = "Continuation" if long_cont and not long_primary else "Primary"
        risk = c["atr14"] * 1.5
        entry = nxt["open"]
        pos = {
            "side": "LONG",
            "signalType": signal_type,
            "signalDate": c["localDate"],
            "entryDate": nxt["localDate"],
            "entry": entry,
            "initialStop": entry - risk,
            "stop": entry - risk,
            "risk": risk,
            "tp": entry + c["atr14"] * cont.TP1_ATR,
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


def stats_for_key(trades: list[dict], key: str) -> dict:
    return cont.enriched_stats([dict(t, rMultiple=t[key]) for t in trades])


def with_funding(trades: list[dict], period: dict) -> list[dict]:
    start = base.date.fromisoformat(period["start"])
    end = base.date.fromisoformat(period["end"])
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


def summarize_by(rows: list[dict], key_fn, r_key: str) -> list[dict]:
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
    source = json.loads(LATEST_SOURCE_JSON.read_text(encoding="utf-8"))
    all_trades = []
    datasets = {}
    for symbol in SYMBOLS:
        candles = enrich_with_ssl_period(
            latest_runner.fetch_tradingview_binance_1d(symbol, latest_runner.WARMUP_DATE, latest_runner.END_DATE),
            14,
        )
        datasets[symbol] = {
            "dailyRows": len(candles),
            "firstDay": candles[0]["localDate"],
            "lastDay": candles[-1]["localDate"],
            "source": "Binance spot native 1D (00:00 UTC), matching TradingView BINANCE 1D",
        }
        all_trades.extend(backtest_symbol_no_short(symbol, candles))
    all_trades.sort(key=lambda trade: trade["exitTime"])
    period = source["period"]
    funded = with_funding(all_trades, period)
    original_stats = stats_for_key(funded, "rMultiple")
    adjusted_stats = stats_for_key(funded, "netRAfterFunding")
    adjusted_curve = funding.equity_curve(funded, "netRAfterFunding")
    adjusted_stats["maxDrawdownDollars"] = min((row["drawdown"] for row in adjusted_curve), default=0)
    cap_equal = funding.portfolio_cap_curve(
        funded,
        {"BTCUSDT": 0.02, "BNBUSDT": 0.02, "SOLUSDT": 0.02},
        "netRAfterFunding",
    )
    result = {
        "generatedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "sourceBaseline": str(LATEST_FUNDING_JSON),
        "variant": "Disable all SHORT entries; keep Primary LONG and LONG Continuation rules unchanged.",
        "period": period,
        "symbols": SYMBOLS,
        "baselineFundingAdjustedStats": baseline["fundingAdjustedStats"],
        "baselinePortfolioCap6Equal": baseline["portfolioCap6Equal"],
        "originalStats": original_stats,
        "fundingAdjustedStats": adjusted_stats,
        "fundingSummary": {
            "totalFundingR": sum(t["fundingR"] for t in funded),
            "fundingEvents": sum(t["fundingEvents"] for t in funded),
            "fundingPaidR": sum(t["fundingPaidR"] for t in funded),
            "fundingReceivedR": sum(t["fundingReceivedR"] for t in funded),
        },
        "portfolioCap6Equal": cap_equal,
        "sideCounts": dict(Counter(t["side"] for t in funded)),
        "signalTypeCounts": dict(Counter(t["signalType"] for t in funded)),
        "bySymbol": summarize_by(funded, lambda t: t["symbol"], "netRAfterFunding"),
        "byYear": summarize_by(funded, lambda t: t["exitTime"][:4], "netRAfterFunding"),
        "datasets": datasets,
        "trades": funded,
    }
    OUT_JSON.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({
        "outJson": str(OUT_JSON),
        "baselineTrades": baseline["fundingAdjustedStats"]["trades"],
        "variantTrades": adjusted_stats["trades"],
        "baselineAdjustedR": baseline["fundingAdjustedStats"]["totalR"],
        "variantAdjustedR": adjusted_stats["totalR"],
        "deltaAdjustedR": adjusted_stats["totalR"] - baseline["fundingAdjustedStats"]["totalR"],
        "baselineMaxDdR": baseline["fundingAdjustedStats"]["maxDrawdownR"],
        "variantMaxDdR": adjusted_stats["maxDrawdownR"],
        "baselinePf": baseline["fundingAdjustedStats"]["profitFactor"],
        "variantPf": adjusted_stats["profitFactor"],
        "baselineCap6EqualEnding": baseline["portfolioCap6Equal"]["endingEquity"],
        "variantCap6EqualEnding": cap_equal["endingEquity"],
        "sideCounts": result["sideCounts"],
        "signalTypeCounts": result["signalTypeCounts"],
    }, indent=2))


if __name__ == "__main__":
    main()
