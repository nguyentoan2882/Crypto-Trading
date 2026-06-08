from __future__ import annotations

import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import backtest_nxt31_utc7_latest as base
import backtest_nxt32_native_1d_latest as native


ROOT = Path(__file__).resolve().parents[1]
OUT_JSON = ROOT / "outputs" / "nxt32_native_1d_tv_atr_latest" / "nxt32_native_1d_tv_atr_latest_results.json"
OUT_XLSX = ROOT / "outputs" / "nxt32_native_1d_tv_atr_latest" / "NXT32_Native1D_TV_ATR_RunnerA_NoContinuation_NoRiskOff_6Y_BTC_SOL_SUI_20K.xlsx"
LATEST = ROOT / "latest"
LATEST_JSON = LATEST / "NXT_Latest_NXT32_Native1D_RunnerA_NoContinuation_NoRiskOff_6Y_BTC_SOL_SUI_20K.json"
LATEST_XLSX = LATEST / "NXT_Latest_NXT32_Native1D_RunnerA_NoContinuation_NoRiskOff_6Y_BTC_SOL_SUI_20K.xlsx"
LATEST_SUMMARY = LATEST / "NXT_Latest_Summary.md"


def atr_rma(candles: list[dict], period: int = 14) -> list[float | None]:
    tr = []
    for i, c in enumerate(candles):
        if i == 0:
            tr.append(c["high"] - c["low"])
        else:
            pc = candles[i - 1]["close"]
            tr.append(max(c["high"] - c["low"], abs(c["high"] - pc), abs(c["low"] - pc)))

    out: list[float | None] = [None] * len(candles)
    if len(tr) < period:
        return out

    prev = sum(tr[:period]) / period
    out[period - 1] = prev
    for i in range(period, len(tr)):
        prev = (prev * (period - 1) + tr[i]) / period
        out[i] = prev
    return out


def enrich_tv_atr(candles: list[dict]) -> list[dict]:
    enriched = base.enrich(candles)
    tv_atr = atr_rma(enriched, 14)
    for i, c in enumerate(enriched):
        c["atr14"] = tv_atr[i]
    return enriched


def main() -> None:
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)

    all_trades = []
    datasets = {}
    for symbol in base.SYMBOLS:
        candles = enrich_tv_atr(native.fetch_native_1d(symbol))
        datasets[symbol] = {
            "dailyRows": len(candles),
            "firstDay": candles[0]["localDate"],
            "lastDay": candles[-1]["localDate"],
            "source": "Binance spot native 1D klines",
        }
        all_trades.extend(base_trade_without_anti_reversal(symbol, candles))

    all_trades.sort(key=lambda x: x["exitTime"])
    result = {
        "generatedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "systemVersion": "NXT v3.2 Simple + Binance Native 1D + TradingView ATR RMA + Runner A + No Continuation + No Risk-Off",
        "period": {
            "start": base.START_DATE.isoformat(),
            "end": (base.END_DATE - base.timedelta(days=1)).isoformat(),
            "timezone": "Binance native daily candles",
        },
        "symbols": base.SYMBOLS,
        "stats": base.stats(all_trades),
        "trades": all_trades,
        "datasets": datasets,
        "assumptions": [
            "Daily candles use Binance native 1D klines, matching TradingView BTCUSDT 1D Binance indicator values.",
            "ATR14 uses TradingView's default Wilder RMA smoothing.",
            "SSL Channel is approximated with SMA(high,10) and SMA(low,10); state flips bullish when close is above high SMA and bearish when close is below low SMA.",
            "Primary LONG: SSL flips bullish, price crosses above EMA20 within 3 candles, distance to EMA50 <= 2 ATR, RSI14 > 50.",
            "Primary SHORT: SSL flips bearish, price crosses below EMA20 within 3 candles, distance to EMA50 <= 2 ATR, RSI14 < 50.",
            "Runner A: close 50% at 2.5 ATR, move remaining 50% to breakeven, exit runner on opposite SSL flip.",
            "Continuation and risk-off overlays are disabled.",
        ],
    }

    OUT_JSON.write_text(json.dumps(result, indent=2), encoding="utf-8")
    native.OUT_XLSX = OUT_XLSX
    native.build_workbook(result)

    shutil.copy2(OUT_JSON, LATEST_JSON)
    shutil.copy2(OUT_XLSX, LATEST_XLSX)
    LATEST_SUMMARY.write_text(
        "\n".join(
            [
                "# Latest NXT System",
                "",
                f"System: {result['systemVersion']}",
                "",
                f"Trades: {result['stats']['trades']}",
                f"Total R: {result['stats']['totalR']:.2f}R",
                f"Max DD R: {result['stats']['maxDrawdownR']:.2f}R",
                f"Win rate: {result['stats']['winRate']:.2%}",
                f"20K Account ending: ${20000 + result['stats']['totalR'] * 1000:,.2f}",
                "",
                "Notes: Uses Binance native 1D candles and TradingView ATR RMA. Continuation and risk-off are disabled.",
                "",
                f"Workbook: {LATEST_XLSX.name}",
                f"JSON: {LATEST_JSON.name}",
                "System doc: NXT_Latest_NXT32_System_And_Indicators.docx",
            ]
        ),
        encoding="utf-8",
    )


def base_trade_without_anti_reversal(symbol: str, candles: list[dict]) -> list[dict]:
    trades, pos, n = [], None, 1
    for i in range(55, len(candles) - 1):
        c, prev, nxt = candles[i], candles[i - 1], candles[i + 1]
        next_date = base.date.fromisoformat(nxt["localDate"])
        if next_date < base.START_DATE or next_date >= base.END_DATE:
            continue
        if pos:
            side = pos["side"]
            ssl_flip = (side == "LONG" and prev["ssl"] == 1 and c["ssl"] == -1) or (side == "SHORT" and prev["ssl"] == -1 and c["ssl"] == 1)
            exit_price = reason = None
            if side == "LONG":
                if c["low"] <= pos["stop"]:
                    exit_price = pos["stop"]
                    reason = "Breakeven stop" if pos["triggered"] else "Stop loss"
                else:
                    if not pos["triggered"] and c["high"] >= pos["tp"]:
                        pos["triggered"] = True
                        pos["tp1Time"] = c["localDate"]
                        pos["stop"] = pos["entry"]
                        pos["realizedR"] += 0.5 * ((pos["tp"] - pos["entry"]) / pos["risk"])
                    if ssl_flip:
                        exit_price = c["close"]
                        reason = "Runner exit: SSL bearish flip"
            else:
                if c["high"] >= pos["stop"]:
                    exit_price = pos["stop"]
                    reason = "Breakeven stop" if pos["triggered"] else "Stop loss"
                else:
                    if not pos["triggered"] and c["low"] <= pos["tp"]:
                        pos["triggered"] = True
                        pos["tp1Time"] = c["localDate"]
                        pos["stop"] = pos["entry"]
                        pos["realizedR"] += 0.5 * ((pos["entry"] - pos["tp"]) / pos["risk"])
                    if ssl_flip:
                        exit_price = c["close"]
                        reason = "Runner exit: SSL bullish flip"
            if exit_price is not None:
                rem = 0.5 if pos["triggered"] else 1.0
                rem_r = (exit_price - pos["entry"]) / pos["risk"] if side == "LONG" else (pos["entry"] - exit_price) / pos["risk"]
                gross = pos["realizedR"] + rem * rem_r
                net = gross - base.cost_r(pos["entry"], pos["risk"])
                trades.append({
                    "symbol": symbol,
                    "tradeNo": n,
                    "side": side,
                    "signalTime": pos["signalDate"],
                    "entryTime": pos["entryDate"],
                    "entryPrice": pos["entry"],
                    "initialStop": pos["initialStop"],
                    "finalStop": pos["stop"],
                    "riskPerUnit": pos["risk"],
                    "tp1": pos["tp"],
                    "tp1Time": pos["tp1Time"],
                    "exitTime": c["localDate"],
                    "exitPrice": exit_price,
                    "exitReason": reason,
                    "grossRMultiple": gross,
                    "costR": base.cost_r(pos["entry"], pos["risk"]),
                    "rMultiple": net,
                    "atr14": pos["atr14"],
                    "rsi14": pos["rsi14"],
                    "distanceToEma50Atr": pos["distance"],
                    "notes": "Binance native 1D candles; TradingView ATR RMA; NXT v3.2 Runner A; no continuation; no risk-off",
                })
                n += 1
                pos = None
            if pos:
                continue

        if any(c[k] is None for k in ["ema20", "ema50", "atr14", "rsi14", "ssl"]) or prev["ssl"] is None:
            continue
        dist = abs(c["close"] - c["ema50"]) / c["atr14"]
        long_ok = prev["ssl"] == -1 and c["ssl"] == 1 and base.recent_cross(candles, i, "LONG") and dist <= 2 and c["rsi14"] > 50
        short_ok = prev["ssl"] == 1 and c["ssl"] == -1 and base.recent_cross(candles, i, "SHORT") and dist <= 2 and c["rsi14"] < 50
        if not (long_ok or short_ok):
            continue
        side = "LONG" if long_ok else "SHORT"
        risk = c["atr14"] * 1.5
        entry = nxt["open"]
        pos = {
            "side": side,
            "signalDate": c["localDate"],
            "entryDate": nxt["localDate"],
            "entry": entry,
            "initialStop": entry - risk if side == "LONG" else entry + risk,
            "stop": entry - risk if side == "LONG" else entry + risk,
            "risk": risk,
            "tp": entry + c["atr14"] * 2.5 if side == "LONG" else entry - c["atr14"] * 2.5,
            "triggered": False,
            "tp1Time": "",
            "realizedR": 0.0,
            "atr14": c["atr14"],
            "rsi14": c["rsi14"],
            "distance": dist,
        }
    return trades


if __name__ == "__main__":
    main()
