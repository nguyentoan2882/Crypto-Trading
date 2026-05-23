import path from "node:path";
import fs from "node:fs/promises";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const inputJson = "outputs/nxt_crypto_btc_sol_sui_6y_v30_correct_no_volume/nxt_v30_correct_no_volume_6y_results.json";
const outputXlsx = "outputs/nxt_crypto_btc_sol_sui_6y_v30_correct_no_volume/NXT_V30_Correct_No_Volume_6Y_BTC_SOL_SUI_20K.xlsx";
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

function getSheet(workbook, name) {
  return workbook.worksheets.items.find(s => s.name === name) ?? workbook.worksheets.add(name);
}

const data = JSON.parse(await fs.readFile(inputJson, "utf8"));
const file = await FileBlob.load(templateXlsx);
const workbook = await SpreadsheetFile.importXlsx(file);

const summary = getSheet(workbook, "Summary");
clear(summary, 40, 16);
baseSheet(summary, "NXT v3.0 Correct No Volume - BTC SOL SUI 6Y", `${data.period.start} to ${data.period.end} | Net Volume filter disabled | Corrected accounting`);
writeMatrix(summary, "A4", [
  ["Metric", "Value"],
  ["Total trades", data.stats.trades],
  ["Win rate", data.stats.winRate],
  ["Total R", data.stats.totalR],
  ["Average R / trade", data.stats.avgR],
  ["Max drawdown (R)", data.stats.maxDrawdownR],
  ["Best trade (R)", data.stats.bestR],
  ["Worst trade (R)", data.stats.worstR],
]);
styleHeader(summary, "A4:B4");
fmt(summary, "B6:B6", "0.0%");
fmt(summary, "B7:B11", "0.00");
writeMatrix(summary, "D4", [["Symbol", "Trades", "Wins", "Losses", "Win Rate", "Total R", "Avg R", "Best R", "Worst R"], ...data.summary.map(r => [
  r.symbol.replace("USDT", ""), r.trades, r.wins, r.losses, r.winRate, r.totalR, r.avgR, r.bestR, r.worstR,
])]);
styleHeader(summary, "D4:L4");
fmt(summary, "H5:H20", "0.0%");
fmt(summary, "I5:L20", "0.00");
finish(summary, "A1:L20");

const tradeHeaders = ["Symbol", "No", "Side", "Signal Time", "Entry Time", "Entry Price", "Initial Stop", "Final Stop", "Risk / Unit", "TP", "TP Time", "TP Ref", "Exit Time", "Exit Price", "Exit Reason", "Gross R", "Cost R", "Net R", "% Move", "TP Hit", "Weekly Regime", "EMA20", "EMA50", "ATR14", "SSL Signal", "Net Volume", "Distance EMA50 ATR", "Notes"];
const tradeToRow = t => [t.symbol.replace("USDT", ""), t.tradeNo, t.side, new Date(t.signalTime), new Date(t.entryTime), t.entryPrice, t.initialStop, t.finalStop, t.riskPerUnit, t.tp1, t.tp1Time ? new Date(t.tp1Time) : "", t.tp2, new Date(t.exitTime), t.exitPrice, t.exitReason, t.grossRMultiple, t.costR, t.rMultiple, t.pctMove, t.tp1Hit, t.weeklyRegime, t.ema20, t.ema50, t.atr14, t.sslAtSignal, t.netVolume, t.distanceToEma50Atr, t.notes ?? ""];
const trades = getSheet(workbook, "Trades");
clear(trades, Math.max(data.trades.length + 10, 230), 28);
baseSheet(trades, "Detailed Trades", "Corrected no-volume variant; one completed trade per row.");
writeMatrix(trades, "A4", [tradeHeaders, ...data.trades.map(tradeToRow)]);
styleHeader(trades, "A4:AB4");
const tradeEnd = data.trades.length + 4;
fmt(trades, `D5:E${tradeEnd}`, "yyyy-mm-dd hh:mm");
fmt(trades, `K5:K${tradeEnd}`, "yyyy-mm-dd hh:mm");
fmt(trades, `M5:M${tradeEnd}`, "yyyy-mm-dd hh:mm");
fmt(trades, `F5:N${tradeEnd}`, "0.000000");
fmt(trades, `P5:R${tradeEnd}`, "0.00");
fmt(trades, `S5:S${tradeEnd}`, "0.00%");
finish(trades, `A1:AB${tradeEnd}`);

const acctRows = [];
let equity = startingEquity;
let peak = startingEquity;
for (let i = 0; i < data.trades.length; i++) {
  const t = data.trades[i];
  const before = equity;
  const risk = before * riskPct;
  const pnl = risk * t.rMultiple;
  equity += pnl;
  peak = Math.max(peak, equity);
  acctRows.push([i + 1, new Date(t.exitTime), t.symbol.replace("USDT", ""), t.side, t.rMultiple, before, risk, pnl, equity, equity / peak - 1]);
}
const acct = getSheet(workbook, "20K Account");
clear(acct, Math.max(acctRows.length + 10, 230), 10);
baseSheet(acct, "20K Account Sizing", "Compounded sequence at 2.0% risk per trade; leverage is not modeled.");
writeMatrix(acct, "A4", [["Trade", "Exit Time", "Symbol", "Side", "Net R", "Equity Before", "Risk USD", "P/L USD", "Equity After", "Drawdown"], ...acctRows]);
styleHeader(acct, "A4:J4");
const acctEnd = acctRows.length + 4;
fmt(acct, `B5:B${acctEnd}`, "yyyy-mm-dd hh:mm");
fmt(acct, `E5:E${acctEnd}`, "0.00");
fmt(acct, `F5:I${acctEnd}`, "$#,##0");
fmt(acct, `J5:J${acctEnd}`, "0.0%");
finish(acct, `A1:J${acctEnd}`);

const assumptions = getSheet(workbook, "Assumptions");
clear(assumptions, 40, 2);
baseSheet(assumptions, "Backtest Assumptions", "Corrected no-volume variant using the project workbook template.");
writeMatrix(assumptions, "A4", [["#", "Assumption"], ...[
  "Net Volume filter is disabled.",
  "Entry still requires SSL crossover, EMA20 cross within 3 candles, and EMA50 distance <= 2 ATR.",
  "Corrected accounting recomputes trade R as full-position P/L at exit minus cost.",
  "The source no-volume trade log was generated from the same 6-year Binance daily dataset.",
  "This file should replace the older no-volume result that overstated R due to TP accounting.",
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
