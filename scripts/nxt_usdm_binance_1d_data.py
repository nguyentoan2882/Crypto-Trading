from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "data_cache" / "binance_usdm_futures_1d_live"
DEFAULT_URL = "https://fapi.binance.com/fapi/v1/klines"


def _ms_at_utc_midnight(day: date) -> int:
    return int(datetime(day.year, day.month, day.day, tzinfo=timezone.utc).timestamp() * 1000)


def _request_klines(url: str, params: dict[str, object]) -> list[list[object]]:
    query = urllib.parse.urlencode(params)
    request = urllib.request.Request(f"{url}?{query}", headers={"User-Agent": "nxt-signal-app/1.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, list):
        raise RuntimeError(f"Unexpected USD-M kline response: {payload}")
    return payload


def _fetch_range(symbol: str, start: date, end_exclusive: date, url: str) -> list[dict]:
    rows: list[dict] = []
    cursor = _ms_at_utc_midnight(start)
    end_ms = _ms_at_utc_midnight(end_exclusive)
    while cursor < end_ms:
        batch = _request_klines(
            url,
            {"symbol": symbol, "interval": "1d", "startTime": cursor, "endTime": end_ms - 1, "limit": 1500},
        )
        if not batch:
            break
        for item in batch:
            open_time = int(item[0])
            if open_time >= end_ms:
                continue
            rows.append(
                {
                    "time": open_time,
                    "open": float(item[1]),
                    "high": float(item[2]),
                    "low": float(item[3]),
                    "close": float(item[4]),
                    "volume": float(item[5]),
                    "closeTime": int(item[6]),
                }
            )
        next_cursor = int(batch[-1][0]) + 86_400_000
        if next_cursor <= cursor:
            break
        cursor = next_cursor
        time.sleep(0.05)
    return rows


def fetch_usdm_1d(symbol: str, start_date: date, end_date: date | None = None) -> list[dict]:
    """Return UTC daily USD-M perpetual candles, including an open current candle when requested."""
    CACHE.mkdir(parents=True, exist_ok=True)
    url = os.environ.get("NXT_USDM_KLINES_URL", DEFAULT_URL).strip() or DEFAULT_URL
    today = datetime.now(timezone.utc).date()
    end_exclusive = end_date or (today + timedelta(days=1))
    path = CACHE / f"{symbol}_1d.json"
    cached: list[dict] = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []

    # Re-fetch a short overlap to repair any interrupted run and refresh the current daily candle.
    refresh_from = max(start_date, today - timedelta(days=45))
    if not cached:
        fresh = _fetch_range(symbol, start_date, end_exclusive, url)
    else:
        first_cached = datetime.fromtimestamp(int(cached[0]["time"]) / 1000, timezone.utc).date()
        last_cached = datetime.fromtimestamp(int(cached[-1]["time"]) / 1000, timezone.utc).date()
        if first_cached > start_date:
            cached = _fetch_range(symbol, start_date, first_cached, url) + cached
        refresh_from = max(start_date, min(refresh_from, last_cached - timedelta(days=2)))
        fresh = _fetch_range(symbol, refresh_from, end_exclusive, url)
    merged = {int(row["time"]): row for row in cached}
    merged.update({int(row["time"]): row for row in fresh})
    raw = sorted(merged.values(), key=lambda row: int(row["time"]))
    path.write_text(json.dumps(raw), encoding="utf-8")

    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    candles: list[dict] = []
    for row in raw:
        day = datetime.fromtimestamp(int(row["time"]) / 1000, timezone.utc).date()
        if not start_date <= day < end_exclusive:
            continue
        item = dict(row)
        item["localDate"] = day.isoformat()
        item["closed"] = int(item.get("closeTime", 0)) < now_ms
        candles.append(item)
    return candles
