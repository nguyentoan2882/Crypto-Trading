import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const file = await FileBlob.load("outputs/nxt_crypto_btc_sol_sui_1y/NXT_Crypto_BTC_SOL_SUI_1Y_Backtest.xlsx");
const workbook = await SpreadsheetFile.importXlsx(file);

for (const range of [
  "Summary!A1:L12",
  "Trades!A4:Y15",
  "Assumptions!A1:B16",
  "Data Quality!A1:D8",
]) {
  const table = await workbook.inspect({
    kind: "table",
    range,
    include: "values,formulas",
    tableMaxRows: 20,
    tableMaxCols: 25,
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
