from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.nxt_core import rules
from app.nxt_core.comparison import comparison_hash, exact_match


DEFAULT_FIXTURE = ROOT / "tests" / "fixtures" / "nxt_rule_golden_v1.json"
DEFAULT_CACHE = ROOT / "data_cache" / "binance_usdm_futures_1d_live"


def load_candles(path: Path, cutoff_utc: str) -> list[dict]:
    cutoff = datetime.fromisoformat(cutoff_utc.replace("Z", "+00:00"))
    cutoff_ms = int(cutoff.timestamp() * 1000)
    rows = []
    for source in json.loads(path.read_text(encoding="utf-8")):
        if int(source["time"]) >= cutoff_ms + 86_400_000:
            continue
        row = dict(source)
        row["localDate"] = datetime.fromtimestamp(int(row["time"]) / 1000, timezone.utc).date().isoformat()
        row["closed"] = int(row["closeTime"]) < cutoff_ms
        rows.append(row)
    return rows


def compare(fixture_path: Path, cache_dir: Path) -> dict:
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    signal_case = fixture["signalCase"]
    candle_sets = {}
    input_checks = {}
    for symbol, metadata in signal_case["inputs"].items():
        path = cache_dir / f"{symbol}_1d.json"
        file_hash = hashlib.sha256(path.read_bytes()).hexdigest().upper()
        rows = load_candles(path, signal_case["cutoffUtc"])
        input_checks[symbol] = {
            "hashMatch": file_hash == metadata["sha256"],
            "rowsMatch": len(rows) == metadata["rowsUsed"],
        }
        candle_sets[symbol] = rows

    regime = rules.btc_regime_by_date(candle_sets["BTCUSDT"])
    actual_signals = {
        symbol: rules.latest_signal_for_symbol(
            symbol,
            candle_sets[symbol],
            regime,
            detected_at="2000-01-01T00:00:00Z",
        )
        for symbol in sorted(candle_sets)
    }
    followup_case = fixture["followupCase"]
    actual_followup = rules.evaluate_accepted_signal_followup(
        followup_case["subject"],
        followup_case["candles"],
        evaluation_date=followup_case["expected"]["candleDate"],
    )
    signal_match = exact_match(signal_case["expected"], actual_signals)
    followup_match = exact_match(followup_case["expected"], actual_followup, ignored_fields=())
    passed = all(all(check.values()) for check in input_checks.values()) and signal_match and followup_match
    return {
        "passed": passed,
        "ruleVersion": fixture["ruleVersion"],
        "fixture": str(fixture_path),
        "inputChecks": input_checks,
        "signalMatch": signal_match,
        "signalExpectedHash": comparison_hash(signal_case["expected"]),
        "signalActualHash": comparison_hash(actual_signals),
        "followupMatch": followup_match,
        "followupExpectedHash": comparison_hash(followup_case["expected"], ignored_fields=()),
        "followupActualHash": comparison_hash(actual_followup, ignored_fields=()),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare the pure NXT rule engine with its versioned golden fixture.")
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE)
    args = parser.parse_args()
    result = compare(args.fixture.resolve(), args.cache_dir.resolve())
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
