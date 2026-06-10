from __future__ import annotations

import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import backtest_nxt31_utc7_latest as base
import backtest_nxt32_native_1d_latest as native
import rebuild_nxt32_native_1d_tv_atr_latest as tv_atr


ROOT = Path.cwd()
OUT_DIR = ROOT / "outputs" / "nxt32_whipsaw_guard_grid"
OUT_JSON = OUT_DIR / "nxt32_whipsaw_guard_grid_results.json"
BASELINE_JSON = ROOT / "latest" / "NXT_Latest_NXT32_Native1D_RunnerA_NoContinuation_NoRiskOff_6Y_BTC_SOL_SUI_20K.json"
WORKBOOK_VARIANTS = {
    "universal_ssl_flip_density_30d_max5",
    "universal_ssl_flip_density_20d_max3",
}

WHIPSAW_WINDOWS = [
    ("2020-05-29", "2020-07-07"),
    ("2022-05-31", "2022-10-05"),
    ("2023-08-02", "2023-10-12"),
]


def trade_in_window(trade: dict, start: str, end: str) -> bool:
    entry = date.fromisoformat(trade["entryTime"])
    return date.fromisoformat(start) <= entry <= date.fromisoformat(end)


def window_breakdown(trades: list[dict]) -> list[dict]:
    rows = []
    for start, end in WHIPSAW_WINDOWS:
        subset = [t for t in trades if trade_in_window(t, start, end)]
        rows.append(
            {
                "start": start,
                "end": end,
                "trades": len(subset),
                "wins": sum(1 for t in subset if t["rMultiple"] > 0),
                "totalR": sum(t["rMultiple"] for t in subset),
                "bySymbol": {
                    symbol: {
                        "trades": len([t for t in subset if t["symbol"] == symbol]),
                        "totalR": sum(t["rMultiple"] for t in subset if t["symbol"] == symbol),
                    }
                    for symbol in sorted({t["symbol"] for t in subset})
                },
            }
        )
    rows.append(
        {
            "start": "combined",
            "end": "combined",
            "trades": sum(r["trades"] for r in rows),
            "wins": sum(r["wins"] for r in rows),
            "totalR": sum(r["totalR"] for r in rows),
            "bySymbol": {},
        }
    )
    return rows


def ssl_flip_count(candles: list[dict], index: int, lookback: int) -> int:
    start = max(1, index - lookback + 1)
    return sum(
        1
        for i in range(start, index + 1)
        if candles[i].get("ssl") is not None
        and candles[i - 1].get("ssl") is not None
        and candles[i]["ssl"] != candles[i - 1]["ssl"]
    )


def backtest_symbol(symbol: str, candles: list[dict], cfg: dict) -> tuple[list[dict], list[dict]]:
    trades, skipped = [], []
    pos = None
    trade_no = 1
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
                pos["favorable20PctReached"] = pos["favorable20PctReached"] or c["high"] >= pos["entry"] * 1.20
            else:
                pos["favorable20PctReached"] = pos["favorable20PctReached"] or c["low"] <= pos["entry"] * 0.80

            ssl_flip = (side == "LONG" and prev["ssl"] == 1 and c["ssl"] == -1) or (
                side == "SHORT" and prev["ssl"] == -1 and c["ssl"] == 1
            )
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
                        if pos["favorable20PctReached"]:
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
                        if pos["favorable20PctReached"]:
                            skip_reversal = "LONG"

            if exit_price is not None:
                rem = 0.5 if pos["triggered"] else 1.0
                rem_r = (exit_price - pos["entry"]) / pos["risk"] if side == "LONG" else (pos["entry"] - exit_price) / pos["risk"]
                gross = pos["realizedR"] + rem * rem_r
                cost = base.cost_r(pos["entry"], pos["risk"])
                trades.append(
                    {
                        "symbol": symbol,
                        "tradeNo": trade_no,
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
                        "costR": cost,
                        "rMultiple": gross - cost,
                        "atr14": pos["atr14"],
                        "rsi14": pos["rsi14"],
                        "distanceToEma50Atr": pos["distance"],
                        "sslFlipCount": pos["sslFlipCount"],
                        "favorable20PctReached": pos["favorable20PctReached"],
                        "notes": cfg["notes"],
                    }
                )
                trade_no += 1
                pos = None
            if pos:
                continue

        if any(c[k] is None for k in ["ema20", "ema50", "atr14", "rsi14", "ssl"]) or prev["ssl"] is None:
            continue
        dist = abs(c["close"] - c["ema50"]) / c["atr14"]
        long_ok = prev["ssl"] == -1 and c["ssl"] == 1 and base.recent_cross(candles, i, "LONG") and dist <= 2 and c["rsi14"] > 50
        short_ok = prev["ssl"] == 1 and c["ssl"] == -1 and base.recent_cross(candles, i, "SHORT") and dist <= 2 and c["rsi14"] < 50

        if skip_reversal == "LONG" and long_ok:
            skipped.append({"symbol": symbol, "date": c["localDate"], "side": "LONG", "reason": "20pct_reversal_skip"})
            long_ok = False
        if skip_reversal == "SHORT" and short_ok:
            skipped.append({"symbol": symbol, "date": c["localDate"], "side": "SHORT", "reason": "20pct_reversal_skip"})
            short_ok = False

        if long_ok or short_ok:
            applies = (not cfg.get("btcOnly")) or symbol == "BTCUSDT"
            flips = ssl_flip_count(candles, i, cfg["lookback"])
            if applies and flips > cfg["maxFlips"]:
                skipped.append(
                    {
                        "symbol": symbol,
                        "date": c["localDate"],
                        "side": "LONG" if long_ok else "SHORT",
                        "reason": "ssl_flip_density",
                        "lookback": cfg["lookback"],
                        "sslFlipCount": flips,
                    }
                )
                long_ok = short_ok = False
            elif applies and dist < cfg.get("minDistanceToEma50Atr", 0):
                skipped.append(
                    {
                        "symbol": symbol,
                        "date": c["localDate"],
                        "side": "LONG" if long_ok else "SHORT",
                        "reason": "min_distance_to_ema50_atr",
                        "distanceToEma50Atr": dist,
                    }
                )
                long_ok = short_ok = False

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
            "sslFlipCount": ssl_flip_count(candles, i, cfg["lookback"]),
            "favorable20PctReached": False,
        }

    return trades, skipped


def run_variant(cfg: dict, candles_by_symbol: dict[str, list[dict]]) -> dict:
    all_trades, all_skipped = [], []
    for symbol, candles in candles_by_symbol.items():
        trades, skipped = backtest_symbol(symbol, candles, cfg)
        all_trades.extend(trades)
        all_skipped.extend(skipped)
    all_trades.sort(key=lambda t: t["exitTime"])
    return {
        "name": cfg["name"],
        "rule": cfg["description"],
        "stats": base.stats(all_trades),
        "whipsawWindows": window_breakdown(all_trades),
        "skippedSignals": all_skipped,
        "trades": all_trades,
    }


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    baseline = json.loads(BASELINE_JSON.read_text(encoding="utf-8"))
    candles_by_symbol = {symbol: tv_atr.enrich_tv_atr(native.fetch_native_1d(symbol)) for symbol in base.SYMBOLS}
    datasets = {
        symbol: {
            "dailyRows": len(candles),
            "firstDay": candles[0]["localDate"],
            "lastDay": candles[-1]["localDate"],
            "source": "Binance spot native 1D klines",
        }
        for symbol, candles in candles_by_symbol.items()
    }

    variants = [
        {
            "name": "universal_ssl_flip_density_30d_max5",
            "lookback": 30,
            "maxFlips": 5,
            "description": "Skip any entry when the previous 30 daily candles already contain more than 5 SSL direction flips.",
            "notes": "NXT v3.2 latest plus universal SSL flip-density whipsaw guard, 30D max 5 flips.",
        },
        {
            "name": "universal_ssl_flip_density_20d_max3",
            "lookback": 20,
            "maxFlips": 3,
            "description": "Skip any entry when the previous 20 daily candles already contain more than 3 SSL direction flips.",
            "notes": "NXT v3.2 latest plus universal SSL flip-density whipsaw guard, 20D max 3 flips.",
        },
        {
            "name": "universal_ssl_flip_density_20d_max3_min_dist_005",
            "lookback": 20,
            "maxFlips": 3,
            "minDistanceToEma50Atr": 0.05,
            "description": "Skip any entry when the previous 20 daily candles contain more than 3 SSL flips, or entry is extremely close to EMA50 (<0.05 ATR).",
            "notes": "NXT v3.2 latest plus 20D max 3 SSL flips and tiny EMA50 distance guard.",
        },
        {
            "name": "btc_only_ssl_flip_density_25d_max4_min_dist_005",
            "lookback": 25,
            "maxFlips": 4,
            "minDistanceToEma50Atr": 0.05,
            "btcOnly": True,
            "description": "BTC-only test: skip BTC entries when previous 25 daily candles contain more than 4 SSL flips, or BTC entry is <0.05 ATR from EMA50.",
            "notes": "NXT v3.2 latest plus BTC-only 25D max 4 SSL flips and tiny EMA50 distance guard.",
        },
    ]

    results = [run_variant(cfg, candles_by_symbol) for cfg in variants]
    workbook_paths = []
    for result in results:
        if result["name"] not in WORKBOOK_VARIANTS:
            continue
        workbook_payload = {
            "generatedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "systemVersion": f"NXT v3.2 Latest + Whipsaw Guard Test - {result['name']}",
            "period": {
                "start": base.START_DATE.isoformat(),
                "end": (base.END_DATE - base.timedelta(days=1)).isoformat(),
                "timezone": "Binance native daily candles",
            },
            "symbols": base.SYMBOLS,
            "stats": result["stats"],
            "trades": result["trades"],
            "datasets": datasets,
            "assumptions": [
                "Baseline is current latest NXT v3.2 with Binance native 1D candles, TradingView ATR RMA, Runner A, 20% reversal-skip, no continuation, and no risk-off.",
                result["rule"],
                "This is a test output only and is not promoted to latest.",
            ],
        }
        native.OUT_XLSX = OUT_DIR / f"{result['name']}.xlsx"
        if not native.OUT_XLSX.exists():
            native.build_workbook(workbook_payload)
        workbook_paths.append(str(native.OUT_XLSX))

    payload = {
        "generatedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "baseline": {
            "name": "latest_nxt32",
            "stats": baseline["stats"],
            "whipsawWindows": window_breakdown(baseline["trades"]),
        },
        "results": results,
        "workbooks": workbook_paths,
    }
    OUT_JSON.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(
        {
            "outJson": str(OUT_JSON),
            "workbooks": workbook_paths,
            "baseline": {
                "totalR": baseline["stats"]["totalR"],
                "maxDrawdownR": baseline["stats"]["maxDrawdownR"],
                "whipsawCombinedR": payload["baseline"]["whipsawWindows"][-1]["totalR"],
            },
            "summary": [
                {
                    "name": r["name"],
                    "trades": r["stats"]["trades"],
                    "totalR": r["stats"]["totalR"],
                    "maxDrawdownR": r["stats"]["maxDrawdownR"],
                    "whipsawCombinedR": r["whipsawWindows"][-1]["totalR"],
                    "skipped": len(r["skippedSignals"]),
                }
                for r in results
            ],
        },
        indent=2,
    ))


if __name__ == "__main__":
    main()
