from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LATEST_JSON = ROOT / "latest" / "NXT_Latest_NXT35_BTC_BNB_SOL_FundingAdjusted_20K.json"
OUT_DIR = ROOT / "outputs" / "nxt35_short_half_risk"
OUT_JSON = OUT_DIR / "NXT35_SHORT_0_5R_Sizing.json"

STARTING_EQUITY = 20_000.0
ONE_R_DOLLARS = 1_000.0
BASE_ALLOCATIONS = {"BTCUSDT": 0.02, "BNBUSDT": 0.02, "SOLUSDT": 0.02}


def side_mult(trade: dict) -> float:
    return 0.5 if trade["side"] == "SHORT" else 1.0


def weighted_stats(trades: list[dict]) -> dict:
    equity = STARTING_EQUITY
    peak = equity
    rows = []
    gross_profit = 0.0
    gross_loss = 0.0
    weighted_total_r = 0.0
    best = None
    worst = None
    for index, trade in enumerate(trades, 1):
        effective_r = float(trade["netRAfterFunding"]) * side_mult(trade)
        weighted_total_r += effective_r
        if effective_r > 0:
            gross_profit += effective_r
        elif effective_r < 0:
            gross_loss += -effective_r
        best = effective_r if best is None else max(best, effective_r)
        worst = effective_r if worst is None else min(worst, effective_r)
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
                "riskMultiplier": side_mult(trade),
                "effectiveR": effective_r,
                "pnl": pnl,
                "equity": equity,
                "drawdown": equity - peak,
            }
        )
    wins = sum(1 for row in rows if row["effectiveR"] > 0)
    losses = len(rows) - wins
    return {
        "trades": len(rows),
        "wins": wins,
        "losses": losses,
        "winRate": wins / len(rows) if rows else 0.0,
        "totalR": weighted_total_r,
        "avgR": weighted_total_r / len(rows) if rows else 0.0,
        "maxDrawdownR": min((row["drawdown"] / ONE_R_DOLLARS for row in rows), default=0.0),
        "maxDrawdownDollars": min((row["drawdown"] for row in rows), default=0.0),
        "bestR": best or 0.0,
        "worstR": worst or 0.0,
        "profitFactor": gross_profit / gross_loss if gross_loss else None,
        "ending20k": equity,
        "equityCurve": rows,
    }


def trade_key(trade: dict) -> str:
    return f"{trade['symbol']}:{trade['tradeNo']}:{trade['entryTime']}:{trade['exitTime']}"


def portfolio_cap_half_short(trades: list[dict]) -> dict:
    events: dict[str, dict[str, list[dict]]] = {}
    for trade in trades:
        events.setdefault(trade["entryTime"], {"entries": [], "exits": []})["entries"].append(trade)
        events.setdefault(trade["exitTime"], {"entries": [], "exits": []})["exits"].append(trade)

    equity = STARTING_EQUITY
    peak = equity
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
        regular_exits = [
            trade for trade in events[event_date]["exits"]
            if trade_key(trade) not in same_day_keys
        ]
        same_day_exits = [
            trade for trade in events[event_date]["exits"]
            if trade_key(trade) in same_day_keys
        ]

        def close_trade(trade: dict) -> None:
            nonlocal equity, peak
            identity = trade_key(trade)
            risk_record = open_risk.pop(identity, None)
            risk_amount = risk_record["riskAmount"] if risk_record else 0.0
            pnl = risk_amount * float(trade["netRAfterFunding"])
            equity += pnl
            peak = max(peak, equity)
            rows[identity] = {
                "riskAmount": risk_amount,
                "riskMultiplier": side_mult(trade),
                "pnl": pnl,
                "equity": equity,
                "drawdown": equity - peak,
                "skipped": risk_record is None,
            }

        for trade in sorted(regular_exits, key=lambda t: (t["symbol"], t["tradeNo"])):
            close_trade(trade)
        for trade in sorted(events[event_date]["entries"], key=lambda t: (t["symbol"], t["tradeNo"])):
            symbol = trade["symbol"]
            trade_cap_pct = BASE_ALLOCATIONS[symbol] * side_mult(trade)
            symbol_capacity = max(0.0, equity * trade_cap_pct - current_open_risk(symbol))
            portfolio_capacity = max(0.0, equity * sum(BASE_ALLOCATIONS.values()) - current_open_risk())
            risk_amount = min(symbol_capacity, portfolio_capacity)
            if risk_amount > 0:
                open_risk[trade_key(trade)] = {"symbol": symbol, "riskAmount": risk_amount}
        for trade in sorted(same_day_exits, key=lambda t: (t["symbol"], t["tradeNo"])):
            close_trade(trade)

    return {
        "endingEquity": equity,
        "netProfit": equity - STARTING_EQUITY,
        "maxDrawdownDollars": min((row["drawdown"] for row in rows.values()), default=0.0),
        "maxDrawdownPct": min(
            (
                row["drawdown"] / max(row["equity"] - row["drawdown"], row["equity"])
                if max(row["equity"] - row["drawdown"], row["equity"]) else 0.0
                for row in rows.values()
            ),
            default=0.0,
        ),
        "executedTrades": sum(1 for row in rows.values() if row["riskAmount"] > 0),
        "skippedTrades": sum(1 for row in rows.values() if row["skipped"]),
        "trades": rows,
    }


def group_stats(trades: list[dict], key_fn) -> list[dict]:
    groups: dict[str, list[dict]] = {}
    for trade in trades:
        groups.setdefault(key_fn(trade), []).append(trade)
    out = []
    for key, rows in sorted(groups.items()):
        stats = weighted_stats(rows)
        stats.pop("equityCurve", None)
        stats["group"] = key
        out.append(stats)
    return out


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    latest = json.loads(LATEST_JSON.read_text(encoding="utf-8"))
    trades = sorted(latest["trades"], key=lambda t: (t["exitTime"], t["entryTime"], t["symbol"], t["tradeNo"]))
    variant_stats = weighted_stats(trades)
    cap_equal = portfolio_cap_half_short(trades)
    result = {
        "generatedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "sourceLatestJson": str(LATEST_JSON),
        "variant": "Sizing overlay only: LONG risk 1.0R, SHORT risk 0.5R. Entries/exits unchanged.",
        "baselineFundingAdjustedStats": latest["fundingAdjustedStats"],
        "baselinePortfolioCap6Equal": latest["portfolioCap6Equal"],
        "variantStats": {k: v for k, v in variant_stats.items() if k != "equityCurve"},
        "portfolioCap6EqualHalfShort": cap_equal,
        "bySide": group_stats(trades, lambda t: t["side"]),
        "bySymbol": group_stats(trades, lambda t: t["symbol"]),
        "byYear": group_stats(trades, lambda t: t["exitTime"][:4]),
    }
    OUT_JSON.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({
        "outJson": str(OUT_JSON),
        "baselineTrades": latest["fundingAdjustedStats"]["trades"],
        "variantTrades": variant_stats["trades"],
        "baselineTotalR": latest["fundingAdjustedStats"]["totalR"],
        "variantEffectiveR": variant_stats["totalR"],
        "deltaEffectiveR": variant_stats["totalR"] - latest["fundingAdjustedStats"]["totalR"],
        "baselineMaxDdR": latest["fundingAdjustedStats"]["maxDrawdownR"],
        "variantMaxDdR": variant_stats["maxDrawdownR"],
        "baselineProfitFactor": latest["fundingAdjustedStats"]["profitFactor"],
        "variantProfitFactor": variant_stats["profitFactor"],
        "baselineEnding": latest["fundingAdjustedStats"]["ending20k"],
        "variantEnding": variant_stats["ending20k"],
        "baselineCap6EqualEnding": latest["portfolioCap6Equal"]["endingEquity"],
        "variantCap6HalfShortEnding": cap_equal["endingEquity"],
        "baselineCap6EqualMaxDd": latest["portfolioCap6Equal"]["maxDrawdownPct"],
        "variantCap6HalfShortMaxDd": cap_equal["maxDrawdownPct"],
    }, indent=2))


if __name__ == "__main__":
    main()
