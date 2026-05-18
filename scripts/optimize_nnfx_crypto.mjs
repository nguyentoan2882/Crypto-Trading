import fs from "node:fs/promises";
import path from "node:path";

const symbols = ["BTCUSDT", "SOLUSDT", "SUIUSDT"];
const end = Date.UTC(2026, 4, 16, 0, 0, 0);
const start = Date.UTC(2025, 4, 16, 0, 0, 0);
const warmupStart = Date.UTC(2024, 10, 1, 0, 0, 0);
const outDir = path.resolve("outputs", "nnfx_crypto_btc_sol_sui_1y");
const yahooSymbols = { BTCUSDT: "BTC-USD", SOLUSDT: "SOL-USD", SUIUSDT: "SUI20947-USD" };

function sma(values, period) {
  const out = Array(values.length).fill(null);
  let sum = 0;
  for (let i = 0; i < values.length; i++) {
    const v = values[i];
    if (v == null || Number.isNaN(v)) continue;
    sum += v;
    if (i >= period) sum -= values[i - period] ?? 0;
    if (i >= period - 1) out[i] = sum / period;
  }
  return out;
}

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

function wma(values, period) {
  const out = Array(values.length).fill(null);
  const denom = (period * (period + 1)) / 2;
  for (let i = period - 1; i < values.length; i++) {
    let weighted = 0;
    let ok = true;
    for (let j = 0; j < period; j++) {
      const v = values[i - period + 1 + j];
      if (v == null) { ok = false; break; }
      weighted += v * (j + 1);
    }
    if (ok) out[i] = weighted / denom;
  }
  return out;
}

function hma(values, period) {
  const half = Math.floor(period / 2);
  const sqrt = Math.max(1, Math.round(Math.sqrt(period)));
  const h = wma(values, half);
  const f = wma(values, period);
  return wma(values.map((_, i) => h[i] == null || f[i] == null ? null : 2 * h[i] - f[i]), sqrt);
}

function atr(candles, period) {
  return sma(candles.map((c, i) => {
    if (i === 0) return c.high - c.low;
    const pc = candles[i - 1].close;
    return Math.max(c.high - c.low, Math.abs(c.high - pc), Math.abs(c.low - pc));
  }), period);
}

function kama(values, period = 50, fast = 2, slow = 30) {
  const out = Array(values.length).fill(null);
  const fastSC = 2 / (fast + 1);
  const slowSC = 2 / (slow + 1);
  for (let i = period; i < values.length; i++) {
    if (i === period) {
      out[i] = values.slice(i - period + 1, i + 1).reduce((s, v) => s + v, 0) / period;
      continue;
    }
    const change = Math.abs(values[i] - values[i - period]);
    let volatility = 0;
    for (let j = i - period + 1; j <= i; j++) volatility += Math.abs(values[j] - values[j - 1]);
    const er = volatility === 0 ? 0 : change / volatility;
    const sc = Math.pow(er * (fastSC - slowSC) + slowSC, 2);
    out[i] = out[i - 1] + sc * (values[i] - out[i - 1]);
  }
  return out;
}

function sslState(candles, length = 10) {
  const hi = sma(candles.map(c => c.high), length);
  const lo = sma(candles.map(c => c.low), length);
  const out = Array(candles.length).fill(null);
  let state = 0;
  for (let i = 0; i < candles.length; i++) {
    if (hi[i] == null || lo[i] == null) continue;
    if (candles[i].close > hi[i]) state = 1;
    else if (candles[i].close < lo[i]) state = -1;
    out[i] = state;
  }
  return out;
}

function tdfiProxy(candles) {
  const closes = candles.map(c => c.close);
  const e13 = ema(closes, 13);
  const raw = closes.map((_, i) => {
    if (i < 14 || e13[i] == null || e13[i - 1] == null) return null;
    const momentum = (e13[i] - e13[i - 1]) / candles[i].close;
    const directional = (candles[i].close - candles[i - 13].close) / candles[i - 13].close;
    return momentum * Math.abs(directional) * 1000;
  });
  return raw.map((v, i) => {
    if (v == null || i < 50) return null;
    let maxAbs = 0;
    for (let j = i - 49; j <= i; j++) maxAbs = Math.max(maxAbs, Math.abs(raw[j] ?? 0));
    return maxAbs === 0 ? 0 : v / maxAbs;
  });
}

function rollingReturn(candles, period) {
  return candles.map((c, i) => i < period ? null : c.close / candles[i - period].close - 1);
}

async function fetchYahooDaily(symbol) {
  const url = new URL(`https://query1.finance.yahoo.com/v8/finance/chart/${yahooSymbols[symbol]}`);
  url.searchParams.set("period1", String(Math.floor(warmupStart / 1000)));
  url.searchParams.set("period2", String(Math.floor(end / 1000)));
  url.searchParams.set("interval", "1d");
  url.searchParams.set("events", "history");
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${symbol}: ${res.status}`);
  const result = (await res.json()).chart?.result?.[0];
  if (!result?.timestamp?.length) throw new Error(`${symbol}: no rows`);
  const q = result.indicators.quote[0];
  return result.timestamp.map((ts, i) => ({
    time: ts * 1000,
    open: q.open[i],
    high: q.high[i],
    low: q.low[i],
    close: q.close[i],
    volume: q.volume[i] ?? 0,
    closeTime: ts * 1000 + 24 * 60 * 60 * 1000 - 1,
  })).filter(c => [c.open, c.high, c.low, c.close].every(v => v != null && !Number.isNaN(v)));
}

function enrich(candles) {
  const closes = candles.map(c => c.close);
  const ranges = candles.map(c => c.high - c.low);
  const rangeVol = candles.map((c, i) => ranges[i] * c.volume);
  const atr14 = atr(candles, 14);
  const hma21 = hma(closes, 21);
  const hma55 = hma(closes, 55);
  return candles.map((c, i) => ({
    ...c,
    atr14: atr14[i],
    atrSma20: sma(atr14, 20)[i],
    kama50: kama(closes, 50)[i],
    ssl: sslState(candles, 10)[i],
    tdfi: tdfiProxy(candles)[i],
    hma21Slope: i && hma21[i] != null && hma21[i - 1] != null ? hma21[i] - hma21[i - 1] : null,
    hma55Slope: i && hma55[i] != null && hma55[i - 1] != null ? hma55[i] - hma55[i - 1] : null,
    vol20: sma(candles.map(x => x.volume), 20)[i],
    rangeVol: rangeVol[i],
    rangeVol20: sma(rangeVol, 20)[i],
    ret14: rollingReturn(candles, 14)[i],
  }));
}

function findByCloseTime(candles, closeTime) {
  let lo = 0, hi = candles.length - 1, ans = null;
  while (lo <= hi) {
    const mid = Math.floor((lo + hi) / 2);
    if (candles[mid].closeTime <= closeTime) { ans = candles[mid]; lo = mid + 1; }
    else hi = mid - 1;
  }
  return ans;
}

function volumeOk(c, side, p) {
  if (!c.vol20 || !c.rangeVol20) return false;
  const directional = side === "LONG" ? c.close >= c.open : c.close <= c.open;
  return (directional && c.volume >= c.vol20 * p.volumeMult) || c.rangeVol >= c.rangeVol20 * p.rangeVolMult;
}

function backtestSymbol(symbol, daily, btcDaily, p) {
  const trades = [];
  let pos = null;
  for (let i = 60; i < daily.length - 1; i++) {
    const c = daily[i], next = daily[i + 1];
    if (next.time < start || next.time > end) continue;
    if (pos) {
      let exit = null, rExit = 0;
      const slope = p.hull === 21 ? c.hma21Slope : c.hma55Slope;
      if (pos.side === "LONG") {
        if (c.low <= pos.stop) { exit = pos.stop; rExit = (exit - pos.entry) / pos.risk; }
        else if (!pos.tp1Done && c.high >= pos.tp1) {
          pos.tp1Done = true;
          pos.realized += p.tp1Weight * ((pos.tp1 - pos.entry) / pos.risk);
          if (p.moveStopToBE) pos.stop = pos.entry;
        } else if (pos.tp1Done && (slope < 0 || c.ssl === -1)) { exit = c.close; rExit = (exit - pos.entry) / pos.risk; }
      } else {
        if (c.high >= pos.stop) { exit = pos.stop; rExit = (pos.entry - exit) / pos.risk; }
        else if (!pos.tp1Done && c.low <= pos.tp1) {
          pos.tp1Done = true;
          pos.realized += p.tp1Weight * ((pos.entry - pos.tp1) / pos.risk);
          if (p.moveStopToBE) pos.stop = pos.entry;
        } else if (pos.tp1Done && (slope > 0 || c.ssl === 1)) { exit = c.close; rExit = (pos.entry - exit) / pos.risk; }
      }
      if (exit != null) {
        trades.push({ symbol, side: pos.side, entryTime: pos.entryTime, exitTime: c.time, r: pos.realized + (1 - (pos.tp1Done ? p.tp1Weight : 0)) * rExit });
        pos = null;
      }
      continue;
    }

    if ([c.atr14, c.atrSma20, c.kama50, c.ssl, c.tdfi, c.vol20, c.rangeVol20].some(v => v == null)) continue;
    const bridge = Math.abs(c.close - c.kama50) / c.atr14;
    const btc = symbol === "BTCUSDT" ? c : findByCloseTime(btcDaily, c.closeTime);
    const relativeStrength = symbol === "BTCUSDT" || (btc?.ret14 != null && c.ret14 != null && c.ret14 > btc.ret14 + p.rsBuffer);
    const atrExpansion = c.atr14 > c.atrSma20 * p.atrExpansionMult;
    const longOk = c.close > c.kama50 && bridge <= p.bridgeMax && c.ssl === 1 && c.tdfi > p.tdfi && atrExpansion && volumeOk(c, "LONG", p) && relativeStrength;
    const shortOk = c.close < c.kama50 && bridge <= p.bridgeMax && c.ssl === -1 && c.tdfi < -p.tdfi && atrExpansion && volumeOk(c, "SHORT", p) && relativeStrength;
    if (!longOk && !shortOk) continue;
    const side = longOk ? "LONG" : "SHORT";
    const entry = next.open;
    const risk = c.atr14 * p.stopAtr;
    pos = {
      side,
      entryTime: next.time,
      entry,
      risk,
      stop: side === "LONG" ? entry - risk : entry + risk,
      tp1: side === "LONG" ? entry + c.atr14 * p.tp1Atr : entry - c.atr14 * p.tp1Atr,
      tp1Done: false,
      realized: 0,
    };
  }
  if (pos) {
    const last = daily[daily.length - 1];
    const remaining = 1 - (pos.tp1Done ? p.tp1Weight : 0);
    const rExit = pos.side === "LONG" ? (last.close - pos.entry) / pos.risk : (pos.entry - last.close) / pos.risk;
    trades.push({ symbol, side: pos.side, entryTime: pos.entryTime, exitTime: last.time, r: pos.realized + remaining * rExit });
  }
  return trades;
}

function stats(trades, p) {
  const ordered = [...trades].sort((a, b) => a.exitTime - b.exitTime);
  const totalR = ordered.reduce((s, t) => s + t.r, 0);
  const wins = ordered.filter(t => t.r > 0).length;
  let cum = 0, peak = 0, dd = 0;
  for (const t of ordered) {
    cum += t.r;
    peak = Math.max(peak, cum);
    dd = Math.min(dd, cum - peak);
  }
  const losses = ordered.filter(t => t.r < 0);
  const grossWin = ordered.filter(t => t.r > 0).reduce((s, t) => s + t.r, 0);
  const grossLoss = Math.abs(losses.reduce((s, t) => s + t.r, 0));
  const bySymbol = Object.fromEntries(symbols.map(s => [s, ordered.filter(t => t.symbol === s).reduce((sum, t) => sum + t.r, 0)]));
  return {
    trades: ordered.length,
    totalR,
    winRate: ordered.length ? wins / ordered.length : 0,
    avgR: ordered.length ? totalR / ordered.length : 0,
    maxDrawdownR: dd,
    profitFactor: grossLoss ? grossWin / grossLoss : grossWin ? 99 : 0,
    bySymbol,
    params: p,
  };
}

const datasets = {};
for (const symbol of symbols) datasets[symbol] = enrich(await fetchYahooDaily(symbol));

const variants = [];
for (const tdfi of [0.05, 0.1, 0.15, 0.2]) {
  for (const bridgeMax of [0.5, 0.75, 1.0]) {
    for (const atrExpansionMult of [1.0, 1.1, 1.2]) {
      for (const volumeMult of [1.0, 1.15]) {
        for (const rangeVolMult of [1.15, 1.35]) {
          for (const stopAtr of [1.2, 1.5, 1.8]) {
            for (const tp1Atr of [1.0, 1.5, 2.0]) {
              for (const tp1Weight of [0.25, 0.5]) {
                for (const moveStopToBE of [true, false]) {
                  for (const hull of [21, 55]) {
                    variants.push({ tdfi, bridgeMax, atrExpansionMult, volumeMult, rangeVolMult, stopAtr, tp1Atr, tp1Weight, moveStopToBE, hull, rsBuffer: 0 });
                  }
                }
              }
            }
          }
        }
      }
    }
  }
}

const results = variants.map(p => {
  const trades = symbols.flatMap(symbol => backtestSymbol(symbol, datasets[symbol], datasets.BTCUSDT, p));
  return stats(trades, p);
}).filter(r => r.trades >= 4);

results.sort((a, b) => {
  const scoreA = a.totalR - Math.max(0, 4 - a.trades) * 2 + Math.min(0, ...Object.values(a.bySymbol)) * 0.25;
  const scoreB = b.totalR - Math.max(0, 4 - b.trades) * 2 + Math.min(0, ...Object.values(b.bySymbol)) * 0.25;
  return scoreB - scoreA;
});

await fs.mkdir(outDir, { recursive: true });
await fs.writeFile(path.join(outDir, "nnfx_crypto_optimization_results.json"), JSON.stringify(results.slice(0, 100), null, 2));
console.table(results.slice(0, 20).map((r, i) => ({
  rank: i + 1,
  totalR: r.totalR.toFixed(2),
  trades: r.trades,
  winRate: `${(r.winRate * 100).toFixed(1)}%`,
  avgR: r.avgR.toFixed(2),
  pf: r.profitFactor.toFixed(2),
  dd: r.maxDrawdownR.toFixed(2),
  BTC: r.bySymbol.BTCUSDT.toFixed(2),
  SOL: r.bySymbol.SOLUSDT.toFixed(2),
  SUI: r.bySymbol.SUIUSDT.toFixed(2),
  tdfi: r.params.tdfi,
  bridge: r.params.bridgeMax,
  atrExp: r.params.atrExpansionMult,
  stop: r.params.stopAtr,
  tp1: r.params.tp1Atr,
  weight: r.params.tp1Weight,
  be: r.params.moveStopToBE,
  hull: r.params.hull,
})));
