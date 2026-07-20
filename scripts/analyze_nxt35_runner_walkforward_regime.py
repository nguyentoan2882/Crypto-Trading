from __future__ import annotations

import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import backtest_nxt35_latest_to_today as latest
from test_nxt33_ssl14 import enrich_with_ssl_period


ROOT = Path(__file__).resolve().parents[1]
SOURCE_JSON = ROOT / "outputs" / "nxt35_runner_exit_variants" / "NXT35_Runner_Exit_Variants.json"
OUT_JSON = ROOT / "outputs" / "nxt35_runner_exit_variants" / "NXT35_Runner_WalkForward_Regime.json"
FOCUS = ["baseline_ssl_flip", "runner_only_ema50_close"]


def ema(values: list[float | None], period: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    valid = [v for v in values[:period] if v is not None]
    if len(valid) < period:
        return out
    prev = sum(valid) / period
    out[period - 1] = prev
    alpha = 2 / (period + 1)
    for i in range(period, len(values)):
        if values[i] is None:
            continue
        prev = values[i] * alpha + prev * (1 - alpha)
        out[i] = prev
    return out


def add_btc_regime(candles: list[dict]) -> dict[str, dict]:
    ema200 = ema([c["close"] for c in candles], 200)
    for i, candle in enumerate(candles):
        candle["ema200"] = ema200[i]
        if candle.get("atr14") is not None and candle.get("close"):
            atr_pct = candle["atr14"] / candle["close"]
            vals = [
                candles[j]["atr14"] / candles[j]["close"]
                for j in range(max(0, i - 179), i + 1)
                if candles[j].get("atr14") is not None and candles[j].get("close")
            ]
            candle["atrPct"] = atr_pct
            candle["atrPctRank180"] = sum(1 for v in vals if v <= atr_pct) / len(vals) if vals else None
        else:
            candle["atrPct"] = None
            candle["atrPctRank180"] = None
        if candle.get("ema50") is None:
            candle["btcTrendRegime"] = "unknown"
        elif candle["close"] > candle["ema50"] and candle["ema20"] > candle["ema50"]:
            candle["btcTrendRegime"] = "bull_structure"
        elif candle["close"] < candle["ema50"] and candle["ema20"] < candle["ema50"]:
            candle["btcTrendRegime"] = "bear_structure"
        else:
            candle["btcTrendRegime"] = "mixed_transition"
        candle["highVolChop"] = bool(
            candle.get("atrPctRank180") is not None
            and candle["atrPctRank180"] >= 0.70
            and candle.get("ema50") is not None
            and abs(candle["close"] - candle["ema50"]) < candle["atr14"]
        )
        candle["ema200Regime"] = (
            "above_ema200"
            if candle.get("ema200") is not None and candle["close"] > candle["ema200"]
            else "below_ema200"
            if candle.get("ema200") is not None
            else "unknown"
        )
    return {c["localDate"]: c for c in candles}


def stats(trades: list[dict]) -> dict:
    total = sum(t["netRAfterFunding"] for t in trades)
    wins = sum(1 for t in trades if t["netRAfterFunding"] > 0)
    gp = sum(t["netRAfterFunding"] for t in trades if t["netRAfterFunding"] > 0)
    gl = -sum(t["netRAfterFunding"] for t in trades if t["netRAfterFunding"] < 0)
    return {
        "trades": len(trades),
        "wins": wins,
        "losses": len(trades) - wins,
        "winRate": wins / len(trades) if trades else 0.0,
        "totalR": total,
        "avgR": total / len(trades) if trades else 0.0,
        "profitFactor": gp / gl if gl else None,
    }


def group_by(trades: list[dict], key_fn) -> list[dict]:
    groups: dict[str, list[dict]] = {}
    for trade in trades:
        groups.setdefault(key_fn(trade), []).append(trade)
    return [dict(group=key, **stats(rows)) for key, rows in sorted(groups.items())]


def annotate_regime(trades: list[dict], btc_by_date: dict[str, dict]) -> list[dict]:
    out = []
    for trade in trades:
        row = dict(trade)
        btc = btc_by_date.get(trade["signalTime"]) or btc_by_date.get(trade["entryTime"])
        if btc is None:
            row["btcTrendRegime"] = "unknown"
            row["highVolChop"] = "unknown"
            row["ema200Regime"] = "unknown"
            row["directionVsBtcTrend"] = "unknown"
        else:
            row["btcTrendRegime"] = btc["btcTrendRegime"]
            row["highVolChop"] = "high_vol_chop" if btc["highVolChop"] else "not_high_vol_chop"
            row["ema200Regime"] = btc["ema200Regime"]
            if (trade["side"] == "LONG" and btc["btcTrendRegime"] == "bull_structure") or (
                trade["side"] == "SHORT" and btc["btcTrendRegime"] == "bear_structure"
            ):
                row["directionVsBtcTrend"] = "with_btc_trend"
            elif btc["btcTrendRegime"] == "mixed_transition":
                row["directionVsBtcTrend"] = "mixed_transition"
            else:
                row["directionVsBtcTrend"] = "against_btc_trend"
        out.append(row)
    return out


def by_year_map(trades: list[dict]) -> dict[int, dict]:
    result = {}
    for year in sorted({int(t["exitTime"][:4]) for t in trades}):
        result[year] = stats([t for t in trades if int(t["exitTime"][:4]) == year])
    return result


def walk_forward(results: list[dict]) -> list[dict]:
    years = sorted({int(t["exitTime"][:4]) for row in results for t in row["trades"]})
    out = []
    for test_year in years[1:]:
        ranked = []
        for row in results:
            train_trades = [t for t in row["trades"] if int(t["exitTime"][:4]) < test_year]
            test_trades = [t for t in row["trades"] if int(t["exitTime"][:4]) == test_year]
            if not train_trades or not test_trades:
                continue
            ranked.append(
                {
                    "variant": row["variant"]["key"],
                    "train": stats(train_trades),
                    "test": stats(test_trades),
                }
            )
        ranked.sort(key=lambda x: (x["train"]["totalR"], x["train"]["profitFactor"] or 0), reverse=True)
        selected = ranked[0]
        baseline = next(x for x in ranked if x["variant"] == "baseline_ssl_flip")
        ema50 = next(x for x in ranked if x["variant"] == "runner_only_ema50_close")
        out.append(
            {
                "testYear": test_year,
                "selectedByPriorYears": selected,
                "baselineTest": baseline["test"],
                "runnerOnlyEma50Test": ema50["test"],
                "selectedDeltaVsBaselineTestR": selected["test"]["totalR"] - baseline["test"]["totalR"],
                "ema50DeltaVsBaselineTestR": ema50["test"]["totalR"] - baseline["test"]["totalR"],
            }
        )
    return out


def main() -> None:
    source = json.loads(SOURCE_JSON.read_text(encoding="utf-8"))
    requested_end = date.fromisoformat(source["period"].get("requestedEnd", source["period"]["lastDataDate"]))
    end = date.fromisoformat(source["period"]["lastDataDate"])
    btc = enrich_with_ssl_period(latest.fetch_usdm_1d("BTCUSDT", requested_end), 14)
    btc = [c for c in btc if date.fromisoformat(c["localDate"]) <= end]
    btc_by_date = add_btc_regime(btc)

    annotated_results = []
    for row in source["results"]:
        trades = annotate_regime(row["trades"], btc_by_date)
        annotated_results.append({**row, "trades": trades})

    focus_rows = []
    for key in FOCUS:
        row = next(r for r in annotated_results if r["variant"]["key"] == key)
        focus_rows.append(
            {
                "variant": key,
                "overall": row["fundingAdjustedStats"],
                "byYear": group_by(row["trades"], lambda t: t["exitTime"][:4]),
                "byBtcTrendRegime": group_by(row["trades"], lambda t: t["btcTrendRegime"]),
                "byDirectionVsBtcTrend": group_by(row["trades"], lambda t: t["directionVsBtcTrend"]),
                "byHighVolChop": group_by(row["trades"], lambda t: t["highVolChop"]),
                "byEma200Regime": group_by(row["trades"], lambda t: t["ema200Regime"]),
            }
        )

    base = next(r for r in focus_rows if r["variant"] == "baseline_ssl_flip")
    ema50 = next(r for r in focus_rows if r["variant"] == "runner_only_ema50_close")
    walk = walk_forward(annotated_results)
    payload = {
        "generatedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "source": str(SOURCE_JSON),
        "period": source["period"],
        "method": {
            "walkForward": "For each year after the first, select the best runner-exit variant using all prior exit years, then score it on the next exit year.",
            "regime": "Classify each trade by BTC regime on signal date: BTC EMA20/EMA50 trend structure, high-volatility chop, EMA200 side, and trade direction vs BTC trend.",
        },
        "focusComparison": {
            "baseline": base,
            "runnerOnlyEma50": ema50,
            "deltaOverall": {
                "trades": ema50["overall"]["trades"] - base["overall"]["trades"],
                "totalR": ema50["overall"]["totalR"] - base["overall"]["totalR"],
                "winRate": ema50["overall"]["winRate"] - base["overall"]["winRate"],
                "maxDrawdownR": ema50["overall"]["maxDrawdownR"] - base["overall"]["maxDrawdownR"],
                "profitFactor": ema50["overall"]["profitFactor"] - base["overall"]["profitFactor"],
            },
        },
        "walkForward": walk,
        "allVariantYearStats": [
            {
                "variant": row["variant"]["key"],
                "byYear": by_year_map(row["trades"]),
            }
            for row in annotated_results
        ],
    }
    OUT_JSON.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps({
        "outJson": str(OUT_JSON),
        "overallDeltaR": payload["focusComparison"]["deltaOverall"]["totalR"],
        "walkForward": [
            {
                "year": row["testYear"],
                "selected": row["selectedByPriorYears"]["variant"],
                "selectedTestR": row["selectedByPriorYears"]["test"]["totalR"],
                "baselineTestR": row["baselineTest"]["totalR"],
                "ema50TestR": row["runnerOnlyEma50Test"]["totalR"],
                "ema50DeltaR": row["ema50DeltaVsBaselineTestR"],
            }
            for row in walk
        ],
        "regimeEma50": {
            "byBtcTrendRegime": ema50["byBtcTrendRegime"],
            "byDirectionVsBtcTrend": ema50["byDirectionVsBtcTrend"],
            "byHighVolChop": ema50["byHighVolChop"],
        },
    }, indent=2))


if __name__ == "__main__":
    main()
