import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const symbols = ["BTCUSDT", "SOLUSDT", "SUIUSDT"];
const end = Date.UTC(2026, 4, 17, 0, 0, 0);
const start = Date.UTC(2020, 4, 17, 0, 0, 0);
const warmupStart = Date.UTC(2019, 10, 1, 0, 0, 0);
const outDir = path.resolve("outputs", "nxt_crypto_btc_sol_sui_6y_v30_tp1_15_tp2_25");
const jsonPath = path.join(outDir, "nxt_v30_tp1_15_tp2_25_6y_results.json");
const xlsxPath = path.join(outDir, "NXT_V30_TP1_15_TP2_25_6Y_BTC_SOL_SUI_20K.xlsx");
const feeRate = 0.0006;
const slippageRate = 0.0005;
const roundTripCostRate = 2 * (feeRate + slippageRate);
const yahooSymbols = {
  BTCUSDT: "BTC-USD",
  SOLUSDT: "SOL-USD",
  SUIUSDT: "SUI20947-USD",
};
const tp1Atr = 1.5;
const tp2Atr = 2.5;
const tp1Weight = 0.5;
const startingEquity = 20000;
const riskPct = 0.02;
const compareOutDir = path.resolve("outputs", "nxt_v30_fixed_signal_comparison_6y");
const compareJsonPath = path.join(compareOutDir, "nxt_v30_fixed_signal_comparison_6y.json");

function iso(ms) {
  return new Date(ms).toISOString().replace(".000Z", "Z");
}

function sma(values, period) {
  const out = Array(values.length).fill(null);
  let sum = 0;
  let count = 0;
  for (let i = 0; i < values.length; i++) {
    const add = values[i];
    if (add != null && !Number.isNaN(add)) {
      sum += add;
      count += 1;
    }
    if (i >= period) {
      const drop = values[i - period];
      if (drop != null && !Number.isNaN(drop)) {
        sum -= drop;
        count -= 1;
      }
    }
    if (i >= period - 1 && count === period) out[i] = sum / period;
  }
  return out;
}

function ema(values, period) {
  const out = Array(values.length).fill(null);
  const k = 2 / (period + 1);
  let sum = 0;
  for (let i = 0; i < values.length; i++) {
    const v = values[i];
    if (i < period) sum += v;
    if (i === period - 1) out[i] = sum / period;
    if (i >= period) out[i] = v * k + out[i - 1] * (1 - k);
  }
  return out;
}

function atr(candles, period) {
  const tr = candles.map((c, i) => {
    if (i === 0) return c.high - c.low;
    const prevClose = candles[i - 1].close;
    return Math.max(c.high - c.low, Math.abs(c.high - prevClose), Math.abs(c.low - prevClose));
  });
  return sma(tr, period);
}

function sslState(candles, length = 10) {
  const highSma = sma(candles.map(c => c.high), length);
  const lowSma = sma(candles.map(c => c.low), length);
  const out = Array(candles.length).fill(null);
  let state = 0;
  for (let i = 0; i < candles.length; i++) {
    if (highSma[i] == null || lowSma[i] == null) continue;
    if (candles[i].close > highSma[i]) state = 1;
    else if (candles[i].close < lowSma[i]) state = -1;
    out[i] = state;
  }
  return out;
}

function netVolume(c) {
  if (c.takerBuyBaseVolume != null) return c.takerBuyBaseVolume * 2 - c.volume;
  if (c.close > c.open) return c.volume;
  if (c.close < c.open) return -c.volume;
  return 0;
}

async function fetchBinanceKlines(symbol, interval, from, to) {
  const rows = [];
  let cursor = from;
  while (cursor < to) {
    const url = new URL("https://api.binance.com/api/v3/klines");
    url.searchParams.set("symbol", symbol);
    url.searchParams.set("interval", interval);
    url.searchParams.set("startTime", String(cursor));
    url.searchParams.set("endTime", String(to));
    url.searchParams.set("limit", "1000");
    const res = await fetch(url);
    if (!res.ok) throw new Error(`${symbol} ${interval} ${res.status}: ${await res.text()}`);
    const batch = await res.json();
    if (!batch.length) break;
    for (const r of batch) {
      rows.push({
        time: Number(r[0]),
        open: Number(r[1]),
        high: Number(r[2]),
        low: Number(r[3]),
        close: Number(r[4]),
        volume: Number(r[5]),
        closeTime: Number(r[6]),
        takerBuyBaseVolume: Number(r[9]),
      });
    }
    const next = Number(batch[batch.length - 1][0]) + 1;
    if (next <= cursor) break;
    cursor = next;
  }
  return rows;
}

async function fetchYahooDaily(symbol, from, to) {
  const yahooSymbol = yahooSymbols[symbol];
  const url = new URL(`https://query1.finance.yahoo.com/v8/finance/chart/${yahooSymbol}`);
  url.searchParams.set("period1", String(Math.floor(from / 1000)));
  url.searchParams.set("period2", String(Math.floor(to / 1000)));
  url.searchParams.set("interval", "1d");
  url.searchParams.set("includePrePost", "false");
  url.searchParams.set("events", "history");
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${yahooSymbol} ${res.status}: ${await res.text()}`);
  const json = await res.json();
  const result = json.chart?.result?.[0];
  if (!result?.timestamp?.length) throw new Error(`${yahooSymbol}: no Yahoo chart rows`);
  const q = result.indicators.quote[0];
  return result.timestamp.map((ts, i) => {
    const time = ts * 1000;
    return {
      time,
      open: q.open[i],
      high: q.high[i],
      low: q.low[i],
      close: q.close[i],
      volume: q.volume[i] ?? 0,
      closeTime: time + 24 * 60 * 60 * 1000 - 1,
    };
  }).filter(c => [c.open, c.high, c.low, c.close].every(v => v != null && !Number.isNaN(v)));
}

function enrich(candles) {
  const closes = candles.map(c => c.close);
  const ema20 = ema(closes, 20);
  const ema50 = ema(closes, 50);
  const atr14 = atr(candles, 14);
  const ssl = sslState(candles, 10);
  return candles.map((c, i) => ({
    ...c,
    ema20: ema20[i],
    ema50: ema50[i],
    atr14: atr14[i],
    ssl: ssl[i],
    netVolume: netVolume(c),
  }));
}

function toWeekly(daily) {
  const weeks = [];
  for (const c of daily) {
    const d = new Date(c.time);
    const day = d.getUTCDay();
    const monday = Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate() - ((day + 6) % 7));
    let w = weeks[weeks.length - 1];
    if (!w || w.time !== monday) {
      w = { time: monday, open: c.open, high: c.high, low: c.low, close: c.close, volume: c.volume, closeTime: c.closeTime };
      weeks.push(w);
    } else {
      w.high = Math.max(w.high, c.high);
      w.low = Math.min(w.low, c.low);
      w.close = c.close;
      w.volume += c.volume;
      w.closeTime = c.closeTime;
    }
  }
  return enrich(weeks);
}

function weeklyRegimeAt(weekly, time) {
  let idx = -1;
  for (let i = 0; i < weekly.length; i++) {
    if (weekly[i].closeTime < time) idx = i;
    else break;
  }
  if (idx < 1) return "NEUTRAL";
  const w = weekly[idx];
  if ([w.ema20, w.ema50, w.ssl].some(v => v == null)) return "NEUTRAL";
  if (w.close > w.ema20 && w.ssl === 1) return "BULL";
  if (w.close < w.ema20 && w.ssl === -1) return "BEAR";
  return "NEUTRAL";
}

function crossedUp(current, previous, key) {
  return previous.close <= previous[key] && current.close > current[key];
}

function crossedDown(current, previous, key) {
  return previous.close >= previous[key] && current.close < current[key];
}

function crossedUpRecently(daily, index, key, lookback = 3) {
  const from = Math.max(1, index - lookback + 1);
  for (let j = from; j <= index; j++) {
    if (crossedUp(daily[j], daily[j - 1], key)) return true;
  }
  return false;
}

function crossedDownRecently(daily, index, key, lookback = 3) {
  const from = Math.max(1, index - lookback + 1);
  for (let j = from; j <= index; j++) {
    if (crossedDown(daily[j], daily[j - 1], key)) return true;
  }
  return false;
}

function costR(entryPrice, riskPerUnit) {
  return (entryPrice * roundTripCostRate) / riskPerUnit;
}

function collectSignals(symbol, daily) {
  const signals = [];
  for (let i = 51; i < daily.length - 1; i++) {
    const prev = daily[i - 1];
    const c = daily[i];
    const next = daily[i + 1];
    if (next.time < start || next.time >= end) continue;
    if ([prev.ema20, prev.ema50, prev.atr14, prev.ssl, c.ema20, c.ema50, c.atr14, c.ssl].some(v => v == null)) continue;
    const sslBullCross = prev.ssl === -1 && c.ssl === 1;
    const sslBearCross = prev.ssl === 1 && c.ssl === -1;
    const priceCrossUpEma20 = crossedUpRecently(daily, i, "ema20", 3);
    const priceCrossDownEma20 = crossedDownRecently(daily, i, "ema20", 3);
    const distanceToEma50Atr = Math.abs(c.close - c.ema50) / c.atr14;
    const distanceOk = distanceToEma50Atr <= 2;
    const longOk = sslBullCross && priceCrossUpEma20 && c.netVolume > 0 && distanceOk;
    const shortOk = sslBearCross && priceCrossDownEma20 && c.netVolume < 0 && distanceOk;
    if (!longOk && !shortOk) continue;
    const side = longOk ? "LONG" : "SHORT";
    const entryPrice = next.open;
    const riskPerUnit = c.atr14 * 1.5;
    signals.push({
      symbol,
      i,
      side,
      signalTime: c.time,
      entryTime: next.time,
      entryPrice,
      initialStop: side === "LONG" ? entryPrice - riskPerUnit : entryPrice + riskPerUnit,
      riskPerUnit,
      atr14: c.atr14,
      ema20: c.ema20,
      ema50: c.ema50,
      sslAtSignal: c.ssl,
      netVolume: c.netVolume,
      distanceToEma50Atr,
      weeklyRegime: "OFF",
    });
  }
  return signals;
}

function createPosition(signal, model) {
  return {
    ...signal,
    stop: signal.initialStop,
    tp1: signal.side === "LONG" ? signal.entryPrice + signal.atr14 * model.tp1Atr : signal.entryPrice - signal.atr14 * model.tp1Atr,
    tp2: signal.side === "LONG" ? signal.entryPrice + signal.atr14 * model.tp2Atr : signal.entryPrice - signal.atr14 * model.tp2Atr,
    breakEvenLevel: signal.side === "LONG" ? signal.entryPrice + signal.atr14 * model.beAtr : signal.entryPrice - signal.atr14 * model.beAtr,
    tp1Done: false,
    breakEvenDone: false,
    tp1Time: null,
    realizedR: 0,
    notes: [],
  };
}

function closePosition(symbol, tradeNo, position, c, exitPrice, exitReason, model) {
  const side = position.side;
  const remainingWeight = position.tp1Done && model.tp1Weight > 0 ? 1 - model.tp1Weight : 1;
  const remainingR = side === "LONG"
    ? (exitPrice - position.entryPrice) / position.riskPerUnit
    : (position.entryPrice - exitPrice) / position.riskPerUnit;
  const grossR = position.realizedR + remainingWeight * remainingR;
  const costInR = costR(position.entryPrice, position.riskPerUnit);
  return {
    symbol,
    tradeNo,
    side,
    signalTime: iso(position.signalTime),
    entryTime: iso(position.entryTime),
    entryPrice: position.entryPrice,
    initialStop: position.initialStop,
    finalStop: position.stop,
    riskPerUnit: position.riskPerUnit,
    tp1: position.tp1,
    tp1Time: position.tp1Time ? iso(position.tp1Time) : "",
    tp2: position.tp2,
    exitTime: iso(c.time),
    exitPrice,
    exitReason,
    grossRMultiple: grossR,
    costR: costInR,
    rMultiple: grossR - costInR,
    pctMove: side === "LONG" ? exitPrice / position.entryPrice - 1 : position.entryPrice / exitPrice - 1,
    tp1Hit: position.breakEvenDone ? "Yes" : "No",
    ema20: position.ema20,
    ema50: position.ema50,
    atr14: position.atr14,
    sslAtSignal: position.sslAtSignal,
    netVolume: position.netVolume,
    distanceToEma50Atr: position.distanceToEma50Atr,
    weeklyRegime: position.weeklyRegime,
    notes: position.notes.join("; "),
  };
}

function backtestFixedSignals(symbol, daily, signals, model) {
  const byIndex = new Map(signals.map(s => [s.i, s]));
  const trades = [];
  const skippedSignals = [];
  let position = null;
  let tradeNo = 1;
  let acceptedSignals = 0;

  for (let i = 51; i < daily.length - 1; i++) {
    const prev = daily[i - 1];
    const c = daily[i];
    const signal = byIndex.get(i);
    if (position) {
      let exitPrice = null;
      let exitReason = null;
      const side = position.side;
      const sslFlip = side === "LONG"
        ? prev.ssl === 1 && c.ssl === -1
        : prev.ssl === -1 && c.ssl === 1;

      if (side === "LONG") {
        if (c.low <= position.stop) {
          exitPrice = position.stop;
          exitReason = position.breakEvenDone ? "Breakeven stop" : "Stop loss";
        } else {
          if (model.tp1Weight > 0 && !position.tp1Done && c.high >= position.tp1) {
            position.tp1Done = true;
            position.breakEvenDone = true;
            position.tp1Time = c.time;
            position.stop = position.entryPrice;
            position.realizedR += model.tp1Weight * ((position.tp1 - position.entryPrice) / position.riskPerUnit);
          } else if (model.tp1Weight === 0 && !position.breakEvenDone && c.high >= position.breakEvenLevel) {
            position.breakEvenDone = true;
            position.tp1Time = c.time;
            position.stop = position.entryPrice;
          }
          if (c.high >= position.tp2) {
            exitPrice = position.tp2;
            exitReason = model.tp1Weight > 0 ? "TP2" : "TP 2.5 ATR";
          } else if (sslFlip) {
            exitPrice = c.close;
            exitReason = "SSL bearish flip";
          }
        }
      } else {
        if (c.high >= position.stop) {
          exitPrice = position.stop;
          exitReason = position.breakEvenDone ? "Breakeven stop" : "Stop loss";
        } else {
          if (model.tp1Weight > 0 && !position.tp1Done && c.low <= position.tp1) {
            position.tp1Done = true;
            position.breakEvenDone = true;
            position.tp1Time = c.time;
            position.stop = position.entryPrice;
            position.realizedR += model.tp1Weight * ((position.entryPrice - position.tp1) / position.riskPerUnit);
          } else if (model.tp1Weight === 0 && !position.breakEvenDone && c.low <= position.breakEvenLevel) {
            position.breakEvenDone = true;
            position.tp1Time = c.time;
            position.stop = position.entryPrice;
          }
          if (c.low <= position.tp2) {
            exitPrice = position.tp2;
            exitReason = model.tp1Weight > 0 ? "TP2" : "TP 2.5 ATR";
          } else if (sslFlip) {
            exitPrice = c.close;
            exitReason = "SSL bullish flip";
          }
        }
      }
      if (exitPrice != null) {
        trades.push(closePosition(symbol, tradeNo++, position, c, exitPrice, exitReason, model));
        position = null;
      }
    }

    if (signal) {
      if (position) {
        skippedSignals.push({ symbol, signalTime: iso(signal.signalTime), entryTime: iso(signal.entryTime), side: signal.side, openEntryTime: iso(position.entryTime) });
      } else {
        position = createPosition(signal, model);
        acceptedSignals += 1;
      }
    }
  }

  if (position) {
    const last = daily[daily.length - 1];
    trades.push(closePosition(symbol, tradeNo++, position, last, last.close, "End of test mark-to-market", model));
  }
  return { trades, acceptedSignals, skippedSignals };
}

function backtestSymbol(symbol, daily, weekly) {
  const trades = [];
  let position = null;
  let tradeNo = 1;

  for (let i = 51; i < daily.length - 1; i++) {
    const prev = daily[i - 1];
    const c = daily[i];
    const next = daily[i + 1];
    if (next.time < start || next.time >= end) continue;

    if (position) {
      let exitPrice = null;
      let exitReason = null;
      const side = position.side;
      const remainingWeight = position.tp1Done ? 1 - tp1Weight : 1;
      const sslFlip = side === "LONG"
        ? prev.ssl === 1 && c.ssl === -1
        : prev.ssl === -1 && c.ssl === 1;

      if (side === "LONG") {
        if (c.low <= position.stop) {
          exitPrice = position.stop;
          exitReason = position.tp1Done ? "Breakeven stop after TP1" : "Stop loss";
        } else {
          if (!position.tp1Done && c.high >= position.tp1) {
            position.tp1Done = true;
            position.breakEvenDone = true;
            position.tp1Time = c.time;
            position.stop = position.entryPrice;
            position.realizedR += tp1Weight * ((position.tp1 - position.entryPrice) / position.riskPerUnit);
            position.notes.push(`TP1 hit ${iso(c.time)} at ${tp1Atr} ATR; ${(tp1Weight * 100).toFixed(0)}% closed and stop moved to entry`);
          }
          if (c.high >= position.tp2) {
            exitPrice = position.tp2;
            exitReason = "TP2";
          } else if (sslFlip) {
            exitPrice = c.close;
            exitReason = "SSL bearish flip";
          }
        }
      } else {
        if (c.high >= position.stop) {
          exitPrice = position.stop;
          exitReason = position.tp1Done ? "Breakeven stop after TP1" : "Stop loss";
        } else {
          if (!position.tp1Done && c.low <= position.tp1) {
            position.tp1Done = true;
            position.breakEvenDone = true;
            position.tp1Time = c.time;
            position.stop = position.entryPrice;
            position.realizedR += tp1Weight * ((position.entryPrice - position.tp1) / position.riskPerUnit);
            position.notes.push(`TP1 hit ${iso(c.time)} at ${tp1Atr} ATR; ${(tp1Weight * 100).toFixed(0)}% closed and stop moved to entry`);
          }
          if (c.low <= position.tp2) {
            exitPrice = position.tp2;
            exitReason = "TP2";
          } else if (sslFlip) {
            exitPrice = c.close;
            exitReason = "SSL bullish flip";
          }
        }
      }

      if (exitPrice != null) {
        const remainingR = side === "LONG"
          ? (exitPrice - position.entryPrice) / position.riskPerUnit
          : (position.entryPrice - exitPrice) / position.riskPerUnit;
        const grossR = position.realizedR + remainingWeight * remainingR;
        const costInR = costR(position.entryPrice, position.riskPerUnit);
        trades.push({
          symbol,
          tradeNo: tradeNo++,
          side,
          signalTime: iso(position.signalTime),
          entryTime: iso(position.entryTime),
          entryPrice: position.entryPrice,
          initialStop: position.initialStop,
          finalStop: position.stop,
          riskPerUnit: position.riskPerUnit,
          tp1: position.tp1,
          tp1Time: position.tp1Time ? iso(position.tp1Time) : "",
          tp2: position.tp2,
          exitTime: iso(c.time),
          exitPrice,
          exitReason,
          grossRMultiple: grossR,
          costR: costInR,
          rMultiple: grossR - costInR,
          pctMove: side === "LONG" ? exitPrice / position.entryPrice - 1 : position.entryPrice / exitPrice - 1,
          tp1Hit: position.breakEvenDone ? "Yes" : "No",
          ema20: position.ema20,
          ema50: position.ema50,
          atr14: position.atr14,
          sslAtSignal: position.sslAtSignal,
          netVolume: position.netVolume,
          distanceToEma50Atr: position.distanceToEma50Atr,
          weeklyRegime: position.weeklyRegime,
          notes: position.notes.join("; "),
        });
        position = null;
      }
      if (position) continue;
    }

    if ([prev.ema20, prev.ema50, prev.atr14, prev.ssl, c.ema20, c.ema50, c.atr14, c.ssl].some(v => v == null)) continue;
    const sslBullCross = prev.ssl === -1 && c.ssl === 1;
    const sslBearCross = prev.ssl === 1 && c.ssl === -1;
    const priceCrossUpEma20 = crossedUpRecently(daily, i, "ema20", 3);
    const priceCrossDownEma20 = crossedDownRecently(daily, i, "ema20", 3);
    const distanceToEma50Atr = Math.abs(c.close - c.ema50) / c.atr14;
    const weeklyRegime = "OFF";
    const distanceOk = distanceToEma50Atr <= 2;
    const longOk = sslBullCross && priceCrossUpEma20 && c.netVolume > 0 && distanceOk;
    const shortOk = sslBearCross && priceCrossDownEma20 && c.netVolume < 0 && distanceOk;
    if (!longOk && !shortOk) continue;

    const side = longOk ? "LONG" : "SHORT";
    const entryPrice = next.open;
    const riskPerUnit = c.atr14 * 1.5;
    const initialStop = side === "LONG" ? entryPrice - riskPerUnit : entryPrice + riskPerUnit;
    position = {
      side,
      signalTime: c.time,
      entryTime: next.time,
      entryPrice,
      initialStop,
      stop: initialStop,
      riskPerUnit,
      tp1: side === "LONG" ? entryPrice + c.atr14 * tp1Atr : entryPrice - c.atr14 * tp1Atr,
      tp2: side === "LONG" ? entryPrice + c.atr14 * tp2Atr : entryPrice - c.atr14 * tp2Atr,
      tp1Done: false,
      breakEvenDone: false,
      tp1Time: null,
      realizedR: 0,
      ema20: c.ema20,
      ema50: c.ema50,
      atr14: c.atr14,
      sslAtSignal: c.ssl,
      netVolume: c.netVolume,
      distanceToEma50Atr,
      weeklyRegime,
      notes: [
        `Signal close ${iso(c.time)}; entry next daily open`,
        `Weekly regime ${weeklyRegime}`,
        `TP1 ${tp1Atr.toFixed(1)} x ATR(14) closes ${(tp1Weight * 100).toFixed(0)}%; TP2 ${tp2Atr.toFixed(1)} x ATR(14) closes the remainder`,
        `SSL ${side === "LONG" ? "bullish" : "bearish"} crossover`,
        `Price crossed ${side === "LONG" ? "above" : "below"} EMA20 within the last 3 candles`,
        `Distance to EMA50 ${distanceToEma50Atr.toFixed(2)} ATR`,
      ],
    };
  }

  if (position) {
    const last = daily[daily.length - 1];
    const remainingWeight = position.tp1Done ? 1 - tp1Weight : 1;
    const remainingR = position.side === "LONG"
      ? (last.close - position.entryPrice) / position.riskPerUnit
      : (position.entryPrice - last.close) / position.riskPerUnit;
    const grossR = position.realizedR + remainingWeight * remainingR;
    const costInR = costR(position.entryPrice, position.riskPerUnit);
    trades.push({
      symbol,
      tradeNo: tradeNo++,
      side: position.side,
      signalTime: iso(position.signalTime),
      entryTime: iso(position.entryTime),
      entryPrice: position.entryPrice,
      initialStop: position.initialStop,
      finalStop: position.stop,
      riskPerUnit: position.riskPerUnit,
      tp1: position.tp1,
      tp1Time: position.tp1Time ? iso(position.tp1Time) : "",
      tp2: position.tp2,
      exitTime: iso(last.time),
      exitPrice: last.close,
      exitReason: "End of test mark-to-market",
      grossRMultiple: grossR,
      costR: costInR,
      rMultiple: grossR - costInR,
      pctMove: position.side === "LONG" ? last.close / position.entryPrice - 1 : position.entryPrice / last.close - 1,
      tp1Hit: position.breakEvenDone ? "Yes" : "No",
      ema20: position.ema20,
      ema50: position.ema50,
      atr14: position.atr14,
      sslAtSignal: position.sslAtSignal,
      netVolume: position.netVolume,
      distanceToEma50Atr: position.distanceToEma50Atr,
      weeklyRegime: position.weeklyRegime,
      notes: position.notes.join("; "),
    });
  }

  return trades;
}

function summarize(trades) {
  return symbols.map(symbol => {
    const rows = trades.filter(t => t.symbol === symbol);
    const wins = rows.filter(t => t.rMultiple > 0).length;
    const totalR = rows.reduce((s, t) => s + t.rMultiple, 0);
    return {
      symbol,
      trades: rows.length,
      wins,
      losses: rows.length - wins,
      winRate: rows.length ? wins / rows.length : 0,
      totalR,
      avgR: rows.length ? totalR / rows.length : 0,
      bestR: rows.length ? Math.max(...rows.map(t => t.rMultiple)) : 0,
      worstR: rows.length ? Math.min(...rows.map(t => t.rMultiple)) : 0,
    };
  });
}

function colName(n) {
  let s = "";
  while (n > 0) {
    const m = (n - 1) % 26;
    s = String.fromCharCode(65 + m) + s;
    n = Math.floor((n - m) / 26);
  }
  return s;
}

function writeMatrix(sheet, startCell, rows) {
  if (!rows.length) return;
  const match = startCell.match(/^([A-Z]+)(\d+)$/);
  const startColNo = match[1].split("").reduce((n, ch) => n * 26 + ch.charCodeAt(0) - 64, 0);
  const startRow = Number(match[2]);
  const endCol = colName(startColNo + rows[0].length - 1);
  const endRow = startRow + rows.length - 1;
  sheet.getRange(`${startCell}:${endCol}${endRow}`).values = rows;
}

function styleHeader(sheet, range) {
  sheet.getRange(range).format = {
    fill: "#17324D",
    font: { color: "#FFFFFF", bold: true },
    horizontalAlignment: "center",
    verticalAlignment: "center",
    wrapText: true,
  };
}

function baseSheet(sheet, title, subtitle) {
  sheet.getRange("A1").values = [[title]];
  sheet.getRange("A1").format = { font: { bold: true, size: 18, color: "#17324D" } };
  sheet.getRange("A2").values = [[subtitle]];
  sheet.getRange("A2").format = { font: { italic: true, color: "#4B5563" } };
}

function numberFormat(sheet, range, format) {
  sheet.getRange(range).format.numberFormat = format;
}

function finishSheet(sheet, usedRange) {
  sheet.getRange(usedRange).format.autofitColumns();
  sheet.getRange(usedRange).format.autofitRows();
}

function drawdown(trades) {
  let cumulative = 0;
  let peak = 0;
  let maxDrawdownR = 0;
  for (const t of trades) {
    cumulative += t.rMultiple;
    peak = Math.max(peak, cumulative);
    maxDrawdownR = Math.min(maxDrawdownR, cumulative - peak);
  }
  return maxDrawdownR;
}

function overallStats(trades, tp1Atr) {
  const totalR = trades.reduce((s, t) => s + t.rMultiple, 0);
  const wins = trades.filter(t => t.rMultiple > 0).length;
  const tp1Hits = trades.filter(t => t.tp1Hit === "Yes").length;
  return {
    tp1Atr,
    trades: trades.length,
    wins,
    losses: trades.length - wins,
    winRate: trades.length ? wins / trades.length : 0,
    tp1HitRate: trades.length ? tp1Hits / trades.length : 0,
    totalR,
    avgR: trades.length ? totalR / trades.length : 0,
    maxDrawdownR: drawdown(trades),
    bestR: trades.length ? Math.max(...trades.map(t => t.rMultiple)) : 0,
    worstR: trades.length ? Math.min(...trades.map(t => t.rMultiple)) : 0,
    summary: summarize(trades),
  };
}

function buildAccountRows(trades) {
  const rows = [];
  let equity = startingEquity;
  let peak = startingEquity;
  let maxDrawdownPct = 0;
  for (let i = 0; i < trades.length; i++) {
    const t = trades[i];
    const equityBefore = equity;
    const riskUsd = equityBefore * riskPct;
    const pnlUsd = riskUsd * t.rMultiple;
    equity += pnlUsd;
    peak = Math.max(peak, equity);
    maxDrawdownPct = Math.min(maxDrawdownPct, equity / peak - 1);
    rows.push({
      trade: i + 1,
      exitTime: t.exitTime,
      symbol: t.symbol.replace("USDT", ""),
      side: t.side,
      rMultiple: t.rMultiple,
      equityBefore,
      riskUsd,
      pnlUsd,
      equityAfter: equity,
      drawdownPct: equity / peak - 1,
    });
  }
  return { rows, finalEquity: equity, maxDrawdownPct };
}

async function buildWorkbook(data) {
  const workbook = Workbook.create();
  const totalTrades = data.trades.length;
  const totalR = data.trades.reduce((s, t) => s + t.rMultiple, 0);
  const wins = data.trades.filter(t => t.rMultiple > 0).length;

  const summary = workbook.worksheets.add("Summary");
  baseSheet(summary, "NXT v3.0 TP1 1.5 ATR / TP2 2.5 ATR - BTC SOL SUI 6Y", `${data.period.start} to ${data.period.end} | 20K account view | Source: ${data.source}`);
  writeMatrix(summary, "A4", [
    ["Metric", "Value"],
    ["Total trades", totalTrades],
    ["Win rate", totalTrades ? wins / totalTrades : 0],
    ["Total R", totalR],
    ["Average R / trade", totalTrades ? totalR / totalTrades : 0],
    ["Max drawdown (R)", drawdown(data.trades)],
    ["Best trade (R)", totalTrades ? Math.max(...data.trades.map(t => t.rMultiple)) : 0],
    ["Worst trade (R)", totalTrades ? Math.min(...data.trades.map(t => t.rMultiple)) : 0],
  ]);
  styleHeader(summary, "A4:B4");
  numberFormat(summary, "B6:B6", "0.0%");
  numberFormat(summary, "B7:B11", "0.00");
  writeMatrix(summary, "D4", [["Symbol", "Trades", "Wins", "Losses", "Win Rate", "Total R", "Avg R", "Best R", "Worst R"], ...data.summary.map(r => [
    r.symbol.replace("USDT", ""), r.trades, r.wins, r.losses, r.winRate, r.totalR, r.avgR, r.bestR, r.worstR,
  ])]);
  styleHeader(summary, "D4:L4");
  numberFormat(summary, "H5:H20", "0.0%");
  numberFormat(summary, "I5:L20", "0.00");
  summary.getRange("A4:L12").format.borders = { preset: "inside", style: "thin", color: "#D7DEE8" };
  summary.getRange("A4:L12").format.borders = { preset: "outside", style: "thin", color: "#9CA3AF" };
  summary.freezePanes.freezeRows(4);
  summary.charts.add("bar", {
    title: "Total R by Symbol",
    categories: data.summary.map(r => r.symbol.replace("USDT", "")),
    series: [{ name: "Total R", values: data.summary.map(r => r.totalR), fill: { type: "solid", color: "#2563EB" } }],
    from: { row: 14, col: 0 },
    extent: { widthPx: 560, heightPx: 300 },
    hasLegend: false,
  });
  finishSheet(summary, "A1:L12");

  const account = buildAccountRows(data.trades);
  writeMatrix(summary, "N4", [
    ["Account Metric", "Value"],
    ["Starting equity", startingEquity],
    ["Risk per trade", riskPct],
    ["Final equity", account.finalEquity],
    ["Net P/L", account.finalEquity - startingEquity],
    ["Compound return", account.finalEquity / startingEquity - 1],
    ["Max compound DD", account.maxDrawdownPct],
  ]);
  styleHeader(summary, "N4:O4");
  numberFormat(summary, "O5:O5", "$#,##0");
  numberFormat(summary, "O6:O6", "0.0%");
  numberFormat(summary, "O7:O8", "$#,##0");
  numberFormat(summary, "O9:O10", "0.0%");

  const tradeHeaders = [
    "Symbol", "No", "Side", "Signal Time", "Entry Time", "Entry Price", "Initial Stop", "Final Stop", "Risk / Unit",
    "TP1 1.5 ATR", "TP1 Time", "TP2 2.5 ATR", "Exit Time", "Exit Price", "Exit Reason", "Gross R", "Cost R", "Net R", "% Move", "TP1 Hit",
    "Weekly Regime", "EMA20", "EMA50", "ATR14", "SSL Signal", "Net Volume", "Distance EMA50 ATR", "Notes",
  ];
  const tradeToRow = t => [
    t.symbol.replace("USDT", ""), t.tradeNo, t.side, new Date(t.signalTime), new Date(t.entryTime), t.entryPrice,
    t.initialStop, t.finalStop, t.riskPerUnit, t.tp1, t.tp1Time ? new Date(t.tp1Time) : "", t.tp2,
    new Date(t.exitTime), t.exitPrice, t.exitReason, t.grossRMultiple, t.costR, t.rMultiple, t.pctMove, t.tp1Hit, t.weeklyRegime, t.ema20, t.ema50,
    t.atr14, t.sslAtSignal, t.netVolume, t.distanceToEma50Atr, t.notes,
  ];
  const trades = workbook.worksheets.add("Trades");
  baseSheet(trades, "Detailed Trades", "One completed trade per row; TP1 closes 50%, TP2 closes remaining 50%.");
  writeMatrix(trades, "A4", [tradeHeaders, ...data.trades.map(tradeToRow)]);
  styleHeader(trades, "A4:AB4");
  trades.freezePanes.freezeRows(4);
  const lastTradeRow = data.trades.length + 4;
  if (data.trades.length) {
    numberFormat(trades, `D5:E${lastTradeRow}`, "yyyy-mm-dd hh:mm");
    numberFormat(trades, `K5:K${lastTradeRow}`, "yyyy-mm-dd hh:mm");
    numberFormat(trades, `M5:M${lastTradeRow}`, "yyyy-mm-dd hh:mm");
    numberFormat(trades, `F5:J${lastTradeRow}`, "0.000000");
    numberFormat(trades, `L5:N${lastTradeRow}`, "0.000000");
    numberFormat(trades, `P5:R${lastTradeRow}`, "0.00");
    numberFormat(trades, `S5:S${lastTradeRow}`, "0.00%");
    numberFormat(trades, `U5:W${lastTradeRow}`, "0.000000");
    numberFormat(trades, `Y5:AA${lastTradeRow}`, "0.00");
    trades.getRange(`A4:AB${lastTradeRow}`).format.borders = { preset: "inside", style: "thin", color: "#E5E7EB" };
  }
  trades.getRange(`A4:AB${Math.max(lastTradeRow, 5)}`).format.wrapText = true;
  finishSheet(trades, `A1:AB${Math.max(lastTradeRow, 5)}`);

  const curve = workbook.worksheets.add("Equity Curve");
  baseSheet(curve, "Equity Curve in R", "Cumulative R by closed trade.");
  const curveRows = [["Trade", "Exit Time", "Symbol", "Side", "R", "Cumulative R"]];
  let runningR = 0;
  data.trades.forEach((t, i) => {
    runningR += t.rMultiple;
    curveRows.push([i + 1, new Date(t.exitTime), t.symbol.replace("USDT", ""), t.side, t.rMultiple, runningR]);
  });
  writeMatrix(curve, "A4", curveRows);
  styleHeader(curve, "A4:F4");
  if (data.trades.length) {
    numberFormat(curve, `B5:B${curveRows.length + 3}`, "yyyy-mm-dd hh:mm");
    numberFormat(curve, `E5:F${curveRows.length + 3}`, "0.00");
  }
  curve.charts.add("line", {
    title: "Cumulative R",
    categories: data.trades.map((_, i) => String(i + 1)),
    series: [{ name: "Cumulative R", values: curveRows.slice(1).map(r => r[5]), line: { fill: "#17324D", style: "solid", width: 2 } }],
    from: { row: 4, col: 7 },
    extent: { widthPx: 720, heightPx: 360 },
    hasLegend: false,
  });
  finishSheet(curve, `A1:F${Math.max(curveRows.length + 3, 5)}`);

  const accountSheet = workbook.worksheets.add("20K Account");
  baseSheet(accountSheet, "20K Account Sizing", `Compounded sequence at ${(riskPct * 100).toFixed(1)}% risk per trade; leverage is not modeled.`);
  writeMatrix(accountSheet, "A4", [[
    "Trade", "Exit Time", "Symbol", "Side", "Net R", "Equity Before", "Risk USD", "P/L USD", "Equity After", "Drawdown",
  ], ...account.rows.map(r => [
    r.trade, new Date(r.exitTime), r.symbol, r.side, r.rMultiple, r.equityBefore, r.riskUsd, r.pnlUsd, r.equityAfter, r.drawdownPct,
  ])]);
  styleHeader(accountSheet, "A4:J4");
  const accountEndRow = account.rows.length + 4;
  if (account.rows.length) {
    numberFormat(accountSheet, `B5:B${accountEndRow}`, "yyyy-mm-dd hh:mm");
    numberFormat(accountSheet, `E5:E${accountEndRow}`, "0.00");
    numberFormat(accountSheet, `F5:I${accountEndRow}`, "$#,##0");
    numberFormat(accountSheet, `J5:J${accountEndRow}`, "0.0%");
    accountSheet.getRange(`A4:J${accountEndRow}`).format.borders = { preset: "inside", style: "thin", color: "#E5E7EB" };
  }
  finishSheet(accountSheet, `A1:J${Math.max(accountEndRow, 5)}`);

  const assumptions = workbook.worksheets.add("Assumptions");
  baseSheet(assumptions, "Backtest Assumptions", "Correct NXT v3.0 with split TP1 1.5 ATR / TP2 2.5 ATR.");
  writeMatrix(assumptions, "A4", [["#", "Assumption"], ...data.assumptions.map((a, i) => [i + 1, a])]);
  styleHeader(assumptions, "A4:B4");
  assumptions.getRange(`A4:B${data.assumptions.length + 4}`).format.wrapText = true;
  finishSheet(assumptions, `A1:B${data.assumptions.length + 4}`);

  const quality = workbook.worksheets.add("Data Quality");
  baseSheet(quality, "Data Quality", "Loaded daily crypto candles; Binance used when available, Yahoo fallback otherwise.");
  writeMatrix(quality, "A4", [["Symbol", "Daily Candles", "Weekly Candles", "First Daily", "Last Daily", "Source"], ...Object.entries(data.datasets).map(([symbol, q]) => [
    symbol.replace("USDT", ""), q.dailyCount, q.weeklyCount, new Date(q.firstDaily), new Date(q.lastDaily), q.source,
  ])]);
  styleHeader(quality, "A4:F4");
  numberFormat(quality, `D5:E${Object.keys(data.datasets).length + 4}`, "yyyy-mm-dd");
  quality.getRange(`A4:F${Object.keys(data.datasets).length + 4}`).format.wrapText = true;
  finishSheet(quality, `A1:F${Object.keys(data.datasets).length + 4}`);

  for (const symbol of symbols) {
    const sheet = workbook.worksheets.add(symbol.replace("USDT", ""));
    baseSheet(sheet, `${symbol.replace("USDT", "")} Trades`, "Filtered trade detail for this symbol.");
    const rows = data.bySymbol[symbol].map(tradeToRow);
    writeMatrix(sheet, "A4", [tradeHeaders, ...rows]);
    styleHeader(sheet, "A4:AB4");
    sheet.freezePanes.freezeRows(4);
    const endRow = rows.length + 4;
    if (rows.length) sheet.getRange(`A4:AB${endRow}`).format.borders = { preset: "inside", style: "thin", color: "#E5E7EB" };
    sheet.getRange(`A4:AB${Math.max(endRow, 5)}`).format.wrapText = true;
    finishSheet(sheet, `A1:AB${Math.max(endRow, 5)}`);
  }

  const errorScan = await workbook.inspect({
    kind: "match",
    searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
    options: { useRegex: true, maxResults: 300 },
    summary: "formula error scan",
  });
  console.log(errorScan.ndjson);
  const summaryPreview = await workbook.inspect({
    kind: "table",
    range: "Summary!A1:L12",
    include: "values,formulas",
    tableMaxRows: 20,
    tableMaxCols: 12,
  });
  console.log(summaryPreview.ndjson);
  await fs.mkdir(outDir, { recursive: true });
  const output = await SpreadsheetFile.exportXlsx(workbook);
  await output.save(xlsxPath);
}

await fs.mkdir(outDir, { recursive: true });
const enriched = {};
const datasets = {};
const weeklyBySymbol = {};
const sourceBySymbol = {};
for (const symbol of symbols) {
  let daily;
  let source = "Binance spot daily klines API";
  try {
    daily = await fetchBinanceKlines(symbol, "1d", warmupStart, end);
    if (!daily.length) throw new Error(`${symbol}: no Binance rows`);
  } catch (err) {
    source = `Yahoo Finance daily crypto chart API fallback (${err.message})`;
    daily = await fetchYahooDaily(symbol, warmupStart, end);
  }
  enriched[symbol] = enrich(daily);
  weeklyBySymbol[symbol] = toWeekly(enriched[symbol]);
  sourceBySymbol[symbol] = source;
  datasets[symbol] = {
    dailyCount: daily.length,
    weeklyCount: weeklyBySymbol[symbol].length,
    firstDaily: daily.length ? iso(daily[0].time) : "",
    lastDaily: daily.length ? iso(daily[daily.length - 1].time) : "",
    source,
  };
}

const signalBySymbol = Object.fromEntries(symbols.map(symbol => [symbol, collectSignals(symbol, enriched[symbol])]));
const models = [
  { key: "corrected_be25_full_tp25", label: "V3 corrected gần nhất: BE trigger 2.5 ATR, full exit 2.5 ATR", tp1Atr: 2.5, beAtr: 2.5, tp2Atr: 2.5, tp1Weight: 0 },
  { key: "split_tp1_15_tp2_25", label: "V3 sửa đổi: TP1 1.5 ATR 50%, TP2 2.5 ATR 50%", tp1Atr: 1.5, beAtr: 1.5, tp2Atr: 2.5, tp1Weight: 0.5 },
];
const comparison = {};
for (const model of models) {
  const runs = symbols.map(symbol => ({ symbol, ...backtestFixedSignals(symbol, enriched[symbol], signalBySymbol[symbol], model) }));
  const modelTrades = runs.flatMap(r => r.trades).sort((a, b) => new Date(a.exitTime) - new Date(b.exitTime));
  comparison[model.key] = {
    label: model.label,
    model,
    rawSignals: runs.reduce((sum, r) => sum + signalBySymbol[r.symbol].length, 0),
    acceptedSignals: runs.reduce((sum, r) => sum + r.acceptedSignals, 0),
    skippedSignals: runs.reduce((sum, r) => sum + r.skippedSignals.length, 0),
    skippedBySymbol: Object.fromEntries(runs.map(r => [r.symbol, r.skippedSignals.length])),
    rawSignalsBySymbol: Object.fromEntries(runs.map(r => [r.symbol, signalBySymbol[r.symbol].length])),
    acceptedBySymbol: Object.fromEntries(runs.map(r => [r.symbol, r.acceptedSignals])),
    stats: overallStats(modelTrades, model.tp1Atr),
    summary: summarize(modelTrades),
    trades: modelTrades,
    skippedSignalsDetail: runs.flatMap(r => r.skippedSignals),
  };
}
const a = comparison.corrected_be25_full_tp25.stats;
const b = comparison.split_tp1_15_tp2_25.stats;
const result = {
  generatedAt: new Date().toISOString(),
  period: { start: iso(start), end: iso(end - 1) },
  symbols,
  note: "Both variants use the same raw entry signal list. Trade count differs only because each symbol can hold one open position; signals that appear while a position is open are skipped.",
  datasets,
  comparison,
  diffSplitMinusCorrected: {
    rawSignals: comparison.split_tp1_15_tp2_25.rawSignals - comparison.corrected_be25_full_tp25.rawSignals,
    acceptedSignals: comparison.split_tp1_15_tp2_25.acceptedSignals - comparison.corrected_be25_full_tp25.acceptedSignals,
    skippedSignals: comparison.split_tp1_15_tp2_25.skippedSignals - comparison.corrected_be25_full_tp25.skippedSignals,
    trades: b.trades - a.trades,
    totalR: b.totalR - a.totalR,
    winRate: b.winRate - a.winRate,
    avgR: b.avgR - a.avgR,
    maxDrawdownR: b.maxDrawdownR - a.maxDrawdownR,
  },
};
await fs.mkdir(compareOutDir, { recursive: true });
await fs.writeFile(compareJsonPath, JSON.stringify(result, null, 2));
console.log(JSON.stringify({
  compareJsonPath,
  corrected: {
    rawSignals: comparison.corrected_be25_full_tp25.rawSignals,
    acceptedSignals: comparison.corrected_be25_full_tp25.acceptedSignals,
    skippedSignals: comparison.corrected_be25_full_tp25.skippedSignals,
    stats: a,
    summary: comparison.corrected_be25_full_tp25.summary,
  },
  split: {
    rawSignals: comparison.split_tp1_15_tp2_25.rawSignals,
    acceptedSignals: comparison.split_tp1_15_tp2_25.acceptedSignals,
    skippedSignals: comparison.split_tp1_15_tp2_25.skippedSignals,
    stats: b,
    summary: comparison.split_tp1_15_tp2_25.summary,
  },
  diffSplitMinusCorrected: result.diffSplitMinusCorrected,
}, null, 2));
process.exit(0);

const trades = symbols.flatMap(symbol => backtestSymbol(symbol, enriched[symbol], weeklyBySymbol[symbol]));
trades.sort((a, b) => new Date(a.exitTime) - new Date(b.exitTime));
const bySymbol = Object.fromEntries(symbols.map(symbol => [symbol, trades.filter(t => t.symbol === symbol)]));
const stats = overallStats(trades, tp1Atr);
const data = {
  generatedAt: new Date().toISOString(),
  source: Object.values(sourceBySymbol).every(s => s === "Binance spot daily klines API")
    ? "Binance spot daily klines API"
    : "Mixed sources; see Data Quality",
  period: { start: iso(start), end: iso(end - 1) },
  symbols,
  tp1Atr,
  tp2Atr,
  tp1Weight,
  startingEquity,
  riskPct,
  stats,
  summary: summarize(trades),
  trades,
  bySymbol,
  datasets,
  assumptions: [
    "Source system: NXT_Trading_System.docx.",
    "Version 2.3 keeps Binance Net Volume and the fee/slippage cost model, removes the Weekly regime filter, allows EMA20 cross within the last 3 candles, and raises the EMA50 distance limit to 2 ATR.",
    "Timeframe: Daily entries only. Signals are evaluated on closed daily candles and entered at the next daily open.",
    "Weekly regime is not used as an entry filter in this version.",
    "Long entry requires SSL 10/10 bullish crossover, price crossing above EMA20 within the last 3 candles, Net Volume > 0, and distance from close to EMA50 <= 2 ATR(14).",
    "Short entry requires SSL 10/10 bearish crossover, price crossing below EMA20 within the last 3 candles, Net Volume < 0, and distance from close to EMA50 <= 2 ATR(14).",
    "SSL Channel is approximated with SMA(high,10) and SMA(low,10); state flips bullish when close is above high SMA and bearish when close is below low SMA.",
    "Net Volume uses Binance taker buy base volume when Binance data is available: taker buy volume x 2 - total volume. On Yahoo fallback, it is approximated from daily candle direction.",
    "Stop loss is 1.5 x ATR(14) from entry.",
    `TP1 is ${tp1Atr} x ATR(14), closing ${(tp1Weight * 100).toFixed(0)}% and moving stop to breakeven.`,
    `TP2 is ${tp2Atr} x ATR(14), closing the remaining ${((1 - tp1Weight) * 100).toFixed(0)}%.`,
    "Position can also exit on opposite SSL flip, stop, or end-of-test mark-to-market if TP2 is not reached.",
    "Conservative intraday ordering: stop is checked before TP1 and TP2 when multiple levels could be touched inside one daily candle.",
    `Cost model: ${feeRate * 100}% fee and ${slippageRate * 100}% slippage per side, deducted from each trade in R terms. Funding, borrow cost, and taxes are still excluded.`,
  ],
};

await fs.writeFile(jsonPath, JSON.stringify(data, null, 2));
await buildWorkbook(data);
console.log(JSON.stringify({
  jsonPath,
  xlsxPath,
  stats: data.stats,
  summary: data.summary,
  datasets: data.datasets,
}, null, 2));
