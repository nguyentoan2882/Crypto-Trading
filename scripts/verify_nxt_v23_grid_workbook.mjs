import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const file = await FileBlob.load("outputs/nxt_crypto_btc_sol_sui_3y_grid/NXT_V23_Grid_3Y_BTC_SOL_SUI.xlsx");
const workbook = await SpreadsheetFile.importXlsx(file);

for (const range of [
  "Ranking!A1:O20",
  "Best Summary!A1:J12",
  "Best Trades!A4:T14",
  "Assumptions!A1:B12",
]) {
  const table = await workbook.inspect({
    kind: "table",
    range,
    include: "values,formulas",
    tableMaxRows: 24,
    tableMaxCols: 20,
  });
  console.log(table.ndjson);
}

const errors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 300 },
  summary: "final formula error scan",
});
console.log(errors.ndjson);
