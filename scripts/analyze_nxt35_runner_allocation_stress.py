import json
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "outputs" / "nxt35_runner_exit_variants" / "NXT35_Runner_Exit_Variants.json"
OUT_JSON = ROOT / "outputs" / "nxt35_runner_exit_variants" / "NXT35_Runner_Allocation_Stress_Test.json"
OUT_MD = ROOT / "outputs" / "nxt35_runner_exit_variants" / "NXT35_Runner_Allocation_Stress_Test.md"

VARIANTS = [
    ("Latest SSL", "baseline_ssl_flip"),
    ("Cond EMA50 50/0/50", "conditional_ema50_btc_above_ema200"),
    ("30/0/70 Cond", "alloc_tp1_30pct_partial_0pct_at_4_0r_cond_ema50"),
    ("30/10@4R/60 Cond", "alloc_tp1_30pct_partial_10pct_at_4_0r_cond_ema50"),
    ("40/0/60 Cond", "alloc_tp1_40pct_partial_0pct_at_4_0r_cond_ema50"),
    ("40/10@4R/50 Cond", "alloc_tp1_40pct_partial_10pct_at_4_0r_cond_ema50"),
    (
        "Guard directional 30/0/70",
        "guard_directional_strong_btc_trend_tp1_30pct_partial_0pct_at_4_0r_cond_ema50",
    ),
    (
        "Guard directional 30/10@4R/60",
        "guard_directional_strong_btc_trend_tp1_30pct_partial_10pct_at_4_0r_cond_ema50",
    ),
    (
        "Guard directional 40/0/60",
        "guard_directional_strong_btc_trend_tp1_40pct_partial_0pct_at_4_0r_cond_ema50",
    ),
    (
        "Guard directional 40/10@4R/50",
        "guard_directional_strong_btc_trend_tp1_40pct_partial_10pct_at_4_0r_cond_ema50",
    ),
]


def trade_r(trade):
    return float(trade.get("netRAfterFunding", trade.get("rMultiple", 0)) or 0)


def trade_date(trade):
    return trade.get("exitTime") or trade.get("entryTime") or trade.get("signalTime") or ""


def calc_stats(trades):
    ordered = sorted(trades, key=trade_date)
    total_r = sum(trade_r(t) for t in ordered)
    wins = sum(trade_r(t) for t in ordered if trade_r(t) > 0)
    losses = -sum(trade_r(t) for t in ordered if trade_r(t) < 0)
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for trade in ordered:
        equity += trade_r(trade)
        peak = max(peak, equity)
        max_dd = min(max_dd, equity - peak)
    return {
        "trades": len(ordered),
        "totalR": total_r,
        "maxDrawdownR": max_dd,
        "profitFactor": wins / losses if losses else None,
    }


def summarize_variant(label, row):
    trades = row["trades"]
    base_stats = calc_stats(trades)
    winners = sorted([t for t in trades if trade_r(t) > 0], key=trade_r, reverse=True)

    stress = {}
    for n in (1, 3, 5, 10):
        removed = {id(t) for t in winners[:n]}
        remaining = [t for t in trades if id(t) not in removed]
        stress[f"removeTop{n}Winners"] = calc_stats(remaining)

    top_winners = []
    for trade in winners[:10]:
        top_winners.append(
            {
                "symbol": trade.get("symbol"),
                "side": trade.get("side"),
                "signalTime": trade.get("signalTime"),
                "entryTime": trade.get("entryTime"),
                "exitTime": trade.get("exitTime"),
                "netRAfterFunding": trade_r(trade),
                "exitReason": trade.get("exitReason"),
            }
        )

    after_top5 = [t for t in trades if id(t) not in {id(w) for w in winners[:5]}]
    by_year_after_top5 = defaultdict(float)
    for trade in after_top5:
        year = trade_date(trade)[:4]
        by_year_after_top5[year] += trade_r(trade)

    concentration = {}
    for n in (1, 3, 5, 10):
        contribution = sum(trade_r(t) for t in winners[:n])
        concentration[f"top{n}R"] = contribution
        concentration[f"top{n}PctOfTotal"] = contribution / base_stats["totalR"] if base_stats["totalR"] else None

    return {
        "label": label,
        "variantKey": row["variant"]["key"],
        "base": base_stats,
        "concentration": concentration,
        "stress": stress,
        "topWinners": top_winners,
        "byYearAfterRemovingTop5": dict(sorted(by_year_after_top5.items())),
    }


def fmt(value):
    if value is None:
        return "n/a"
    return f"{value:.2f}"


def pct(value):
    if value is None:
        return "n/a"
    return f"{value * 100:.1f}%"


def main():
    data = json.loads(SOURCE.read_text(encoding="utf-8"))
    by_key = {row["variant"]["key"]: row for row in data["results"]}
    summaries = [summarize_variant(label, by_key[key]) for label, key in VARIANTS]

    payload = {
        "source": str(SOURCE.relative_to(ROOT)),
        "metric": "netRAfterFunding",
        "stressMethod": "Remove the largest winning trades by funding-adjusted R, then recompute chronological total R, drawdown, and profit factor.",
        "variants": summaries,
    }
    OUT_JSON.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    lines = [
        "# NXT Runner Allocation Stress Test",
        "",
        "Metric: net R after funding. Stress method: remove the largest winning trades and recompute the remaining chronological curve.",
        "",
        "| Variant | Base R | Max DD | PF | Top 5 % | Remove Top 5 R | Remove Top 10 R |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in summaries:
        base = row["base"]
        conc = row["concentration"]
        stress = row["stress"]
        lines.append(
            "| {label} | {base_r} | {dd} | {pf} | {top5} | {rm5} | {rm10} |".format(
                label=row["label"],
                base_r=fmt(base["totalR"]),
                dd=fmt(base["maxDrawdownR"]),
                pf=fmt(base["profitFactor"]),
                top5=pct(conc["top5PctOfTotal"]),
                rm5=fmt(stress["removeTop5Winners"]["totalR"]),
                rm10=fmt(stress["removeTop10Winners"]["totalR"]),
            )
        )

    lines.extend(["", "## Top 5 Winners"])
    for row in summaries:
        lines.extend(["", f"### {row['label']}"])
        for trade in row["topWinners"][:5]:
            symbol = (trade["symbol"] or "").replace("USDT", "")
            lines.append(
                f"- {symbol} {trade['side']} signal {trade['signalTime']} exit {trade['exitTime']}: {trade['netRAfterFunding']:.2f}R"
            )

    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {OUT_JSON}")
    print(f"Wrote {OUT_MD}")


if __name__ == "__main__":
    main()
