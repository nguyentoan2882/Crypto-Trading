from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone

from app.nxt_cloud.config import PUBLIC_BINANCE_KLINES_URL


DAY_MS = 86_400_000


def _midnight_ms(day: date) -> int:
    return int(datetime(day.year, day.month, day.day, tzinfo=timezone.utc).timestamp() * 1000)


class BinanceUsdMMarketData:
    """Public klines-only adapter. It has no credential or signed-request path."""

    def __init__(self, start_date: date, url: str = PUBLIC_BINANCE_KLINES_URL, timeout: int = 30) -> None:
        if url != PUBLIC_BINANCE_KLINES_URL:
            raise ValueError("unapproved Binance endpoint")
        self.start_date = start_date
        self.url = url
        self.timeout = timeout

    def _request(self, params: dict[str, object]) -> list[list[object]]:
        query = urllib.parse.urlencode(params)
        request = urllib.request.Request(f"{self.url}?{query}", headers={"User-Agent": "nxt-cloud-shadow/1.0"})
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if not isinstance(payload, list):
            raise RuntimeError("unexpected Binance klines response")
        return payload

    def daily_candles(self, symbol: str) -> list[dict]:
        if symbol not in {"BTCUSDT", "BNBUSDT", "SOLUSDT"}:
            raise ValueError("symbol is outside the approved shadow universe")
        now = datetime.now(timezone.utc)
        end_exclusive = now.date() + timedelta(days=1)
        cursor = _midnight_ms(self.start_date)
        end_ms = _midnight_ms(end_exclusive)
        rows: dict[int, dict] = {}
        while cursor < end_ms:
            batch = self._request({"symbol": symbol, "interval": "1d", "startTime": cursor, "endTime": end_ms - 1, "limit": 1500})
            if not batch:
                break
            for item in batch:
                if len(item) < 7:
                    raise RuntimeError("malformed Binance kline")
                open_time = int(item[0])
                close_time = int(item[6])
                day = datetime.fromtimestamp(open_time / 1000, timezone.utc).date()
                rows[open_time] = {
                    "time": open_time,
                    "open": float(item[1]),
                    "high": float(item[2]),
                    "low": float(item[3]),
                    "close": float(item[4]),
                    "volume": float(item[5]),
                    "closeTime": close_time,
                    "localDate": day.isoformat(),
                    "closed": close_time < int(now.timestamp() * 1000),
                }
            next_cursor = int(batch[-1][0]) + DAY_MS
            if next_cursor <= cursor:
                raise RuntimeError("Binance pagination did not advance")
            cursor = next_cursor
            if len(batch) == 1500:
                time.sleep(0.05)
        return [rows[key] for key in sorted(rows)]
