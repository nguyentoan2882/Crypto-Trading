import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const variant = process.argv[2] || "";
const file = await FileBlob.load(
  variant === "btc_eth"
    ? "outputs/htf_pullback_backtest_btc_eth/HTF_Trend_Pullback_Backtest_6M_BTC_ETH.xlsx"
    : "outputs/htf_pullback_backtest/HTF_Trend_Pullback_Backtest_6M.xlsx"
);
const workbook = await SpreadsheetFile.importXlsx(file);
const summary = await workbook.inspect({
  kind: "table",
  range: "Summary!A4:L11",
  include: "values,formulas",
  tableMaxRows: 12,
  tableMaxCols: 12,
});
console.log(summary.ndjson);
const trades = await workbook.inspect({
  kind: "table",
  range: "Trades!A4:R12",
  include: "values,formulas",
  tableMaxRows: 10,
  tableMaxCols: 18,
});
console.log(trades.ndjson);
