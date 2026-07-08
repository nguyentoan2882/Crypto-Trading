from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

import audit_nxt34_btc_bnb_sol_funding_adjusted as funding
import backtest_nxt32_native_1d_latest as native
import test_nxt33_long_only_pullback_continuation as cont
import test_nxt35_early_be_10pct_native_1d as test
from nxt_tradingview_binance_1d_data import fetch_tradingview_binance_1d
from test_nxt33_ssl14 import enrich_with_ssl_period

THRESHOLDS = [None, 0.05, 0.06, 0.0625, 0.065, 0.0675, 0.07, 0.0725, 0.075, 0.08, 0.09, 0.10, 0.11, 0.12, 0.13, 0.14, 0.15, 0.16, 0.18, 0.20]
OUT_DIR = ROOT / "outputs" / "nxt35_early_be_walk_forward_native_1d"
OUT_JSON = OUT_DIR / "NXT35_Early_BE_7pct_OOS_WalkForward.json"

def subset_stats(trades, years):
    subset=[t for t in trades if int(t["exitTime"][:4]) in years]
    stats=funding.stats_for_key(subset,"netRAfterFunding")
    return {"years":sorted(years), **stats}

def label(value):
    return "No Early-BE" if value is None else f"{value*100:g}%"

def main():
    OUT_DIR.mkdir(parents=True,exist_ok=True)
    datasets={s:enrich_with_ssl_period(fetch_tradingview_binance_1d(s,native.WARMUP_DATE,native.END_DATE),14) for s in test.SYMBOLS}
    fund={s:funding.fetch_monthly_funding(s,native.START_DATE,native.END_DATE) for s in test.SYMBOLS}
    old=(cont.TP1_ATR,cont.EARLY_BE_PROFIT_PCT)
    try:
        runs={value:test.run(value,datasets,fund) for value in THRESHOLDS}
    finally:
        cont.TP1_ATR,cont.EARLY_BE_PROFIT_PCT=old

    development_years={2020,2021,2022,2023}
    oos_years={2024,2025,2026}
    dev_rank=[]
    for value in THRESHOLDS:
        stats=subset_stats(runs[value]["trades"],development_years)
        dev_rank.append({"threshold":label(value),"thresholdValue":value,"stats":stats})
    dev_rank.sort(key=lambda x:x["stats"]["totalR"],reverse=True)
    selected=dev_rank[0]["thresholdValue"]
    chronological={
        "developmentYears":sorted(development_years),
        "oosYears":sorted(oos_years),
        "bestDevelopmentThreshold":label(selected),
        "developmentTop5":dev_rank[:5],
        "selectedThresholdOos":subset_stats(runs[selected]["trades"],oos_years),
        "baselineOos":subset_stats(runs[None]["trades"],oos_years),
        "fixed7PctDevelopment":subset_stats(runs[0.07]["trades"],development_years),
        "fixed7PctOos":subset_stats(runs[0.07]["trades"],oos_years),
    }

    rolling=[]
    for test_year in [2023,2024,2025,2026]:
        train_years=set(range(test_year-3,test_year))
        ranked=[]
        for value in THRESHOLDS:
            stats=subset_stats(runs[value]["trades"],train_years)
            ranked.append((stats["totalR"],value,stats))
        ranked.sort(key=lambda x:x[0],reverse=True)
        chosen=ranked[0][1]
        test_years={test_year}
        chosen_test=subset_stats(runs[chosen]["trades"],test_years)
        baseline_test=subset_stats(runs[None]["trades"],test_years)
        fixed7_test=subset_stats(runs[0.07]["trades"],test_years)
        rolling.append({
            "trainYears":sorted(train_years),"testYear":test_year,
            "selectedThreshold":label(chosen),"selectedTrainR":ranked[0][0],
            "selectedTest":chosen_test,"baselineTest":baseline_test,"fixed7PctTest":fixed7_test,
            "selectedDeltaRVsBaseline":chosen_test["totalR"]-baseline_test["totalR"],
            "fixed7PctDeltaRVsBaseline":fixed7_test["totalR"]-baseline_test["totalR"],
        })

    fixed7_yearly=[]
    for year in range(2020,2027):
        b=subset_stats(runs[None]["trades"],{year}); v=subset_stats(runs[0.07]["trades"],{year})
        fixed7_yearly.append({"year":year,"baselineR":b["totalR"],"earlyBe7R":v["totalR"],"deltaR":v["totalR"]-b["totalR"],"baselineTrades":b["trades"],"earlyBe7Trades":v["trades"]})

    result={
        "generatedAt":datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00","Z"),
        "method":"Chronological OOS plus rolling 3-year training / next-year test; threshold selected by funding-adjusted Total R; 2026 is partial through 2026-05-16.",
        "chronologicalOos":chronological,"rollingWalkForward":rolling,"fixed7PctByYear":fixed7_yearly,
    }
    OUT_JSON.write_text(json.dumps(result,indent=2),encoding="utf-8")
    print(json.dumps({"output":str(OUT_JSON),**result},indent=2))

if __name__=="__main__": main()
