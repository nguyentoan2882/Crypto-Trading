from __future__ import annotations

import csv
import io
import json
import sys
import time
import urllib.error
import urllib.request
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import backtest_nxt31_utc7_latest as base
import backtest_nxt32_native_1d_latest as native
import test_nxt33_long_only_pullback_continuation as cont
from test_nxt33_ssl14 import enrich_with_ssl_period
import audit_nxt34_btc_bnb_sol_funding_adjusted as funding


ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "data_cache" / "binance_usdm_futures_1d"
OUT_DIR = ROOT / "outputs" / "nxt35_usdm_futures_6y"
OUT_JSON = OUT_DIR / "NXT35_USDM_Futures_BTC_BNB_SOL_6Y_FundingAdjusted.json"
SPOT_BASELINE = ROOT / "latest" / "NXT_Latest_NXT35_BTC_BNB_SOL_FundingAdjusted_20K.json"

SYMBOLS = ["BTCUSDT", "BNBUSDT", "SOLUSDT"]
START_DATE = date(2020, 5, 17)
END_DATE = date(2026, 5, 17)
WARMUP_DATE = date(2019, 11, 1)


def month_iter(start: date, end: date):
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        yield y, m
        m += 1
        if m == 13:
            y += 1
            m = 1


def normalize_ms(value: str) -> int:
    number = int(float(value))
    return number // 1000 if number > 10_000_000_000_000 else number


def read_zip(url: str) -> list[dict]:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "nxt-usdm-backtest/1.0"})
        with urllib.request.urlopen(req, timeout=30) as response:
            payload = response.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return []
        raise
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        names = [name for name in archive.namelist() if name.endswith(".csv")]
        if not names:
            return []
        with archive.open(names[0]) as raw:
            rows = []
            reader = csv.reader(io.TextIOWrapper(raw, encoding="utf-8"))
            for row in reader:
                if not row or row[0] in {"open_time", "Open time"}:
                    continue
                rows.append(
                    {
                        "time": normalize_ms(row[0]),
                        "open": float(row[1]),
                        "high": float(row[2]),
                        "low": float(row[3]),
                        "close": float(row[4]),
                        "volume": float(row[5]),
                    }
                )
            return rows


def fetch_usdm_1d(symbol: str) -> list[dict]:
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / f"{symbol}_1d_{WARMUP_DATE}_{END_DATE - timedelta(days=1)}.json"
    if path.exists():
        raw = json.loads(path.read_text(encoding="utf-8"))
    else:
        raw = []
        for year, month in month_iter(WARMUP_DATE, END_DATE):
            url = (
                "https://data.binance.vision/data/futures/um/monthly/klines/"
                f"{symbol}/1d/{symbol}-1d-{year}-{month:02d}.zip"
            )
            batch = read_zip(url)
            raw.extend(batch)
            if batch:
                print(symbol, year, f"{month:02d}", len(batch))
            time.sleep(0.02)
        raw = sorted({int(row["time"]): row for row in raw}.values(), key=lambda row: int(row["time"]))
        path.write_text(json.dumps(raw), encoding="utf-8")

    candles = []
    for row in raw:
        day = datetime.fromtimestamp(int(row["time"]) / 1000, timezone.utc).date()
        if WARMUP_DATE <= day <= END_DATE:
            item = dict(row)
            item["localDate"] = day.isoformat()
            candles.append(item)
    return candles


def stats_for_key(trades: list[dict], key: str) -> dict:
    return funding.stats_for_key(trades, key)


def main() -> None:
    # The shared backtest reads these module globals.
    native.START_DATE = START_DATE
    native.END_DATE = END_DATE
    native.WARMUP_DATE = WARMUP_DATE

    all_trades = []
    datasets = {}
    for symbol in SYMBOLS:
        candles = fetch_usdm_1d(symbol)
        enriched = enrich_with_ssl_period(candles, 14)
        trades = cont.backtest_symbol(symbol, enriched)
        all_trades.extend(trades)
        datasets[symbol] = {
            "rows": len(candles),
            "firstDay": candles[0]["localDate"] if candles else None,
            "lastDay": candles[-1]["localDate"] if candles else None,
            "firstTradeEntry": min((t["entryTime"] for t in trades), default=None),
            "trades": len(trades),
            "source": "Binance USD-M perpetual contract 1D klines",
        }

    all_trades.sort(key=lambda trade: (trade["exitTime"], trade["symbol"], trade["tradeNo"]))
    funding_by_symbol = {
        symbol: funding.fetch_monthly_funding(symbol, START_DATE, END_DATE)
        for symbol in SYMBOLS
    }
    for trade in all_trades:
        trade.update(funding.funding_for_trade(trade, funding_by_symbol[trade["symbol"]]))
        trade["netRAfterFunding"] = trade["rMultiple"] + trade["fundingR"]

    adjusted = stats_for_key(all_trades, "netRAfterFunding")
    original = stats_for_key(all_trades, "rMultiple")
    by_symbol = []
    for symbol in SYMBOLS:
        rows = [trade for trade in all_trades if trade["symbol"] == symbol]
        stats = stats_for_key(rows, "netRAfterFunding")
        stats["symbol"] = symbol
        stats["fundingR"] = sum(trade["fundingR"] for trade in rows)
        by_symbol.append(stats)
    by_year = []
    for year in sorted({trade["exitTime"][:4] for trade in all_trades}):
        rows = [trade for trade in all_trades if trade["exitTime"].startswith(year)]
        stats = stats_for_key(rows, "netRAfterFunding")
        stats["year"] = year
        by_year.append(stats)

    spot = json.loads(SPOT_BASELINE.read_text(encoding="utf-8"))
    result = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "system": "NXT v3.5 BTC/BNB/SOL on Binance USD-M perpetual 1D contract candles",
        "period": {"start": START_DATE.isoformat(), "endExclusive": END_DATE.isoformat()},
        "datasets": datasets,
        "originalStats": original,
        "fundingAdjustedStats": adjusted,
        "fundingSummary": {
            "totalFundingR": sum(trade["fundingR"] for trade in all_trades),
            "events": sum(trade["fundingEvents"] for trade in all_trades),
        },
        "bySymbol": by_symbol,
        "byYear": by_year,
        "comparisonToSpotBaseline": {
            "spotTrades": spot["fundingAdjustedStats"]["trades"],
            "spotTotalR": spot["fundingAdjustedStats"]["totalR"],
            "spotMaxDrawdownR": spot["fundingAdjustedStats"]["maxDrawdownR"],
            "spotProfitFactor": spot["fundingAdjustedStats"]["profitFactor"],
            "tradeDelta": adjusted["trades"] - spot["fundingAdjustedStats"]["trades"],
            "totalRDelta": adjusted["totalR"] - spot["fundingAdjustedStats"]["totalR"],
            "maxDrawdownRDelta": adjusted["maxDrawdownR"] - spot["fundingAdjustedStats"]["maxDrawdownR"],
        },
        "assumptions": [
            "Signals and ATR/EMA/RSI/SSL are calculated from Binance USD-M perpetual contract 1D klines.",
            "Entry remains the next USD-M daily contract open after signal close.",
            "Stop and TP are evaluated against USD-M contract high/low; this is not mark-price OHLC.",
            "Trading cost is included by the existing NXT cost model.",
            "Actual Binance USD-M funding history is overlaid per trade.",
            "SOL perpetual history begins later than the common portfolio start, reducing its available test period.",
        ],
        "trades": all_trades,
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k not in {"trades"}}, indent=2))
    print(OUT_JSON)


if __name__ == "__main__":
    main()
