import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const symbols = ["BTCUSDT", "SOLUSDT", "SUIUSDT"];
const end = Date.UTC(2026, 4, 16, 0, 0, 0);
const start = Date.UTC(2025, 4, 16, 0, 0, 0);
const warmupStart = Date.UTC(2024, 10, 1, 0, 0, 0);
const profile = process.argv.includes("--optimized") ? "optimized" : "baseline";
const outDir = path.resolve("outputs", profile === "optimized" ? "nnfx_crypto_btc_sol_sui_1y_optimized" : "nnfx_crypto_btc_sol_sui_1y");
const jsonPath = path.join(outDir, profile === "optimized" ? "nnfx_crypto_btc_sol_sui_1y_optimized_results.json" : "nnfx_crypto_btc_sol_sui_1y_results.json");
const xlsxPath = path.join(outDir, profile === "optimized" ? "NNFX_Crypto_BTC_SOL_SUI_1Y_Optimized_Backtest.xlsx" : "NNFX_Crypto_BTC_SOL_SUI_1Y_Backtest.xlsx");
const params = profile === "optimized"
  ? { tdfi: 0.1, bridgeMax: 1, atrExpansionMult: 1, volumeMult: 1.15, rangeVolMult: 1.35, stopAtr: 1.2, tp1Atr: 1.5, tp1Weight: 0.25, moveStopToBE: false, hull: 55, rsBuffer: 0 }
  : { tdfi: 0.05, bridgeMax: 1, atrExpansionMult: 1, volumeMult: 1, rangeVolMult: 1.15, stopAtr: 1.5, tp1Atr: 1, tp1Weight: 0.5, moveStopToBE: true, hull: 55, rsBuffer: 0 };
const yahooSymbols = {
  BTCUSDT: "BTC-USD",
  SOLUSDT: "SOL-USD",
  SUIUSDT: "SUI20947-USD",
};

function iso(ms) {
  return new Date(ms).toISOString().replace(".000Z", "Z");
}

function sma(values, period) {
  const out = Array(values.length).fill(null);
  let sum = 0;
  for (let i = 0; i < values.length; i++) {
    const v = values[i];
    if (v == null || Number.isNaN(v)) {
      out[i] = null;
      continue;
    }
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
    const v = values[i];
    if (i < period) sum += v;
    if (i === period - 1) out[i] = sum / period;
    if (i >= period) out[i] = v * k + out[i - 1] * (1 - k);
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
      if (v == null) {
        ok = false;
        break;
      }
      weighted += v * (j + 1);
    }
    if (ok) out[i] = weighted / denom;
  }
  return out;
}

function hma(values, period) {
  const half = Math.floor(period / 2);
  const sqrt = Math.max(1, Math.round(Math.sqrt(period)));
  const wmaHalf = wma(values, half);
  const wmaFull = wma(values, period);
  const diff = values.map((_, i) => (wmaHalf[i] == null || wmaFull[i] == null ? null : 2 * wmaHalf[i] - wmaFull[i]));
  return wma(diff, sqrt);
}

function atr(candles, period) {
  const tr = candles.map((c, i) => {
    if (i === 0) return c.high - c.low;
    const prevClose = candles[i - 1].close;
    return Math.max(c.high - c.low, Math.abs(c.high - prevClose), Math.abs(c.low - prevClose));
  });
  return sma(tr, period);
}

function kama(values, period = 50, fast = 2, slow = 30) {
  const out = Array(values.length).fill(null);
  const fastSC = 2 / (fast + 1);
  const slowSC = 2 / (slow + 1);
  for (let i = 0; i < values.length; i++) {
    if (i < period) continue;
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

function rollingReturn(candles, period) {
  return candles.map((c, i) => (i < period ? null : c.close / candles[i - period].close - 1));
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
  const rows = [];
  for (let i = 0; i < result.timestamp.length; i++) {
    const open = q.open[i], high = q.high[i], low = q.low[i], close = q.close[i];
    if ([open, high, low, close].some(v => v == null || Number.isNaN(v))) continue;
    const time = result.timestamp[i] * 1000;
    rows.push({
      time,
      open,
      high,
      low,
      close,
      volume: q.volume[i] ?? 0,
      closeTime: time + 24 * 60 * 60 * 1000 - 1,
    });
  }
  return rows;
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

function tdfiProxy(candles) {
  const closes = candles.map(c => c.close);
  const ema13 = ema(closes, 13);
  const raw = closes.map((_, i) => {
    if (i < 14 || ema13[i] == null || ema13[i - 1] == null) return null;
    const momentum = (ema13[i] - ema13[i - 1]) / candles[i].close;
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

function enrich(candles) {
  const closes = candles.map(c => c.close);
  const ranges = candles.map(c => c.high - c.low);
  const rangeVol = candles.map((c, i) => ranges[i] * c.volume);
  const atr14 = atr(candles, 14);
  const atrSma20 = sma(atr14, 20);
  const kama50 = kama(closes, 50);
  const ssl = sslState(candles, 10);
  const tdfi = tdfiProxy(candles);
  const hma21 = hma(closes, 21);
  const hma55 = hma(closes, 55);
  const vol20 = sma(candles.map(c => c.volume), 20);
  const rangeVol20 = sma(rangeVol, 20);
  const ret14 = rollingReturn(candles, 14);
  return candles.map((c, i) => ({
    ...c,
    atr14: atr14[i],
    atrSma20: atrSma20[i],
    kama50: kama50[i],
    ssl: ssl[i],
    tdfi: tdfi[i],
    hma21Slope: i > 0 && hma21[i] != null && hma21[i - 1] != null ? hma21[i] - hma21[i - 1] : null,
    hma55: hma55[i],
    hmaSlope: i > 0 && hma55[i] != null && hma55[i - 1] != null ? hma55[i] - hma55[i - 1] : null,
    vol20: vol20[i],
    rangeVol: rangeVol[i],
    rangeVol20: rangeVol20[i],
    ret14: ret14[i],
  }));
}

function betterVolumeOk(c, side) {
  if (!c.vol20 || !c.rangeVol20) return false;
  const directional = side === "LONG" ? c.close >= c.open : c.close <= c.open;
  const greenOrClimax = (directional && c.volume >= c.vol20 * params.volumeMult) || c.rangeVol >= c.rangeVol20 * params.rangeVolMult;
  return greenOrClimax;
}

function findByCloseTime(candles, closeTime) {
  let lo = 0, hi = candles.length - 1, ans = null;
  while (lo <= hi) {
    const mid = Math.floor((lo + hi) / 2);
    if (candles[mid].closeTime <= closeTime) {
      ans = candles[mid];
      lo = mid + 1;
    } else {
      hi = mid - 1;
    }
  }
  return ans;
}

function backtestSymbol(symbol, daily, btcDaily) {
  const trades = [];
  let position = null;
  let tradeNo = 1;

  for (let i = 60; i < daily.length - 1; i++) {
    const c = daily[i];
    const next = daily[i + 1];
    if (next.time < start || next.time > end) continue;

    if (position) {
      let exitPrice = null;
      let exitReason = null;
      let remainingR = 0;
      const side = position.side;

      const hullSlope = params.hull === 21 ? c.hma21Slope : c.hmaSlope;
      if (side === "LONG") {
        if (c.low <= position.stop) {
          exitPrice = position.stop;
          exitReason = position.tp1Done ? "Breakeven / trailing stop" : "Stop loss";
          remainingR = (exitPrice - position.entryPrice) / position.riskPerUnit;
        } else if (!position.tp1Done && c.high >= position.tp1) {
          position.tp1Done = true;
          position.realizedR += params.tp1Weight * ((position.tp1 - position.entryPrice) / position.riskPerUnit);
          if (params.moveStopToBE) position.stop = position.entryPrice;
          position.notes.push(`TP1 hit ${iso(c.time)} @ ${position.tp1.toFixed(6)}; ${params.moveStopToBE ? "stop moved to breakeven" : "initial stop retained"}`);
        } else if (position.tp1Done && (hullSlope < 0 || c.ssl === -1)) {
          exitPrice = c.close;
          exitReason = hullSlope < 0 ? "Hull bearish exit" : "SSL bearish exit";
          remainingR = (exitPrice - position.entryPrice) / position.riskPerUnit;
        }
      } else {
        if (c.high >= position.stop) {
          exitPrice = position.stop;
          exitReason = position.tp1Done ? "Breakeven / trailing stop" : "Stop loss";
          remainingR = (position.entryPrice - exitPrice) / position.riskPerUnit;
        } else if (!position.tp1Done && c.low <= position.tp1) {
          position.tp1Done = true;
          position.realizedR += params.tp1Weight * ((position.entryPrice - position.tp1) / position.riskPerUnit);
          if (params.moveStopToBE) position.stop = position.entryPrice;
          position.notes.push(`TP1 hit ${iso(c.time)} @ ${position.tp1.toFixed(6)}; ${params.moveStopToBE ? "stop moved to breakeven" : "initial stop retained"}`);
        } else if (position.tp1Done && (hullSlope > 0 || c.ssl === 1)) {
          exitPrice = c.close;
          exitReason = hullSlope > 0 ? "Hull bullish exit" : "SSL bullish exit";
          remainingR = (position.entryPrice - exitPrice) / position.riskPerUnit;
        }
      }

      if (exitPrice != null) {
        const remainingWeight = position.tp1Done ? 1 - params.tp1Weight : 1;
        const totalR = position.realizedR + remainingWeight * remainingR;
        trades.push({
          symbol,
          tradeNo: tradeNo++,
          side,
          entryTime: iso(position.entryTime),
          entrySignalTime: iso(position.signalTime),
          entryPrice: position.entryPrice,
          initialStop: position.initialStop,
          finalStop: position.stop,
          riskPerUnit: position.riskPerUnit,
          tp1: position.tp1,
          exitTime: iso(c.time),
          exitPrice,
          exitReason,
          rMultiple: totalR,
          pctMove: side === "LONG" ? exitPrice / position.entryPrice - 1 : position.entryPrice / exitPrice - 1,
          tp1Hit: position.tp1Done ? "Yes" : "No",
          kama50: position.kama50,
          atr14: position.atr14,
          tdfi: position.tdfi,
          atrExpansion: position.atrExpansion,
          bridgeDistanceAtr: position.bridgeDistanceAtr,
          relativeStrength: position.relativeStrength,
          notes: position.notes.join("; "),
        });
        position = null;
      }
      continue;
    }

    const required = [c.atr14, c.atrSma20, c.kama50, c.ssl, c.tdfi, c.hma55, c.vol20, c.rangeVol20];
    if (required.some(v => v == null)) continue;
    const bridgeDistanceAtr = Math.abs(c.close - c.kama50) / c.atr14;
    const atrExpansion = c.atr14 > c.atrSma20 * params.atrExpansionMult;
    const btc = symbol === "BTCUSDT" ? c : findByCloseTime(btcDaily, c.closeTime);
    const relativeStrength = symbol === "BTCUSDT" ? true : btc?.ret14 != null && c.ret14 != null && c.ret14 > btc.ret14 + params.rsBuffer;
    const longOk = c.close > c.kama50 && bridgeDistanceAtr <= params.bridgeMax && c.ssl === 1 && c.tdfi > params.tdfi && atrExpansion && betterVolumeOk(c, "LONG") && relativeStrength;
    const shortOk = c.close < c.kama50 && bridgeDistanceAtr <= params.bridgeMax && c.ssl === -1 && c.tdfi < -params.tdfi && atrExpansion && betterVolumeOk(c, "SHORT") && relativeStrength;
    if (!longOk && !shortOk) continue;

    const side = longOk ? "LONG" : "SHORT";
    const entryPrice = next.open;
    const riskPerUnit = c.atr14 * params.stopAtr;
    const initialStop = side === "LONG" ? entryPrice - riskPerUnit : entryPrice + riskPerUnit;
    const tp1 = side === "LONG" ? entryPrice + c.atr14 * params.tp1Atr : entryPrice - c.atr14 * params.tp1Atr;
    position = {
      side,
      signalTime: c.time,
      entryTime: next.time,
      entryPrice,
      initialStop,
      stop: initialStop,
      riskPerUnit,
      tp1,
      tp1Done: false,
      realizedR: 0,
      kama50: c.kama50,
      atr14: c.atr14,
      tdfi: c.tdfi,
      atrExpansion: `${c.atr14.toFixed(6)} > ${c.atrSma20.toFixed(6)}`,
      bridgeDistanceAtr,
      relativeStrength: symbol === "BTCUSDT" ? "N/A - BTC base asset" : `${(c.ret14 * 100).toFixed(2)}% vs BTC ${(btc.ret14 * 100).toFixed(2)}%`,
      notes: [
        `Signal close ${iso(c.time)}; entry next daily open`,
        `Baseline ${side === "LONG" ? "close > KAMA50" : "close < KAMA50"}`,
        `SSL ${side === "LONG" ? "bullish" : "bearish"}; TDFI ${c.tdfi.toFixed(3)}`,
      ],
    };
  }

  if (position) {
    const last = daily[daily.length - 1];
    const remainingR = position.side === "LONG"
      ? (last.close - position.entryPrice) / position.riskPerUnit
      : (position.entryPrice - last.close) / position.riskPerUnit;
    const totalR = position.realizedR + (position.tp1Done ? 0.5 : 1) * remainingR;
    trades.push({
      symbol,
      tradeNo: tradeNo++,
      side: position.side,
      entryTime: iso(position.entryTime),
      entrySignalTime: iso(position.signalTime),
      entryPrice: position.entryPrice,
      initialStop: position.initialStop,
      finalStop: position.stop,
      riskPerUnit: position.riskPerUnit,
      tp1: position.tp1,
      exitTime: iso(last.time),
      exitPrice: last.close,
      exitReason: "End of test mark-to-market",
      rMultiple: totalR,
      pctMove: position.side === "LONG" ? last.close / position.entryPrice - 1 : position.entryPrice / last.close - 1,
      tp1Hit: position.tp1Done ? "Yes" : "No",
      kama50: position.kama50,
      atr14: position.atr14,
      tdfi: position.tdfi,
      atrExpansion: position.atrExpansion,
      bridgeDistanceAtr: position.bridgeDistanceAtr,
      relativeStrength: position.relativeStrength,
      notes: position.notes.join("; "),
    });
  }

  return trades;
}

function summarize(trades, symbols) {
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
  const startCol = match[1];
  const startRow = Number(match[2]);
  const startColNo = startCol.split("").reduce((n, ch) => n * 26 + ch.charCodeAt(0) - 64, 0);
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
  const totalTrades = data.trades.length;
  const totalR = data.trades.reduce((s, t) => s + t.rMultiple, 0);
  const wins = data.trades.filter(t => t.rMultiple > 0).length;
  let cumulative = 0;
  let peak = 0;
  let maxDrawdownR = 0;
  for (const t of data.trades) {
    cumulative += t.rMultiple;
    peak = Math.max(peak, cumulative);
    maxDrawdownR = Math.min(maxDrawdownR, cumulative - peak);
  }

  const summary = workbook.worksheets.add("Summary");
  baseSheet(summary, profile === "optimized" ? "NNFX Crypto Trend System - 1Y Optimized Backtest" : "NNFX Crypto Trend System - 1Y Backtest", `${data.period.start} to ${data.period.end} | BTC, SOL, SUI | Source: ${data.source}`);
  const kpis = [
    ["Metric", "Value"],
    ["Total trades", totalTrades],
    ["Win rate", totalTrades ? wins / totalTrades : 0],
    ["Total R", totalR],
    ["Average R / trade", totalTrades ? totalR / totalTrades : 0],
    ["Max drawdown (R)", maxDrawdownR],
    ["Best trade (R)", totalTrades ? Math.max(...data.trades.map(t => t.rMultiple)) : 0],
    ["Worst trade (R)", totalTrades ? Math.min(...data.trades.map(t => t.rMultiple)) : 0],
  ];
  writeMatrix(summary, "A4", kpis);
  styleHeader(summary, "A4:B4");
  numberFormat(summary, "B6:B6", "0.0%");
  numberFormat(summary, "B7:B11", "0.00");
  const symbolHeaders = ["Symbol", "Trades", "Wins", "Losses", "Win Rate", "Total R", "Avg R", "Best R", "Worst R"];
  writeMatrix(summary, "D4", [symbolHeaders, ...data.summary.map(r => [
    r.symbol.replace("USDT", ""), r.trades, r.wins, r.losses, r.winRate, r.totalR, r.avgR, r.bestR, r.worstR,
  ])]);
  styleHeader(summary, "D4:L4");
  numberFormat(summary, "H5:L20", "0.00");
  numberFormat(summary, "H5:H20", "0.0%");
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

  if (profile === "optimized") {
    const comparison = workbook.worksheets.add("Optimization");
    baseSheet(comparison, "Optimization Comparison", "Baseline vs selected optimized profile plus top grid-search variants.");
    let baseline = null;
    try {
      baseline = JSON.parse(await fs.readFile(path.resolve("outputs", "nnfx_crypto_btc_sol_sui_1y", "nnfx_crypto_btc_sol_sui_1y_results.json"), "utf8"));
    } catch {
      baseline = null;
    }
    const baselineTrades = baseline?.trades ?? [];
    const baselineTotalR = baselineTrades.reduce((s, t) => s + t.rMultiple, 0);
    const baselineWins = baselineTrades.filter(t => t.rMultiple > 0).length;
    const comparisonRows = [
      ["Profile", "Trades", "Win Rate", "Total R", "Avg R / Trade", "BTC R", "SOL R", "SUI R"],
      ["Baseline", baselineTrades.length, baselineTrades.length ? baselineWins / baselineTrades.length : 0, baselineTotalR, baselineTrades.length ? baselineTotalR / baselineTrades.length : 0,
        baseline?.summary?.find(r => r.symbol === "BTCUSDT")?.totalR ?? 0,
        baseline?.summary?.find(r => r.symbol === "SOLUSDT")?.totalR ?? 0,
        baseline?.summary?.find(r => r.symbol === "SUIUSDT")?.totalR ?? 0],
      ["Optimized", totalTrades, totalTrades ? wins / totalTrades : 0, totalR, totalTrades ? totalR / totalTrades : 0,
        data.summary.find(r => r.symbol === "BTCUSDT")?.totalR ?? 0,
        data.summary.find(r => r.symbol === "SOLUSDT")?.totalR ?? 0,
        data.summary.find(r => r.symbol === "SUIUSDT")?.totalR ?? 0],
    ];
    writeMatrix(comparison, "A4", comparisonRows);
    styleHeader(comparison, "A4:H4");
    numberFormat(comparison, "C5:C6", "0.0%");
    numberFormat(comparison, "D5:H6", "0.00");
    try {
      const topVariants = JSON.parse(await fs.readFile(path.resolve("outputs", "nnfx_crypto_btc_sol_sui_1y", "nnfx_crypto_optimization_results.json"), "utf8")).slice(0, 20);
      writeMatrix(comparison, "A9", [[
        "Rank", "Trades", "Win Rate", "Total R", "Avg R", "Max DD", "Profit Factor", "BTC R", "SOL R", "SUI R",
        "TDFI", "Bridge", "ATR Exp", "Volume", "Range Vol", "Stop ATR", "TP1 ATR", "TP1 Weight", "Move BE", "Hull",
      ], ...topVariants.map((r, i) => [
        i + 1, r.trades, r.winRate, r.totalR, r.avgR, r.maxDrawdownR, r.profitFactor,
        r.bySymbol.BTCUSDT, r.bySymbol.SOLUSDT, r.bySymbol.SUIUSDT,
        r.params.tdfi, r.params.bridgeMax, r.params.atrExpansionMult, r.params.volumeMult, r.params.rangeVolMult,
        r.params.stopAtr, r.params.tp1Atr, r.params.tp1Weight, r.params.moveStopToBE ? "Yes" : "No", r.params.hull,
      ])]);
      styleHeader(comparison, "A9:T9");
      numberFormat(comparison, "C10:C29", "0.0%");
      numberFormat(comparison, "D10:J29", "0.00");
      numberFormat(comparison, "K10:R29", "0.00");
    } catch {
      writeMatrix(comparison, "A9", [["Optimization details", "Run scripts/optimize_nnfx_crypto.mjs to populate top variants."]]);
    }
    comparison.getRange("A4:T29").format.wrapText = true;
    finishSheet(comparison, "A1:T29");
  }

  const tradeHeaders = [
    "Symbol", "No", "Side", "Signal Time", "Entry Time", "Entry Price", "Initial Stop", "Final Stop", "Risk / Unit", "TP1",
    "Exit Time", "Exit Price", "Exit Reason", "R Multiple", "% Move", "TP1 Hit", "KAMA50", "ATR14", "TDFI", "ATR Expansion",
    "Bridge Distance ATR", "Relative Strength", "Notes",
  ];
  const tradeToRow = t => [
    t.symbol.replace("USDT", ""), t.tradeNo, t.side, new Date(t.entrySignalTime), new Date(t.entryTime), t.entryPrice,
    t.initialStop, t.finalStop, t.riskPerUnit, t.tp1, new Date(t.exitTime), t.exitPrice, t.exitReason, t.rMultiple,
    t.pctMove, t.tp1Hit, t.kama50, t.atr14, t.tdfi, t.atrExpansion, t.bridgeDistanceAtr, t.relativeStrength, t.notes,
  ];
  const trades = workbook.worksheets.add("Trades");
  baseSheet(trades, "Detailed Trades", `One completed trade per row; TP1 closes ${(params.tp1Weight * 100).toFixed(0)}%, remaining exits on Hull/SSL reversal or stop.`);
  writeMatrix(trades, "A4", [tradeHeaders, ...data.trades.map(tradeToRow)]);
  styleHeader(trades, "A4:W4");
  trades.freezePanes.freezeRows(4);
  const lastTradeRow = data.trades.length + 4;
  if (data.trades.length) {
    numberFormat(trades, `D5:E${lastTradeRow}`, "yyyy-mm-dd hh:mm");
    numberFormat(trades, `K5:K${lastTradeRow}`, "yyyy-mm-dd hh:mm");
    numberFormat(trades, `F5:J${lastTradeRow}`, "0.000000");
    numberFormat(trades, `L5:L${lastTradeRow}`, "0.000000");
    numberFormat(trades, `N5:N${lastTradeRow}`, "0.00");
    numberFormat(trades, `O5:O${lastTradeRow}`, "0.00%");
    numberFormat(trades, `Q5:R${lastTradeRow}`, "0.000000");
    numberFormat(trades, `S5:S${lastTradeRow}`, "0.000");
    numberFormat(trades, `U5:U${lastTradeRow}`, "0.00");
    trades.getRange(`A4:W${lastTradeRow}`).format.borders = { preset: "inside", style: "thin", color: "#E5E7EB" };
  }
  trades.getRange(`A4:W${Math.max(lastTradeRow, 5)}`).format.wrapText = true;
  finishSheet(trades, `A1:W${Math.max(lastTradeRow, 5)}`);

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

  const assumptions = workbook.worksheets.add("Assumptions");
  baseSheet(assumptions, "Backtest Assumptions", "Objective translation of the NNFX Crypto Trend System DOCX.");
  writeMatrix(assumptions, "A4", [["#", "Assumption"], ...data.assumptions.map((a, i) => [i + 1, a])]);
  styleHeader(assumptions, "A4:B4");
  assumptions.getRange(`A4:B${data.assumptions.length + 4}`).format.wrapText = true;
  finishSheet(assumptions, `A1:B${data.assumptions.length + 4}`);

  const quality = workbook.worksheets.add("Data Quality");
  baseSheet(quality, "Data Quality", "Loaded Yahoo Finance daily crypto candles.");
  writeMatrix(quality, "A4", [["Symbol", "Daily Candles", "First Daily", "Last Daily"], ...Object.entries(data.datasets).map(([symbol, q]) => [
    symbol.replace("USDT", ""), q.dailyCount, new Date(q.firstDaily), new Date(q.lastDaily),
  ])]);
  styleHeader(quality, "A4:D4");
  numberFormat(quality, `C5:D${Object.keys(data.datasets).length + 4}`, "yyyy-mm-dd");
  finishSheet(quality, `A1:D${Object.keys(data.datasets).length + 4}`);

  for (const symbol of Object.keys(data.bySymbol)) {
    const sheet = workbook.worksheets.add(symbol.replace("USDT", ""));
    baseSheet(sheet, `${symbol.replace("USDT", "")} Trades`, "Filtered trade detail for this symbol.");
    const rows = data.bySymbol[symbol].map(tradeToRow);
    writeMatrix(sheet, "A4", [tradeHeaders, ...rows]);
    styleHeader(sheet, "A4:W4");
    sheet.freezePanes.freezeRows(4);
    const endRow = rows.length + 4;
    if (rows.length) {
      numberFormat(sheet, `D5:E${endRow}`, "yyyy-mm-dd hh:mm");
      numberFormat(sheet, `K5:K${endRow}`, "yyyy-mm-dd hh:mm");
      numberFormat(sheet, `F5:J${endRow}`, "0.000000");
      numberFormat(sheet, `L5:L${endRow}`, "0.000000");
      numberFormat(sheet, `N5:N${endRow}`, "0.00");
      numberFormat(sheet, `O5:O${endRow}`, "0.00%");
      sheet.getRange(`A4:W${endRow}`).format.borders = { preset: "inside", style: "thin", color: "#E5E7EB" };
    }
    sheet.getRange(`A4:W${Math.max(endRow, 5)}`).format.wrapText = true;
    finishSheet(sheet, `A1:W${Math.max(endRow, 5)}`);
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
const datasets = {};
const enriched = {};
for (const symbol of symbols) {
  const daily = await fetchYahooDaily(symbol, warmupStart, end);
  enriched[symbol] = enrich(daily);
  datasets[symbol] = {
    dailyCount: daily.length,
    firstDaily: daily.length ? iso(daily[0].time) : "",
    lastDaily: daily.length ? iso(daily[daily.length - 1].time) : "",
  };
}

const trades = symbols.flatMap(symbol => backtestSymbol(symbol, enriched[symbol], enriched.BTCUSDT));
trades.sort((a, b) => new Date(a.exitTime) - new Date(b.exitTime));
const bySymbol = Object.fromEntries(symbols.map(symbol => [symbol, trades.filter(t => t.symbol === symbol)]));
const data = {
  generatedAt: new Date().toISOString(),
  profile,
  params,
  source: "Yahoo Finance daily crypto chart API",
  period: { start: iso(start), end: iso(end) },
  symbols,
  summary: summarize(trades, symbols),
  trades,
  bySymbol,
  datasets,
  assumptions: [
    "Source system: NNFX_Crypto_Trend_System.docx.",
    "Timeframe: Daily only. Signals are evaluated on closed daily candles and entered at the next daily open.",
    "Baseline: KAMA50. Long requires close > KAMA50; short requires close < KAMA50.",
    `Optimization profile: ${profile}.`,
    `Bridge Too Far: absolute distance between close and KAMA50 must be <= ${params.bridgeMax} ATR(14).`,
    "SSL Hybrid is approximated with a 10-period SSL channel using SMA(high,10) and SMA(low,10).",
    `TDFI is implemented as a normalized EMA13 directional-force proxy, with thresholds > ${params.tdfi} for long and < -${params.tdfi} for short.`,
    `Better Volume is translated into an objective participation filter: directional candle volume >= ${params.volumeMult}x SMA20 volume, or range-volume >= ${params.rangeVolMult}x its SMA20.`,
    `ATR expansion filter is required: ATR(14) > ${params.atrExpansionMult}x ATR(14) SMA20.`,
    "For SOL and SUI, relative strength filter requires 14-day return greater than BTC 14-day return. BTC is treated as the base asset.",
    `Stop loss is ${params.stopAtr} x ATR(14) from entry. TP1 is ${params.tp1Atr} x ATR(14), closing ${(params.tp1Weight * 100).toFixed(0)}%${params.moveStopToBE ? " and moving stop to breakeven" : " while retaining the initial stop"}.`,
    `Remaining ${(100 - params.tp1Weight * 100).toFixed(0)}% exits on Hull Suite proxy reversal using HMA${params.hull} slope, SSL reversal, stop, or end-of-test mark-to-market.`,
    "Conservative intraday ordering: stop is checked before TP1 when both could occur inside the same daily candle.",
    "Data source is Yahoo Finance daily crypto candles because Binance API requests were reset by the local network during this run.",
    "Results are expressed in R multiples before funding, slippage, borrowing cost, and exchange fees.",
  ],
};

await fs.writeFile(jsonPath, JSON.stringify(data, null, 2));
await buildWorkbook(data);
console.log(JSON.stringify({
  jsonPath,
  xlsxPath,
  totalTrades: trades.length,
  totalR: trades.reduce((s, t) => s + t.rMultiple, 0),
  summary: data.summary,
}, null, 2));
