import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const file = await FileBlob.load("outputs/nxt_crypto_btc_sol_sui_3y_v24/NXT_Crypto_BTC_SOL_SUI_3Y_V24_Backtest.xlsx");
const workbook = await SpreadsheetFile.importXlsx(file);

for (const range of [
  "Summary!A1:L12",
  "Trades!A4:AB12",
  "Assumptions!A1:B18",
  "Data Quality!A1:F8",
]) {
  const table = await workbook.inspect({
    kind: "table",
    range,
    include: "values,formulas",
    tableMaxRows: 20,
    tableMaxCols: 28,
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
