from __future__ import annotations

import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import backtest_nxt31_utc7_latest as base
import backtest_nxt32_native_1d_latest as native
import backtest_nxt35_us_top3_stocks_3y as yahoo_runner
import test_nxt33_long_only_pullback_continuation as cont
from test_nxt33_ssl14 import enrich_with_ssl_period


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "outputs" / "nxt35_market_universe_6y"
OUT_JSON = OUT_DIR / "NXT35_Market_Universe_6Y_Scan.json"
CRYPTO_JSON = ROOT / "latest" / "NXT_Latest_NXT35_BTC_BNB_SOL_FundingAdjusted_20K.json"

START_DATE = date(2020, 5, 17)
END_DATE = date(2026, 5, 17)
WARMUP_DATE = date(2019, 11, 1)

CANDIDATES = [
    # US broad/growth/sector equity proxies.
    ("US broad equity", "SPY", "SPDR S&P 500 ETF"),
    ("US broad equity", "QQQ", "Invesco Nasdaq 100 ETF"),
    ("US broad equity", "IWM", "iShares Russell 2000 ETF"),
    ("US broad equity", "DIA", "SPDR Dow Jones Industrial Average ETF"),
    ("US sector equity", "XLK", "Technology Select Sector SPDR"),
    ("US sector equity", "XLE", "Energy Select Sector SPDR"),
    ("US sector equity", "XLF", "Financial Select Sector SPDR"),
    ("US sector equity", "XBI", "SPDR S&P Biotech ETF"),
    ("US sector equity", "SMH", "VanEck Semiconductor ETF"),
    ("US sector equity", "ARKK", "ARK Innovation ETF"),
    # International/country equity proxies.
    ("International equity", "EEM", "iShares MSCI Emerging Markets ETF"),
    ("International equity", "EFA", "iShares MSCI EAFE ETF"),
    ("International equity", "EWJ", "iShares MSCI Japan ETF"),
    ("International equity", "EWZ", "iShares MSCI Brazil ETF"),
    ("International equity", "INDA", "iShares MSCI India ETF"),
    ("International equity", "FXI", "iShares China Large-Cap ETF"),
    ("International equity", "EWT", "iShares MSCI Taiwan ETF"),
    ("International equity", "EWY", "iShares MSCI South Korea ETF"),
    # Commodity proxies.
    ("Commodity ETF", "GLD", "SPDR Gold Shares"),
    ("Commodity ETF", "SLV", "iShares Silver Trust"),
    ("Commodity ETF", "USO", "United States Oil Fund"),
    ("Commodity ETF", "UNG", "United States Natural Gas Fund"),
    ("Commodity ETF", "DBA", "Invesco DB Agriculture Fund"),
    ("Commodity ETF", "DBC", "Invesco DB Commodity Index Tracking Fund"),
    # Bond/rates proxies.
    ("Bond ETF", "TLT", "iShares 20+ Year Treasury Bond ETF"),
    ("Bond ETF", "IEF", "iShares 7-10 Year Treasury Bond ETF"),
    ("Bond ETF", "HYG", "iShares High Yield Corporate Bond ETF"),
    ("Bond ETF", "LQD", "iShares Investment Grade Corporate Bond ETF"),
    # Currency proxies.
    ("Currency ETF", "UUP", "Invesco DB US Dollar Index Bullish Fund"),
    ("Currency ETF", "FXE", "Invesco CurrencyShares Euro Trust"),
    ("Currency ETF", "FXY", "Invesco CurrencyShares Japanese Yen Trust"),
    # Yahoo continuous futures where available.
    ("Index future", "ES=F", "E-mini S&P 500 futures"),
    ("Index future", "NQ=F", "Nasdaq 100 futures"),
    ("Index future", "RTY=F", "Russell 2000 futures"),
    ("Commodity future", "GC=F", "Gold futures"),
    ("Commodity future", "SI=F", "Silver futures"),
    ("Commodity future", "CL=F", "Crude oil futures"),
    ("Commodity future", "NG=F", "Natural gas futures"),
    ("Rates future", "ZB=F", "30-Year Treasury Bond futures"),
    ("Currency future", "DX-Y.NYB", "US Dollar Index"),
]


def profit_factor(rows: list[dict], key: str = "rMultiple") -> float | None:
    gp = sum(t[key] for t in rows if t[key] > 0)
    gl = -sum(t[key] for t in rows if t[key] < 0)
    return gp / gl if gl else None


def stats(rows: list[dict], key: str = "rMultiple") -> dict:
    out = base.stats(rows, key)
    out["profitFactor"] = profit_factor(rows, key)
    out["ending20k"] = 20_000 + out["totalR"] * 1_000
    return out


def side_stats(rows: list[dict]) -> dict:
    return {side: stats([t for t in rows if t["side"] == side]) for side in ["LONG", "SHORT"]}


def signal_stats(rows: list[dict]) -> dict:
    return {kind: stats([t for t in rows if t.get("signalType") == kind]) for kind in ["Primary", "Continuation"]}


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    old = (native.START_DATE, native.END_DATE, native.WARMUP_DATE)
    old_runner_dates = (yahoo_runner.START_DATE, yahoo_runner.END_DATE, yahoo_runner.WARMUP_DATE)
    native.START_DATE, native.END_DATE, native.WARMUP_DATE = START_DATE, END_DATE, WARMUP_DATE
    yahoo_runner.START_DATE, yahoo_runner.END_DATE, yahoo_runner.WARMUP_DATE = START_DATE, END_DATE, WARMUP_DATE
    results = []
    errors = []
    try:
        for asset_class, symbol, name in CANDIDATES:
            try:
                candles = yahoo_runner.fetch_yahoo_1d(symbol)
                if len(candles) < 250:
                    raise RuntimeError(f"insufficient rows: {len(candles)}")
                enriched = enrich_with_ssl_period(candles, 14)
                trades = cont.backtest_symbol(symbol, enriched)
                trades.sort(key=lambda t: (t["exitTime"], t["symbol"], t["tradeNo"]))
                st = stats(trades)
                results.append(
                    {
                        "assetClass": asset_class,
                        "symbol": symbol,
                        "name": name,
                        "dataRows": len(candles),
                        "firstDay": candles[0]["localDate"],
                        "lastDay": candles[-1]["localDate"],
                        "stats": st,
                        "sideStats": side_stats(trades),
                        "signalStats": signal_stats(trades),
                        "topWinners": sorted(trades, key=lambda t: t["rMultiple"], reverse=True)[:5],
                        "topLosers": sorted(trades, key=lambda t: t["rMultiple"])[:5],
                    }
                )
                print(symbol, st["trades"], round(st["totalR"], 2), round(st["maxDrawdownR"], 2), st["profitFactor"])
            except Exception as exc:
                errors.append({"assetClass": asset_class, "symbol": symbol, "name": name, "error": str(exc)})
                print("ERROR", symbol, exc)
    finally:
        native.START_DATE, native.END_DATE, native.WARMUP_DATE = old
        yahoo_runner.START_DATE, yahoo_runner.END_DATE, yahoo_runner.WARMUP_DATE = old_runner_dates

    crypto = json.loads(CRYPTO_JSON.read_text(encoding="utf-8"))
    crypto_stats = crypto["fundingAdjustedStats"]
    payload = {
        "generatedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "period": {"start": START_DATE.isoformat(), "end": (END_DATE).isoformat(), "warmup": WARMUP_DATE.isoformat()},
        "method": "NXT v3.5 Yahoo daily scan using SSL14, Runner A, Early-BE 7%, anti-immediate-reversal, LONG-only pullback continuation. Crypto baseline is published funding-adjusted latest BTC/BNB/SOL.",
        "selectionNote": "ETF/futures proxies were selected as liquid market representatives; this scan ranks suitability by realized 6Y backtest statistics, not forecast opinions.",
        "cryptoBaseline": {
            "assetClass": "Crypto latest portfolio",
            "symbols": crypto["symbols"],
            "stats": crypto_stats,
            "fundingBySymbol": crypto["fundingBySymbol"],
        },
        "results": sorted(results, key=lambda r: r["stats"]["totalR"], reverse=True),
        "errors": errors,
    }
    OUT_JSON.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(OUT_JSON)


if __name__ == "__main__":
    main()
