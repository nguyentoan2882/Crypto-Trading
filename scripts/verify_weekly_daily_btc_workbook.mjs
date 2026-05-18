import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const file = await FileBlob.load("outputs/weekly_daily_btc_1y/Weekly_Daily_Position_Trend_BTC_1Y_Backtest.xlsx");
const workbook = await SpreadsheetFile.importXlsx(file);

for (const range of ["Summary!A1:I12", "Trade Detail!A1:V8", "Assumptions!A1:B17", "Data Quality!A1:D6"]) {
  const table = await workbook.inspect({
    kind: "table",
    range,
    include: "values,formulas",
    tableMaxRows: 20,
    tableMaxCols: 24,
  });
  console.log(table.ndjson);
}

const errors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 100 },
  summary: "formula error scan",
});
console.log(errors.ndjson);

for (const sheetName of ["Summary", "Trade Detail", "Equity Curve", "Assumptions", "Data Quality"]) {
  const image = await workbook.render({ sheetName, scale: 1 });
  console.log(`Rendered ${sheetName}: ${image.size ?? "ok"}`);
}
