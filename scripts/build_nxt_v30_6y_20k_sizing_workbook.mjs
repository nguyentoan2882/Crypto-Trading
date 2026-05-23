import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const root = path.resolve(".");
const inputJson = path.join(root, "outputs", "nxt_crypto_btc_sol_sui_6y_v30_close_25", "nxt_v30_close_25_6y_results.json");
const outDir = path.join(root, "outputs", "nxt_crypto_btc_sol_sui_6y_v30_close_25");
const xlsxPath = path.join(outDir, "NXT_V30_6Y_20K_2pct_Position_Sizing.xlsx");
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

function maxDrawdownFromEquity(rows) {
  let peak = startingEquity;
  let maxDrawdown = 0;
  for (const row of rows) {
    peak = Math.max(peak, row.equityAfter);
    maxDrawdown = Math.min(maxDrawdown, row.equityAfter / peak - 1);
  }
  return maxDrawdown;
}

function buildSizingRows(trades) {
  let equity = startingEquity;
  return trades.map((trade, index) => {
    const riskUsd = equity * riskPct;
    const stopDistance = Math.abs(trade.entryPrice - trade.initialStop);
    const stopDistancePct = stopDistance / trade.entryPrice;
    const quantity = stopDistance > 0 ? riskUsd / stopDistance : 0;
    const notional = quantity * trade.entryPrice;
    const pnlUsd = riskUsd * trade.rMultiple;
    const equityAfter = equity + pnlUsd;
    const row = {
      no: index + 1,
      symbol: trade.symbol.replace("USDT", ""),
      side: trade.side,
      signalTime: trade.signalTime,
      entryTime: trade.entryTime,
      exitTime: trade.exitTime,
      entryPrice: trade.entryPrice,
      initialStop: trade.initialStop,
      stopDistance,
      stopDistancePct,
      riskPct,
      equityBefore: equity,
      riskUsd,
      quantity,
      notional,
      margin2x: notional / 2,
      margin5x: notional / 5,
      margin10x: notional / 10,
      rMultiple: trade.rMultiple,
      pnlUsd,
      equityAfter,
      exitReason: trade.exitReason,
    };
    equity = equityAfter;
    return row;
  });
}

function summarizeSymbol(rows, symbol) {
  const subset = rows.filter(r => r.symbol === symbol);
  const totalPnl = subset.reduce((sum, r) => sum + r.pnlUsd, 0);
  const totalR = subset.reduce((sum, r) => sum + r.rMultiple, 0);
  const wins = subset.filter(r => r.rMultiple > 0).length;
  const avgNotional = subset.reduce((sum, r) => sum + r.notional, 0) / subset.length;
  const maxNotional = Math.max(...subset.map(r => r.notional));
  return {
    symbol,
    trades: subset.length,
    wins,
    losses: subset.length - wins,
    winRate: wins / subset.length,
    totalR,
    pnlUsd: totalPnl,
    avgNotional,
    maxNotional,
  };
}

const raw = JSON.parse(await fs.readFile(inputJson, "utf8"));
const trades = [...raw.trades].sort((a, b) => new Date(a.exitTime) - new Date(b.exitTime));
const sizingRows = buildSizingRows(trades);
const finalEquity = sizingRows.at(-1)?.equityAfter ?? startingEquity;
const totalPnl = finalEquity - startingEquity;
const wins = sizingRows.filter(r => r.rMultiple > 0).length;
const maxDrawdown = maxDrawdownFromEquity(sizingRows);
const symbols = [...new Set(sizingRows.map(r => r.symbol))];

const workbook = Workbook.create();

const summary = workbook.worksheets.add("Sizing Summary");
baseSheet(summary, "NXT v3.0 6Y Position Sizing", "Starting equity $20,000 | Risk 2% per trade | Net R already includes fee/slippage");
writeMatrix(summary, "A4", [
  ["Metric", "Value"],
  ["Starting equity", startingEquity],
  ["Risk per trade", riskPct],
  ["Completed trades", sizingRows.length],
  ["Win rate", wins / sizingRows.length],
  ["Final equity", finalEquity],
  ["Total P&L", totalPnl],
  ["Account multiple", finalEquity / startingEquity],
  ["Max drawdown", maxDrawdown],
  ["Largest risk USD", Math.max(...sizingRows.map(r => r.riskUsd))],
  ["Largest notional", Math.max(...sizingRows.map(r => r.notional))],
  ["Largest margin needed @2x", Math.max(...sizingRows.map(r => r.margin2x))],
]);
styleHeader(summary, "A4:B4");
numberFormat(summary, "B5:B5", "$#,##0");
numberFormat(summary, "B6:B6", "0.0%");
numberFormat(summary, "B8:B9", "$#,##0");
numberFormat(summary, "B10:B10", "0.00x");
numberFormat(summary, "B11:B11", "0.0%");
numberFormat(summary, "B12:B14", "$#,##0");

writeMatrix(summary, "D4", [
  ["Coin", "Trades", "Wins", "Losses", "Win Rate", "Total R", "P&L USD", "Avg Notional", "Max Notional"],
  ...symbols.map(symbol => {
    const s = summarizeSymbol(sizingRows, symbol);
    return [s.symbol, s.trades, s.wins, s.losses, s.winRate, s.totalR, s.pnlUsd, s.avgNotional, s.maxNotional];
  }),
]);
styleHeader(summary, "D4:L4");
numberFormat(summary, "H5:H20", "0.0%");
numberFormat(summary, "I5:I20", "0.00");
numberFormat(summary, "J5:L20", "$#,##0");
summary.charts.add("line", {
  title: "Compound Equity ($20k, 2% Risk)",
  categories: sizingRows.map(r => String(r.no)),
  series: [{ name: "Equity", values: sizingRows.map(r => r.equityAfter), line: { fill: "#17324D", style: "solid", width: 2 } }],
  from: { row: 15, col: 0 },
  extent: { widthPx: 740, heightPx: 320 },
  hasLegend: false,
});
summary.getRange("A4:L14").format.wrapText = true;
finishSheet(summary, "A1:L14");

const tradesSheet = workbook.worksheets.add("Trades Sizing");
baseSheet(tradesSheet, "Trade-by-Trade Position Sizing", "Position values are calculated from equity before each trade and stop distance.");
const headers = [
  "No", "Symbol", "Side", "Signal Time", "Entry Time", "Exit Time", "Entry Price", "Initial Stop", "Stop Distance", "Stop %",
  "Risk %", "Equity Before", "Risk USD", "Coin Qty", "Position Notional", "Margin @2x", "Margin @5x", "Margin @10x",
  "Net R", "P&L USD", "Equity After", "Exit Reason",
];
writeMatrix(tradesSheet, "A4", [
  headers,
  ...sizingRows.map(r => [
    r.no, r.symbol, r.side, new Date(r.signalTime), new Date(r.entryTime), new Date(r.exitTime), r.entryPrice, r.initialStop, r.stopDistance, r.stopDistancePct,
    r.riskPct, r.equityBefore, r.riskUsd, r.quantity, r.notional, r.margin2x, r.margin5x, r.margin10x,
    r.rMultiple, r.pnlUsd, r.equityAfter, r.exitReason,
  ]),
]);
styleHeader(tradesSheet, "A4:V4");
tradesSheet.freezePanes.freezeRows(4);
const lastRow = sizingRows.length + 4;
numberFormat(tradesSheet, `D5:F${lastRow}`, "yyyy-mm-dd");
numberFormat(tradesSheet, `G5:I${lastRow}`, "0.000000");
numberFormat(tradesSheet, `J5:K${lastRow}`, "0.0%");
numberFormat(tradesSheet, `L5:M${lastRow}`, "$#,##0");
numberFormat(tradesSheet, `N5:N${lastRow}`, "0.000000");
numberFormat(tradesSheet, `O5:R${lastRow}`, "$#,##0");
numberFormat(tradesSheet, `S5:S${lastRow}`, "0.00");
numberFormat(tradesSheet, `T5:U${lastRow}`, "$#,##0");
tradesSheet.getRange(`A4:V${lastRow}`).format.wrapText = true;
finishSheet(tradesSheet, `A1:V${lastRow}`);

const assumptions = workbook.worksheets.add("Sizing Assumptions");
baseSheet(assumptions, "Sizing Assumptions", "How to read position values.");
writeMatrix(assumptions, "A4", [
  ["#", "Assumption"],
  [1, "Starting equity is $20,000."],
  [2, "Each trade risks 2% of equity immediately before that trade."],
  [3, "Risk USD = Equity Before x 2%."],
  [4, "Coin Qty = Risk USD / absolute distance between entry and initial stop."],
  [5, "Position Notional = Coin Qty x Entry Price."],
  [6, "Margin examples assume isolated margin and are estimated as Notional divided by leverage. They do not include exchange maintenance margin or liquidation buffer."],
  [7, "Net R from the backtest already includes the fee/slippage cost model. Funding, borrow cost, taxes, minimum order constraints, and live execution errors are excluded."],
  [8, "Rows are compounded sequentially by exit time, matching the completed-trade order in the 6Y backtest."],
]);
styleHeader(assumptions, "A4:B4");
assumptions.getRange("A4:B12").format.wrapText = true;
finishSheet(assumptions, "A1:B12");

const errors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 300 },
  summary: "formula error scan",
});
console.log(errors.ndjson);

const preview = await workbook.inspect({
  kind: "table",
  range: "Sizing Summary!A1:L14",
  include: "values,formulas",
  tableMaxRows: 20,
  tableMaxCols: 12,
});
console.log(preview.ndjson);

await fs.mkdir(outDir, { recursive: true });
const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(xlsxPath);
console.log(JSON.stringify({ xlsxPath, finalEquity, totalPnl, trades: sizingRows.length }, null, 2));
