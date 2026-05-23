import fs from "node:fs/promises";
import path from "node:path";
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const execFileAsync = promisify(execFile);
const sourceJson = "outputs/nxt_v30_rsi_regime_grid_6y/nxt_v30_rsi_regime_grid_6y_results.json";
const outDir = "outputs/nxt_v31_rsi50_6y";
const outJson = path.join(outDir, "nxt_v31_rsi50_6y_results.json");
const outXlsx = path.join(outDir, "NXT_V31_RSI50_6Y_BTC_SOL_SUI_20K.xlsx");
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

function accountRows(trades) {
  const rows = [];
  let equity = startingEquity;
  let peak = startingEquity;
  let maxDrawdownPct = 0;
  for (let i = 0; i < trades.length; i++) {
    const t = trades[i];
    const before = equity;
    const risk = before * riskPct;
    const pnl = risk * t.rMultiple;
    equity += pnl;
    peak = Math.max(peak, equity);
    const dd = equity / peak - 1;
    maxDrawdownPct = Math.min(maxDrawdownPct, dd);
    rows.push([i + 1, new Date(t.exitTime), t.symbol.replace("USDT", ""), t.side, t.rMultiple, before, risk, pnl, equity, dd]);
  }
  return { rows, finalEquity: equity, compoundReturn: equity / startingEquity - 1, maxDrawdownPct };
}

const source = JSON.parse(await fs.readFile(sourceJson, "utf8"));
const selected = source.variants.find(v => v.key === "rsi_50_50");
if (!selected) throw new Error("RSI 50/50 variant not found");

const result = {
  generatedAt: new Date().toISOString(),
  systemVersion: "NXT v3.1",
  versionChange: "Replace Net Volume directional filter with RSI14 regime 50/50: LONG RSI14 > 50, SHORT RSI14 < 50.",
  source: "Binance spot daily klines API",
  period: source.period,
  symbols: source.symbols,
  assumptions: [
    "NXT v3.1 keeps corrected NXT v3.0 entry structure, exit logic, and cost model.",
    "Noise filter is RSI14 regime 50/50: LONG requires RSI14 > 50; SHORT requires RSI14 < 50.",
    "Common entry logic remains SSL 10/10 crossover, EMA20 cross within last 3 candles, and EMA50 distance <= 2 ATR.",
    "Stop loss is 1.5 x ATR(14) from entry.",
    "Corrected exit benchmark uses full-position accounting with the 2.5 ATR exit / breakeven trigger model.",
    "Cost model remains 0.06% fee and 0.05% slippage per side; funding, borrow cost, and taxes are excluded.",
  ],
  stats: selected.stats,
  summary: selected.summary,
  trades: selected.trades,
  bySymbol: Object.fromEntries(source.symbols.map(symbol => [symbol, selected.trades.filter(t => t.symbol === symbol)])),
  datasets: source.datasets,
};

await fs.mkdir(outDir, { recursive: true });
await fs.writeFile(outJson, JSON.stringify(result, null, 2));

const template = await FileBlob.load(templateXlsx);
const workbook = await SpreadsheetFile.importXlsx(template);
const acct = accountRows(result.trades);

const summary = getSheet(workbook, "Summary");
clear(summary, 40, 16);
baseSheet(summary, "NXT v3.1 RSI 50/50 - BTC SOL SUI 6Y", `${result.period.start} to ${result.period.end} | Template: NXT_Backtest_Workbook_Template.xlsx`);
writeMatrix(summary, "A4", [
  ["Metric", "Value"],
  ["System version", "NXT v3.1"],
  ["Total trades", result.stats.trades],
  ["Win rate", result.stats.winRate],
  ["Total R", result.stats.totalR],
  ["Average R / trade", result.stats.avgR],
  ["Max drawdown (R)", result.stats.maxDrawdownR],
  ["Final equity 20K", acct.finalEquity],
  ["Compound return", acct.compoundReturn],
]);
styleHeader(summary, "A4:B4");
fmt(summary, "B7:B7", "0.0%");
fmt(summary, "B8:B10", "0.00");
fmt(summary, "B11:B11", "$#,##0");
fmt(summary, "B12:B12", "0.0%");
writeMatrix(summary, "D4", [["Symbol", "Trades", "Wins", "Losses", "Win Rate", "Total R", "Avg R", "Best R", "Worst R"], ...result.summary.map(r => [
  r.symbol.replace("USDT", ""), r.trades, r.wins, r.losses, r.winRate, r.totalR, r.avgR, r.bestR, r.worstR,
])]);
styleHeader(summary, "D4:L4");
fmt(summary, "H5:H20", "0.0%");
fmt(summary, "I5:L20", "0.00");
finish(summary, "A1:L20");

const tradeHeaders = ["Symbol", "No", "Side", "Signal Time", "Entry Time", "Entry Price", "Initial Stop", "Final Stop", "Risk / Unit", "TP", "TP Time", "TP Ref", "Exit Time", "Exit Price", "Exit Reason", "Gross R", "Cost R", "Net R", "% Move", "TP Hit", "Weekly Regime", "EMA20", "EMA50", "ATR14", "SSL Signal", "Net Volume", "Distance EMA50 ATR", "Notes"];
const tradeToRow = t => [t.symbol.replace("USDT", ""), t.tradeNo, t.side, new Date(t.signalTime), new Date(t.entryTime), t.entryPrice, t.initialStop, t.finalStop, t.riskPerUnit, t.tp1, t.tp1Time ? new Date(t.tp1Time) : "", t.tp2, new Date(t.exitTime), t.exitPrice, t.exitReason, t.grossRMultiple, t.costR, t.rMultiple, t.pctMove, t.tp1Hit, t.weeklyRegime, t.ema20, t.ema50, t.atr14, t.sslAtSignal, t.netVolume, t.distanceToEma50Atr, t.notes ?? ""];

const trades = getSheet(workbook, "Trades");
clear(trades, Math.max(result.trades.length + 10, 220), 28);
baseSheet(trades, "Detailed Trades - NXT v3.1 RSI 50/50", "One completed trade per row.");
writeMatrix(trades, "A4", [tradeHeaders, ...result.trades.map(tradeToRow)]);
styleHeader(trades, "A4:AB4");
const tradeEnd = result.trades.length + 4;
fmt(trades, `D5:E${tradeEnd}`, "yyyy-mm-dd hh:mm");
fmt(trades, `K5:K${tradeEnd}`, "yyyy-mm-dd hh:mm");
fmt(trades, `M5:M${tradeEnd}`, "yyyy-mm-dd hh:mm");
fmt(trades, `F5:N${tradeEnd}`, "0.000000");
fmt(trades, `P5:R${tradeEnd}`, "0.00");
fmt(trades, `S5:S${tradeEnd}`, "0.00%");
finish(trades, `A1:AB${tradeEnd}`);

const accountSheet = getSheet(workbook, "20K Account");
clear(accountSheet, Math.max(acct.rows.length + 10, 220), 10);
baseSheet(accountSheet, "20K Account Sizing - NXT v3.1", "Compounded sequence at 2.0% risk per trade; leverage is not modeled.");
writeMatrix(accountSheet, "A4", [["Trade", "Exit Time", "Symbol", "Side", "Net R", "Equity Before", "Risk USD", "P/L USD", "Equity After", "Drawdown"], ...acct.rows]);
styleHeader(accountSheet, "A4:J4");
const acctEnd = acct.rows.length + 4;
fmt(accountSheet, `B5:B${acctEnd}`, "yyyy-mm-dd hh:mm");
fmt(accountSheet, `E5:E${acctEnd}`, "0.00");
fmt(accountSheet, `F5:I${acctEnd}`, "$#,##0");
fmt(accountSheet, `J5:J${acctEnd}`, "0.0%");
finish(accountSheet, `A1:J${acctEnd}`);

const assumptions = getSheet(workbook, "Assumptions");
clear(assumptions, 40, 2);
baseSheet(assumptions, "Backtest Assumptions", "NXT v3.1 RSI 50/50 using the project workbook template.");
writeMatrix(assumptions, "A4", [["#", "Assumption"], ...result.assumptions.map((text, i) => [i + 1, text])]);
styleHeader(assumptions, "A4:B4");
finish(assumptions, "A1:B20");

const quality = getSheet(workbook, "Data Quality");
clear(quality, 20, 6);
baseSheet(quality, "Data Quality", "Loaded daily crypto candles.");
writeMatrix(quality, "A4", [["Symbol", "Daily Candles", "Weekly Candles", "First Daily", "Last Daily", "Source"], ...Object.entries(result.datasets).map(([symbol, q]) => [
  symbol.replace("USDT", ""), q.dailyCount, q.weeklyCount, new Date(q.firstDaily), new Date(q.lastDaily), q.source,
])]);
styleHeader(quality, "A4:F4");
fmt(quality, "D5:E20", "yyyy-mm-dd");
finish(quality, "A1:F20");

const errors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 300 },
  summary: "formula error scan",
});
console.log(errors.ndjson);

const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outXlsx);
await execFileAsync(
  "C:\\Users\\Admin\\.cache\\codex-runtimes\\codex-primary-runtime\\dependencies\\python\\python.exe",
  ["scripts\\apply_backtest_template_format.py", outXlsx],
  { cwd: process.cwd() },
);
console.log(JSON.stringify({ outJson, outXlsx, stats: result.stats, account: { finalEquity: acct.finalEquity, compoundReturn: acct.compoundReturn, maxDrawdownPct: acct.maxDrawdownPct } }, null, 2));
