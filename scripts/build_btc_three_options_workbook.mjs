import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const root = "D:/Workspace/Codex/Investment";
const sourcePath = path.join(root, "outputs/nxt_latest_btc_max_binance_history/NXT_Latest_BTC_Max_Binance_History_20K.json");
const outputDir = path.join(root, "outputs/nxt_latest_btc_max_binance_history");
const outputPath = path.join(outputDir, "NXT_Latest_BTC_3_Options_FixedR_2pct_5pct_20K.xlsx");
const previewDir = path.join(outputDir, "preview");
const source = JSON.parse(await fs.readFile(sourcePath, "utf8"));
const trades = [...source.trades].sort((a, b) => a.entryTime.localeCompare(b.entryTime) || a.tradeNo - b.tradeNo);

const wb = Workbook.create();
const summary = wb.worksheets.add("Summary");
const detail = wb.worksheets.add("Trade Detail");
const yearly = wb.worksheets.add("Yearly");
const assumptions = wb.worksheets.add("Assumptions");
const checks = wb.worksheets.add("Checks");
const chartData = wb.worksheets.add("Chart Data");
for (const ws of [summary, detail, yearly, assumptions, checks, chartData]) {
  ws.showGridLines = false;
}

const navy = "#17365D", blue = "#1F4E78", teal = "#0F6B78", lightBlue = "#D9EAF7";
const lightTeal = "#DDEBF7", green = "#E2F0D9", red = "#FCE4D6", gray = "#F2F2F2", white = "#FFFFFF";
const currency = '$#,##0.00;[Red]($#,##0.00);-';
const percent = '0.00%;[Red](0.00%);-';
const number = '#,##0.00;[Red](#,##0.00);-';
let fixedPreviewEq = 20000, fixedPreviewPeak = 20000, fixedMaxDdPct = 0;
for (const t of trades) {
  fixedPreviewEq += 1000 * t.rMultiple;
  fixedPreviewPeak = Math.max(fixedPreviewPeak, fixedPreviewEq);
  fixedMaxDdPct = Math.min(fixedMaxDdPct, (fixedPreviewEq - fixedPreviewPeak) / fixedPreviewPeak);
}

function title(ws, range, text) {
  ws.mergeCells(range);
  const r = ws.getRange(range);
  r.values = [[text]];
  r.format = { fill: navy, font: { bold: true, color: white, size: 16 }, verticalAlignment: "center" };
  r.format.rowHeight = 30;
}
function header(range) {
  range.format = {
    fill: blue, font: { bold: true, color: white }, wrapText: true,
    horizontalAlignment: "center", verticalAlignment: "center",
    borders: { preset: "all", style: "thin", color: "#B4C6E7" },
  };
}
function body(range) {
  range.format.borders = { preset: "all", style: "thin", color: "#D9E2F3" };
}

title(summary, "A1:H1", "NXT Latest BTC — 3 Capital Options");
summary.mergeCells("A2:H2");
summary.getRange("A2").values = [[`BTCUSDT native 1D | ${source.dataStart} to ${source.dataEnd} | Starting equity $20,000 | ${trades.length} trades`]];
summary.getRange("A2:H2").format = { fill: lightBlue, font: { italic: true, color: "#404040" } };
summary.getRange("A4:D4").values = [["Input", "Fixed R", "Compounding 2%", "Compounding 5%"]];
header(summary.getRange("A4:D4"));
summary.getRange("A5:D7").values = [
  ["Starting Equity", 20000, 20000, 20000],
  ["Risk Rule", 1000, 0.02, 0.05],
  ["Risk Display", "$1,000 fixed", "2.00% current equity", "5.00% current equity"],
];
summary.getRange("B5:D5").format.numberFormat = currency;
summary.getRange("B6").format.numberFormat = currency;
summary.getRange("C6:D6").format.numberFormat = percent;
summary.getRange("B5:D6").format.font = { color: "#0000FF" };
body(summary.getRange("A5:D7"));

summary.getRange("A9:D9").values = [["Metric", "Fixed R", "Compounding 2%", "Compounding 5%"]];
header(summary.getRange("A9:D9"));
const lastRow = trades.length + 4;
summary.getRange("A10:A17").values = [
  ["Ending Equity"], ["Net Profit"], ["Total Return"], ["Max Drawdown $"],
  ["Max Drawdown %"], ["Trades"], ["Win Rate"], ["Profit Factor"],
];
summary.getRange("B10:D17").formulas = [
  [`='Trade Detail'!U${lastRow}`, `='Trade Detail'!Y${lastRow}`, `='Trade Detail'!AD${lastRow}`],
  ["=B10-B5", "=C10-C5", "=D10-D5"],
  ["=B10/B5-1", "=C10/C5-1", "=D10/D5-1"],
  [`=MIN('Trade Detail'!V5:V${lastRow})`, `=MIN('Trade Detail'!Z5:Z${lastRow})`, `=MIN('Trade Detail'!AE5:AE${lastRow})`],
  [`=${fixedMaxDdPct}`, `=MIN('Trade Detail'!AA5:AA${lastRow})`, `=MIN('Trade Detail'!AF5:AF${lastRow})`],
  [`=COUNTA('Trade Detail'!A5:A${lastRow})`, `=B15`, `=B15`],
  [`=COUNTIF('Trade Detail'!R5:R${lastRow},\">0\")/B15`, "=B16", "=B16"],
  [`=SUMIF('Trade Detail'!R5:R${lastRow},\">0\",'Trade Detail'!R5:R${lastRow})/-SUMIF('Trade Detail'!R5:R${lastRow},\"<0\",'Trade Detail'!R5:R${lastRow})`, "=B17", "=B17"],
];
summary.getRange("B10:D11").format.numberFormat = currency;
summary.getRange("B12:D12").format.numberFormat = percent;
summary.getRange("B13:D13").format.numberFormat = currency;
summary.getRange("B14:D14").format.numberFormat = percent;
summary.getRange("B16:D16").format.numberFormat = percent;
summary.getRange("B17:D17").format.numberFormat = "0.00x";
body(summary.getRange("A10:D17"));
summary.getRange("B10:B17").format.fill = gray;
summary.getRange("C10:C17").format.fill = green;
summary.getRange("D10:D17").format.fill = red;

summary.getRange("F4:H4").values = [["Option", "Ending Equity", "Max DD %"]];
header(summary.getRange("F4:H4"));
summary.getRange("F5:F7").values = [["Fixed R"], ["2%"], ["5%"]];
summary.getRange("G5:H7").formulas = [["=B10", "=B14"], ["=C10", "=C14"], ["=D10", "=D14"]];
summary.getRange("G5:G7").format.numberFormat = currency;
summary.getRange("H5:H7").format.numberFormat = percent;
body(summary.getRange("F5:H7"));

const detailHeaders = [
  "No", "Symbol", "Signal Type", "Side", "Signal Date", "Entry Date", "Exit Date", "Entry Price",
  "Initial Stop", "Final Stop", "Risk / Unit", "TP1", "TP1 Date", "Exit Price", "Exit Reason",
  "Gross R", "Cost R", "Net R", "Fixed Risk $", "Fixed P&L $", "Fixed Equity $", "Fixed DD $",
  "2% Risk $", "2% P&L $", "2% Equity $", "2% DD $", "2% DD %",
  "5% Risk $", "5% P&L $", "5% Equity $", "5% DD $", "5% DD %"
];
title(detail, "A1:AF1", "BTC Trade Detail — Fixed R vs 2% vs 5%");
detail.mergeCells("A2:AF2");
detail.getRange("A2").values = [["Blue values are source trade data; black cells are formulas. Equity changes when each trade closes."]];
detail.getRange("A4:AF4").values = [detailHeaders];
header(detail.getRange("A4:AF4"));
const rows = trades.map((t, i) => [
  i + 1, "BTCUSDT", t.signalType, t.side, t.signalTime, t.entryTime, t.exitTime, t.entryPrice,
  t.initialStop, t.finalStop, t.riskPerUnit, t.tp1, t.tp1Time || "", t.exitPrice, t.exitReason,
  t.grossRMultiple, t.costR, t.rMultiple, null, null, null, null, null, null, null, null, null, null, null, null, null, null
]);
detail.getRange(`A5:AF${lastRow}`).values = rows;
for (let r = 5; r <= lastRow; r++) {
  detail.getRange(`S${r}:AF${r}`).formulas = [[
    "=Summary!$B$6", `=S${r}*R${r}`, r === 5 ? `=Summary!$B$5+T${r}` : `=U${r-1}+T${r}`,
    r === 5 ? `=U${r}-MAX(Summary!$B$5,U${r})` : `=U${r}-MAX(Summary!$B$5,MAX($U$5:U${r}))`,
    r === 5 ? "=Summary!$C$5*Summary!$C$6" : `=Y${r-1}*Summary!$C$6`,
    `=W${r}*R${r}`, r === 5 ? `=Summary!$C$5+X${r}` : `=Y${r-1}+X${r}`,
    r === 5 ? `=Y${r}-MAX(Summary!$C$5,Y${r})` : `=Y${r}-MAX(Summary!$C$5,MAX($Y$5:Y${r}))`,
    `=Z${r}/MAX(Summary!$C$5,MAX($Y$5:Y${r}))`,
    r === 5 ? "=Summary!$D$5*Summary!$D$6" : `=AD${r-1}*Summary!$D$6`,
    `=AB${r}*R${r}`, r === 5 ? `=Summary!$D$5+AC${r}` : `=AD${r-1}+AC${r}`,
    r === 5 ? `=AD${r}-MAX(Summary!$D$5,AD${r})` : `=AD${r}-MAX(Summary!$D$5,MAX($AD$5:AD${r}))`,
    `=AE${r}/MAX(Summary!$D$5,MAX($AD$5:AD${r}))`
  ]];
}
detail.getRange(`A5:R${lastRow}`).format.font = { color: "#0000FF" };
detail.getRange(`H5:N${lastRow}`).format.numberFormat = number;
detail.getRange(`P5:R${lastRow}`).format.numberFormat = "0.000";
detail.getRange(`S5:AF${lastRow}`).format.numberFormat = currency;
detail.getRange(`AA5:AA${lastRow}`).format.numberFormat = percent;
detail.getRange(`AF5:AF${lastRow}`).format.numberFormat = percent;
detail.getRange(`E5:G${lastRow}`).format.numberFormat = "yyyy-mm-dd";
detail.getRange(`M5:M${lastRow}`).format.numberFormat = "yyyy-mm-dd";
detail.getRange(`R5:R${lastRow}`).conditionalFormats.add("cellIs", { operator: "greaterThan", formula: 0, format: { font: { color: "#008000" } } });
detail.getRange(`R5:R${lastRow}`).conditionalFormats.add("cellIs", { operator: "lessThan", formula: 0, format: { font: { color: "#C00000" } } });
body(detail.getRange(`A5:AF${lastRow}`));
detail.freezePanes.freezeRows(4);
detail.freezePanes.freezeColumns(7);
detail.tables.add(`A4:AF${lastRow}`, true, "BTCTradeDetail");

const years = [...new Set(trades.map(t => t.exitTime.slice(0, 4)))].sort();
title(yearly, "A1:J1", "Yearly Performance");
yearly.getRange("A4:J4").values = [["Year", "Trades", "Total R", "Fixed P&L", "Fixed End Equity", "2% P&L", "2% End Equity", "5% P&L", "5% End Equity", "Win Rate"]];
header(yearly.getRange("A4:J4"));
let fixedEq = 20000, eq2 = 20000, eq5 = 20000;
const yearlyRows = [];
for (const y of years) {
  const subset = trades.filter(t => t.exitTime.startsWith(y));
  let fixedPnl = 0, pnl2 = 0, pnl5 = 0;
  for (const t of subset) {
    fixedPnl += 1000 * t.rMultiple;
    pnl2 += eq2 * 0.02 * t.rMultiple;
    eq2 += eq2 * 0.02 * t.rMultiple;
    pnl5 += eq5 * 0.05 * t.rMultiple;
    eq5 += eq5 * 0.05 * t.rMultiple;
  }
  fixedEq += fixedPnl;
  yearlyRows.push([
    Number(y), subset.length, subset.reduce((s, t) => s + t.rMultiple, 0), fixedPnl, fixedEq,
    pnl2, eq2, pnl5, eq5, subset.filter(t => t.rMultiple > 0).length / subset.length
  ]);
}
yearly.getRange(`A5:J${years.length + 4}`).values = yearlyRows;
yearly.getRange(`C5:C${years.length + 4}`).format.numberFormat = "0.00";
yearly.getRange(`D5:I${years.length + 4}`).format.numberFormat = currency;
yearly.getRange(`J5:J${years.length + 4}`).format.numberFormat = percent;
body(yearly.getRange(`A5:J${years.length + 4}`));
yearly.freezePanes.freezeRows(4);

title(assumptions, "A1:D1", "Assumptions and Limitations");
assumptions.getRange("A4:D4").values = [["Item", "Value", "Unit", "Notes"]];
header(assumptions.getRange("A4:D4"));
assumptions.getRange("A5:D13").values = [
  ["System", "NXT latest BTC-only", "", "Native Binance 1D, SSL14, Runner A, anti-immediate-reversal, LONG-only continuation"],
  ["Data period", `${source.dataStart} to ${source.dataEnd}`, "", "Maximum Binance BTCUSDT history available in this run"],
  ["Starting equity", 20000, "USD", "Same starting capital for all options"],
  ["Fixed risk", 1000, "USD/trade", "Fixed R option does not compound"],
  ["Option 2%", 0.02, "% equity/trade", "Risk recalculated from current closed-trade equity"],
  ["Option 5%", 0.05, "% equity/trade", "Aggressive scenario"],
  ["Trading cost", "Included in Net R", "", "Uses source backtest cost model"],
  ["Funding", "Not included", "", "Results may be overstated for long holding periods"],
  ["Drawdown", "Closed-trade equity", "", "Does not include intratrade mark-to-market drawdown"],
];
assumptions.getRange("B7:B8").format.numberFormat = currency;
assumptions.getRange("B9:B10").format.numberFormat = percent;
body(assumptions.getRange("A5:D13"));

title(checks, "A1:F1", "Model Checks");
checks.getRange("A4:F4").values = [["Check", "Actual", "Expected", "Difference", "Tolerance", "Status"]];
header(checks.getRange("A4:F4"));
checks.getRange("A5:A9").values = [["Trade count"], ["Fixed ending equity"], ["2% ending equity"], ["5% ending equity"], ["Source total R"]];
checks.getRange("B5:F9").formulas = [
  ["=Summary!B15", `=${trades.length}`, "=B5-C5", "=0", '=IF(ABS(D5)<=E5,"OK","FAIL")'],
  ["=Summary!B10", `=${20000 + source.stats.totalR * 1000}`, "=B6-C6", "=0.01", '=IF(ABS(D6)<=E6,"OK","FAIL")'],
  ["=Summary!C10", "=73489.9220832914", "=B7-C7", "=0.01", '=IF(ABS(D7)<=E7,"OK","FAIL")'],
  ["=Summary!D10", "=368173.943681928", "=B8-C8", "=0.01", '=IF(ABS(D8)<=E8,"OK","FAIL")'],
  [`=SUM('Trade Detail'!R5:R${lastRow})`, `=${source.stats.totalR}`, "=B9-C9", "=0.000001", '=IF(ABS(D9)<=E9,"OK","FAIL")'],
];
checks.getRange("B6:E8").format.numberFormat = currency;
checks.getRange("B9:E9").format.numberFormat = "0.000000";
body(checks.getRange("A5:F9"));
checks.getRange("F5:F9").conditionalFormats.add("containsText", { text: "OK", format: { fill: green, font: { bold: true, color: "#006100" } } });
checks.getRange("F5:F9").conditionalFormats.add("containsText", { text: "FAIL", format: { fill: red, font: { bold: true, color: "#9C0006" } } });

chartData.getRange(`A1:D${trades.length + 1}`).values = [
  ["Trade", "Fixed R", "2%", "5%"],
  ...trades.map((_, i) => [i + 1, null, null, null])
];
chartData.getRange(`B2:D${trades.length + 1}`).formulas = trades.map((_, i) => {
  const r = i + 5;
  return [`='Trade Detail'!U${r}`, `='Trade Detail'!Y${r}`, `='Trade Detail'!AD${r}`];
});
const chart = summary.charts.add("line", chartData.getRange(`A1:D${trades.length + 1}`));
chart.title = "Equity Curves by Trade";
chart.hasLegend = true;
chart.yAxis = { numberFormatCode: "$#,##0" };
chart.xAxis = { axisType: "textAxis" };
chart.setPosition("F9", "N27");

chartData.getRange("A:D").format.columnWidth = 16;
chartData.getRange("B:D").format.numberFormat = currency;
header(chartData.getRange("A1:D1"));

summary.getRange("A:H").format.columnWidth = 18;
summary.getRange("A:A").format.columnWidth = 24;
detail.getRange("A:AF").format.columnWidth = 13;
detail.getRange("C:C").format.columnWidth = 16;
detail.getRange("O:O").format.columnWidth = 28;
detail.getRange("E:G").format.columnWidth = 12;
yearly.getRange("A:J").format.columnWidth = 16;
assumptions.getRange("A:A").format.columnWidth = 22;
assumptions.getRange("B:B").format.columnWidth = 28;
assumptions.getRange("C:C").format.columnWidth = 18;
assumptions.getRange("D:D").format.columnWidth = 58;
assumptions.getRange("D5:D13").format.wrapText = true;
checks.getRange("A:F").format.columnWidth = 18;
checks.getRange("A:A").format.columnWidth = 28;

await fs.mkdir(previewDir, { recursive: true });
for (const sheetName of ["Summary", "Trade Detail", "Yearly", "Assumptions", "Checks", "Chart Data"]) {
  const preview = await wb.render({ sheetName, autoCrop: "all", scale: sheetName === "Trade Detail" ? 0.7 : 1, format: "png" });
  await fs.writeFile(path.join(previewDir, `${sheetName.replaceAll(" ", "_")}.png`), new Uint8Array(await preview.arrayBuffer()));
}
const xlsx = await SpreadsheetFile.exportXlsx(wb);
await xlsx.save(outputPath);
console.log(outputPath);
console.log((await wb.inspect({ kind: "table", range: "Summary!A4:H17", include: "values,formulas", tableMaxRows: 20, tableMaxCols: 10 })).ndjson);
console.log((await wb.inspect({ kind: "match", searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A", options: { useRegex: true, maxResults: 100 }, summary: "formula errors" })).ndjson);
