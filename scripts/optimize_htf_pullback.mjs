import fs from "node:fs/promises";
import path from "node:path";

const symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "LINKUSDT", "AAVEUSDT", "SUIUSDT", "INJUSDT"];
const start = Date.UTC(2025, 10, 12);
const end = Date.UTC(2026, 4, 12, 23, 59, 59);
const warmupStart = Date.UTC(2024, 10, 1);

function ema(values, period) {
  const out = Array(values.length).fill(null);
  const k = 2 / (period + 1);
  let sum = 0;
  for (let i = 0; i < values.length; i++) {
    if (i < period) sum += values[i];
    if (i === period - 1) out[i] = sum / period;
    if (i >= period) out[i] = values[i] * k + out[i - 1] * (1 - k);
  }
  return out;
}

function sma(values, period) {
  const out = Array(values.length).fill(null);
  let sum = 0;
  for (let i = 0; i < values.length; i++) {
    sum += values[i];
    if (i >= period) sum -= values[i - period];
    if (i >= period - 1) out[i] = sum / period;
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

async function fetchKlines(symbol, interval, from, to) {
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
    rows.push(...batch.map(r => ({
      time: Number(r[0]), open: Number(r[1]), high: Number(r[2]), low: Number(r[3]),
      close: Number(r[4]), volume: Number(r[5]), closeTime: Number(r[6]),
    })));
    cursor = Number(batch[batch.length - 1][0]) + 1;
  }
  return rows;
}

function enrich(candles) {
  const closes = candles.map(c => c.close);
  const vols = candles.map(c => c.volume);
  const ema20 = ema(closes, 20);
  const ema50 = ema(closes, 50);
  const atr14 = atr(candles, 14);
  const vol20 = sma(vols, 20);
  return candles.map((c, i) => ({ ...c, ema20: ema20[i], ema50: ema50[i], atr14: atr14[i], vol20: vol20[i] }));
}

function idxBefore(candles, time) {
  let lo = 0, hi = candles.length - 1, ans = -1;
  while (lo <= hi) {
    const mid = Math.floor((lo + hi) / 2);
    if (candles[mid].closeTime < time) { ans = mid; lo = mid + 1; } else hi = mid - 1;
  }
  return ans;
}

function swingLow(candles, i, lookback) {
  let v = Infinity;
  for (let j = Math.max(0, i - lookback); j <= i; j++) v = Math.min(v, candles[j].low);
  return v;
}

function swingHigh(candles, i, lookback) {
  let v = -Infinity;
  for (let j = Math.max(0, i - lookback); j <= i; j++) v = Math.max(v, candles[j].high);
  return v;
}

function overlapsEma(h4, i, daily, bars, tol) {
  const tolerance = daily.close * tol;
  for (let j = Math.max(0, i - bars); j <= i; j++) {
    if (h4[j].low <= daily.ema20 + tolerance && h4[j].high >= daily.ema20 - tolerance) return true;
  }
  return false;
}

function bullish(h4, i, breakoutLookback) {
  const c = h4[i], p = h4[i - 1];
  return (c.close > c.open && p.close < p.open && c.close > p.open && c.open <= p.close)
    || (c.close > p.high && c.close > c.open)
    || (c.close > swingHigh(h4, i - 1, breakoutLookback));
}

function bearish(h4, i, breakoutLookback) {
  const c = h4[i], p = h4[i - 1];
  return (c.close < c.open && p.close > p.open && c.close < p.open && c.open >= p.close)
    || (c.close < p.low && c.close < c.open)
    || (c.close < swingLow(h4, i - 1, breakoutLookback));
}

function backtestSymbol(symbol, h4, daily, weekly, p) {
  const trades = [];
  let pos = null;
  let lastExitTime = 0;
  for (let i = 60; i < h4.length; i++) {
    const c = h4[i];
    if (c.time < start || c.time > end) continue;
    if (pos) {
      let exit = null;
      let rExit = 0;
      if (pos.side === "LONG") {
        const trail = pos.tp1Done && p.trailAfterTp1 ? Math.max(pos.stop, c.ema20 ?? pos.stop) : pos.stop;
        if (c.low <= trail) { exit = trail; rExit = (exit - pos.entry) / pos.risk; }
        else if (!pos.tp1Done && c.high >= pos.tp1) { pos.tp1Done = true; pos.realized = 0.5; pos.stop = pos.entry; }
        else if (pos.tp1Done && c.high >= pos.tp2) { exit = pos.tp2; rExit = 2; }
      } else {
        const trail = pos.tp1Done && p.trailAfterTp1 ? Math.min(pos.stop, c.ema20 ?? pos.stop) : pos.stop;
        if (c.high >= trail) { exit = trail; rExit = (pos.entry - exit) / pos.risk; }
        else if (!pos.tp1Done && c.low <= pos.tp1) { pos.tp1Done = true; pos.realized = 0.5; pos.stop = pos.entry; }
        else if (pos.tp1Done && c.low <= pos.tp2) { exit = pos.tp2; rExit = 2; }
      }
      if (exit !== null) {
        const remaining = pos.tp1Done ? 0.5 : 1;
        trades.push({ symbol, side: pos.side, entryTime: pos.entryTime, exitTime: c.time, r: pos.realized + remaining * rExit });
        pos = null;
        lastExitTime = c.time;
      }
      continue;
    }
    if (c.time - lastExitTime < p.cooldownBars * 4 * 60 * 60 * 1000) continue;
    const dIdx = idxBefore(daily, c.time);
    const wIdx = idxBefore(weekly, c.time);
    if (dIdx < 55 || wIdx < 24) continue;
    const d = daily[dIdx], w = weekly[wIdx], prevW = weekly[wIdx - p.weeklySlopeWeeks];
    if (!d?.ema20 || !d?.ema50 || !w?.ema20 || !prevW?.ema20 || !c.atr14 || !c.vol20) continue;
    const weeklyBull = w.close > w.ema20 && w.ema20 > prevW.ema20;
    const weeklyBear = w.close < w.ema20 && w.ema20 < prevW.ema20;
    const volumeOk = c.volume > c.vol20 * p.volumeMult;
    const dailyLong = d.ema20 > d.ema50 && d.close > d.ema20 * (1 + p.dailyDistance);
    const dailyShort = d.ema20 < d.ema50 && d.close < d.ema20 * (1 - p.dailyDistance);
    if (weeklyBull && dailyLong && volumeOk && overlapsEma(h4, i, d, p.pullbackBars, p.pullbackTol) && bullish(h4, i, p.breakoutLookback)) {
      const entry = c.close;
      const stop = Math.min(swingLow(h4, i - 1, p.swingLookback), entry - c.atr14 * p.atrMult);
      const risk = entry - stop;
      if (risk > 0) pos = { side: "LONG", entryTime: c.time, entry, stop, risk, tp1: entry + risk, tp2: entry + p.tp2R * risk, tp1Done: false, realized: 0 };
    } else if (weeklyBear && dailyShort && volumeOk && overlapsEma(h4, i, d, p.pullbackBars, p.pullbackTol) && bearish(h4, i, p.breakoutLookback)) {
      const entry = c.close;
      const stop = Math.max(swingHigh(h4, i - 1, p.swingLookback), entry + c.atr14 * p.atrMult);
      const risk = stop - entry;
      if (risk > 0) pos = { side: "SHORT", entryTime: c.time, entry, stop, risk, tp1: entry - risk, tp2: entry - p.tp2R * risk, tp1Done: false, realized: 0 };
    }
  }
  return trades;
}

function stats(trades) {
  const totalR = trades.reduce((s, t) => s + t.r, 0);
  const wins = trades.filter(t => t.r > 0).length;
  let cum = 0, peak = 0, dd = 0;
  for (const t of trades.sort((a, b) => a.exitTime - b.exitTime)) {
    cum += t.r; peak = Math.max(peak, cum); dd = Math.min(dd, cum - peak);
  }
  return { trades: trades.length, totalR, winRate: trades.length ? wins / trades.length : 0, avgR: trades.length ? totalR / trades.length : 0, maxDrawdownR: dd };
}

const datasets = {};
for (const symbol of symbols) {
  console.log(`Fetching ${symbol}`);
  const [h4, daily, weekly] = await Promise.all([
    fetchKlines(symbol, "4h", warmupStart, end).then(enrich),
    fetchKlines(symbol, "1d", warmupStart, end).then(enrich),
    fetchKlines(symbol, "1w", warmupStart, end).then(enrich),
  ]);
  datasets[symbol] = { h4, daily, weekly };
}

const variants = [];
for (const volumeMult of [1.0, 1.05, 1.1, 1.2]) {
  for (const pullbackTol of [0.008, 0.012, 0.018, 0.025]) {
    for (const pullbackBars of [6, 9, 12]) {
      for (const cooldownBars of [0, 6, 12]) {
        for (const tp2R of [2, 2.5, 3]) {
          variants.push({
            volumeMult, pullbackTol, pullbackBars, cooldownBars, tp2R,
            weeklySlopeWeeks: 3, dailyDistance: 0, breakoutLookback: 8, swingLookback: 10, atrMult: 1, trailAfterTp1: true,
          });
        }
      }
    }
  }
}

const results = [];
for (const p of variants) {
  const trades = symbols.flatMap(symbol => backtestSymbol(symbol, datasets[symbol].h4, datasets[symbol].daily, datasets[symbol].weekly, p));
  const s = stats(trades);
  results.push({ ...s, params: p });
}

results.sort((a, b) => b.totalR - a.totalR);
await fs.mkdir("outputs", { recursive: true });
await fs.writeFile(path.join("outputs", "htf_pullback_optimization_results.json"), JSON.stringify(results.slice(0, 30), null, 2));
console.table(results.slice(0, 12).map(r => ({
  totalR: r.totalR.toFixed(2),
  trades: r.trades,
  winRate: `${(r.winRate * 100).toFixed(1)}%`,
  avgR: r.avgR.toFixed(3),
  maxDD: r.maxDrawdownR.toFixed(2),
  volume: r.params.volumeMult,
  tol: `${(r.params.pullbackTol * 100).toFixed(1)}%`,
  bars: r.params.pullbackBars,
  cooldown: r.params.cooldownBars,
  tp2R: r.params.tp2R,
})));
