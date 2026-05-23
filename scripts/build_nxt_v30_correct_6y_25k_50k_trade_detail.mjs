import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const root = path.resolve(".");
const inputJson = path.join(root, "outputs", "nxt_crypto_btc_sol_sui_6y_v30_close_25_correct", "nxt_v30_close_25_correct_6y_results.json");
const outDir = path.join(root, "outputs", "nxt_crypto_btc_sol_sui_6y_v30_close_25_correct");
const xlsxPath = path.join(outDir, "NXT_V30_Correct_6Y_Trade_Detail_25K_50K.xlsx");
const startingEquities = [25000, 50000];
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

function maxDrawdownFromEquity(rows, equityKey, startingEquity) {
  let peak = startingEquity;
  let maxDrawdown = 0;
  for (const row of rows) {
    peak = Math.max(peak, row[equityKey]);
    maxDrawdown = Math.min(maxDrawdown, row[equityKey] / peak - 1);
  }
  return maxDrawdown;
}

function buildSizingRows(trades) {
  const equityByAccount = Object.fromEntries(startingEquities.map(v => [v, v]));
  return trades.map((trade, index) => {
    const stopDistance = Math.abs(trade.entryPrice - trade.initialStop);
    const stopDistancePct = stopDistance / trade.entryPrice;
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
      rMultiple: trade.rMultiple,
      exitReason: trade.exitReason,
    };
    for (const startEquity of startingEquities) {
      const suffix = startEquity === 25000 ? "25k" : "50k";
      const equity = equityByAccount[startEquity];
      const riskUsd = equity * riskPct;
      const quantity = stopDistance > 0 ? riskUsd / stopDistance : 0;
      const notional = quantity * trade.entryPrice;
      const pnlUsd = riskUsd * trade.rMultiple;
      const equityAfter = equity + pnlUsd;
      row[`equityBefore_${suffix}`] = equity;
      row[`riskUsd_${suffix}`] = riskUsd;
      row[`quantity_${suffix}`] = quantity;
      row[`notional_${suffix}`] = notional;
      row[`margin2x_${suffix}`] = notional / 2;
      row[`pnlUsd_${suffix}`] = pnlUsd;
      row[`equityAfter_${suffix}`] = equityAfter;
      equityByAccount[startEquity] = equityAfter;
    }
    return row;
  });
}

function summarizeSymbol(rows, symbol) {
  const subset = rows.filter(r => r.symbol === symbol);
  const totalPnl25 = subset.reduce((sum, r) => sum + r.pnlUsd_25k, 0);
  const totalPnl50 = subset.reduce((sum, r) => sum + r.pnlUsd_50k, 0);
  const totalR = subset.reduce((sum, r) => sum + r.rMultiple, 0);
  const wins = subset.filter(r => r.rMultiple > 0).length;
  const avgNotional25 = subset.reduce((sum, r) => sum + r.notional_25k, 0) / subset.length;
  const maxNotional25 = Math.max(...subset.map(r => r.notional_25k));
  return {
    symbol,
    trades: subset.length,
    wins,
    losses: subset.length - wins,
    winRate: wins / subset.length,
    totalR,
    pnl25: totalPnl25,
    pnl50: totalPnl50,
    avgNotional25,
    maxNotional25,
  };
}

const raw = JSON.parse(await fs.readFile(inputJson, "utf8"));
const trades = [...raw.trades].sort((a, b) => new Date(a.exitTime) - new Date(b.exitTime));
const sizingRows = buildSizingRows(trades);
const wins = sizingRows.filter(r => r.rMultiple > 0).length;
const final25 = sizingRows.at(-1)?.equityAfter_25k ?? 25000;
const final50 = sizingRows.at(-1)?.equityAfter_50k ?? 50000;
const maxDrawdown25 = maxDrawdownFromEquity(sizingRows, "equityAfter_25k", 25000);
const maxDrawdown50 = maxDrawdownFromEquity(sizingRows, "equityAfter_50k", 50000);
const symbols = [...new Set(sizingRows.map(r => r.symbol))];

const workbook = Workbook.create();

const summary = workbook.worksheets.add("Sizing Summary");
baseSheet(summary, "NXT v3.0 Corrected 6Y Trade Detail", "Starting equity $25,000 and $50,000 | Risk 2% per trade | Net R already includes fee/slippage");
writeMatrix(summary, "A4", [
  ["Metric", "Value"],
  ["Starting equity 25k", 25000],
  ["Starting equity 50k", 50000],
  ["Risk per trade", riskPct],
  ["Completed trades", sizingRows.length],
  ["Win rate", wins / sizingRows.length],
  ["Final equity 25k", final25],
  ["Final equity 50k", final50],
  ["P&L 25k", final25 - 25000],
  ["P&L 50k", final50 - 50000],
  ["Account multiple", final25 / 25000],
  ["Max drawdown 25k", maxDrawdown25],
  ["Max drawdown 50k", maxDrawdown50],
  ["Largest notional 25k", Math.max(...sizingRows.map(r => r.notional_25k))],
  ["Largest notional 50k", Math.max(...sizingRows.map(r => r.notional_50k))],
]);
styleHeader(summary, "A4:B4");
numberFormat(summary, "B5:B6", "$#,##0");
numberFormat(summary, "B7:B7", "0.0%");
numberFormat(summary, "B10:B13", "$#,##0");
numberFormat(summary, "B14:B14", "0.00x");
numberFormat(summary, "B15:B16", "0.0%");
numberFormat(summary, "B17:B18", "$#,##0");

writeMatrix(summary, "D4", [
  ["Coin", "Trades", "Wins", "Losses", "Win Rate", "Total R", "P&L 25k", "P&L 50k", "Avg Notional 25k", "Max Notional 25k"],
  ...symbols.map(symbol => {
    const s = summarizeSymbol(sizingRows, symbol);
    return [s.symbol, s.trades, s.wins, s.losses, s.winRate, s.totalR, s.pnl25, s.pnl50, s.avgNotional25, s.maxNotional25];
  }),
]);
styleHeader(summary, "D4:M4");
numberFormat(summary, "H5:H20", "0.0%");
numberFormat(summary, "I5:I20", "0.00");
numberFormat(summary, "J5:M20", "$#,##0");
summary.charts.add("line", {
  title: "Compound Equity ($25k and $50k, 2% Risk)",
  categories: sizingRows.map(r => String(r.no)),
  series: [
    { name: "Equity 25k", values: sizingRows.map(r => r.equityAfter_25k), line: { fill: "#17324D", style: "solid", width: 2 } },
    { name: "Equity 50k", values: sizingRows.map(r => r.equityAfter_50k), line: { fill: "#2563EB", style: "solid", width: 2 } },
  ],
  from: { row: 15, col: 0 },
  extent: { widthPx: 740, heightPx: 320 },
  hasLegend: true,
});
summary.getRange("A4:M18").format.wrapText = true;
finishSheet(summary, "A1:M18");

const tradesSheet = workbook.worksheets.add("Trades Sizing");
baseSheet(tradesSheet, "Trade-by-Trade Detail", "Corrected v3.0 full close at 2.5 ATR; position values use equity before each trade and stop distance.");
const headers = [
  "No", "Symbol", "Side", "Signal Time", "Entry Time", "Exit Time", "Entry Price", "Initial Stop", "Stop Distance", "Stop %",
  "Risk %", "Net R", "Exit Reason",
  "Equity Before 25k", "Risk USD 25k", "Coin Qty 25k", "Position Notional 25k", "Margin @2x 25k", "P&L USD 25k", "Equity After 25k",
  "Equity Before 50k", "Risk USD 50k", "Coin Qty 50k", "Position Notional 50k", "Margin @2x 50k", "P&L USD 50k", "Equity After 50k",
];
writeMatrix(tradesSheet, "A4", [
  headers,
  ...sizingRows.map(r => [
    r.no, r.symbol, r.side, new Date(r.signalTime), new Date(r.entryTime), new Date(r.exitTime), r.entryPrice, r.initialStop, r.stopDistance, r.stopDistancePct,
    r.riskPct, r.rMultiple, r.exitReason,
    r.equityBefore_25k, r.riskUsd_25k, r.quantity_25k, r.notional_25k, r.margin2x_25k, r.pnlUsd_25k, r.equityAfter_25k,
    r.equityBefore_50k, r.riskUsd_50k, r.quantity_50k, r.notional_50k, r.margin2x_50k, r.pnlUsd_50k, r.equityAfter_50k,
  ]),
]);
styleHeader(tradesSheet, "A4:AA4");
tradesSheet.freezePanes.freezeRows(4);
const lastRow = sizingRows.length + 4;
numberFormat(tradesSheet, `D5:F${lastRow}`, "yyyy-mm-dd");
numberFormat(tradesSheet, `G5:I${lastRow}`, "0.000000");
numberFormat(tradesSheet, `J5:K${lastRow}`, "0.0%");
numberFormat(tradesSheet, `L5:L${lastRow}`, "0.00");
numberFormat(tradesSheet, `N5:O${lastRow}`, "$#,##0");
numberFormat(tradesSheet, `P5:P${lastRow}`, "0.000000");
numberFormat(tradesSheet, `Q5:S${lastRow}`, "$#,##0");
numberFormat(tradesSheet, `T5:T${lastRow}`, "$#,##0");
numberFormat(tradesSheet, `U5:V${lastRow}`, "$#,##0");
numberFormat(tradesSheet, `W5:W${lastRow}`, "0.000000");
numberFormat(tradesSheet, `X5:AA${lastRow}`, "$#,##0");
tradesSheet.getRange(`A4:AA${lastRow}`).format.wrapText = true;
finishSheet(tradesSheet, `A1:AA${lastRow}`);

const assumptions = workbook.worksheets.add("Sizing Assumptions");
baseSheet(assumptions, "Sizing Assumptions", "How to read position values.");
writeMatrix(assumptions, "A4", [
  ["#", "Assumption"],
  [1, "Starting equities are $25,000 and $50,000."],
  [2, "Each trade risks 2% of equity immediately before that trade."],
  [3, "Risk USD = Equity Before x 2%."],
  [4, "Coin Qty = Risk USD / absolute distance between entry and initial stop."],
  [5, "Position Notional = Coin Qty x Entry Price."],
  [6, "Margin @2x assumes isolated margin and is estimated as Notional divided by 2. It does not include exchange maintenance margin or liquidation buffer."],
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
console.log(JSON.stringify({ xlsxPath, final25, final50, trades: sizingRows.length }, null, 2));
