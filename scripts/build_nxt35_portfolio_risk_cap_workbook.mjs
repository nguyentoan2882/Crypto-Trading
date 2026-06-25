import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const root = "D:/Workspace/Codex/Investment";
const dir = path.join(root, "outputs/nxt35_portfolio_risk_cap_3pct");
const sourcePath = path.join(dir, "NXT35_BTC_BNB_SOL_6Y_RiskCap3pct.json");
const outputPath = path.join(dir, "NXT35_BTC_BNB_SOL_6Y_RiskCap3pct_20K.xlsx");
const previewDir = path.join(dir, "preview");
const data = JSON.parse(await fs.readFile(sourcePath, "utf8"));
const result = data.result;
const trades = result.tradeDetail;

const wb = Workbook.create();
const summary = wb.worksheets.add("Summary");
const detail = wb.worksheets.add("Trade Detail");
const yearly = wb.worksheets.add("Yearly");
const capped = wb.worksheets.add("Capped Entries");
const assumptions = wb.worksheets.add("Assumptions");
const checks = wb.worksheets.add("Checks");
const chartData = wb.worksheets.add("Chart Data");
for (const ws of [summary, detail, yearly, capped, assumptions, checks, chartData]) ws.showGridLines = false;

const navy = "#17365D", blue = "#1F4E78", white = "#FFFFFF", pale = "#D9EAF7";
const green = "#E2F0D9", orange = "#FCE4D6", gray = "#F2F2F2";
const currency = '$#,##0.00;[Red]($#,##0.00);-';
const percent = '0.00%;[Red](0.00%);-';

function title(ws, address, text) {
  ws.mergeCells(address);
  ws.getRange(address).values = [[text]];
  ws.getRange(address).format = { fill: navy, font: { bold: true, color: white, size: 16 }, rowHeight: 30 };
}
function header(r) {
  r.format = {
    fill: blue, font: { bold: true, color: white }, wrapText: true,
    horizontalAlignment: "center", verticalAlignment: "center",
    borders: { preset: "all", style: "thin", color: "#B4C6E7" },
  };
}
function borders(r) {
  r.format.borders = { preset: "all", style: "thin", color: "#D9E2F3" };
}

title(summary, "A1:H1", "NXT v3.5 BTC–BNB–SOL — Portfolio Risk Cap 3%");
summary.mergeCells("A2:H2");
summary.getRange("A2").values = [[`${data.period.start} to ${data.period.end} | Starting equity $20,000 | Funding-adjusted Net R`]];
summary.getRange("A2:H2").format = { fill: pale, font: { italic: true, color: "#404040" } };
summary.getRange("A4:D4").values = [["Risk Rule", "BTC", "BNB", "SOL"]];
header(summary.getRange("A4:D4"));
summary.getRange("A5:D7").values = [
  ["Per-symbol maximum", 0.015, 0.0075, 0.0075],
  ["Portfolio cap", 0.03, 0.03, 0.03],
  ["Equity basis", "Realized equity", "Realized equity", "Realized equity"],
];
summary.getRange("B5:D6").format.numberFormat = percent;
summary.getRange("B5:D6").format.font = { color: "#0000FF" };
borders(summary.getRange("A5:D7"));

summary.getRange("A9:C9").values = [["Metric", "Result", "Interpretation"]];
header(summary.getRange("A9:C9"));
summary.getRange("A10:A19").values = [
  ["Starting Equity"], ["Ending Equity"], ["Net Profit"], ["Total Return"], ["Max Drawdown $"],
  ["Max Drawdown %"], ["Trades"], ["Capped Entries"], ["Skipped Entries"], ["Maximum Open Risk"],
];
summary.getRange("B10:B19").values = [[
  result.startingEquity], [result.endingEquity], [result.netProfit], [result.returnPct],
  [result.maxDrawdownDollars], [result.maxDrawdownPct], [result.trades], [result.cappedEntries],
  [result.skippedEntries], [result.maxOpenRiskPctAtEntry],
];
summary.getRange("C10:C19").values = [
  ["Initial account"], ["Final realized equity"], ["After costs and funding"], ["Compounded return"],
  ["Closed-trade equity curve"], ["Peak-to-trough"], ["All NXT signals retained"],
  ["Risk reduced by 3% cap"], ["No trade received zero size"], ["Cap respected at entry"],
];
summary.getRange("B10:B12").format.numberFormat = currency;
summary.getRange("B13:B13").format.numberFormat = percent;
summary.getRange("B14:B14").format.numberFormat = currency;
summary.getRange("B15:B15").format.numberFormat = percent;
summary.getRange("B19:B19").format.numberFormat = percent;
borders(summary.getRange("A10:C19"));
summary.getRange("B11:B19").format.fill = green;

summary.getRange("F4:H4").values = [["Scenario", "Ending Equity", "Max DD %"]];
header(summary.getRange("F4:H4"));
summary.getRange("F5:H5").values = [["Risk Cap 3%", result.endingEquity, result.maxDrawdownPct]];
summary.getRange("G5").format.numberFormat = currency;
summary.getRange("H5").format.numberFormat = percent;
borders(summary.getRange("F5:H5"));

const headers = [
  "Exit Seq", "Symbol", "Trade #", "Type", "Side", "Signal Date", "Entry Date", "TP1 Date", "Exit Date",
  "Entry Price", "Initial Stop", "TP1", "Exit Price", "Exit Reason", "Net R After Funding",
  "Symbol Limit %", "Equity at Entry", "Requested Risk $", "Open Risk Before $", "Capacity Before $",
  "Allocated Risk $", "Allocated Risk %", "Open Risk After $", "Open Risk After %", "Capped?", "Skipped?",
  "P&L $", "Equity After Exit", "Drawdown $", "Drawdown %"
];
title(detail, "A1:AD1", "Trade Detail — Portfolio Risk Allocation");
detail.mergeCells("A2:AD2");
detail.getRange("A2").values = [["Risk is allocated at entry from realized equity. TP1 releases initial risk after same-day entries are processed."]];
detail.getRange("A4:AD4").values = [headers];
header(detail.getRange("A4:AD4"));
const detailRows = trades.map(t => [
  t.exitSequence, t.symbol, t.tradeNo, t.signalType, t.side, t.signalTime, t.entryTime, t.tp1Time || "", t.exitTime,
  t.entryPrice, t.initialStop, t.tp1, t.exitPrice, t.exitReason, t.netRAfterFunding,
  t.symbolLimitPct, t.equityAtEntry, t.requestedRisk, t.openRiskBefore, t.capacityBefore,
  t.allocatedRisk, t.allocatedRiskPct, t.openRiskAfter, t.openRiskAfterPct, t.wasCapped, t.wasSkipped,
  t.pnl, t.equityAfterExit, t.drawdown, t.drawdownPct
]);
const last = detailRows.length + 4;
detail.getRange(`A5:AD${last}`).values = detailRows;
detail.getRange(`F5:I${last}`).format.numberFormat = "yyyy-mm-dd";
detail.getRange(`J5:O${last}`).format.numberFormat = "#,##0.0000";
detail.getRange(`P5:P${last}`).format.numberFormat = percent;
detail.getRange(`Q5:U${last}`).format.numberFormat = currency;
detail.getRange(`V5:V${last}`).format.numberFormat = percent;
detail.getRange(`W5:W${last}`).format.numberFormat = currency;
detail.getRange(`X5:X${last}`).format.numberFormat = percent;
detail.getRange(`AA5:AC${last}`).format.numberFormat = currency;
detail.getRange(`AD5:AD${last}`).format.numberFormat = percent;
detail.getRange(`A5:AD${last}`).format.font = { color: "#0000FF" };
borders(detail.getRange(`A5:AD${last}`));
detail.getRange(`Y5:Y${last}`).conditionalFormats.add("cellIs", { operator: "equal", formula: "TRUE", format: { fill: orange, font: { bold: true, color: "#9C5700" } } });
detail.freezePanes.freezeRows(4);
detail.freezePanes.freezeColumns(9);
detail.tables.add(`A4:AD${last}`, true, "RiskCapTrades");

title(yearly, "A1:F1", "Yearly Performance");
yearly.getRange("A4:F4").values = [["Year", "Trades", "P&L $", "Ending Equity", "Capped Entries", "Skipped Entries"]];
header(yearly.getRange("A4:F4"));
yearly.getRange(`A5:F${data.result.yearly.length + 4}`).values = data.result.yearly.map(y => [
  Number(y.year), y.trades, y.pnl, y.endingEquity, y.cappedEntries, y.skippedEntries
]);
yearly.getRange(`C5:D${data.result.yearly.length + 4}`).format.numberFormat = currency;
borders(yearly.getRange(`A5:F${data.result.yearly.length + 4}`));

const cappedRows = trades.filter(t => t.wasCapped);
title(capped, "A1:J1", "Entries Reduced by Portfolio Cap");
capped.getRange("A4:J4").values = [["Symbol", "Entry Date", "Exit Date", "Equity", "Requested Risk", "Open Risk Before", "Capacity", "Allocated Risk", "Requested %", "Allocated %"]];
header(capped.getRange("A4:J4"));
capped.getRange(`A5:J${cappedRows.length + 4}`).values = cappedRows.map(t => [
  t.symbol, t.entryTime, t.exitTime, t.equityAtEntry, t.requestedRisk, t.openRiskBefore,
  t.capacityBefore, t.allocatedRisk, t.symbolLimitPct, t.allocatedRiskPct
]);
capped.getRange(`B5:C${cappedRows.length + 4}`).format.numberFormat = "yyyy-mm-dd";
capped.getRange(`D5:H${cappedRows.length + 4}`).format.numberFormat = currency;
capped.getRange(`I5:J${cappedRows.length + 4}`).format.numberFormat = percent;
borders(capped.getRange(`A5:J${cappedRows.length + 4}`));

title(assumptions, "A1:D1", "Assumptions and Execution Rules");
assumptions.getRange("A4:D4").values = [["Item", "Value", "Unit", "Notes"]];
header(assumptions.getRange("A4:D4"));
assumptions.getRange("A5:D13").values = [
  ["Starting equity", 20000, "USD", "Realized account equity"],
  ["BTC maximum", 0.015, "% equity", "Maximum requested initial risk"],
  ["BNB maximum", 0.0075, "% equity", "Maximum requested initial risk"],
  ["SOL maximum", 0.0075, "% equity", "Maximum requested initial risk"],
  ["Portfolio cap", 0.03, "% equity", "Total currently open initial risk"],
  ["Sizing time", "Entry date", "", "Uses realized equity available at entry"],
  ["TP1", "Releases risk", "", "Runner stop is assumed at breakeven after TP1"],
  ["Same-day TP1/entry", "Entry first", "", "Conservative because D1 data lacks intraday ordering"],
  ["P&L recognition", "Exit date", "", "No mark-to-market unrealized P&L"],
];
assumptions.getRange("B5").format.numberFormat = currency;
assumptions.getRange("B6:B9").format.numberFormat = percent;
borders(assumptions.getRange("A5:D13"));

title(checks, "A1:F1", "Model Checks");
checks.getRange("A4:F4").values = [["Check", "Actual", "Expected", "Difference", "Tolerance", "Status"]];
header(checks.getRange("A4:F4"));
checks.getRange("A5:A9").values = [["Trade count"], ["Ending equity"], ["Capped entry count"], ["Skipped entry count"], ["Maximum open risk"]];
checks.getRange("B5:F9").formulas = [
  [`=COUNTA('Trade Detail'!A5:A${last})`, `=${result.trades}`, "=B5-C5", "=0", '=IF(ABS(D5)<=E5,"OK","FAIL")'],
  [`=LOOKUP(2,1/('Trade Detail'!AB5:AB${last}<>\"\"),'Trade Detail'!AB5:AB${last})`, `=${result.endingEquity}`, "=B6-C6", "=0.01", '=IF(ABS(D6)<=E6,"OK","FAIL")'],
  [`=COUNTA('Capped Entries'!A5:A${cappedRows.length + 4})`, `=${result.cappedEntries}`, "=B7-C7", "=0", '=IF(ABS(D7)<=E7,"OK","FAIL")'],
  [`=COUNTIF('Trade Detail'!Z5:Z${last},TRUE)`, `=${result.skippedEntries}`, "=B8-C8", "=0", '=IF(ABS(D8)<=E8,"OK","FAIL")'],
  [`=MAX('Trade Detail'!X5:X${last})`, "=3%", "=B9-C9", "=0.0000001", '=IF(ABS(D9)<=E9,"OK","FAIL")'],
];
checks.getRange("B6:E6").format.numberFormat = currency;
checks.getRange("B9:E9").format.numberFormat = percent;
borders(checks.getRange("A5:F9"));
checks.getRange("F5:F9").conditionalFormats.add("containsText", { text: "OK", format: { fill: green, font: { bold: true, color: "#006100" } } });
checks.getRange("F5:F9").conditionalFormats.add("containsText", { text: "FAIL", format: { fill: orange, font: { bold: true, color: "#9C0006" } } });

chartData.getRange(`A1:B${trades.length + 1}`).values = [["Exit Sequence", "Equity"], ...trades.map(t => [t.exitSequence, t.equityAfterExit])];
header(chartData.getRange("A1:B1"));
chartData.getRange(`B2:B${trades.length + 1}`).format.numberFormat = currency;
const chart = summary.charts.add("line", chartData.getRange(`A1:B${trades.length + 1}`));
chart.title = "Portfolio Equity Curve";
chart.hasLegend = false;
chart.yAxis = { numberFormatCode: "$#,##0" };
chart.xAxis = { axisType: "textAxis" };
chart.setPosition("E9", "M25");

summary.getRange("A:A").format.columnWidth = 25;
summary.getRange("B:D").format.columnWidth = 18;
summary.getRange("C:C").format.columnWidth = 30;
detail.getRange("A:AD").format.columnWidth = 13;
detail.getRange("N:N").format.columnWidth = 28;
yearly.getRange("A:F").format.columnWidth = 18;
capped.getRange("A:J").format.columnWidth = 18;
assumptions.getRange("A:A").format.columnWidth = 24;
assumptions.getRange("B:C").format.columnWidth = 20;
assumptions.getRange("D:D").format.columnWidth = 60;
assumptions.getRange("D5:D13").format.wrapText = true;
checks.getRange("A:F").format.columnWidth = 20;

await fs.mkdir(previewDir, { recursive: true });
for (const name of ["Summary", "Trade Detail", "Yearly", "Capped Entries", "Assumptions", "Checks"]) {
  const image = await wb.render({ sheetName: name, autoCrop: "all", scale: name === "Trade Detail" ? 0.7 : 1, format: "png" });
  await fs.writeFile(path.join(previewDir, `${name.replaceAll(" ", "_")}.png`), new Uint8Array(await image.arrayBuffer()));
}
const out = await SpreadsheetFile.exportXlsx(wb);
await out.save(outputPath);
console.log(outputPath);
console.log((await wb.inspect({ kind: "table", range: "Summary!A4:H19", include: "values,formulas", tableMaxRows: 20, tableMaxCols: 10 })).ndjson);
console.log((await wb.inspect({ kind: "match", searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A", options: { useRegex: true, maxResults: 100 }, summary: "formula errors" })).ndjson);
