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


def _candidate_urls() -> list[str]:
    configured = os.environ.get("NXT_USDM_KLINES_URLS", "").strip()
    if configured:
        values = configured.replace(";", ",").split(",")
    else:
        values = [os.environ.get("NXT_USDM_KLINES_URL", DEFAULT_URL)]
    urls: list[str] = []
    for value in values:
        url = value.strip()
        if url and url not in urls:
            urls.append(url)
    return urls or [DEFAULT_URL]


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
    today = datetime.now(timezone.utc).date()
    end_exclusive = end_date or (today + timedelta(days=1))
    latest_required = min(end_exclusive - timedelta(days=1), today - timedelta(days=1))
    path = CACHE / f"{symbol}_1d.json"
    cached: list[dict] = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []

    # Re-fetch a short overlap to repair any interrupted run and refresh the current daily candle.
    refresh_from = max(start_date, today - timedelta(days=45))
    errors: list[str] = []
    fresh: list[dict] | None = None
    prefix: list[dict] = []
    first_cached = None
    last_cached = None
    if cached:
        first_cached = datetime.fromtimestamp(int(cached[0]["time"]) / 1000, timezone.utc).date()
        last_cached = datetime.fromtimestamp(int(cached[-1]["time"]) / 1000, timezone.utc).date()
        refresh_from = max(start_date, min(refresh_from, last_cached - timedelta(days=2)))

    for url in _candidate_urls():
        try:
            prefix = _fetch_range(symbol, start_date, first_cached, url) if first_cached and first_cached > start_date else []
            fresh = _fetch_range(symbol, refresh_from if cached else start_date, end_exclusive, url)
            break
        except Exception as exc:
            errors.append(f"{url}: {exc}")

    if fresh is None:
        # A current cache is safe during a transient outage. Never silently
        # evaluate stale candles because the missing close can change a signal.
        if not cached or last_cached is None or last_cached < latest_required:
            cached_label = last_cached.isoformat() if last_cached else "none"
            detail = " | ".join(errors) or "no endpoint configured"
            raise RuntimeError(
                f"USD-M live data unavailable and cache is stale for {symbol}: "
                f"required {latest_required.isoformat()}, cached {cached_label}. {detail}"
            )
        fresh = []

    if prefix:
        cached = prefix + cached
    merged = {int(row["time"]): row for row in cached}
    merged.update({int(row["time"]): row for row in fresh})
    raw = sorted(merged.values(), key=lambda row: int(row["time"]))
    last_available = datetime.fromtimestamp(int(raw[-1]["time"]) / 1000, timezone.utc).date() if raw else None
    if last_available is None or last_available < latest_required:
        available_label = last_available.isoformat() if last_available else "none"
        raise RuntimeError(
            f"USD-M data is stale for {symbol} after refresh: "
            f"required {latest_required.isoformat()}, available {available_label}."
        )
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
