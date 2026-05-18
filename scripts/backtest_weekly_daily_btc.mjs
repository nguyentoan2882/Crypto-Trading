import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const symbol = "BTCUSDT";
const displaySymbol = "BTC";
const end = Date.UTC(2026, 4, 13, 0, 0, 0);
const start = Date.UTC(2025, 4, 13, 0, 0, 0);
const warmupStart = Date.UTC(2024, 3, 1, 0, 0, 0);
const outDir = path.resolve("outputs", "weekly_daily_btc_1y");
const jsonPath = path.join(outDir, "weekly_daily_btc_1y_results.json");
const xlsxPath = path.join(outDir, "Weekly_Daily_Position_Trend_BTC_1Y_Backtest.xlsx");

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
    const v = values[i] ?? 0;
    sum += v;
    if (i >= period) sum -= values[i - period] ?? 0;
    if (i >= period - 1 && values.slice(i - period + 1, i + 1).every(x => x !== null && x !== undefined)) {
      out[i] = sum / period;
    }
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

async function fetchKlines(interval, from, to) {
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
  const atr20 = sma(atr14, 20);
  return candles.map((c, i) => ({
    ...c,
    ema20: ema20[i],
    ema50: ema50[i],
    atr14: atr14[i],
    atr20: atr20[i],
    vol20: vol20[i],
  }));
}

function indexLastClosedBefore(candles, time) {
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

function highestHigh(candles, from, to) {
  let value = -Infinity;
  for (let i = Math.max(0, from); i <= to; i++) value = Math.max(value, candles[i].high);
  return value;
}

function lowestLow(candles, from, to) {
  let value = Infinity;
  for (let i = Math.max(0, from); i <= to; i++) value = Math.min(value, candles[i].low);
  return value;
}

function weeklyLongRegime(weekly, i) {
  const w = weekly[i], prev = weekly[i - 3];
  if (!w?.ema20 || !prev?.ema20 || i < 8) return false;
  const hh = highestHigh(weekly, i - 3, i) > highestHigh(weekly, i - 8, i - 4);
  const hl = lowestLow(weekly, i - 3, i) > lowestLow(weekly, i - 8, i - 4);
  return w.close > w.ema20 && w.ema20 > prev.ema20 && hh && hl;
}

function weeklyShortRegime(weekly, i) {
  const w = weekly[i], prev = weekly[i - 3];
  if (!w?.ema20 || !prev?.ema20 || i < 8) return false;
  const lh = highestHigh(weekly, i - 3, i) < highestHigh(weekly, i - 8, i - 4);
  const ll = lowestLow(weekly, i - 3, i) < lowestLow(weekly, i - 8, i - 4);
  return w.close < w.ema20 && w.ema20 < prev.ema20 && lh && ll;
}

function touchesDailyEma(c) {
  const buffer = c.atr14 * 0.15;
  return (
    (c.low <= c.ema20 + buffer && c.high >= c.ema20 - buffer) ||
    (c.low <= c.ema50 + buffer && c.high >= c.ema50 - buffer)
  );
}

function bullishSignal(daily, i) {
  const c = daily[i], p = daily[i - 1];
  const bullishEngulf = c.close > c.open && p.close < p.open && c.close > p.open && c.open <= p.close;
  const reclaim20 = c.low < c.ema20 && c.close > c.ema20 && c.close > c.open;
  const reclaim50 = c.low < c.ema50 && c.close > c.ema50 && c.close > c.open;
  const compressionBreakout = c.close > highestHigh(daily, i - 7, i - 1) && c.volume > c.vol20;
  const failedBreakdown = c.low < swingLow(daily, i - 6, 6) && c.close > daily[i - 1].high;
  return bullishEngulf || reclaim20 || reclaim50 || compressionBreakout || failedBreakdown;
}

function bearishSignal(daily, i) {
  const c = daily[i], p = daily[i - 1];
  const bearishEngulf = c.close < c.open && p.close > p.open && c.close < p.open && c.open >= p.close;
  const reject20 = c.high > c.ema20 && c.close < c.ema20 && c.close < c.open;
  const reject50 = c.high > c.ema50 && c.close < c.ema50 && c.close < c.open;
  const compressionBreakdown = c.close < lowestLow(daily, i - 7, i - 1) && c.volume > c.vol20;
  const failedBreakout = c.high > swingHigh(daily, i - 6, 6) && c.close < daily[i - 1].low;
  return bearishEngulf || reject20 || reject50 || compressionBreakdown || failedBreakout;
}

function classifyPhase(c) {
  const emaSlope = c.ema20 - c.prevEma20;
  const atrExpanding = c.atr14 > c.atr20;
  const volumeIncreasing = c.volume > c.vol20;
  const strongSlope = Math.abs(emaSlope) > c.atr14 * 0.04;
  const compressed = c.atr14 < c.atr20 * 0.85;
  if (compressed || Math.abs(emaSlope) < c.atr14 * 0.015) return "Chop";
  if (strongSlope && atrExpanding && volumeIncreasing) return "Expansion";
  if (emaSlope > 0 && c.ema20 > c.ema50) return "Trend";
  if (atrExpanding && Math.abs(c.close - c.open) < (c.high - c.low) * 0.25) return "Distribution";
  return "Trend";
}

function backtest(daily, weekly) {
  const trades = [];
  let position = null;
  let tradeNo = 1;

  for (let i = 70; i < daily.length; i++) {
    const c = daily[i];
    if (c.closeTime < start || c.closeTime >= end) continue;
    if (!c.ema20 || !c.ema50 || !c.atr14 || !c.atr20 || !c.vol20 || !daily[i - 1]?.ema20) continue;
    c.prevEma20 = daily[i - 1].ema20;

    const wIdx = indexLastClosedBefore(weekly, c.closeTime);
    const w = weekly[wIdx];
    const phase = classifyPhase(c);

    if (position) {
      const side = position.side;
      let exitPrice = null;
      let exitReason = null;
      let openRemainderR = 0;
      const lowerLowBreak = c.low < swingLow(daily, i - 2, 5);
      const lowerHighBreak = c.high > swingHigh(daily, i - 2, 5);
      const weeklyReversal = side === "LONG" ? weeklyShortRegime(weekly, wIdx) : weeklyLongRegime(weekly, wIdx);

      if (side === "LONG") {
        if (c.low <= position.stop) {
          exitPrice = position.stop;
          exitReason = "Initial stop";
          openRemainderR = -1;
        } else if (!position.tp1Done && c.high >= position.tp1) {
          position.tp1Done = true;
          position.realizedR += 0.25;
          position.remaining = 0.75;
          position.notes.push(`TP1 25% at ${iso(c.closeTime)} @ ${position.tp1.toFixed(2)}`);
        }
        if (!position.tp2Done && c.high >= position.tp2) {
          position.tp2Done = true;
          position.realizedR += 0.50;
          position.remaining = 0.50;
          position.notes.push(`TP2 25% at ${iso(c.closeTime)} @ ${position.tp2.toFixed(2)}`);
        }
        if (exitPrice === null && position.tp2Done && (c.close < c.ema20 || lowerLowBreak || weeklyReversal)) {
          exitPrice = c.close;
          exitReason = weeklyReversal ? "Weekly bearish reversal" : c.close < c.ema20 ? "Daily close below EMA20" : "Lower-low structure break";
          openRemainderR = (exitPrice - position.entry) / position.risk;
        }
      } else {
        if (c.high >= position.stop) {
          exitPrice = position.stop;
          exitReason = "Initial stop";
          openRemainderR = -1;
        } else if (!position.tp1Done && c.low <= position.tp1) {
          position.tp1Done = true;
          position.realizedR += 0.25;
          position.remaining = 0.75;
          position.notes.push(`TP1 25% at ${iso(c.closeTime)} @ ${position.tp1.toFixed(2)}`);
        }
        if (!position.tp2Done && c.low <= position.tp2) {
          position.tp2Done = true;
          position.realizedR += 0.50;
          position.remaining = 0.50;
          position.notes.push(`TP2 25% at ${iso(c.closeTime)} @ ${position.tp2.toFixed(2)}`);
        }
        if (exitPrice === null && position.tp2Done && (c.close > c.ema20 || lowerHighBreak || weeklyReversal)) {
          exitPrice = c.close;
          exitReason = weeklyReversal ? "Weekly bullish reversal" : c.close > c.ema20 ? "Daily close above EMA20" : "Higher-high structure break";
          openRemainderR = (position.entry - exitPrice) / position.risk;
        }
      }

      if (exitPrice !== null) {
        const totalR = position.realizedR + position.remaining * openRemainderR;
        trades.push({
          symbol,
          tradeNo: tradeNo++,
          side,
          phase: position.phase,
          riskAllocation: position.riskAllocation,
          entryTime: iso(position.entryTime),
          entryPrice: position.entry,
          stopInitial: position.stop,
          riskPerUnit: position.risk,
          tp1: position.tp1,
          tp2: position.tp2,
          exitTime: iso(c.closeTime),
          exitPrice,
          exitReason,
          rMultiple: totalR,
          pctMove: side === "LONG" ? exitPrice / position.entry - 1 : position.entry / exitPrice - 1,
          setup: position.setup,
          weeklyRegime: position.weeklyRegime,
          dailyTrend: position.dailyTrend,
          atrExpansion: position.atrExpansion,
          volumeConfirmation: position.volumeConfirmation,
          notes: position.notes.join("; "),
        });
        position = null;
      }
      continue;
    }

    if (phase === "Chop" || !w) continue;
    const volumeOk = c.volume > c.vol20;
    const atrExpansion = c.atr14 > c.atr20;
    const notExtendedLong = c.close <= c.ema20 + 2 * c.atr14;
    const notExtendedShort = c.close >= c.ema20 - 2 * c.atr14;
    const dailyLong = c.ema20 > c.ema50 && c.close > c.ema20;
    const dailyShort = c.ema20 < c.ema50 && c.close < c.ema20;

    if (weeklyLongRegime(weekly, wIdx) && dailyLong && atrExpansion && volumeOk && touchesDailyEma(c) && notExtendedLong && bullishSignal(daily, i)) {
      const entry = c.close;
      const structureStop = swingLow(daily, i - 1, 10);
      const atrStop = entry - 1.5 * c.atr14;
      const stop = Math.min(structureStop, atrStop);
      const risk = entry - stop;
      if (risk <= 0) continue;
      position = {
        side: "LONG",
        phase,
        riskAllocation: phase === "Expansion" ? "1.0%" : "0.5%",
        entryTime: c.closeTime,
        entry,
        stop,
        risk,
        tp1: entry + risk,
        tp2: entry + 2 * risk,
        tp1Done: false,
        tp2Done: false,
        remaining: 1,
        realizedR: 0,
        setup: "Daily EMA20/EMA50 pullback + bullish daily confirmation",
        weeklyRegime: `Bullish: close ${w.close.toFixed(2)} > W EMA20 ${w.ema20.toFixed(2)} with HH-HL structure`,
        dailyTrend: `EMA20 ${c.ema20.toFixed(2)} > EMA50 ${c.ema50.toFixed(2)}`,
        atrExpansion: `${c.atr14.toFixed(2)} > ATR20 ${c.atr20.toFixed(2)}`,
        volumeConfirmation: `${c.volume.toFixed(2)} > Vol20 ${c.vol20.toFixed(2)}`,
        notes: [],
      };
    } else if (weeklyShortRegime(weekly, wIdx) && dailyShort && atrExpansion && volumeOk && touchesDailyEma(c) && notExtendedShort && bearishSignal(daily, i)) {
      const entry = c.close;
      const structureStop = swingHigh(daily, i - 1, 10);
      const atrStop = entry + 1.5 * c.atr14;
      const stop = Math.max(structureStop, atrStop);
      const risk = stop - entry;
      if (risk <= 0) continue;
      position = {
        side: "SHORT",
        phase,
        riskAllocation: phase === "Expansion" ? "1.0%" : "0.5%",
        entryTime: c.closeTime,
        entry,
        stop,
        risk,
        tp1: entry - risk,
        tp2: entry - 2 * risk,
        tp1Done: false,
        tp2Done: false,
        remaining: 1,
        realizedR: 0,
        setup: "Daily EMA20/EMA50 relief rally + bearish daily confirmation",
        weeklyRegime: `Bearish: close ${w.close.toFixed(2)} < W EMA20 ${w.ema20.toFixed(2)} with LH-LL structure`,
        dailyTrend: `EMA20 ${c.ema20.toFixed(2)} < EMA50 ${c.ema50.toFixed(2)}`,
        atrExpansion: `${c.atr14.toFixed(2)} > ATR20 ${c.atr20.toFixed(2)}`,
        volumeConfirmation: `${c.volume.toFixed(2)} > Vol20 ${c.vol20.toFixed(2)}`,
        notes: ["Funding/open interest unavailable from spot kline source; short filter approximated with BTC bearish regime + weak structure."],
      };
    }
  }
  return trades;
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
  const startColNum = match[1].charCodeAt(0) - 64;
  const startRow = Number(match[2]);
  const endCol = colName(startColNum + rows[0].length - 1);
  const endRow = startRow + rows.length - 1;
  sheet.getRange(`${startCell}:${endCol}${endRow}`).values = rows;
}

function styleHeader(sheet, range) {
  sheet.getRange(range).format = {
    fill: "#173B4F",
    font: { color: "#FFFFFF", bold: true },
    horizontalAlignment: "center",
    verticalAlignment: "center",
    wrapText: true,
  };
}

function baseSheet(sheet, title, subtitle) {
  sheet.getRange("A1").values = [[title]];
  sheet.getRange("A1").format = { font: { bold: true, size: 18, color: "#173B4F" } };
  sheet.getRange("A2").values = [[subtitle]];
  sheet.getRange("A2").format = { font: { italic: true, color: "#4B5563" } };
}

function numberFormat(sheet, range, format) {
  sheet.getRange(range).format.numberFormat = format;
}

function finishSheet(sheet, range) {
  sheet.getRange(range).format.autofitColumns();
  sheet.getRange(range).format.autofitRows();
}

async function buildWorkbook(data) {
  const workbook = Workbook.create();
  const trades = data.trades;
  const totalR = trades.reduce((s, t) => s + t.rMultiple, 0);
  const wins = trades.filter(t => t.rMultiple > 0).length;
  let cumulative = 0;
  let peak = 0;
  let maxDrawdownR = 0;
  for (const t of trades) {
    cumulative += t.rMultiple;
    peak = Math.max(peak, cumulative);
    maxDrawdownR = Math.min(maxDrawdownR, cumulative - peak);
  }

  const summary = workbook.worksheets.add("Summary");
  baseSheet(summary, "Weekly-Daily Position Trend System - BTC 1Y Backtest", `${data.period.start} to ${data.period.end} | Source: ${data.source}`);
  const kpis = [
    ["Metric", "Value"],
    ["Symbol", displaySymbol],
    ["Completed trades", trades.length],
    ["Win rate", trades.length ? wins / trades.length : 0],
    ["Total R", totalR],
    ["Average R / trade", trades.length ? totalR / trades.length : 0],
    ["Best trade (R)", trades.length ? Math.max(...trades.map(t => t.rMultiple)) : 0],
    ["Worst trade (R)", trades.length ? Math.min(...trades.map(t => t.rMultiple)) : 0],
    ["Max drawdown (R)", maxDrawdownR],
  ];
  writeMatrix(summary, "A4", kpis);
  styleHeader(summary, "A4:B4");
  numberFormat(summary, "B7:B7", "0.0%");
  numberFormat(summary, "B8:B12", "0.00");
  summary.getRange("A4:B12").format.borders = { preset: "inside", style: "thin", color: "#D7DEE8" };
  summary.getRange("A4:B12").format.borders = { preset: "outside", style: "thin", color: "#9CA3AF" };

  const bySideRows = [["Side", "Trades", "Wins", "Win Rate", "Total R", "Avg R"]];
  for (const side of ["LONG", "SHORT"]) {
    const rows = trades.filter(t => t.side === side);
    const sideWins = rows.filter(t => t.rMultiple > 0).length;
    const sideR = rows.reduce((s, t) => s + t.rMultiple, 0);
    bySideRows.push([side, rows.length, sideWins, rows.length ? sideWins / rows.length : 0, sideR, rows.length ? sideR / rows.length : 0]);
  }
  writeMatrix(summary, "D4", bySideRows);
  styleHeader(summary, "D4:I4");
  numberFormat(summary, "G5:G6", "0.0%");
  numberFormat(summary, "H5:I6", "0.00");
  summary.freezePanes.freezeRows(4);
  finishSheet(summary, "A1:I12");

  const headers = [
    "Symbol", "No", "Side", "Phase", "Risk Allocation", "Entry Time", "Entry Price", "Initial Stop",
    "Risk / Unit", "TP1", "TP2", "Exit Time", "Exit Price", "Exit Reason", "R Multiple", "% Move",
    "Setup", "Weekly Regime", "Daily Trend", "ATR Expansion", "Volume Confirmation", "Notes",
  ];
  const toRow = t => [
    displaySymbol, t.tradeNo, t.side, t.phase, t.riskAllocation, new Date(t.entryTime), t.entryPrice, t.stopInitial,
    t.riskPerUnit, t.tp1, t.tp2, new Date(t.exitTime), t.exitPrice, t.exitReason, t.rMultiple, t.pctMove,
    t.setup, t.weeklyRegime, t.dailyTrend, t.atrExpansion, t.volumeConfirmation, t.notes,
  ];

  const tradesSheet = workbook.worksheets.add("Trade Detail");
  baseSheet(tradesSheet, "Trade Detail", "Entry/exit list from Daily signals under confirmed Weekly regime.");
  writeMatrix(tradesSheet, "A4", [headers, ...trades.map(toRow)]);
  styleHeader(tradesSheet, "A4:V4");
  const lastTradeRow = Math.max(trades.length + 4, 5);
  numberFormat(tradesSheet, `F5:F${lastTradeRow}`, "yyyy-mm-dd");
  numberFormat(tradesSheet, `L5:L${lastTradeRow}`, "yyyy-mm-dd");
  numberFormat(tradesSheet, `G5:M${lastTradeRow}`, "0.00");
  numberFormat(tradesSheet, `O5:O${lastTradeRow}`, "0.00");
  numberFormat(tradesSheet, `P5:P${lastTradeRow}`, "0.00%");
  tradesSheet.getRange(`A4:V${lastTradeRow}`).format.wrapText = true;
  tradesSheet.getRange(`A4:V${lastTradeRow}`).format.borders = { preset: "inside", style: "thin", color: "#E5E7EB" };
  tradesSheet.freezePanes.freezeRows(4);
  finishSheet(tradesSheet, `A1:V${lastTradeRow}`);

  const curveSheet = workbook.worksheets.add("Equity Curve");
  baseSheet(curveSheet, "Equity Curve in R", "Sequential closed trades; R is weighted by 25%/25%/50% scaling model.");
  const curveRows = [["Trade", "Exit Time", "Side", "R", "Cumulative R"]];
  let running = 0;
  trades.forEach((t, i) => {
    running += t.rMultiple;
    curveRows.push([i + 1, new Date(t.exitTime), t.side, t.rMultiple, running]);
  });
  writeMatrix(curveSheet, "A4", curveRows);
  styleHeader(curveSheet, "A4:E4");
  numberFormat(curveSheet, `B5:B${Math.max(curveRows.length + 3, 5)}`, "yyyy-mm-dd");
  numberFormat(curveSheet, `D5:E${Math.max(curveRows.length + 3, 5)}`, "0.00");
  curveSheet.freezePanes.freezeRows(4);
  if (trades.length) {
    curveSheet.charts.add("line", {
      title: "Cumulative R",
      categories: trades.map((_, i) => String(i + 1)),
      series: [{ name: "Cumulative R", values: curveRows.slice(1).map(r => r[4]), line: { fill: "#173B4F", style: "solid", width: 2 } }],
      from: { row: 4, col: 7 },
      extent: { widthPx: 720, heightPx: 360 },
      hasLegend: false,
    });
  }
  finishSheet(curveSheet, `A1:E${Math.max(curveRows.length + 3, 5)}`);

  const assumptions = workbook.worksheets.add("Assumptions");
  baseSheet(assumptions, "Backtest Assumptions", "Objective translation of the discretionary rules in Weekly_Daily_Position_Trend_System.docx.");
  writeMatrix(assumptions, "A4", [["#", "Assumption"], ...data.assumptions.map((a, i) => [i + 1, a])]);
  styleHeader(assumptions, "A4:B4");
  assumptions.getRange(`A4:B${data.assumptions.length + 4}`).format.wrapText = true;
  assumptions.getRange(`A4:B${data.assumptions.length + 4}`).format.borders = { preset: "inside", style: "thin", color: "#E5E7EB" };
  finishSheet(assumptions, `A1:B${data.assumptions.length + 4}`);

  const quality = workbook.worksheets.add("Data Quality");
  baseSheet(quality, "Data Quality", "Loaded candle counts and usable ranges.");
  writeMatrix(quality, "A4", [
    ["Dataset", "Candles", "First Candle", "Last Candle"],
    ["Daily", data.datasets.dailyCount, data.datasets.firstDaily, data.datasets.lastDaily],
    ["Weekly", data.datasets.weeklyCount, data.datasets.firstWeekly, data.datasets.lastWeekly],
  ]);
  styleHeader(quality, "A4:D4");
  finishSheet(quality, "A1:D6");

  const scan = await workbook.inspect({
    kind: "match",
    searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
    options: { useRegex: true, maxResults: 100 },
    summary: "formula error scan",
  });
  console.log(scan.ndjson);
  const preview = await workbook.inspect({
    kind: "table",
    range: "Summary!A1:I12",
    include: "values,formulas",
    tableMaxRows: 15,
    tableMaxCols: 10,
  });
  console.log(preview.ndjson);

  const output = await SpreadsheetFile.exportXlsx(workbook);
  await output.save(xlsxPath);
}

const [dailyRaw, weeklyRaw] = await Promise.all([
  fetchKlines("1d", warmupStart, end),
  fetchKlines("1w", warmupStart, end),
]);
const daily = enrich(dailyRaw);
const weekly = enrich(weeklyRaw);
const trades = backtest(daily, weekly);
trades.sort((a, b) => a.entryTime.localeCompare(b.entryTime));

const data = {
  generatedAt: iso(Date.now()),
  source: "Binance spot klines API",
  period: { start: iso(start), end: iso(end - 1) },
  symbol,
  datasets: {
    dailyCount: daily.length,
    weeklyCount: weekly.length,
    firstDaily: daily[0] ? iso(daily[0].time) : null,
    lastDaily: daily[daily.length - 1] ? iso(daily[daily.length - 1].time) : null,
    firstWeekly: weekly[0] ? iso(weekly[0].time) : null,
    lastWeekly: weekly[weekly.length - 1] ? iso(weekly[weekly.length - 1].time) : null,
  },
  assumptions: [
    "Backtest period uses closed daily candles from 2025-05-13 through 2026-05-12 UTC, matching the current date 2026-05-13 in Asia/Saigon.",
    "Symbol: BTCUSDT spot OHLCV from Binance. Relative strength filter is neutral because BTC is the benchmark asset.",
    "Weekly long regime: weekly close above EMA20, EMA20 higher than three weeks earlier, and recent 4-week high/low structure above the prior 4-week structure.",
    "Weekly short regime: weekly close below EMA20, EMA20 lower than three weeks earlier, and recent 4-week high/low structure below the prior 4-week structure.",
    "Daily long condition: EMA20 above EMA50 and daily close above EMA20. Daily short condition is the inverse.",
    "Healthy pullback or relief rally: the signal day's range overlaps Daily EMA20 or EMA50 with a 0.15 ATR buffer.",
    "ATR expansion active: Daily ATR14 above its 20-day average. Volume confirms continuation when daily volume is above its 20-day average.",
    "Entry signal can be engulfing candle, EMA reclaim/rejection, compression breakout/breakdown, or failed breakdown/breakout reclaim on Daily candles.",
    "No-trade/chop: EMA20 slope is flat or ATR is compressed versus its 20-day average. Entries more than 2 ATR from EMA20 are skipped.",
    "Initial stop: below Daily swing low or 1.5 ATR for longs, above Daily swing high or 1.5 ATR for shorts, using the wider stop.",
    "Exit model: 25% at 1R, 25% at 2R, remaining 50% trails until Daily trend break: EMA20 close break, market-structure break, or weekly reversal.",
    "If stop and target occur in the same daily candle, stop-first conservative execution is used.",
    "Funding/open-interest inputs from the short-system section are not available in spot kline data, so short entries use bearish BTC regime and weak structure as the objective proxy.",
  ],
  trades,
};

await fs.mkdir(outDir, { recursive: true });
await fs.writeFile(jsonPath, JSON.stringify(data, null, 2));
await buildWorkbook(data);
console.log(`Saved ${jsonPath}`);
console.log(`Saved ${xlsxPath}`);
console.log(`Trades: ${trades.length}`);
