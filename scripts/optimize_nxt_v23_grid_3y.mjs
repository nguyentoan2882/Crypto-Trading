import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const symbols = ["BTCUSDT", "SOLUSDT", "SUIUSDT"];
const end = Date.UTC(2026, 4, 17, 0, 0, 0);
const start = Date.UTC(2023, 4, 17, 0, 0, 0);
const warmupStart = Date.UTC(2022, 10, 1, 0, 0, 0);
const outDir = path.resolve("outputs", "nxt_crypto_btc_sol_sui_3y_grid");
const jsonPath = path.join(outDir, "nxt_v23_grid_3y_results.json");
const xlsxPath = path.join(outDir, "NXT_V23_Grid_3Y_BTC_SOL_SUI.xlsx");
const feeRate = 0.0006;
const slippageRate = 0.0005;
const roundTripCostRate = 2 * (feeRate + slippageRate);

const distanceValues = [1.75, 2.0, 2.25, 2.5];
const splitValues = [
  { tp1Weight: 0.3, tp2Weight: 0.7, label: "30/70" },
  { tp1Weight: 0.4, tp2Weight: 0.6, label: "40/60" },
  { tp1Weight: 0.5, tp2Weight: 0.5, label: "50/50" },
  { tp1Weight: 0.6, tp2Weight: 0.4, label: "60/40" },
];

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
    netVolume: c.takerBuyBaseVolume * 2 - c.volume,
  }));
}

function crossedUp(current, previous, key) {
  return previous.close <= previous[key] && current.close > current[key];
}

function crossedDown(current, previous, key) {
  return previous.close >= previous[key] && current.close < current[key];
}

function crossedUpRecently(daily, index, key, lookback = 3) {
  const from = Math.max(1, index - lookback + 1);
  for (let j = from; j <= index; j++) if (crossedUp(daily[j], daily[j - 1], key)) return true;
  return false;
}

function crossedDownRecently(daily, index, key, lookback = 3) {
  const from = Math.max(1, index - lookback + 1);
  for (let j = from; j <= index; j++) if (crossedDown(daily[j], daily[j - 1], key)) return true;
  return false;
}

function costR(entryPrice, riskPerUnit) {
  return (entryPrice * roundTripCostRate) / riskPerUnit;
}

function closeTrade(trades, position, exitCandle, exitPrice, exitReason, tradeNo, side, p) {
  const remainingR = side === "LONG"
    ? (exitPrice - position.entryPrice) / position.riskPerUnit
    : (position.entryPrice - exitPrice) / position.riskPerUnit;
  const remainingWeight = 1 - position.realizedWeight;
  const grossR = position.realizedR + remainingWeight * remainingR;
  const costInR = costR(position.entryPrice, position.riskPerUnit);
  trades.push({
    symbol: position.symbol,
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
    tp2Time: position.tp2Time ? iso(position.tp2Time) : "",
    exitTime: iso(exitCandle.time),
    exitPrice,
    exitReason,
    grossRMultiple: grossR,
    costR: costInR,
    rMultiple: grossR - costInR,
    pctMove: side === "LONG" ? exitPrice / position.entryPrice - 1 : position.entryPrice / exitPrice - 1,
    tp1Hit: position.tp1Done ? "Yes" : "No",
    tp2Hit: position.tp2Done ? "Yes" : "No",
    ema20: position.ema20,
    ema50: position.ema50,
    atr14: position.atr14,
    sslAtSignal: position.sslAtSignal,
    netVolume: position.netVolume,
    distanceToEma50Atr: position.distanceToEma50Atr,
    params: p,
    notes: position.notes.join("; "),
  });
}

function backtestSymbol(symbol, daily, p) {
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
      const sslFlip = side === "LONG" ? prev.ssl === 1 && c.ssl === -1 : prev.ssl === -1 && c.ssl === 1;
      if (side === "LONG") {
        if (c.low <= position.stop) {
          exitPrice = position.stop;
          exitReason = position.tp1Done ? "Breakeven stop after TP1" : "Stop loss";
        } else {
          if (!position.tp1Done && c.high >= position.tp1) {
            position.tp1Done = true;
            position.tp1Time = c.time;
            position.realizedR += p.tp1Weight * ((position.tp1 - position.entryPrice) / position.riskPerUnit);
            position.realizedWeight += p.tp1Weight;
            position.stop = position.entryPrice;
            position.notes.push(`TP1 hit ${iso(c.time)}; ${(p.tp1Weight * 100).toFixed(0)}% closed; remaining stop moved to breakeven`);
          }
          if (position.tp1Done && !position.tp2Done && c.high >= position.tp2) {
            position.tp2Done = true;
            position.tp2Time = c.time;
            position.realizedR += p.tp2Weight * ((position.tp2 - position.entryPrice) / position.riskPerUnit);
            position.realizedWeight += p.tp2Weight;
            position.notes.push(`TP2 hit ${iso(c.time)}; additional ${(p.tp2Weight * 100).toFixed(0)}% closed`);
          }
          if (sslFlip) {
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
            position.tp1Time = c.time;
            position.realizedR += p.tp1Weight * ((position.entryPrice - position.tp1) / position.riskPerUnit);
            position.realizedWeight += p.tp1Weight;
            position.stop = position.entryPrice;
            position.notes.push(`TP1 hit ${iso(c.time)}; ${(p.tp1Weight * 100).toFixed(0)}% closed; remaining stop moved to breakeven`);
          }
          if (position.tp1Done && !position.tp2Done && c.low <= position.tp2) {
            position.tp2Done = true;
            position.tp2Time = c.time;
            position.realizedR += p.tp2Weight * ((position.entryPrice - position.tp2) / position.riskPerUnit);
            position.realizedWeight += p.tp2Weight;
            position.notes.push(`TP2 hit ${iso(c.time)}; additional ${(p.tp2Weight * 100).toFixed(0)}% closed`);
          }
          if (sslFlip) {
            exitPrice = c.close;
            exitReason = "SSL bullish flip";
          }
        }
      }
      if (exitPrice != null) {
        closeTrade(trades, position, c, exitPrice, exitReason, tradeNo++, side, p);
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
    const distanceOk = distanceToEma50Atr <= p.distanceMax;
    const longOk = sslBullCross && priceCrossUpEma20 && c.netVolume > 0 && distanceOk;
    const shortOk = sslBearCross && priceCrossDownEma20 && c.netVolume < 0 && distanceOk;
    if (!longOk && !shortOk) continue;

    const side = longOk ? "LONG" : "SHORT";
    const entryPrice = next.open;
    const riskPerUnit = c.atr14 * 1.5;
    const initialStop = side === "LONG" ? entryPrice - riskPerUnit : entryPrice + riskPerUnit;
    position = {
      symbol,
      side,
      signalTime: c.time,
      entryTime: next.time,
      entryPrice,
      initialStop,
      stop: initialStop,
      riskPerUnit,
      tp1: side === "LONG" ? entryPrice + c.atr14 * 1.5 : entryPrice - c.atr14 * 1.5,
      tp2: side === "LONG" ? entryPrice + c.atr14 * 2.5 : entryPrice - c.atr14 * 2.5,
      tp1Done: false,
      tp2Done: false,
      tp1Time: null,
      tp2Time: null,
      realizedR: 0,
      realizedWeight: 0,
      ema20: c.ema20,
      ema50: c.ema50,
      atr14: c.atr14,
      sslAtSignal: c.ssl,
      netVolume: c.netVolume,
      distanceToEma50Atr,
      notes: [
        `Signal close ${iso(c.time)}; entry next daily open`,
        `Distance to EMA50 ${distanceToEma50Atr.toFixed(2)} ATR`,
      ],
    };
  }
  if (position) {
    const last = daily[daily.length - 1];
    closeTrade(trades, position, last, last.close, "End of test mark-to-market", tradeNo++, position.side, p);
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

function stats(trades, p) {
  let cum = 0;
  let peak = 0;
  let maxDrawdownR = 0;
  for (const t of trades) {
    cum += t.rMultiple;
    peak = Math.max(peak, cum);
    maxDrawdownR = Math.min(maxDrawdownR, cum - peak);
  }
  const totalR = trades.reduce((s, t) => s + t.rMultiple, 0);
  const wins = trades.filter(t => t.rMultiple > 0).length;
  return {
    ...p,
    trades: trades.length,
    winRate: trades.length ? wins / trades.length : 0,
    totalR,
    avgR: trades.length ? totalR / trades.length : 0,
    maxDrawdownR,
    bestR: trades.length ? Math.max(...trades.map(t => t.rMultiple)) : 0,
    worstR: trades.length ? Math.min(...trades.map(t => t.rMultiple)) : 0,
    summary: summarize(trades),
  };
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

async function buildWorkbook(data) {
  const workbook = Workbook.create();
  const ranking = workbook.worksheets.add("Ranking");
  baseSheet(ranking, "NXT v2.3 Grid Optimization - 3Y", `${data.period.start} to ${data.period.end} | BTC, SOL, SUI | Source: Binance`);
  const rankRows = [[
    "Rank", "Distance Max", "Split", "TP1 Weight", "TP2 Weight", "Trades", "Win Rate", "Total R", "Avg R", "Max DD", "Best R", "Worst R", "BTC R", "SOL R", "SUI R",
  ], ...data.results.map((r, i) => [
    i + 1, r.distanceMax, r.label, r.tp1Weight, r.tp2Weight, r.trades, r.winRate, r.totalR, r.avgR, r.maxDrawdownR, r.bestR, r.worstR,
    r.summary.find(s => s.symbol === "BTCUSDT")?.totalR ?? 0,
    r.summary.find(s => s.symbol === "SOLUSDT")?.totalR ?? 0,
    r.summary.find(s => s.symbol === "SUIUSDT")?.totalR ?? 0,
  ])];
  writeMatrix(ranking, "A4", rankRows);
  styleHeader(ranking, "A4:O4");
  numberFormat(ranking, `G5:G${rankRows.length + 3}`, "0.0%");
  numberFormat(ranking, `H5:O${rankRows.length + 3}`, "0.00");
  ranking.getRange(`A4:O${rankRows.length + 3}`).format.wrapText = true;
  finishSheet(ranking, `A1:O${rankRows.length + 3}`);

  const best = data.best;
  const summary = workbook.worksheets.add("Best Summary");
  baseSheet(summary, "Best Variant Summary", `Distance ${best.distanceMax}, split ${best.label}`);
  writeMatrix(summary, "A4", [
    ["Metric", "Value"],
    ["Trades", best.trades],
    ["Win Rate", best.winRate],
    ["Total R", best.totalR],
    ["Avg R", best.avgR],
    ["Max DD", best.maxDrawdownR],
    ["Best R", best.bestR],
    ["Worst R", best.worstR],
  ]);
  styleHeader(summary, "A4:B4");
  numberFormat(summary, "B6:B6", "0.0%");
  numberFormat(summary, "B7:B11", "0.00");
  writeMatrix(summary, "D4", [["Symbol", "Trades", "Win Rate", "Total R", "Avg R", "Best R", "Worst R"], ...best.summary.map(s => [
    s.symbol.replace("USDT", ""), s.trades, s.winRate, s.totalR, s.avgR, s.bestR, s.worstR,
  ])]);
  styleHeader(summary, "D4:J4");
  numberFormat(summary, "F5:F8", "0.0%");
  numberFormat(summary, "G5:J8", "0.00");
  finishSheet(summary, "A1:J12");

  const tradeHeaders = [
    "Symbol", "Side", "Signal Time", "Entry Time", "Entry Price", "Initial Stop", "TP1", "TP1 Time", "TP2", "TP2 Time",
    "Exit Time", "Exit Price", "Exit Reason", "Gross R", "Cost R", "Net R", "TP1 Hit", "TP2 Hit", "Distance EMA50 ATR", "Notes",
  ];
  const trades = workbook.worksheets.add("Best Trades");
  baseSheet(trades, "Best Variant Trade Detail", `Best grid variant: distance ${best.distanceMax}, split ${best.label}`);
  writeMatrix(trades, "A4", [tradeHeaders, ...data.bestTrades.map(t => [
    t.symbol.replace("USDT", ""), t.side, new Date(t.signalTime), new Date(t.entryTime), t.entryPrice, t.initialStop, t.tp1,
    t.tp1Time ? new Date(t.tp1Time) : "", t.tp2, t.tp2Time ? new Date(t.tp2Time) : "", new Date(t.exitTime), t.exitPrice,
    t.exitReason, t.grossRMultiple, t.costR, t.rMultiple, t.tp1Hit, t.tp2Hit, t.distanceToEma50Atr, t.notes,
  ])]);
  styleHeader(trades, "A4:T4");
  const lastTradeRow = data.bestTrades.length + 4;
  if (data.bestTrades.length) {
    numberFormat(trades, `C5:D${lastTradeRow}`, "yyyy-mm-dd");
    numberFormat(trades, `H5:H${lastTradeRow}`, "yyyy-mm-dd");
    numberFormat(trades, `J5:K${lastTradeRow}`, "yyyy-mm-dd");
    numberFormat(trades, `E5:G${lastTradeRow}`, "0.000000");
    numberFormat(trades, `I5:I${lastTradeRow}`, "0.000000");
    numberFormat(trades, `L5:L${lastTradeRow}`, "0.000000");
    numberFormat(trades, `N5:P${lastTradeRow}`, "0.00");
    numberFormat(trades, `S5:S${lastTradeRow}`, "0.00");
  }
  trades.getRange(`A4:T${Math.max(lastTradeRow, 5)}`).format.wrapText = true;
  finishSheet(trades, `A1:T${Math.max(lastTradeRow, 5)}`);

  const assumptions = workbook.worksheets.add("Assumptions");
  baseSheet(assumptions, "Grid Assumptions", "All variants keep NXT v2.3 entry logic and fixed TP exits.");
  writeMatrix(assumptions, "A4", [["#", "Assumption"], ...data.assumptions.map((a, i) => [i + 1, a])]);
  styleHeader(assumptions, "A4:B4");
  assumptions.getRange(`A4:B${data.assumptions.length + 4}`).format.wrapText = true;
  finishSheet(assumptions, `A1:B${data.assumptions.length + 4}`);

  const errorScan = await workbook.inspect({
    kind: "match",
    searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
    options: { useRegex: true, maxResults: 300 },
    summary: "formula error scan",
  });
  console.log(errorScan.ndjson);
  await fs.mkdir(outDir, { recursive: true });
  const output = await SpreadsheetFile.exportXlsx(workbook);
  await output.save(xlsxPath);
}

await fs.mkdir(outDir, { recursive: true });
const enriched = {};
const datasets = {};
for (const symbol of symbols) {
  const daily = await fetchBinanceKlines(symbol, "1d", warmupStart, end);
  enriched[symbol] = enrich(daily);
  datasets[symbol] = {
    dailyCount: daily.length,
    firstDaily: daily.length ? iso(daily[0].time) : "",
    lastDaily: daily.length ? iso(daily[daily.length - 1].time) : "",
  };
}

const runs = [];
for (const distanceMax of distanceValues) {
  for (const split of splitValues) {
    const p = { distanceMax, ...split };
    const trades = symbols.flatMap(symbol => backtestSymbol(symbol, enriched[symbol], p));
    trades.sort((a, b) => new Date(a.exitTime) - new Date(b.exitTime));
    runs.push({ params: p, trades, stats: stats(trades, p) });
  }
}

runs.sort((a, b) => {
  const scoreA = a.stats.totalR + a.stats.maxDrawdownR * 0.35;
  const scoreB = b.stats.totalR + b.stats.maxDrawdownR * 0.35;
  return scoreB - scoreA;
});

const data = {
  generatedAt: new Date().toISOString(),
  period: { start: iso(start), end: iso(end - 1) },
  symbols,
  datasets,
  results: runs.map(r => r.stats),
  best: runs[0].stats,
  bestTrades: runs[0].trades,
  assumptions: [
    "Base entry logic: NXT v2.3, no Weekly regime filter, SSL crossover plus EMA20 cross within last 3 candles, Binance taker-volume Net Volume, and EMA50 distance filter.",
    "Grid variable 1: maximum distance from close to EMA50 measured in ATR(14): 1.75, 2.00, 2.25, 2.50.",
    "Grid variable 2: fixed-exit split at TP1/TP2: 30/70, 40/60, 50/50, 60/40.",
    "TP1 remains 1.5 x ATR(14). TP2 remains 2.5 x ATR(14). No runner is used in this grid.",
    `Cost model: ${feeRate * 100}% fee and ${slippageRate * 100}% slippage per side, deducted from each trade in R terms.`,
    "Ranking sheet is sorted by a simple risk-adjusted score: Total R plus 0.35 x Max Drawdown R. Max Drawdown is negative, so deeper drawdown is penalized.",
  ],
};

await fs.writeFile(jsonPath, JSON.stringify(data, null, 2));
await buildWorkbook(data);
console.log(JSON.stringify({
  jsonPath,
  xlsxPath,
  best: data.best,
  topFive: data.results.slice(0, 5).map(r => ({
    distanceMax: r.distanceMax,
    split: r.label,
    trades: r.trades,
    winRate: r.winRate,
    totalR: r.totalR,
    avgR: r.avgR,
    maxDrawdownR: r.maxDrawdownR,
  })),
}, null, 2));
