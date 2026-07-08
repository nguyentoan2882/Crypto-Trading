from __future__ import annotations

import http.client
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CACHE_DIR = ROOT / "data_cache" / "binance_spot_1d"
BINANCE_API = os.environ.get("NXT_BINANCE_KLINES_URL", "https://data-api.binance.vision/api/v3/klines")
DAY_MS = 86_400_000


def _load_cache(symbol: str) -> dict[int, dict]:
    path = CACHE_DIR / f"{symbol}.json"
    if not path.exists():
        return {}
    return {int(row["time"]): dict(row) for row in json.loads(path.read_text(encoding="utf-8"))}


def fetch_tradingview_binance_1d(
    symbol: str,
    start_date: date,
    end_date: date | None = None,
) -> list[dict]:
    """Return Binance native 00:00 UTC daily bars used by TradingView BINANCE:* 1D."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    by_time = _load_cache(symbol)
    requested_start = int(datetime.combine(start_date, datetime.min.time(), timezone.utc).timestamp() * 1000)
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    end_ms = (
        int(datetime.combine(end_date, datetime.min.time(), timezone.utc).timestamp() * 1000)
        if end_date is not None
        else now_ms
    )
    start_ms = requested_start
    if by_time:
        # Re-fetch a rolling window because a cached daily row may have been saved
        # while its candle was still open. Append-only refreshes permanently kept
        # those partial OHLC values and caused repeated TradingView mismatches.
        refresh_start = end_ms - 45 * DAY_MS
        start_ms = max(requested_start, min(max(by_time) + DAY_MS, refresh_start))
    changed = False

    while start_ms <= end_ms:
        query = urllib.parse.urlencode({
            "symbol": symbol,
            "interval": "1d",
            "startTime": start_ms,
            "endTime": end_ms,
            "limit": 1000,
        })
        request = urllib.request.Request(
            f"{BINANCE_API}?{query}",
            headers={"User-Agent": "nxt-tradingview-binance-1d/1.0"},
        )
        batch = None
        last_error: Exception | None = None
        for attempt in range(4):
            try:
                with urllib.request.urlopen(request, timeout=30) as response:
                    batch = json.loads(response.read().decode("utf-8"))
                break
            except (urllib.error.URLError, TimeoutError, ConnectionResetError, http.client.IncompleteRead) as exc:
                last_error = exc
                time.sleep(1 + attempt * 2)
        if batch is None:
            raise RuntimeError(f"Failed to fetch Binance native 1D data for {symbol}") from last_error
        if not batch:
            break
        for item in batch:
            by_time[int(item[0])] = {
                "time": int(item[0]),
                "open": float(item[1]),
                "high": float(item[2]),
                "low": float(item[3]),
                "close": float(item[4]),
                "volume": float(item[5]),
                "closeTime": int(item[6]),
                "takerBuyBaseVolume": float(item[9]),
            }
            changed = True
        next_start = int(batch[-1][0]) + DAY_MS
        if next_start <= start_ms:
            break
        start_ms = next_start
        time.sleep(0.03)

    rows = sorted(by_time.values(), key=lambda row: int(row["time"]))
    if changed:
        (CACHE_DIR / f"{symbol}.json").write_text(json.dumps(rows), encoding="utf-8")

    result = []
    for row in rows:
        bar_date = datetime.fromtimestamp(int(row["time"]) / 1000, timezone.utc).date()
        if bar_date < start_date or (end_date is not None and bar_date > end_date):
            continue
        item = dict(row)
        item.setdefault("closeTime", int(item["time"]) + DAY_MS - 1)
        item.setdefault("takerBuyBaseVolume", 0.0)
        item["localDate"] = bar_date.isoformat()
        item["closed"] = int(item["closeTime"]) <= now_ms
        result.append(item)
    return result
