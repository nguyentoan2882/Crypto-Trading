import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const variant = process.argv[2] || "";
const inputPath = path.resolve("outputs", variant ? `htf_pullback_backtest_results_${variant}.json` : "htf_pullback_backtest_results.json");
const outputDir = path.resolve("outputs", variant ? `htf_pullback_backtest_${variant}` : "htf_pullback_backtest");
const outputPath = path.join(outputDir, variant ? `HTF_Trend_Pullback_Backtest_6M_${variant.toUpperCase()}.xlsx` : "HTF_Trend_Pullback_Backtest_6M.xlsx");
const data = JSON.parse(await fs.readFile(inputPath, "utf8"));

const workbook = Workbook.create();

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
  const endCol = colName(startCol.charCodeAt(0) - 64 + rows[0].length - 1);
  const endRow = startRow + rows.length - 1;
  sheet.getRange(`${startCell}:${endCol}${endRow}`).values = rows;
}

function styleHeader(sheet, range) {
  const r = sheet.getRange(range);
  r.format = {
    fill: "#153E5C",
    font: { color: "#FFFFFF", bold: true },
    horizontalAlignment: "center",
    verticalAlignment: "center",
    wrapText: true,
  };
}

function baseSheet(sheet, title, subtitle) {
  sheet.getRange("A1").values = [[title]];
  sheet.getRange("A1").format = { font: { bold: true, size: 18, color: "#153E5C" } };
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

const dashboard = workbook.worksheets.add("Summary");
baseSheet(dashboard, "HTF Trend Pullback System v1 - 6M Backtest", `${data.period.start} to ${data.period.end} | Source: ${data.source}`);
const kpiRows = [
  ["Metric", "Value"],
  ["Total trades", totalTrades],
  ["Win rate", totalTrades ? wins / totalTrades : 0],
  ["Total R", totalR],
  ["Average R / trade", totalTrades ? totalR / totalTrades : 0],
  ["Max drawdown (R)", maxDrawdownR],
  ["Best trade (R)", totalTrades ? Math.max(...data.trades.map(t => t.rMultiple)) : 0],
  ["Worst trade (R)", totalTrades ? Math.min(...data.trades.map(t => t.rMultiple)) : 0],
];
writeMatrix(dashboard, "A4", kpiRows);
styleHeader(dashboard, "A4:B4");
numberFormat(dashboard, "B6:B6", "0.0%");
numberFormat(dashboard, "B7:B11", "0.00");

const summaryHeaders = ["Symbol", "Trades", "Wins", "Losses", "Win Rate", "Total R", "Avg R", "Best R", "Worst R"];
const summaryRows = data.summary.map(r => [
  r.symbol, r.trades, r.wins, r.losses, r.winRate, r.totalR, r.avgR, r.bestR, r.worstR,
]);
writeMatrix(dashboard, "D4", [summaryHeaders, ...summaryRows]);
styleHeader(dashboard, "D4:L4");
numberFormat(dashboard, "H5:L20", "0.00");
numberFormat(dashboard, "H5:H20", "0.0%");
dashboard.getRange("A4:L12").format.borders = { preset: "inside", style: "thin", color: "#D7DEE8" };
dashboard.getRange("A4:L12").format.borders = { preset: "outside", style: "thin", color: "#9CA3AF" };
dashboard.freezePanes.freezeRows(4);
dashboard.charts.add("bar", {
  title: "Total R by Symbol",
  categories: data.summary.map(r => r.symbol),
  series: [{ name: "Total R", values: data.summary.map(r => r.totalR), fill: { type: "solid", color: "#2F80ED" } }],
  from: { row: 14, col: 0 },
  extent: { widthPx: 560, heightPx: 300 },
  hasLegend: false,
  yAxis: { majorGridlines: { fill: "#E5E7EB", style: "solid", width: 1 } },
});
dashboard.charts.add("bar", {
  title: "Trade Count by Symbol",
  categories: data.summary.map(r => r.symbol),
  series: [{ name: "Trades", values: data.summary.map(r => r.trades), fill: { type: "solid", color: "#10B981" } }],
  from: { row: 14, col: 7 },
  extent: { widthPx: 520, heightPx: 300 },
  hasLegend: false,
});
finishSheet(dashboard, "A1:L12");

const tradeHeaders = [
  "Symbol", "No", "Side", "Entry Time", "Entry Price", "Initial Stop", "Risk / Unit", "TP1", "TP2",
  "Exit Time", "Exit Price", "Exit Reason", "R Multiple", "% Move", "Setup", "Weekly Regime", "Daily Trend", "Notes",
];
function tradeToRow(t) {
  return [
    t.symbol.replace("USDT", ""), t.tradeNo, t.side, new Date(t.entryTime), t.entryPrice, t.stopInitial, t.riskPerUnit,
    t.tp1, t.tp2, new Date(t.exitTime), t.exitPrice, t.exitReason, t.rMultiple, t.pctMove,
    t.setup, t.weeklyRegime, t.dailyTrend, t.notes,
  ];
}

const tradesSheet = workbook.worksheets.add("Trades");
baseSheet(tradesSheet, "Detailed Trades", "One row per completed trade. R assumes 50% TP1 then 50% TP2/trailing logic.");
writeMatrix(tradesSheet, "A4", [tradeHeaders, ...data.trades.map(tradeToRow)]);
styleHeader(tradesSheet, `A4:R4`);
tradesSheet.freezePanes.freezeRows(4);
numberFormat(tradesSheet, `E5:K${data.trades.length + 4}`, "0.000000");
numberFormat(tradesSheet, `D5:D${data.trades.length + 4}`, "yyyy-mm-dd hh:mm");
numberFormat(tradesSheet, `J5:J${data.trades.length + 4}`, "yyyy-mm-dd hh:mm");
numberFormat(tradesSheet, `M5:M${data.trades.length + 4}`, "0.00");
numberFormat(tradesSheet, `N5:N${data.trades.length + 4}`, "0.00%");
tradesSheet.getRange(`A4:R${data.trades.length + 4}`).format.borders = { preset: "inside", style: "thin", color: "#E5E7EB" };
tradesSheet.getRange(`A4:R${data.trades.length + 4}`).format.wrapText = true;
finishSheet(tradesSheet, `A1:R${data.trades.length + 4}`);

const curveSheet = workbook.worksheets.add("Equity Curve");
baseSheet(curveSheet, "Equity Curve in R", "Cumulative R, assuming sequential closed trades and no portfolio exposure cap.");
const curveRows = [["Trade", "Exit Time", "Symbol", "Side", "R", "Cumulative R"]];
let runningR = 0;
data.trades.forEach((t, i) => {
  runningR += t.rMultiple;
  curveRows.push([i + 1, new Date(t.exitTime), t.symbol.replace("USDT", ""), t.side, t.rMultiple, runningR]);
});
writeMatrix(curveSheet, "A4", curveRows);
styleHeader(curveSheet, "A4:F4");
numberFormat(curveSheet, `E5:F${curveRows.length + 3}`, "0.00");
numberFormat(curveSheet, `B5:B${curveRows.length + 3}`, "yyyy-mm-dd hh:mm");
curveSheet.freezePanes.freezeRows(4);
curveSheet.charts.add("line", {
  title: "Cumulative R",
  categories: data.trades.map((_, i) => String(i + 1)),
  series: [{ name: "Cumulative R", values: curveRows.slice(1).map(r => r[5]), line: { fill: "#153E5C", style: "solid", width: 2 } }],
  from: { row: 4, col: 7 },
  extent: { widthPx: 720, heightPx: 360 },
  hasLegend: false,
  yAxis: { majorGridlines: { fill: "#E5E7EB", style: "solid", width: 1 } },
});
finishSheet(curveSheet, `A1:F${curveRows.length + 3}`);

const assumptions = workbook.worksheets.add("Assumptions");
baseSheet(assumptions, "Backtest Assumptions", "The DOCX rules are discretionary, so these objective translations were used.");
writeMatrix(assumptions, "A4", [["#", "Assumption"], ...data.assumptions.map((a, i) => [i + 1, a])]);
styleHeader(assumptions, "A4:B4");
assumptions.getRange(`A4:B${data.assumptions.length + 4}`).format.wrapText = true;
finishSheet(assumptions, `A1:B${data.assumptions.length + 4}`);

const dataQuality = workbook.worksheets.add("Data Quality");
baseSheet(dataQuality, "Data Quality", "Candle counts and loaded ranges from Binance spot klines.");
const qualityRows = [["Symbol", "H4 Candles", "Daily Candles", "Weekly Candles", "First H4", "Last H4"]];
for (const [symbol, q] of Object.entries(data.datasets)) {
  qualityRows.push([symbol.replace("USDT", ""), q.h4Count, q.dailyCount, q.weeklyCount, q.firstH4, q.lastH4]);
}
writeMatrix(dataQuality, "A4", qualityRows);
styleHeader(dataQuality, "A4:F4");
finishSheet(dataQuality, `A1:F${qualityRows.length + 3}`);

for (const symbol of Object.keys(data.bySymbol)) {
  const sheet = workbook.worksheets.add(symbol);
  baseSheet(sheet, `${symbol} Trades`, "Filtered trade detail for this symbol.");
  const rows = data.bySymbol[symbol].map(tradeToRow);
  writeMatrix(sheet, "A4", [tradeHeaders, ...rows]);
  styleHeader(sheet, "A4:R4");
  sheet.freezePanes.freezeRows(4);
  if (rows.length) {
    numberFormat(sheet, `E5:K${rows.length + 4}`, "0.000000");
    numberFormat(sheet, `D5:D${rows.length + 4}`, "yyyy-mm-dd hh:mm");
    numberFormat(sheet, `J5:J${rows.length + 4}`, "yyyy-mm-dd hh:mm");
    numberFormat(sheet, `M5:M${rows.length + 4}`, "0.00");
    numberFormat(sheet, `N5:N${rows.length + 4}`, "0.00%");
    sheet.getRange(`A4:R${rows.length + 4}`).format.borders = { preset: "inside", style: "thin", color: "#E5E7EB" };
  }
  sheet.getRange(`A4:R${Math.max(rows.length + 4, 5)}`).format.wrapText = true;
  finishSheet(sheet, `A1:R${Math.max(rows.length + 4, 5)}`);
}

const errorScan = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 300 },
  summary: "formula error scan",
});
console.log(errorScan.ndjson);

const dashboardPreview = await workbook.inspect({
  kind: "table",
  range: "Summary!A1:L12",
  include: "values,formulas",
  tableMaxRows: 20,
  tableMaxCols: 12,
});
console.log(dashboardPreview.ndjson);

await fs.mkdir(outputDir, { recursive: true });
const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);
console.log(`Saved ${outputPath}`);
