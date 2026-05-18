const fs = await import("node:fs/promises");
const path = await import("node:path");

const requestedSymbols = process.argv.slice(2).map(s => s.toUpperCase().replace(/USDT$/, "") + "USDT");
const symbols = requestedSymbols.length ? requestedSymbols : ["BTCUSDT", "ETHUSDT", "SOLUSDT", "LINKUSDT", "AAVEUSDT", "SUIUSDT", "INJUSDT"];
const start = Date.UTC(2025, 10, 12, 0, 0, 0);
const end = Date.UTC(2026, 4, 12, 23, 59, 59);
const warmupStart = Date.UTC(2024, 10, 1, 0, 0, 0);
const outDir = path.resolve("outputs");
const outSuffix = requestedSymbols.length ? `_${symbols.map(s => s.replace("USDT", "").toLowerCase()).join("_")}` : "";
const outFile = path.join(outDir, `htf_pullback_backtest_results${outSuffix}.json`);

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
    for (const r of batch) {
      rows.push({
        time: Number(r[0]),
        open: Number(r[1]),
        high: Number(r[2]),
        low: Number(r[3]),
        close: Number(r[4]),
        volume: Number(r[5]),
        closeTime: Number(r[6]),
      });
    }
    const next = Number(batch[batch.length - 1][0]) + 1;
    if (next <= cursor) break;
    cursor = next;
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

function lastBefore(candles, time) {
  let lo = 0, hi = candles.length - 1, ans = null;
  while (lo <= hi) {
    const mid = Math.floor((lo + hi) / 2);
    if (candles[mid].closeTime < time) {
      ans = candles[mid];
      lo = mid + 1;
    } else {
      hi = mid - 1;
    }
  }
  return ans;
}

function indexLastBefore(candles, time) {
  let lo = 0, hi = candles.length - 1, ans = -1;
  while (lo <= hi) {
    const mid = Math.floor((lo + hi) / 2);
    if (candles[mid].closeTime < time) {
      ans = mid;
      lo = mid + 1;
    } else {
      hi = mid - 1;
    }
  }
  return ans;
}

function iso(ms) {
  return new Date(ms).toISOString().replace(".000Z", "Z");
}

function swingLow(candles, i, lookback) {
  let value = Infinity;
  for (let j = Math.max(0, i - lookback); j <= i; j++) value = Math.min(value, candles[j].low);
  return value;
}

function swingHigh(candles, i, lookback) {
  let value = -Infinity;
  for (let j = Math.max(0, i - lookback); j <= i; j++) value = Math.max(value, candles[j].high);
  return value;
}

function hasRecentDailyPullback(h4, i, daily) {
  const tolerance = daily.close * 0.012;
  for (let j = Math.max(0, i - 6); j <= i; j++) {
    if (h4[j].low <= daily.ema20 + tolerance && h4[j].high >= daily.ema20 - tolerance) return true;
  }
  return false;
}

function hasRecentDailyRally(h4, i, daily) {
  const tolerance = daily.close * 0.012;
  for (let j = Math.max(0, i - 6); j <= i; j++) {
    if (h4[j].high >= daily.ema20 - tolerance && h4[j].low <= daily.ema20 + tolerance) return true;
  }
  return false;
}

function bullishSignal(h4, i) {
  const c = h4[i], p = h4[i - 1];
  const engulf = c.close > c.open && p.close < p.open && c.close > p.open && c.open <= p.close;
  const reclaim = c.close > p.high && c.close > c.open;
  const breakout = c.close > swingHigh(h4, i - 1, 8);
  return engulf || reclaim || breakout;
}

function bearishSignal(h4, i) {
  const c = h4[i], p = h4[i - 1];
  const engulf = c.close < c.open && p.close > p.open && c.close < p.open && c.open >= p.close;
  const rejection = c.close < p.low && c.close < c.open;
  const breakdown = c.close < swingLow(h4, i - 1, 8);
  return engulf || rejection || breakdown;
}

function backtestSymbol(symbol, h4, daily, weekly) {
  const trades = [];
  let position = null;
  let tradeNo = 1;

  for (let i = 60; i < h4.length; i++) {
    const c = h4[i];
    if (c.time < start || c.time > end) continue;

    if (position) {
      const side = position.side;
      let exitPrice = null;
      let exitReason = null;
      let rExit = 0;

      if (side === "LONG") {
        const trail = c.ema20 ? Math.max(position.stop, c.ema20) : position.stop;
        if (c.low <= trail) {
          exitPrice = trail;
          exitReason = position.tp1Done ? "Trailing stop / breakeven" : "Stop loss";
          rExit = (exitPrice - position.entry) / position.risk;
        } else if (!position.tp1Done && c.high >= position.tp1) {
          position.tp1Done = true;
          position.realizedR += 0.5;
          position.stop = position.entry;
          position.notes.push(`TP1 at ${iso(c.time)} @ ${position.tp1.toFixed(6)}`);
        } else if (position.tp1Done && c.high >= position.tp2) {
          exitPrice = position.tp2;
          exitReason = "TP2";
          rExit = 2;
        }
      } else {
        const trail = c.ema20 ? Math.min(position.stop, c.ema20) : position.stop;
        if (c.high >= trail) {
          exitPrice = trail;
          exitReason = position.tp1Done ? "Trailing stop / breakeven" : "Stop loss";
          rExit = (position.entry - exitPrice) / position.risk;
        } else if (!position.tp1Done && c.low <= position.tp1) {
          position.tp1Done = true;
          position.realizedR += 0.5;
          position.stop = position.entry;
          position.notes.push(`TP1 at ${iso(c.time)} @ ${position.tp1.toFixed(6)}`);
        } else if (position.tp1Done && c.low <= position.tp2) {
          exitPrice = position.tp2;
          exitReason = "TP2";
          rExit = 2;
        }
      }

      if (exitPrice !== null) {
        const remainingWeight = position.tp1Done ? 0.5 : 1;
        const totalR = position.realizedR + remainingWeight * rExit;
        trades.push({
          symbol,
          tradeNo: tradeNo++,
          side,
          entryTime: iso(position.entryTime),
          entryPrice: position.entry,
          stopInitial: position.initialStop,
          riskPerUnit: position.risk,
          tp1: position.tp1,
          tp2: position.tp2,
          exitTime: iso(c.time),
          exitPrice,
          exitReason,
          rMultiple: totalR,
          pctMove: side === "LONG" ? (exitPrice / position.entry - 1) : (position.entry / exitPrice - 1),
          setup: position.setup,
          weeklyRegime: position.weeklyRegime,
          dailyTrend: position.dailyTrend,
          notes: position.notes.join("; "),
        });
        position = null;
      }
      continue;
    }

    const dIdx = indexLastBefore(daily, c.time);
    const wIdx = indexLastBefore(weekly, c.time);
    if (dIdx < 55 || wIdx < 24) continue;
    const d = daily[dIdx];
    const w = weekly[wIdx];
    const prevW = weekly[wIdx - 3];
    if (!d.ema20 || !d.ema50 || !w.ema20 || !prevW.ema20 || !c.atr14 || !c.vol20) continue;

    const volumeOk = c.volume > c.vol20 * 1.1;
    const weeklyBull = w.close > w.ema20 && w.ema20 > prevW.ema20;
    const weeklyBear = w.close < w.ema20 && w.ema20 < prevW.ema20;
    const dailyLong = d.ema20 > d.ema50 && d.close > d.ema20;
    const dailyShort = d.ema20 < d.ema50 && d.close < d.ema20;

    if (weeklyBull && dailyLong && volumeOk && hasRecentDailyPullback(h4, i, d) && bullishSignal(h4, i)) {
      const entry = c.close;
      let stop = Math.min(swingLow(h4, i - 1, 10), entry - c.atr14);
      if (entry <= stop) continue;
      const risk = entry - stop;
      position = {
        side: "LONG",
        entryTime: c.time,
        entry,
        stop,
        initialStop: stop,
        risk,
        tp1: entry + risk,
        tp2: entry + 2 * risk,
        tp1Done: false,
        realizedR: 0,
        setup: "Daily EMA20 pullback + H4 bullish confirmation + volume expansion",
        weeklyRegime: `Bullish: close ${w.close.toFixed(4)} > W EMA20 ${w.ema20.toFixed(4)}`,
        dailyTrend: `EMA20 ${d.ema20.toFixed(4)} > EMA50 ${d.ema50.toFixed(4)}`,
        notes: [],
      };
    } else if (weeklyBear && dailyShort && volumeOk && hasRecentDailyRally(h4, i, d) && bearishSignal(h4, i)) {
      const entry = c.close;
      let stop = Math.max(swingHigh(h4, i - 1, 10), entry + c.atr14);
      if (entry >= stop) continue;
      const risk = stop - entry;
      position = {
        side: "SHORT",
        entryTime: c.time,
        entry,
        stop,
        initialStop: stop,
        risk,
        tp1: entry - risk,
        tp2: entry - 2 * risk,
        tp1Done: false,
        realizedR: 0,
        setup: "Daily EMA20 relief rally + H4 bearish confirmation + volume expansion",
        weeklyRegime: `Bearish: close ${w.close.toFixed(4)} < W EMA20 ${w.ema20.toFixed(4)}`,
        dailyTrend: `EMA20 ${d.ema20.toFixed(4)} < EMA50 ${d.ema50.toFixed(4)}`,
        notes: [],
      };
    }
  }

  return trades;
}

const datasets = {};
const allTrades = [];
for (const symbol of symbols) {
  console.log(`Fetching ${symbol}`);
  const [h4Raw, dailyRaw, weeklyRaw] = await Promise.all([
    fetchKlines(symbol, "4h", warmupStart, end),
    fetchKlines(symbol, "1d", warmupStart, end),
    fetchKlines(symbol, "1w", warmupStart, end),
  ]);
  const h4 = enrich(h4Raw);
  const daily = enrich(dailyRaw);
  const weekly = enrich(weeklyRaw);
  datasets[symbol] = {
    h4Count: h4.length,
    dailyCount: daily.length,
    weeklyCount: weekly.length,
    firstH4: h4[0] ? iso(h4[0].time) : null,
    lastH4: h4[h4.length - 1] ? iso(h4[h4.length - 1].time) : null,
  };
  allTrades.push(...backtestSymbol(symbol, h4, daily, weekly));
}

allTrades.sort((a, b) => a.entryTime.localeCompare(b.entryTime));
const bySymbol = Object.fromEntries(symbols.map(s => [s.replace("USDT", ""), allTrades.filter(t => t.symbol === s)]));
const summary = symbols.map(symbol => {
  const trades = allTrades.filter(t => t.symbol === symbol);
  const wins = trades.filter(t => t.rMultiple > 0).length;
  const totalR = trades.reduce((sum, t) => sum + t.rMultiple, 0);
  return {
    symbol: symbol.replace("USDT", ""),
    trades: trades.length,
    wins,
    losses: trades.length - wins,
    winRate: trades.length ? wins / trades.length : 0,
    totalR,
    avgR: trades.length ? totalR / trades.length : 0,
    bestR: trades.length ? Math.max(...trades.map(t => t.rMultiple)) : 0,
    worstR: trades.length ? Math.min(...trades.map(t => t.rMultiple)) : 0,
  };
});

const assumptions = [
  "Backtest period: 2025-11-12 through 2026-05-12 UTC, using Binance spot OHLCV.",
  "Watchlist from the DOCX: BTC, ETH, SOL, LINK, AAVE, SUI, INJ versus USDT.",
  "Weekly bullish regime: weekly close above EMA20 and EMA20 higher than three weeks earlier.",
  "Weekly bearish regime: weekly close below EMA20 and EMA20 lower than three weeks earlier.",
  "Daily long trend: EMA20 above EMA50 and daily close above EMA20. Daily short trend is inverse.",
  "Pullback/relief rally: last seven H4 candles overlap the Daily EMA20 within 1.2% of daily close.",
  "H4 confirmation: engulfing, close reclaim/breakdown, or 8-candle consolidation breakout.",
  "Volume confirmation: H4 volume greater than 1.1x its 20-period SMA.",
  "Entry is H4 close. One open trade per symbol. No portfolio-level exposure cap is applied.",
  "Initial stop is H4 swing low/high over previous 10 candles, expanded to at least 1 ATR14 H4.",
  "Exit model: 50% at TP1 = 1R, then stop moves to breakeven; remaining 50% exits at TP2 = 2R or H4 EMA20 trailing stop.",
  "If stop and target are both touched in the same H4 candle, the conservative stop-first path is used.",
];

await fs.mkdir(outDir, { recursive: true });
await fs.writeFile(outFile, JSON.stringify({
  generatedAt: iso(Date.now()),
  source: "Binance spot klines API",
  period: { start: iso(start), end: iso(end) },
  symbols,
  datasets,
  assumptions,
  summary,
  trades: allTrades,
  bySymbol,
}, null, 2));

console.log(`Saved ${outFile}`);
console.log(`Trades: ${allTrades.length}`);
