from __future__ import annotations

from datetime import date
from pathlib import Path

import backtest_nxt35_us_top3_stocks_3y as runner


ROOT = Path(__file__).resolve().parents[1]

runner.START_DATE = date(2020, 5, 17)
runner.END_DATE = date(2026, 5, 17)
runner.WARMUP_DATE = date(2019, 11, 1)
runner.OUT_DIR = ROOT / "outputs" / "nxt35_us_top3_stocks_6y"
runner.OUT_JSON = runner.OUT_DIR / "NXT35_US_Top3_Stocks_6Y.json"
runner.OUT_XLSX = runner.OUT_DIR / "NXT35_US_Top3_Stocks_6Y_20K.xlsx"


if __name__ == "__main__":
    runner.main()
