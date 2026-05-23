from __future__ import annotations

import csv
import datetime as dt
import io
import json
import sys
import urllib.error
import urllib.request
import zipfile
from pathlib import Path


SYMBOLS = ["BTCUSDT", "SOLUSDT", "SUIUSDT"]
START_YEAR, START_MONTH = 2019, 11
END_YEAR, END_MONTH = 2026, 5
END_DATE = dt.date(2026, 5, 17)
OUT_DIR = Path("data_cache/binance_spot_1d")


def months():
    year, month = START_YEAR, START_MONTH
    while (year, month) <= (END_YEAR, END_MONTH):
        yield year, month
        month += 1
        if month == 13:
            year += 1
            month = 1


def read_zip_csv(url: str):
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            payload = response.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return []
        raise

    rows = []
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        names = [n for n in zf.namelist() if n.endswith(".csv")]
        if not names:
            return []
        with zf.open(names[0]) as f:
            text = io.TextIOWrapper(f, encoding="utf-8")
            for row in csv.reader(text):
                if not row or row[0] == "open_time":
                    continue
                open_time = int(float(row[0]))
                close_time = int(float(row[6]))
                if open_time > 10_000_000_000_000:
                    open_time //= 1000
                if close_time > 10_000_000_000_000:
                    close_time //= 1000
                rows.append(
                    {
                        "time": open_time,
                        "open": float(row[1]),
                        "high": float(row[2]),
                        "low": float(row[3]),
                        "close": float(row[4]),
                        "volume": float(row[5]),
                        "closeTime": close_time,
                        "takerBuyBaseVolume": float(row[9]),
                    }
                )
    return rows


def daily_dates(year: int, month: int):
    current = dt.date(year, month, 1)
    while current <= END_DATE and current.month == month:
        yield current
        current += dt.timedelta(days=1)


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for symbol in SYMBOLS:
        all_rows = []
        for year, month in months():
            url = f"https://data.binance.vision/data/spot/monthly/klines/{symbol}/1d/{symbol}-1d-{year}-{month:02d}.zip"
            rows = read_zip_csv(url)
            if not rows and (year, month) == (END_YEAR, END_MONTH):
                for day in daily_dates(year, month):
                    daily_url = f"https://data.binance.vision/data/spot/daily/klines/{symbol}/1d/{symbol}-1d-{day:%Y-%m-%d}.zip"
                    day_rows = read_zip_csv(daily_url)
                    rows.extend(day_rows)
            all_rows.extend(rows)
            if rows:
                print(f"{symbol} {year}-{month:02d}: {len(rows)}")
        all_rows = sorted({r["time"]: r for r in all_rows}.values(), key=lambda r: r["time"])
        (OUT_DIR / f"{symbol}.json").write_text(json.dumps(all_rows), encoding="utf-8")
        print(f"saved {symbol}: {len(all_rows)} rows", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
