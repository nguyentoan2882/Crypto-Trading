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
from nxt_tradingview_binance_1d_data import fetch_tradingview_binance_1d
from test_nxt33_ssl14 import enrich_with_ssl_period

SYMBOLS=["BTCUSDT","BNBUSDT","SOLUSDT"]
OUT_DIR=ROOT/"outputs"/"nxt35_continuation_ssl_flip_native_1d"
OUT_JSON=OUT_DIR/"NXT35_Continuation_SSL_Flip_Bullish.json"

def key(t): return (t["symbol"],t["side"],t["signalTime"],t["entryTime"])

def stats_by(rows,field):
    out=[]
    for value in sorted({str(t[field]) for t in rows}):
        subset=[t for t in rows if str(t[field])==value]
        item=funding.stats_for_key(subset,"netRAfterFunding");item["group"]=value;out.append(item)
    return out

def run(require_flip,datasets,fund):
    cont.CONTINUATION_REQUIRE_SSL_FLIP=require_flip
    trades=[]
    for symbol in SYMBOLS: trades.extend(cont.backtest_symbol(symbol,datasets[symbol]))
    trades.sort(key=lambda t:(t["exitTime"],t["symbol"],t["tradeNo"]))
    for t in trades:
        t.update(funding.funding_for_trade(t,fund[t["symbol"]]));t["netRAfterFunding"]=t["rMultiple"]+t["fundingR"]
    return {"stats":funding.stats_for_key(trades,"netRAfterFunding"),"bySymbol":stats_by(trades,"symbol"),"bySignalType":stats_by(trades,"signalType"),"trades":trades}

def main():
    OUT_DIR.mkdir(parents=True,exist_ok=True)
    datasets={s:enrich_with_ssl_period(fetch_tradingview_binance_1d(s,native.WARMUP_DATE,native.END_DATE),14) for s in SYMBOLS}
    fund={s:funding.fetch_monthly_funding(s,native.START_DATE,native.END_DATE) for s in SYMBOLS}
    old=cont.CONTINUATION_REQUIRE_SSL_FLIP
    try:
        baseline=run(False,datasets,fund);variant=run(True,datasets,fund)
    finally: cont.CONTINUATION_REQUIRE_SSL_FLIP=old
    bk={key(t) for t in baseline["trades"]};vk={key(t) for t in variant["trades"]}
    removed=[t for t in baseline["trades"] if key(t) not in vk];added=[t for t in variant["trades"] if key(t) not in bk]
    b,v=baseline["stats"],variant["stats"]
    payload={"generatedAt":datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00","Z"),"rule":"Continuation LONG requires prev SSL=-1 and current SSL=+1 on the signal bar; all other current latest rules including Early-BE High/Low 7% remain unchanged.","baseline":baseline,"variant":variant,"delta":{"trades":v["trades"]-b["trades"],"totalR":v["totalR"]-b["totalR"],"winRate":v["winRate"]-b["winRate"],"maxDrawdownR":v["maxDrawdownR"]-b["maxDrawdownR"],"profitFactor":v["profitFactor"]-b["profitFactor"]},"removedTradeStats":funding.stats_for_key(removed,"netRAfterFunding"),"addedTradeStats":funding.stats_for_key(added,"netRAfterFunding"),"removedTrades":removed,"addedTrades":added}
    OUT_JSON.write_text(json.dumps(payload,indent=2),encoding="utf-8")
    print(json.dumps({"output":str(OUT_JSON),"baseline":b,"variant":v,"delta":payload["delta"],"baselineByType":baseline["bySignalType"],"variantByType":variant["bySignalType"],"removed":payload["removedTradeStats"],"added":payload["addedTradeStats"]},indent=2))

if __name__=="__main__":main()
