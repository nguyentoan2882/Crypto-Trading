from __future__ import annotations

import json
import os
import time
import http.client
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CACHE_DIR = ROOT / "data_cache" / "binance_spot_1h"
BINANCE_API = os.environ.get("NXT_BINANCE_KLINES_URL", "https://data-api.binance.vision/api/v3/klines")
UTC7_OFFSET = timedelta(hours=7)


def _seed_rows(symbol: str) -> list[dict]:
    live_path = CACHE_DIR / f"{symbol}_1h_live.json"
    candidates = sorted(
        (path for path in CACHE_DIR.glob(f"{symbol}_1h_*.json") if path != live_path),
        key=lambda path: path.stat().st_size,
        reverse=True,
    )
    if live_path.exists():
        candidates.insert(0, live_path)
    rows: dict[int, dict] = {}
    for path in candidates[:2]:
        for row in json.loads(path.read_text(encoding="utf-8")):
            rows[int(row["time"])] = row
    return sorted(rows.values(), key=lambda row: int(row["time"]))


def fetch_1h(symbol: str, start_date: date, end_date: date | None = None) -> list[dict]:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    rows = _seed_rows(symbol)
    by_time = {int(row["time"]): dict(row) for row in rows}
    changed = False
    start_ms = int(datetime.combine(start_date, datetime.min.time(), timezone.utc).timestamp() * 1000)
    if by_time:
        start_ms = max(start_ms, max(by_time) + 3_600_000)
    end_ms = (
        int(datetime.combine(end_date + timedelta(days=1), datetime.min.time(), timezone.utc).timestamp() * 1000) - 1
        if end_date
        else int(datetime.now(timezone.utc).timestamp() * 1000)
    )

    while start_ms <= end_ms:
        query = urllib.parse.urlencode({
            "symbol": symbol,
            "interval": "1h",
            "startTime": start_ms,
            "endTime": end_ms,
            "limit": 1000,
        })
        request = urllib.request.Request(f"{BINANCE_API}?{query}", headers={"User-Agent": "nxt-tradingview-utc7/1.0"})
        last_error: Exception | None = None
        batch = None
        for attempt in range(4):
            try:
                with urllib.request.urlopen(request, timeout=30) as response:
                    batch = json.loads(response.read().decode("utf-8"))
                break
            except (urllib.error.URLError, TimeoutError, ConnectionResetError, http.client.IncompleteRead) as exc:
                last_error = exc
                time.sleep(1 + attempt * 2)
        if batch is None:
            raise RuntimeError(f"Failed to fetch Binance 1H data for {symbol}") from last_error
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
        next_start = int(batch[-1][0]) + 3_600_000
        if next_start <= start_ms:
            break
        start_ms = next_start
        time.sleep(0.03)

    all_rows = sorted(by_time.values(), key=lambda row: int(row["time"]))
    if changed or not (CACHE_DIR / f"{symbol}_1h_live.json").exists():
        (CACHE_DIR / f"{symbol}_1h_live.json").write_text(json.dumps(all_rows), encoding="utf-8")
    return [row for row in all_rows if int(row["time"]) <= end_ms]


def resample_utc7(rows: list[dict], now_ms: int | None = None) -> list[dict]:
    now_ms = now_ms if now_ms is not None else int(datetime.now(timezone.utc).timestamp() * 1000)
    bars: list[dict] = []
    current: dict | None = None
    for row in sorted(rows, key=lambda item: int(item["time"])):
        local_day = (datetime.fromtimestamp(int(row["time"]) / 1000, timezone.utc) + UTC7_OFFSET).date()
        label = local_day.isoformat()
        if current is None or current["localDate"] != label:
            open_ms = int((datetime.combine(local_day, datetime.min.time(), timezone.utc) - UTC7_OFFSET).timestamp() * 1000)
            current = {
                "localDate": label,
                "time": open_ms,
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": float(row.get("volume", 0.0)),
                "takerBuyBaseVolume": float(row.get("takerBuyBaseVolume", 0.0)),
                "closeTime": open_ms + 86_400_000 - 1,
            }
            bars.append(current)
        else:
            current["high"] = max(float(current["high"]), float(row["high"]))
            current["low"] = min(float(current["low"]), float(row["low"]))
            current["close"] = float(row["close"])
            current["volume"] += float(row.get("volume", 0.0))
            current["takerBuyBaseVolume"] += float(row.get("takerBuyBaseVolume", 0.0))
        current["closed"] = int(current["closeTime"]) <= now_ms
    return bars


def fetch_tradingview_utc7_1d(symbol: str, start_date: date, end_date: date | None = None) -> list[dict]:
    rows = fetch_1h(symbol, start_date - timedelta(days=1), end_date)
    bars = resample_utc7(rows)
    return [
        bar for bar in bars
        if date.fromisoformat(bar["localDate"]) >= start_date
        and (end_date is None or date.fromisoformat(bar["localDate"]) <= end_date)
    ]
