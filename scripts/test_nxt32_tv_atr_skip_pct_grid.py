from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import backtest_nxt31_utc7_latest as base
import backtest_nxt32_native_1d_latest as native
import rebuild_nxt32_native_1d_tv_atr_latest as tv_atr
from test_nxt32_tv_atr_skip_20pct_reversal import backtest_symbol as backtest_20pct


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "outputs" / "nxt32_tv_atr_skip_pct_grid_6y"
OUT_JSON = OUT_DIR / "nxt32_tv_atr_skip_pct_grid_6y_results.json"
OUT_XLSX_PREFIX = "NXT32_TV_ATR_Skip_Pct_Grid"


def backtest_with_threshold(symbol: str, candles: list[dict], threshold: float) -> tuple[list[dict], list[dict]]:
    if abs(threshold - 0.20) < 1e-12:
        return backtest_20pct(symbol, candles)

    trades, skipped, pos, n = [], [], None, 1
    skip_reversal = None
    for i in range(55, len(candles) - 1):
        c, prev, nxt = candles[i], candles[i - 1], candles[i + 1]
        next_date = base.date.fromisoformat(nxt["localDate"])
        if next_date < base.START_DATE or next_date >= base.END_DATE:
            continue

        skip_reversal = None
        if pos:
            side = pos["side"]
            if side == "LONG":
                pos["favorablePct"] = pos["favorablePct"] or c["high"] >= pos["entry"] * (1 + threshold)
            else:
                pos["favorablePct"] = pos["favorablePct"] or c["low"] <= pos["entry"] * (1 - threshold)

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
                        if pos["favorablePct"]:
                            skip_reversal = "SHORT"
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
                        if pos["favorablePct"]:
                            skip_reversal = "LONG"

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
                    "favorableThresholdReached": pos["favorablePct"],
                    "notes": f"Binance native 1D candles; TradingView ATR RMA; skip opposite SSL flip after prior {threshold:.0%} favorable move",
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

        if skip_reversal == "LONG" and long_ok:
            skipped.append({"symbol": symbol, "date": c["localDate"], "side": "LONG", "threshold": threshold})
            long_ok = False
        if skip_reversal == "SHORT" and short_ok:
            skipped.append({"symbol": symbol, "date": c["localDate"], "side": "SHORT", "threshold": threshold})
            short_ok = False

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
            "favorablePct": False,
        }
    return trades, skipped


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    datasets = {}
    enriched_by_symbol = {}
    for symbol in base.SYMBOLS:
        candles = tv_atr.enrich_tv_atr(native.fetch_native_1d(symbol))
        enriched_by_symbol[symbol] = candles
        datasets[symbol] = {
            "dailyRows": len(candles),
            "firstDay": candles[0]["localDate"],
            "lastDay": candles[-1]["localDate"],
            "source": "Binance spot native 1D klines",
        }

    results = []
    thresholds = [0.15, 0.20, 0.25, 0.30]
    for threshold in thresholds:
        all_trades = []
        all_skipped = []
        for symbol, candles in enriched_by_symbol.items():
            trades, skipped = backtest_with_threshold(symbol, candles, threshold)
            all_trades.extend(trades)
            all_skipped.extend(skipped)
        all_trades.sort(key=lambda x: x["exitTime"])
        result = {
            "threshold": threshold,
            "stats": base.stats(all_trades),
            "trades": all_trades,
            "skippedSignals": all_skipped,
        }
        results.append(result)

        workbook_result = {
            "generatedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "systemVersion": f"NXT v3.2 TV ATR + Skip Opposite SSL Flip After {threshold:.0%} Favorable Prior Move",
            "period": {
                "start": base.START_DATE.isoformat(),
                "end": (base.END_DATE - base.timedelta(days=1)).isoformat(),
                "timezone": "Binance native daily candles",
            },
            "symbols": base.SYMBOLS,
            "stats": result["stats"],
            "trades": all_trades,
            "datasets": datasets,
            "assumptions": [
                "Baseline is current NXT v3.2 Simple with Binance native 1D candles and TradingView ATR RMA.",
                f"Test filter only: if the previous trade moved at least {threshold:.0%} in favor from entry, skip the opposite SSL flip entry on the exit candle.",
                "This is a test output only and is not promoted to latest.",
            ],
        }
        native.OUT_XLSX = OUT_DIR / f"{OUT_XLSX_PREFIX}_{int(threshold * 100)}Pct_6Y_BTC_SOL_SUI_20K.xlsx"
        native.build_workbook(workbook_result)

    baseline = json.loads((ROOT / "latest" / "NXT_Latest_NXT32_Native1D_RunnerA_NoContinuation_NoRiskOff_6Y_BTC_SOL_SUI_20K.json").read_text(encoding="utf-8"))
    payload = {
        "generatedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "baselineStats": baseline["stats"],
        "results": results,
    }
    OUT_JSON.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps({
        "outJson": str(OUT_JSON),
        "workbooks": [str(OUT_DIR / f"{OUT_XLSX_PREFIX}_{int(t * 100)}Pct_6Y_BTC_SOL_SUI_20K.xlsx") for t in thresholds],
        "baseline": baseline["stats"],
        "summary": [
            {
                "threshold": f"{r['threshold']:.0%}",
                "trades": r["stats"]["trades"],
                "totalR": r["stats"]["totalR"],
                "winRate": r["stats"]["winRate"],
                "maxDrawdownR": r["stats"]["maxDrawdownR"],
                "skipped": len(r["skippedSignals"]),
            }
            for r in results
        ],
    }, indent=2))


if __name__ == "__main__":
    main()
