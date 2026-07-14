from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import promote_nxt34_btc_bnb_sol_latest as latest_runner
from test_nxt33_ssl14 import enrich_with_ssl_period


ROOT = Path(__file__).resolve().parents[1]
LATEST_JSON = ROOT / "latest" / "NXT_Latest_NXT35_BTC_BNB_SOL_FundingAdjusted_20K.json"
OUT_DIR = ROOT / "outputs" / "nxt35_regime_throttle_variants"
OUT_JSON = OUT_DIR / "NXT35_Regime_Throttle_Variants.json"

STARTING_EQUITY = 20_000.0
ONE_R_DOLLARS = 1_000.0
BASE_ALLOCATIONS = {"BTCUSDT": 0.02, "BNBUSDT": 0.02, "SOLUSDT": 0.02}


def load_btc_regime() -> dict[str, dict]:
    candles = enrich_with_ssl_period(
        latest_runner.fetch_tradingview_binance_1d("BTCUSDT", latest_runner.WARMUP_DATE, latest_runner.END_DATE),
        14,
    )
    by_date = {c["localDate"]: c for c in candles}
    for i, c in enumerate(candles):
        lookback_30 = candles[max(1, i - 29): i + 1]
        c["sslFlipCount30"] = sum(
            1
            for j in range(1, len(lookback_30))
            if lookback_30[j - 1].get("ssl") is not None
            and lookback_30[j].get("ssl") is not None
            and lookback_30[j - 1]["ssl"] != lookback_30[j]["ssl"]
        )
        if c.get("ema50") is not None and i >= 20 and candles[i - 20].get("ema50") is not None:
            c["ema50Slope20"] = c["ema50"] - candles[i - 20]["ema50"]
        else:
            c["ema50Slope20"] = None
        if c.get("atr14") is not None:
            atr_pct_values = [
                candles[j]["atr14"] / candles[j]["close"]
                for j in range(max(0, i - 179), i + 1)
                if candles[j].get("atr14") is not None and candles[j].get("close")
            ]
            atr_pct = c["atr14"] / c["close"]
            c["atrPct"] = atr_pct
            c["atrPctRank180"] = sum(1 for v in atr_pct_values if v <= atr_pct) / len(atr_pct_values) if atr_pct_values else None
        else:
            c["atrPct"] = None
            c["atrPctRank180"] = None
    return by_date


def trend_quality_score(trade: dict, btc: dict) -> int:
    side = trade["side"]
    score = 0
    if side == "LONG":
        score += int(btc["close"] > btc["ema50"])
        score += int(btc["ema20"] > btc["ema50"])
        score += int(btc.get("ema50Slope20") is not None and btc["ema50Slope20"] > 0)
    else:
        score += int(btc["close"] < btc["ema50"])
        score += int(btc["ema20"] < btc["ema50"])
        score += int(btc.get("ema50Slope20") is not None and btc["ema50Slope20"] < 0)
    score += int(btc.get("sslFlipCount30", 99) <= 2)
    return score


def multiplier_for(variant_key: str, trade: dict, btc_by_date: dict[str, dict]) -> tuple[float, str]:
    btc = btc_by_date[trade["signalTime"]]
    side = trade["side"]
    if variant_key == "btc_trend_throttle":
        if side == "LONG" and btc["close"] < btc["ema50"] and btc["ema20"] < btc["ema50"]:
            return 0.5, "LONG while BTC close<EMA50 and EMA20<EMA50"
        if side == "SHORT" and btc["close"] > btc["ema50"] and btc["ema20"] > btc["ema50"]:
            return 0.5, "SHORT while BTC close>EMA50 and EMA20>EMA50"
        return 1.0, "BTC trend not adverse"
    if variant_key == "ssl_flip_density":
        if btc.get("sslFlipCount30", 0) >= 4:
            return 0.5, f"BTC SSL flips 30d={btc.get('sslFlipCount30')}"
        return 1.0, f"BTC SSL flips 30d={btc.get('sslFlipCount30')}"
    if variant_key == "trend_quality_score":
        score = trend_quality_score(trade, btc)
        return (1.0, f"score={score}") if score >= 3 else (0.5, f"score={score}")
    if variant_key == "volatility_chop":
        is_chop = (
            btc.get("atrPctRank180") is not None
            and btc["atrPctRank180"] >= 0.70
            and abs(btc["close"] - btc["ema50"]) < btc["atr14"]
        )
        if is_chop:
            return 0.5, f"ATR pct rank={btc['atrPctRank180']:.2f}; close within 1 ATR of EMA50"
        return 1.0, "not volatility chop"
    if variant_key == "quality_plus_flip":
        score = trend_quality_score(trade, btc)
        if score < 3 or btc.get("sslFlipCount30", 0) >= 4:
            return 0.5, f"score={score}; flips30={btc.get('sslFlipCount30')}"
        return 1.0, f"score={score}; flips30={btc.get('sslFlipCount30')}"
    raise ValueError(f"Unknown variant {variant_key}")


def weighted_stats(trades: list[dict], variant_key: str, btc_by_date: dict[str, dict]) -> dict:
    equity = STARTING_EQUITY
    peak = equity
    rows = []
    gross_profit = 0.0
    gross_loss = 0.0
    total_r = 0.0
    throttled = 0
    for index, trade in enumerate(trades, 1):
        mult, reason = multiplier_for(variant_key, trade, btc_by_date)
        throttled += int(mult < 1)
        effective_r = float(trade["netRAfterFunding"]) * mult
        total_r += effective_r
        if effective_r > 0:
            gross_profit += effective_r
        elif effective_r < 0:
            gross_loss += -effective_r
        pnl = effective_r * ONE_R_DOLLARS
        equity += pnl
        peak = max(peak, equity)
        rows.append(
            {
                "no": index,
                "exitTime": trade["exitTime"],
                "symbol": trade["symbol"],
                "side": trade["side"],
                "signalType": trade["signalType"],
                "sourceR": trade["netRAfterFunding"],
                "riskMultiplier": mult,
                "throttleReason": reason,
                "effectiveR": effective_r,
                "pnl": pnl,
                "equity": equity,
                "drawdown": equity - peak,
            }
        )
    wins = sum(1 for row in rows if row["effectiveR"] > 0)
    return {
        "trades": len(rows),
        "throttledTrades": throttled,
        "wins": wins,
        "losses": len(rows) - wins,
        "winRate": wins / len(rows) if rows else 0.0,
        "totalR": total_r,
        "avgR": total_r / len(rows) if rows else 0.0,
        "maxDrawdownR": min((row["drawdown"] / ONE_R_DOLLARS for row in rows), default=0.0),
        "maxDrawdownDollars": min((row["drawdown"] for row in rows), default=0.0),
        "profitFactor": gross_profit / gross_loss if gross_loss else None,
        "ending20k": equity,
        "equityCurve": rows,
    }


def trade_key(trade: dict) -> str:
    return f"{trade['symbol']}:{trade['tradeNo']}:{trade['entryTime']}:{trade['exitTime']}"


def portfolio_cap(trades: list[dict], variant_key: str, btc_by_date: dict[str, dict]) -> dict:
    events: dict[str, dict[str, list[dict]]] = {}
    for trade in trades:
        events.setdefault(trade["entryTime"], {"entries": [], "exits": []})["entries"].append(trade)
        events.setdefault(trade["exitTime"], {"entries": [], "exits": []})["exits"].append(trade)

    equity = STARTING_EQUITY
    peak = equity
    max_dd = 0.0
    max_dd_pct = 0.0
    open_risk: dict[str, dict] = {}
    rows = {}

    def current_open_risk(symbol: str | None = None) -> float:
        return sum(
            row["riskAmount"]
            for row in open_risk.values()
            if symbol is None or row["symbol"] == symbol
        )

    for event_date in sorted(events):
        same_day_keys = {
            trade_key(trade)
            for trade in events[event_date]["entries"]
            if trade["exitTime"] == event_date
        }
        regular_exits = [t for t in events[event_date]["exits"] if trade_key(t) not in same_day_keys]
        same_day_exits = [t for t in events[event_date]["exits"] if trade_key(t) in same_day_keys]

        def close_trade(trade: dict) -> None:
            nonlocal equity, peak, max_dd, max_dd_pct
            identity = trade_key(trade)
            risk_record = open_risk.pop(identity, None)
            risk_amount = risk_record["riskAmount"] if risk_record else 0.0
            pnl = risk_amount * float(trade["netRAfterFunding"])
            equity += pnl
            peak = max(peak, equity)
            dd = equity - peak
            max_dd = min(max_dd, dd)
            max_dd_pct = min(max_dd_pct, dd / peak if peak else 0.0)
            rows[identity] = {
                "riskAmount": risk_amount,
                "riskMultiplier": risk_record["multiplier"] if risk_record else 0.0,
                "pnl": pnl,
                "equity": equity,
                "drawdown": dd,
                "skipped": risk_record is None,
            }

        for trade in sorted(regular_exits, key=lambda t: (t["symbol"], t["tradeNo"])):
            close_trade(trade)
        for trade in sorted(events[event_date]["entries"], key=lambda t: (t["symbol"], t["tradeNo"])):
            symbol = trade["symbol"]
            mult, _ = multiplier_for(variant_key, trade, btc_by_date)
            symbol_capacity = max(0.0, equity * BASE_ALLOCATIONS[symbol] * mult - current_open_risk(symbol))
            portfolio_capacity = max(0.0, equity * sum(BASE_ALLOCATIONS.values()) - current_open_risk())
            risk_amount = min(symbol_capacity, portfolio_capacity)
            if risk_amount > 0:
                open_risk[trade_key(trade)] = {"symbol": symbol, "riskAmount": risk_amount, "multiplier": mult}
        for trade in sorted(same_day_exits, key=lambda t: (t["symbol"], t["tradeNo"])):
            close_trade(trade)

    return {
        "endingEquity": equity,
        "netProfit": equity - STARTING_EQUITY,
        "maxDrawdownDollars": max_dd,
        "maxDrawdownPct": max_dd_pct,
        "executedTrades": sum(1 for row in rows.values() if row["riskAmount"] > 0),
        "skippedTrades": sum(1 for row in rows.values() if row["skipped"]),
    }


def group_stats(rows: list[dict], key_fn) -> list[dict]:
    groups: dict[str, list[dict]] = {}
    for row in rows:
        groups.setdefault(key_fn(row), []).append(row)
    out = []
    for group, subset in sorted(groups.items()):
        total = sum(row["effectiveR"] for row in subset)
        out.append(
            {
                "group": group,
                "trades": len(subset),
                "throttledTrades": sum(1 for row in subset if row["riskMultiplier"] < 1),
                "totalR": total,
                "avgR": total / len(subset),
            }
        )
    return out


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    latest = json.loads(LATEST_JSON.read_text(encoding="utf-8"))
    trades = sorted(latest["trades"], key=lambda t: (t["exitTime"], t["entryTime"], t["symbol"], t["tradeNo"]))
    btc_by_date = load_btc_regime()
    variants = [
        ("btc_trend_throttle", "BTC adverse trend: halve LONGs in BTC bear structure and SHORTs in BTC bull structure."),
        ("trend_quality_score", "Score 3-4 uses 1R; score 0-2 uses 0.5R."),
        ("ssl_flip_density", "BTC SSL14 flips >=4 times in last 30 days uses 0.5R."),
        ("volatility_chop", "BTC ATR/close top 30% of 180d and close within 1 ATR of EMA50 uses 0.5R."),
        ("quality_plus_flip", "Use 0.5R if Trend Quality Score <3 or BTC SSL flips >=4 in last 30 days."),
    ]
    runs = []
    for key, description in variants:
        stats = weighted_stats(trades, key, btc_by_date)
        curve = stats.pop("equityCurve")
        cap = portfolio_cap(trades, key, btc_by_date)
        runs.append(
            {
                "variant": {"key": key, "description": description},
                "stats": stats,
                "deltaVsBaseline": {
                    "totalR": stats["totalR"] - latest["fundingAdjustedStats"]["totalR"],
                    "maxDrawdownR": stats["maxDrawdownR"] - latest["fundingAdjustedStats"]["maxDrawdownR"],
                    "profitFactor": stats["profitFactor"] - latest["fundingAdjustedStats"]["profitFactor"],
                    "ending20k": stats["ending20k"] - latest["fundingAdjustedStats"]["ending20k"],
                },
                "portfolioCap6Equal": cap,
                "portfolioCapDeltaVsBaseline": {
                    "endingEquity": cap["endingEquity"] - latest["portfolioCap6Equal"]["endingEquity"],
                    "maxDrawdownPct": cap["maxDrawdownPct"] - latest["portfolioCap6Equal"]["maxDrawdownPct"],
                },
                "bySymbol": group_stats(curve, lambda row: row["symbol"]),
                "byYear": group_stats(curve, lambda row: row["exitTime"][:4]),
            }
        )
    result = {
        "generatedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "sourceLatestJson": str(LATEST_JSON),
        "method": "Sizing overlay only. Latest entries, exits, funding-adjusted R and chronology are unchanged; regime only changes risk multiplier at entry.",
        "baselineFundingAdjustedStats": latest["fundingAdjustedStats"],
        "baselinePortfolioCap6Equal": latest["portfolioCap6Equal"],
        "runs": runs,
    }
    OUT_JSON.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({
        "outJson": str(OUT_JSON),
        "baselineTotalR": latest["fundingAdjustedStats"]["totalR"],
        "baselineMaxDdR": latest["fundingAdjustedStats"]["maxDrawdownR"],
        "baselinePf": latest["fundingAdjustedStats"]["profitFactor"],
        "baselineCapEnding": latest["portfolioCap6Equal"]["endingEquity"],
        "runs": [
            {
                "key": run["variant"]["key"],
                "throttledTrades": run["stats"]["throttledTrades"],
                "totalR": run["stats"]["totalR"],
                "deltaR": run["deltaVsBaseline"]["totalR"],
                "maxDdR": run["stats"]["maxDrawdownR"],
                "profitFactor": run["stats"]["profitFactor"],
                "ending20k": run["stats"]["ending20k"],
                "capEnding": run["portfolioCap6Equal"]["endingEquity"],
                "capMaxDdPct": run["portfolioCap6Equal"]["maxDrawdownPct"],
            }
            for run in runs
        ],
    }, indent=2))


if __name__ == "__main__":
    main()
