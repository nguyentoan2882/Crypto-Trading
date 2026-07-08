from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(Path(__file__).resolve().parent))

import audit_nxt34_btc_bnb_sol_funding_adjusted as funding
import backtest_nxt32_native_1d_latest as native
import test_nxt33_long_only_pullback_continuation as cont
from nxt_tradingview_binance_1d_data import fetch_tradingview_binance_1d
from test_nxt33_ssl14 import enrich_with_ssl_period

SYMBOLS=["BTCUSDT","BNBUSDT","SOLUSDT"]
OUT_DIR=ROOT/"outputs"/"nxt35_short_continuation_native_1d"
OUT_JSON=OUT_DIR/"NXT35_Enable_SHORT_Continuation.json"

def key(t):return (t["symbol"],t["side"],t["signalTime"],t["entryTime"])
def grouped(rows,field):
 out=[]
 for value in sorted({str(t[field]) for t in rows}):
  s=funding.stats_for_key([t for t in rows if str(t[field])==value],"netRAfterFunding");s["group"]=value;out.append(s)
 return out
def run(enabled,datasets,fund):
 cont.ENABLE_SHORT_CONTINUATION=enabled;trades=[]
 for symbol in SYMBOLS:trades.extend(cont.backtest_symbol(symbol,datasets[symbol]))
 trades.sort(key=lambda t:(t["exitTime"],t["symbol"],t["tradeNo"]))
 for t in trades:t.update(funding.funding_for_trade(t,fund[t["symbol"]]));t["netRAfterFunding"]=t["rMultiple"]+t["fundingR"]
 return {"stats":funding.stats_for_key(trades,"netRAfterFunding"),"bySymbol":grouped(trades,"symbol"),"bySide":grouped(trades,"side"),"bySignalType":grouped(trades,"signalType"),"trades":trades}
def main():
 OUT_DIR.mkdir(parents=True,exist_ok=True)
 data={s:enrich_with_ssl_period(fetch_tradingview_binance_1d(s,native.WARMUP_DATE,native.END_DATE),14) for s in SYMBOLS};fund={s:funding.fetch_monthly_funding(s,native.START_DATE,native.END_DATE) for s in SYMBOLS}
 old=cont.ENABLE_SHORT_CONTINUATION
 try:b=run(False,data,fund);v=run(True,data,fund)
 finally:cont.ENABLE_SHORT_CONTINUATION=old
 bk={key(t) for t in b["trades"]};vk={key(t) for t in v["trades"]};added=[t for t in v["trades"] if key(t) not in bk];removed=[t for t in b["trades"] if key(t) not in vk];bs,vs=b["stats"],v["stats"]
 btc_june=[t for t in v["trades"] if t["symbol"]=="BTCUSDT" and t["signalTime"]=="2022-06-10"]
 result={"generatedAt":datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00","Z"),"rule":"Enable symmetric SHORT Continuation: SSL flips bearish, close < EMA20 < EMA50, high touches EMA20 within 5 bars, close < previous close; no RSI or EMA50-distance filter. Other latest rules unchanged.","baseline":b,"variant":v,"delta":{"trades":vs["trades"]-bs["trades"],"totalR":vs["totalR"]-bs["totalR"],"winRate":vs["winRate"]-bs["winRate"],"maxDrawdownR":vs["maxDrawdownR"]-bs["maxDrawdownR"],"profitFactor":vs["profitFactor"]-bs["profitFactor"]},"addedStats":funding.stats_for_key(added,"netRAfterFunding"),"removedStats":funding.stats_for_key(removed,"netRAfterFunding"),"btcSignal20220610":btc_june,"addedTrades":added,"removedTrades":removed}
 OUT_JSON.write_text(json.dumps(result,indent=2),encoding="utf-8");print(json.dumps({"output":str(OUT_JSON),"baseline":bs,"variant":vs,"delta":result["delta"],"variantBySide":v["bySide"],"variantByType":v["bySignalType"],"added":result["addedStats"],"removed":result["removedStats"],"btcSignal20220610":btc_june},indent=2))
if __name__=="__main__":main()
