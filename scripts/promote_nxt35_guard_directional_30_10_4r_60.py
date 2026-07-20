from __future__ import annotations

import json
import shutil
import sys
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import audit_nxt34_btc_bnb_sol_funding_adjusted as funding
import backtest_nxt35_latest_to_today as latest
import test_nxt35_runner_exit_variants as runner
from test_nxt33_ssl14 import enrich_with_ssl_period


ROOT = Path(__file__).resolve().parents[1]
LATEST = ROOT / "latest"
OUT = ROOT / "outputs" / "nxt35_guard_directional_30_10_4r_60"
ARCHIVE_ROOT = ROOT / "outputs" / "archive_from_latest"
PREFIX = "NXT_Latest_NXT35_USDM_GuardDirectional_30_10At4R_60"
KEY = "guard_directional_strong_btc_trend_tp1_30pct_partial_10pct_at_4_0r_cond_ema50"


def main() -> None:
    prior = json.loads((LATEST / "NXT_Latest_NXT35_USDM_BlockShortAfterLosingLong_FundingAdjusted_20K.json").read_text(encoding="utf-8"))
    end_date = date.fromisoformat(prior["period"]["lastDataDate"])
    requested_end = date.fromisoformat(prior["period"].get("requestedEnd", prior["period"]["lastDataDate"]))
    variant = next(row for row in runner.VARIANTS if row["key"] == KEY)

    datasets = {}
    for symbol in runner.SYMBOLS:
        candles = enrich_with_ssl_period(latest.fetch_usdm_1d(symbol, requested_end), 14)
        datasets[symbol] = [row for row in candles if date.fromisoformat(row["localDate"]) <= end_date]
    btc_by_date = runner.add_btc_regime(datasets["BTCUSDT"])

    trades, open_positions = [], []
    for symbol in runner.SYMBOLS:
        symbol_trades, open_position = runner.backtest_symbol(symbol, datasets[symbol], end_date, variant, btc_by_date)
        trades.extend(symbol_trades)
        if open_position:
            open_positions.append(open_position)
    trades.sort(key=lambda t: (t["exitTime"], t["entryTime"], t["symbol"], t["tradeNo"]))
    funded = runner.add_funding(trades, latest.START_DATE, end_date)

    original = funding.stats_for_key(funded, "rMultiple")
    adjusted = funding.stats_for_key(funded, "netRAfterFunding")
    original["ending20k"] = funding.STARTING_EQUITY + original["totalR"] * funding.ONE_R_DOLLARS
    adjusted["ending20k"] = funding.STARTING_EQUITY + adjusted["totalR"] * funding.ONE_R_DOLLARS
    curve = funding.equity_curve(funded, "netRAfterFunding")
    adjusted["maxDrawdownDollars"] = min((row["drawdown"] for row in curve), default=0.0)
    equal = funding.portfolio_cap_curve(funded, {"BTCUSDT": 0.02, "BNBUSDT": 0.02, "SOLUSDT": 0.02}, "netRAfterFunding")
    btc_heavy = funding.portfolio_cap_curve(funded, {"BTCUSDT": 0.03, "BNBUSDT": 0.015, "SOLUSDT": 0.015}, "netRAfterFunding")
    by_symbol = []
    for symbol in runner.SYMBOLS:
        subset = [row for row in funded if row["symbol"] == symbol]
        by_symbol.append({"symbol": symbol, "originalR": sum(row["rMultiple"] for row in subset), "fundingR": sum(row["fundingR"] for row in subset), "adjustedR": sum(row["netRAfterFunding"] for row in subset), "fundingEvents": sum(row["fundingEvents"] for row in subset)})

    result = {
        "generatedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "systemVersion": "NXT v3.5 USD-M BTC/BNB/SOL + Guard directional 30/10@4R/60",
        "candidateStatus": "Promoted to latest after rerunning the full USD-M 1D funding-adjusted backtest.",
        "runnerRule": {"name": "Guard directional 30/10@4R/60", "variantKey": KEY, "tp1Fraction": 0.30, "partialFraction": 0.10, "partialAtR": 4.0, "tailFraction": 0.60, "tail": "EMA50 close only when BTC is directionally strong (LONG: close > EMA200 and close > EMA50 with EMA20 > EMA50; SHORT inverse); otherwise opposite SSL flip."},
        "period": prior["period"], "symbols": runner.SYMBOLS, "originalStats": original, "fundingAdjustedStats": adjusted,
        "fundingSummary": {"totalFundingR": sum(row["fundingR"] for row in funded), "fundingEvents": sum(row["fundingEvents"] for row in funded), "fundingPaidR": sum(row["fundingPaidR"] for row in funded), "fundingReceivedR": sum(row["fundingReceivedR"] for row in funded)},
        "fundingBySymbol": by_symbol, "trades": funded, "equityCurveFundingAdjusted": curve, "portfolioCap6Equal": equal, "portfolioCap6BtcHeavy": btc_heavy, "openPositions": open_positions,
    }

    OUT.mkdir(parents=True, exist_ok=True)
    out_json = OUT / f"{PREFIX}_FundingAdjusted_20K.json"
    out_xlsx = OUT / f"{PREFIX}_FundingAdjusted_20K.xlsx"
    out_json.write_text(json.dumps(result, indent=2), encoding="utf-8")
    funding.OUT_XLSX = out_xlsx
    funding.build_workbook(result)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    archive = ARCHIVE_ROOT / f"before_guard_directional_30_10at4r_60_{stamp}"
    archive.mkdir(parents=True, exist_ok=False)
    for path in LATEST.glob("NXT_Latest_*"):
        if path.is_file():
            shutil.copy2(path, archive / path.name)
    shutil.copy2(out_json, LATEST / out_json.name)
    shutil.copy2(out_xlsx, LATEST / out_xlsx.name)

    summary = f"""# NXT Latest Summary

## Promoted system

NXT v3.5 USD-M BTC/BNB/SOL, SSL14, Runner A, Early-BE 7%, anti-immediate-reversal, LONG-only pullback continuation, and block SHORT after losing pre-TP1 LONG SSL exit.

**New runner rule - Guard directional 30/10@4R/60:** take 30% at TP1 (2.5 ATR), 10% at 4R, then manage the 60% tail with EMA50 only when BTC is strongly aligned with the trade direction (LONG: BTC close > EMA200 and EMA50, EMA20 > EMA50; SHORT: inverse). Otherwise, exit that tail on an opposite SSL flip.

## Rerun results

- Period: {prior['period']['start']} to {end_date.isoformat()}
- Trades: {adjusted['trades']}
- Funding-adjusted total: {adjusted['totalR']:.2f}R
- Max drawdown: {adjusted['maxDrawdownR']:.2f}R
- Win rate: {adjusted['winRate'] * 100:.2f}%
- Profit factor: {adjusted['profitFactor']:.2f}
- Fixed-$1,000R ending equity: ${adjusted['ending20k']:,.2f}
- Portfolio cap 6% equal-split ending equity: ${equal['endingEquity']:,.2f}

## Published artifacts

- `{out_json.name}`
- `{out_xlsx.name}`

Prior `latest/` artifacts are archived at `{archive.relative_to(ROOT).as_posix()}`.
"""
    (LATEST / "NXT_Latest_Summary.md").write_text(summary, encoding="utf-8")
    print(json.dumps({"json": str(LATEST / out_json.name), "xlsx": str(LATEST / out_xlsx.name), "archive": str(archive), "stats": adjusted, "cap6EqualEnding": equal["endingEquity"]}, indent=2))


if __name__ == "__main__":
    main()
