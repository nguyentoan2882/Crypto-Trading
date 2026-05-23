import fs from "node:fs/promises";
import path from "node:path";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const inputJson = "outputs/nxt_v30_rsi_regime_grid_6y/nxt_v30_rsi_regime_grid_6y_results.json";
const outputXlsx = "outputs/nxt_v30_rsi_regime_grid_6y/NXT_V30_RSI_Regime_Grid_6Y_BTC_SOL_SUI.xlsx";
const templateXlsx = "templates/NXT_Backtest_Workbook_Template.xlsx";
const startingEquity = 20000;
const riskPct = 0.02;

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

function clear(sheet, rows, cols) {
  writeMatrix(sheet, "A1", Array.from({ length: rows }, () => Array(cols).fill("")));
}

function getSheet(workbook, name) {
  return workbook.worksheets.items.find(s => s.name === name) ?? workbook.worksheets.add(name);
}

function baseSheet(sheet, title, subtitle) {
  sheet.getRange("A1").values = [[title]];
  sheet.getRange("A1").format = { font: { bold: true, size: 18, color: "#17324D" } };
  sheet.getRange("A2").values = [[subtitle]];
  sheet.getRange("A2").format = { font: { italic: true, color: "#4B5563" } };
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

function fmt(sheet, range, format) {
  sheet.getRange(range).format.numberFormat = format;
}

function finish(sheet, range) {
  sheet.getRange(range).format.wrapText = true;
  sheet.getRange(range).format.autofitColumns();
  sheet.getRange(range).format.autofitRows();
}

function accountStats(trades) {
  let equity = startingEquity;
  let peak = startingEquity;
  let maxDrawdownPct = 0;
  for (const t of trades) {
    equity += equity * riskPct * t.rMultiple;
    peak = Math.max(peak, equity);
    maxDrawdownPct = Math.min(maxDrawdownPct, equity / peak - 1);
  }
  return { finalEquity: equity, compoundReturn: equity / startingEquity - 1, maxDrawdownPct };
}

const data = JSON.parse(await fs.readFile(inputJson, "utf8"));
const template = await FileBlob.load(templateXlsx);
const workbook = await SpreadsheetFile.importXlsx(template);
const best = data.variants.find(v => v.key === data.bestVariantKey);
const ranking = data.ranking.map(r => {
  const v = data.variants.find(x => x.key === r.key);
  return { ...r, account: accountStats(v.trades) };
});

const summary = getSheet(workbook, "Summary");
clear(summary, 40, 18);
baseSheet(summary, "NXT v3.0 RSI Regime Grid - BTC SOL SUI 6Y", `${data.period.start} to ${data.period.end} | Best: ${best.name} | Template: NXT_Backtest_Workbook_Template.xlsx`);
writeMatrix(summary, "A4", [
  ["Metric", "Value"],
  ["Best filter", best.name],
  ["Best Total R", best.stats.totalR],
  ["Best Win Rate", best.stats.winRate],
  ["Best Max DD (R)", best.stats.maxDrawdownR],
  ["Best Final Equity 20K", accountStats(best.trades).finalEquity],
]);
styleHeader(summary, "A4:B4");
fmt(summary, "B6:B6", "0.00");
fmt(summary, "B7:B7", "0.0%");
fmt(summary, "B8:B8", "0.00");
fmt(summary, "B9:B9", "$#,##0");
writeMatrix(summary, "D4", [[
  "Rank", "Filter", "Description", "Trades", "Win Rate", "Total R", "Avg R", "Max DD R", "Final Equity", "BTC R", "SOL R", "SUI R",
], ...ranking.map((r, i) => [
  i + 1, r.name, r.description, r.trades, r.winRate, r.totalR, r.avgR, r.maxDrawdownR, r.account.finalEquity,
  r.summary.find(s => s.symbol === "BTCUSDT")?.totalR ?? 0,
  r.summary.find(s => s.symbol === "SOLUSDT")?.totalR ?? 0,
  r.summary.find(s => s.symbol === "SUIUSDT")?.totalR ?? 0,
])]);
styleHeader(summary, "D4:O4");
fmt(summary, "H5:H20", "0.0%");
fmt(summary, "I5:O20", "0.00");
fmt(summary, "L5:L20", "$#,##0");
finish(summary, "A1:O20");

const grid = getSheet(workbook, "RSI Grid");
clear(grid, 40, 14);
baseSheet(grid, "RSI Regime Grid Detail", "All variants keep corrected NXT v3.0 exit and vary only RSI14 long/short thresholds.");
writeMatrix(grid, "A4", [[
  "Filter", "Description", "Trades", "Wins", "Losses", "Win Rate", "TP Hit Rate", "Total R", "Avg R", "Max DD R", "Best R", "Worst R", "Final Equity", "Return",
], ...ranking.map(r => [
  r.name, r.description, r.trades, r.wins, r.losses, r.winRate, r.tp1HitRate, r.totalR, r.avgR, r.maxDrawdownR, r.bestR, r.worstR, r.account.finalEquity, r.account.compoundReturn,
])]);
styleHeader(grid, "A4:N4");
fmt(grid, "F5:G20", "0.0%");
fmt(grid, "H5:L20", "0.00");
fmt(grid, "M5:M20", "$#,##0");
fmt(grid, "N5:N20", "0.0%");
finish(grid, "A1:N20");

const tradeHeaders = ["Symbol", "No", "Side", "Signal Time", "Entry Time", "Entry Price", "Initial Stop", "Final Stop", "Risk / Unit", "TP", "TP Time", "TP Ref", "Exit Time", "Exit Price", "Exit Reason", "Gross R", "Cost R", "Net R", "% Move", "TP Hit", "Weekly Regime", "EMA20", "EMA50", "ATR14", "SSL Signal", "Net Volume", "Distance EMA50 ATR", "Notes"];
const tradeToRow = t => [t.symbol.replace("USDT", ""), t.tradeNo, t.side, new Date(t.signalTime), new Date(t.entryTime), t.entryPrice, t.initialStop, t.finalStop, t.riskPerUnit, t.tp1, t.tp1Time ? new Date(t.tp1Time) : "", t.tp2, new Date(t.exitTime), t.exitPrice, t.exitReason, t.grossRMultiple, t.costR, t.rMultiple, t.pctMove, t.tp1Hit, t.weeklyRegime, t.ema20, t.ema50, t.atr14, t.sslAtSignal, t.netVolume, t.distanceToEma50Atr, t.notes ?? ""];
const trades = getSheet(workbook, "Trades");
clear(trades, Math.max(best.trades.length + 10, 220), 28);
baseSheet(trades, `Detailed Trades - ${best.name}`, "One completed trade per row for the best noise filter.");
writeMatrix(trades, "A4", [tradeHeaders, ...best.trades.map(tradeToRow)]);
styleHeader(trades, "A4:AB4");
const tradeEnd = best.trades.length + 4;
fmt(trades, `D5:E${tradeEnd}`, "yyyy-mm-dd hh:mm");
fmt(trades, `K5:K${tradeEnd}`, "yyyy-mm-dd hh:mm");
fmt(trades, `M5:M${tradeEnd}`, "yyyy-mm-dd hh:mm");
fmt(trades, `F5:N${tradeEnd}`, "0.000000");
fmt(trades, `P5:R${tradeEnd}`, "0.00");
fmt(trades, `S5:S${tradeEnd}`, "0.00%");
finish(trades, `A1:AB${tradeEnd}`);

const assumptions = getSheet(workbook, "Assumptions");
clear(assumptions, 40, 2);
baseSheet(assumptions, "Backtest Assumptions", "RSI regime grid using the project workbook template.");
writeMatrix(assumptions, "A4", [["#", "Assumption"], ...[
  "Only RSI14 long/short thresholds change between variants.",
  "Common entry logic remains SSL crossover, EMA20 cross within last 3 candles, and EMA50 distance <= 2 ATR.",
  "Corrected NXT v3.0 exit and cost model are preserved.",
  "Tested threshold pairs: 50/50, 52/48, 55/45, 58/42, and 60/40.",
  "All data came from Binance spot daily klines API.",
].map((text, i) => [i + 1, text])]);
styleHeader(assumptions, "A4:B4");
finish(assumptions, "A1:B20");

const errors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 300 },
  summary: "formula error scan",
});
console.log(errors.ndjson);

await fs.mkdir(path.dirname(outputXlsx), { recursive: true });
const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputXlsx);
console.log(outputXlsx);
