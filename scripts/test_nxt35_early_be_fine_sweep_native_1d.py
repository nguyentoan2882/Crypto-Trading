from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

import audit_nxt34_btc_bnb_sol_funding_adjusted as funding
import backtest_nxt32_native_1d_latest as native
import test_nxt33_long_only_pullback_continuation as cont
import test_nxt35_early_be_10pct_native_1d as test
from nxt_tradingview_binance_1d_data import fetch_tradingview_binance_1d
from test_nxt33_ssl14 import enrich_with_ssl_period

VALUES = [0.060, 0.0625, 0.065, 0.0675, 0.070, 0.0725, 0.075, 0.0775, 0.080]
OUT = ROOT / "outputs" / "nxt35_early_be_pct_sweep_native_1d" / "NXT35_Early_BE_Fine_6_to_8pct_Native1D.json"

def yearly(rows):
    out=[]
    for year in range(2020, 2027):
        subset=[t for t in rows if t["exitTime"].startswith(str(year))]
        st=funding.stats_for_key(subset,"netRAfterFunding"); st["year"]=year; out.append(st)
    return out

def main():
    datasets={s:enrich_with_ssl_period(fetch_tradingview_binance_1d(s,native.WARMUP_DATE,native.END_DATE),14) for s in test.SYMBOLS}
    fund={s:funding.fetch_monthly_funding(s,native.START_DATE,native.END_DATE) for s in test.SYMBOLS}
    old=(cont.TP1_ATR,cont.EARLY_BE_PROFIT_PCT)
    try:
        baseline=test.run(None,datasets,fund)
        variants=[test.run(v,datasets,fund) for v in VALUES]
    finally:
        cont.TP1_ATR,cont.EARLY_BE_PROFIT_PCT=old
    rows=[]
    for value,result in zip(VALUES,variants):
        s=result["stats"]
        rows.append({"thresholdPct":value*100,"totalR":s["totalR"],"deltaR":s["totalR"]-baseline["stats"]["totalR"],"profitFactor":s["profitFactor"],"maxDrawdownR":s["maxDrawdownR"],"trades":s["trades"],"triggered":result["earlyBeTriggered"],"beExits":result["earlyBeStopExits"],"bySymbol":result["bySymbol"],"byYear":yearly(result["trades"])})
    OUT.write_text(json.dumps({"baseline":baseline["stats"],"variants":rows},indent=2),encoding="utf-8")
    print(json.dumps({"output":str(OUT),"variants":[{k:r[k] for k in ["thresholdPct","totalR","deltaR","profitFactor","maxDrawdownR","trades","triggered","beExits"]} for r in rows]},indent=2))

if __name__=="__main__": main()
