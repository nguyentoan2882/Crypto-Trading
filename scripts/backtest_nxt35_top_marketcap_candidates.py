from __future__ import annotations

import json
import sys
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import backtest_nxt32_native_1d_latest as native
import test_nxt33_long_only_pullback_continuation as cont
from test_nxt33_ssl14 import enrich_with_ssl_period

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "outputs" / "nxt35_top_marketcap_candidates"
OUT_JSON = OUT_DIR / "NXT35_Top_MarketCap_Candidates.json"
CACHE = ROOT / "data_cache" / "binance_spot_1d"

START_DATE = native.START_DATE
END_DATE = native.END_DATE
WARMUP_DATE = native.WARMUP_DATE

# Current CoinGecko top-20 non-stable snapshot, 2026-06-21.
CANDIDATES = [
    ("BTC", "Bitcoin", 1), ("ETH", "Ethereum", 2), ("BNB", "BNB", 4),
    ("XRP", "XRP", 6), ("SOL", "Solana", 7), ("TRX", "TRON", 8),
    ("FIGR_HELOC", "Figure Heloc", 9), ("HYPE", "Hyperliquid", 10),
    ("DOGE", "Dogecoin", 11), ("RAIN", "Rain", 13), ("LEO", "LEO Token", 14),
    ("ZEC", "Zcash", 15), ("XLM", "Stellar", 16), ("WBT", "WhiteBIT Coin", 17),
    ("ADA", "Cardano", 18), ("XMR", "Monero", 19), ("LINK", "Chainlink", 20),
    ("CC", "Canton", 21), ("TON", "Toncoin", 23), ("LAB", "LAB", 24),
]


def http_json(url: str) -> object:
    req = urllib.request.Request(url, headers={"User-Agent": "nxt-top20-research/1.0"})
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def exchange_symbols() -> set[str]:
    data = http_json("https://data-api.binance.vision/api/v3/exchangeInfo")
    return {
        row["symbol"] for row in data["symbols"]
        if row["status"] == "TRADING" and row["quoteAsset"] == "USDT"
    }


def fetch_1d(symbol: str) -> list[dict]:
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / f"{symbol}.json"
    rows = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    by_time = {int(r["time"]): dict(r) for r in rows}
    start = int(datetime(WARMUP_DATE.year, WARMUP_DATE.month, WARMUP_DATE.day, tzinfo=timezone.utc).timestamp() * 1000)
    if by_time:
        start = max(start, max(by_time) + 86_400_000)
    end = int(datetime(END_DATE.year, END_DATE.month, END_DATE.day, tzinfo=timezone.utc).timestamp() * 1000)
    while start <= end:
        q = urllib.parse.urlencode({"symbol": symbol, "interval": "1d", "startTime": start, "endTime": end, "limit": 1000})
        batch = http_json(f"https://data-api.binance.vision/api/v3/klines?{q}")
        if not batch:
            break
        for x in batch:
            by_time[int(x[0])] = {
                "time": int(x[0]), "open": float(x[1]), "high": float(x[2]),
                "low": float(x[3]), "close": float(x[4]), "volume": float(x[5]),
            }
        nxt = int(batch[-1][0]) + 86_400_000
        if nxt <= start:
            break
        start = nxt
        time.sleep(0.03)
    raw = sorted(by_time.values(), key=lambda r: int(r["time"]))
    path.write_text(json.dumps(raw), encoding="utf-8")
    out = []
    for row in raw:
        d = datetime.fromtimestamp(int(row["time"]) / 1000, timezone.utc).date()
        if WARMUP_DATE <= d <= END_DATE:
            item = dict(row)
            item["localDate"] = d.isoformat()
            out.append(item)
    return out


def main() -> None:
    available = exchange_symbols()
    results = []
    for ticker, name, rank in CANDIDATES:
        symbol = f"{ticker}USDT"
        if symbol not in available:
            results.append({"rank": rank, "ticker": ticker, "name": name, "symbol": symbol, "status": "Not available on Binance spot USDT"})
            continue
        candles = fetch_1d(symbol)
        if len(candles) < 70:
            results.append({"rank": rank, "ticker": ticker, "name": name, "symbol": symbol, "status": "Insufficient history", "rows": len(candles)})
            continue
        enriched = enrich_with_ssl_period(candles, 14)
        trades = cont.backtest_symbol(symbol, enriched)
        stats = cont.enriched_stats(trades)
        first = candles[0]["localDate"]
        last = candles[-1]["localDate"]
        years = (date.fromisoformat(last) - max(date.fromisoformat(first), START_DATE)).days / 365.2425
        results.append({
            "rank": rank, "ticker": ticker, "name": name, "symbol": symbol, "status": "Tested",
            "dataStart": first, "dataEnd": last, "testYears": years, "trades": stats["trades"],
            "winRate": stats["winRate"], "totalRBeforeFunding": stats["totalR"],
            "avgR": stats["avgR"], "maxDrawdownR": stats["maxDrawdownR"],
            "profitFactor": stats["profitFactor"], "bestR": stats["bestR"], "worstR": stats["worstR"],
            "tradesDetail": trades,
        })
        print(ticker, stats["trades"], round(stats["totalR"], 2), round(stats["maxDrawdownR"], 2), round(years, 2))

    payload = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "marketCapSnapshotDate": "2026-06-21",
        "period": {"start": START_DATE.isoformat(), "end": (END_DATE).isoformat()},
        "method": "NXT v3.5 native 1D SSL14 Runner A anti-reversal LONG-only continuation; trading cost included; funding not yet overlaid.",
        "results": results,
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(OUT_JSON)


if __name__ == "__main__":
    main()
