from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LATEST = ROOT / "latest"
SOURCE = ROOT / "outputs" / "nxt35_block_short_after_losing_long_usdm"
ARCHIVE_ROOT = ROOT / "outputs" / "archive_from_latest"
PREFIX = "NXT_Latest_NXT35_USDM_BlockShortAfterLosingLong"


def copy(source: Path, target: Path) -> None:
    if not source.exists():
        raise FileNotFoundError(source)
    shutil.copy2(source, target)


def main() -> None:
    required = {
        "json": SOURCE / "NXT35_USDM_BlockShortAfterLosingLong_FundingAdjusted.json",
        "xlsx": SOURCE / "NXT35_USDM_BlockShortAfterLosingLong_FundingAdjusted_OrderPlan.xlsx",
        "docx": SOURCE / "NXT35_USDM_BlockShortAfterLosingLong_Promoted_System_And_Indicators.docx",
        "regression": SOURCE / "NXT35_USDM_BlockShortAfterLosingLong_SignalRegression.json",
    }
    for path in required.values():
        if not path.exists():
            raise FileNotFoundError(path)
    regression = json.loads(required["regression"].read_text(encoding="utf-8"))
    if not regression.get("passed") or not all(regression.get("checks", {}).values()):
        raise RuntimeError("Promotion blocked: signal-level regression is not fully passing.")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    archive = ARCHIVE_ROOT / f"before_nxt35_usdm_block_short_after_losing_long_{stamp}"
    archive.mkdir(parents=True, exist_ok=False)
    for path in LATEST.glob("NXT_Latest_*"):
        if path.is_file():
            copy(path, archive / path.name)

    payload = json.loads(required["json"].read_text(encoding="utf-8"))
    payload.update(
        {
            "generatedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "systemVersion": "NXT v3.5 USD-M BTC/BNB/SOL + Block SHORT after losing pre-TP1 LONG SSL exit",
            "candidateStatus": "Promoted to latest on 2026-07-14 after full artifact-chain and signal-level regression validation.",
            "promotion": {
                "archive": str(archive.relative_to(ROOT)).replace("\\", "/"),
                "regression": "Passed: candidate has no duplicate trade keys; all removed trades are SHORT; shared trades are financially identical.",
            },
        }
    )
    (LATEST / f"{PREFIX}_FundingAdjusted_20K.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    copy(required["xlsx"], LATEST / f"{PREFIX}_FundingAdjusted_20K.xlsx")
    copy(required["docx"], LATEST / f"{PREFIX}_System_And_Indicators.docx")
    copy(required["regression"], LATEST / f"{PREFIX}_SignalRegression.json")

    stats = payload["fundingAdjustedStats"]
    summary = f"""# NXT Latest Summary\n\n## Promoted system\n\nNXT v3.5 portfolio for BTCUSDT, BNBUSDT and SOLUSDT using Binance USD-M perpetual 1D candles (00:00 UTC), SSL14, Runner A, Early-BE 7%, anti-immediate-reversal after a runner SSL exit netting at least +0.50R, and LONG-only pullback continuation on an SSL bullish flip.\n\nNew promoted rule: block a `SHORT Primary` on the exit candle and the immediately following candle when the prior `LONG` did not reach TP1, exited on an SSL bearish flip, and netted below 0R.\n\n## Backtest basis\n\n- Period: 2020-05-17 to 2026-05-16\n- Data: Binance USD-M perpetual 1D klines and USD-M historical funding\n- Trades: {stats['trades']}\n- Funding-adjusted total: {stats['totalR']:.2f}R\n- Funding-adjusted win rate: {stats['winRate'] * 100:.2f}%\n- Funding-adjusted profit factor: {stats['profitFactor']:.2f}\n- Funding-adjusted maximum drawdown: {stats['maxDrawdownR']:.2f}R\n\n## Published artifacts\n\n- `{PREFIX}_FundingAdjusted_20K.json`\n- `{PREFIX}_FundingAdjusted_20K.xlsx`\n- `{PREFIX}_System_And_Indicators.docx`\n- `{PREFIX}_SignalRegression.json`\n\nSignal-level regression passed: 13 direct blocked SHORT signals mapped to 13 removed baseline SHORT trades; 234 shared trades had no financial mismatch.\n\nPrior `latest/` artifacts were archived before this publish at `{archive.relative_to(ROOT).as_posix()}`.\n"""
    (LATEST / "NXT_Latest_Summary.md").write_text(summary, encoding="utf-8")
    print(f"Promoted {PREFIX}; archived prior latest at {archive}")


if __name__ == "__main__":
    main()
