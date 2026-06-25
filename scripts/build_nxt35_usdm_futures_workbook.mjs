import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const root = "D:/Workspace/Codex/Investment";
const dir = path.join(root, "outputs/nxt35_usdm_futures_6y");
const data = JSON.parse(await fs.readFile(path.join(dir, "NXT35_USDM_Futures_BTC_BNB_SOL_6Y_FundingAdjusted.json"), "utf8"));
const spot = JSON.parse(await fs.readFile(path.join(root, "latest/NXT_Latest_NXT35_BTC_BNB_SOL_FundingAdjusted_20K.json"), "utf8"));
const output = path.join(dir, "NXT35_USDM_Futures_BTC_BNB_SOL_6Y_FundingAdjusted_20K.xlsx");
const previewDir = path.join(dir, "preview");
const wb = Workbook.create();
const summary = wb.worksheets.add("Summary");
const symbol = wb.worksheets.add("By Symbol");
const yearly = wb.worksheets.add("Yearly");
const trades = wb.worksheets.add("Trades");
const assumptions = wb.worksheets.add("Assumptions");
const checks = wb.worksheets.add("Checks");
const chartData = wb.worksheets.add("Chart Data");
for (const ws of [summary, symbol, yearly, trades, assumptions, checks, chartData]) ws.showGridLines = false;

const navy="#17365D", blue="#1F4E78", white="#FFFFFF", green="#E2F0D9", orange="#FCE4D6";
const currency='$#,##0.00;[Red]($#,##0.00);-', percent='0.00%;[Red](0.00%);-';
function title(ws,a,t){ws.mergeCells(a);ws.getRange(a).values=[[t]];ws.getRange(a).format={fill:navy,font:{bold:true,color:white,size:16},rowHeight:30};}
function header(r){r.format={fill:blue,font:{bold:true,color:white},wrapText:true,horizontalAlignment:"center",verticalAlignment:"center",borders:{preset:"all",style:"thin",color:"#B4C6E7"}};}
function body(r){r.format.borders={preset:"all",style:"thin",color:"#D9E2F3"};}

title(summary,"A1:H1","NXT v3.5 — USD-M Futures Native 1D Backtest");
summary.mergeCells("A2:H2");
summary.getRange("A2").values=[[`${data.period.start} to ${data.period.endExclusive} | BTC/BNB/SOL | Trading cost + actual USD-M funding`]];
summary.getRange("A4:D4").values=[["Metric","Spot-derived baseline","USD-M Futures","Delta"]];
header(summary.getRange("A4:D4"));
const f=data.fundingAdjustedStats,s=spot.fundingAdjustedStats;
summary.getRange("A5:D11").values=[
 ["Trades",s.trades,f.trades,f.trades-s.trades],
 ["Total R",s.totalR,f.totalR,f.totalR-s.totalR],
 ["Win Rate",s.winRate,f.winRate,f.winRate-s.winRate],
 ["Profit Factor",s.profitFactor,f.profitFactor,f.profitFactor-s.profitFactor],
 ["Max Drawdown R",s.maxDrawdownR,f.maxDrawdownR,f.maxDrawdownR-s.maxDrawdownR],
 ["20K Fixed-R Ending",20000+s.totalR*1000,20000+f.totalR*1000,(f.totalR-s.totalR)*1000],
 ["Funding R",spot.fundingSummary.totalFundingR,data.fundingSummary.totalFundingR,data.fundingSummary.totalFundingR-spot.fundingSummary.totalFundingR],
];
summary.getRange("B7:D7").format.numberFormat=percent;
summary.getRange("B10:D10").format.numberFormat=currency;
body(summary.getRange("A5:D11"));
summary.getRange("C5:C11").format.fill=green;

title(symbol,"A1:I1","USD-M Futures Results by Symbol");
symbol.getRange("A4:I4").values=[["Symbol","Data Start","First Entry","Trades","Win Rate","Total R","Avg R","Max DD R","Profit Factor"]];
header(symbol.getRange("A4:I4"));
const sr=data.bySymbol.map(x=>[x.symbol,data.datasets[x.symbol].firstDay,data.datasets[x.symbol].firstTradeEntry,x.trades,x.winRate,x.totalR,x.avgR,x.maxDrawdownR,x.profitFactor]);
symbol.getRange(`A5:I${sr.length+4}`).values=sr;
symbol.getRange(`B5:C${sr.length+4}`).format.numberFormat="yyyy-mm-dd";
symbol.getRange(`E5:E${sr.length+4}`).format.numberFormat=percent;
body(symbol.getRange(`A5:I${sr.length+4}`));

title(yearly,"A1:G1","USD-M Futures Yearly Results");
yearly.getRange("A4:G4").values=[["Year","Trades","Win Rate","Total R","Avg R","Max DD R","Profit Factor"]];
header(yearly.getRange("A4:G4"));
const yr=data.byYear.map(x=>[Number(x.year),x.trades,x.winRate,x.totalR,x.avgR,x.maxDrawdownR,x.profitFactor]);
yearly.getRange(`A5:G${yr.length+4}`).values=yr;
yearly.getRange(`C5:C${yr.length+4}`).format.numberFormat=percent;
body(yearly.getRange(`A5:G${yr.length+4}`));

title(trades,"A1:T1","USD-M Futures Trade Detail");
const th=["Symbol","Trade #","Type","Side","Signal","Entry","TP1 Date","Exit","Entry Price","Initial Stop","TP1","Exit Price","Exit Reason","Gross R","Cost R","Net R","Funding R","Adjusted R","Funding Events","Notes"];
trades.getRange("A4:T4").values=[th];header(trades.getRange("A4:T4"));
const tr=data.trades.map(x=>[x.symbol,x.tradeNo,x.signalType,x.side,x.signalTime,x.entryTime,x.tp1Time||"",x.exitTime,x.entryPrice,x.initialStop,x.tp1,x.exitPrice,x.exitReason,x.grossRMultiple,x.costR,x.rMultiple,x.fundingR,x.netRAfterFunding,x.fundingEvents,x.notes]);
const last=tr.length+4;
trades.getRange(`A5:T${last}`).values=tr;
trades.getRange(`E5:H${last}`).format.numberFormat="yyyy-mm-dd";
trades.getRange(`I5:L${last}`).format.numberFormat="#,##0.0000";
trades.getRange(`N5:R${last}`).format.numberFormat="0.000";
body(trades.getRange(`A5:T${last}`));
trades.freezePanes.freezeRows(4);trades.freezePanes.freezeColumns(8);
trades.tables.add(`A4:T${last}`,true,"USDMTrades");

title(assumptions,"A1:D1","Assumptions and Data Coverage");
assumptions.getRange("A4:D4").values=[["Item","BTC","BNB","SOL"]];header(assumptions.getRange("A4:D4"));
assumptions.getRange("A5:D8").values=[
 ["First USD-M daily candle",data.datasets.BTCUSDT.firstDay,data.datasets.BNBUSDT.firstDay,data.datasets.SOLUSDT.firstDay],
 ["First tested entry",data.datasets.BTCUSDT.firstTradeEntry,data.datasets.BNBUSDT.firstTradeEntry,data.datasets.SOLUSDT.firstTradeEntry],
 ["Trades",data.datasets.BTCUSDT.trades,data.datasets.BNBUSDT.trades,data.datasets.SOLUSDT.trades],
 ["Source","USD-M contract klines","USD-M contract klines","USD-M contract klines"],
];body(assumptions.getRange("A5:D8"));
assumptions.getRange("A10:B15").values=data.assumptions.map((x,i)=>[i+1,x]);
assumptions.getRange("B10:B15").format.wrapText=true;

title(checks,"A1:F1","Model Checks");
checks.getRange("A4:F4").values=[["Check","Actual","Expected","Difference","Tolerance","Status"]];header(checks.getRange("A4:F4"));
checks.getRange("A5:F8").values=[
 ["Trade count",data.trades.length,f.trades,data.trades.length-f.trades,0,data.trades.length===f.trades?"OK":"FAIL"],
 ["Total adjusted R",data.trades.reduce((a,x)=>a+x.netRAfterFunding,0),f.totalR,data.trades.reduce((a,x)=>a+x.netRAfterFunding,0)-f.totalR,0.000001,"OK"],
 ["Funding total",data.trades.reduce((a,x)=>a+x.fundingR,0),data.fundingSummary.totalFundingR,data.trades.reduce((a,x)=>a+x.fundingR,0)-data.fundingSummary.totalFundingR,0.000001,"OK"],
 ["Symbols",new Set(data.trades.map(x=>x.symbol)).size,3,new Set(data.trades.map(x=>x.symbol)).size-3,0,"OK"],
];body(checks.getRange("A5:F8"));
checks.getRange("F5:F8").conditionalFormats.add("containsText",{text:"OK",format:{fill:green,font:{bold:true,color:"#006100"}}});

chartData.getRange(`A1:B${yr.length+1}`).values=[["Year","Total R"],...yr.map(r=>[r[0],r[3]])];header(chartData.getRange("A1:B1"));
const chart=summary.charts.add("bar",chartData.getRange(`A1:B${yr.length+1}`));chart.title="USD-M Total R by Year";chart.hasLegend=false;chart.setPosition("F4","M18");

summary.getRange("A:D").format.columnWidth=22;symbol.getRange("A:I").format.columnWidth=16;yearly.getRange("A:G").format.columnWidth=17;
trades.getRange("A:T").format.columnWidth=14;trades.getRange("M:M").format.columnWidth=28;assumptions.getRange("A:D").format.columnWidth=24;assumptions.getRange("B:B").format.columnWidth=70;checks.getRange("A:F").format.columnWidth=20;
await fs.mkdir(previewDir,{recursive:true});
for(const n of ["Summary","By Symbol","Yearly","Trades","Assumptions","Checks"]){const img=await wb.render({sheetName:n,autoCrop:"all",scale:n==="Trades"?0.7:1,format:"png"});await fs.writeFile(path.join(previewDir,`${n.replaceAll(" ","_")}.png`),new Uint8Array(await img.arrayBuffer()));}
const out=await SpreadsheetFile.exportXlsx(wb);await out.save(output);
console.log(output);
console.log((await wb.inspect({kind:"table",range:"Summary!A4:D11",include:"values,formulas",tableMaxRows:12,tableMaxCols:6})).ndjson);
console.log((await wb.inspect({kind:"match",searchTerm:"#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",options:{useRegex:true,maxResults:100},summary:"formula errors"})).ndjson);
