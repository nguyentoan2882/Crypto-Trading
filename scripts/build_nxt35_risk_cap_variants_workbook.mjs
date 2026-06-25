import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const root = "D:/Workspace/Codex/Investment";
const dir = path.join(root, "outputs/nxt35_portfolio_risk_cap_variants");
const data = JSON.parse(await fs.readFile(path.join(dir, "NXT35_BTC_BNB_SOL_6Y_RiskCap_3_5_6_8pct.json"), "utf8"));
const output = path.join(dir, "NXT35_BTC_BNB_SOL_6Y_RiskCap_3_5_6_8pct_20K.xlsx");
const previewDir = path.join(dir, "preview");
const names = ["Cap 3%", "Cap 5%", "Cap 6%", "Cap 8%"];
const wb = Workbook.create();
const summary = wb.worksheets.add("Summary");
const yearly = wb.worksheets.add("Yearly");
const detail = wb.worksheets.add("Trade Comparison");
const capped = wb.worksheets.add("Capped Entries");
const assumptions = wb.worksheets.add("Assumptions");
const checks = wb.worksheets.add("Checks");
const chartData = wb.worksheets.add("Chart Data");
for (const ws of [summary, yearly, detail, capped, assumptions, checks, chartData]) ws.showGridLines = false;

const navy="#17365D", blue="#1F4E78", white="#FFFFFF", green="#E2F0D9", orange="#FCE4D6";
const currency='$#,##0.00;[Red]($#,##0.00);-', percent='0.00%;[Red](0.00%);-';
function title(ws,a,t){ws.mergeCells(a);ws.getRange(a).values=[[t]];ws.getRange(a).format={fill:navy,font:{bold:true,color:white,size:16},rowHeight:30};}
function header(r){r.format={fill:blue,font:{bold:true,color:white},wrapText:true,horizontalAlignment:"center",verticalAlignment:"center",borders:{preset:"all",style:"thin",color:"#B4C6E7"}};}
function body(r){r.format.borders={preset:"all",style:"thin",color:"#D9E2F3"};}

title(summary,"A1:H1","NXT v3.5 BTC–BNB–SOL — Risk Cap Variants");
summary.mergeCells("A2:H2");
summary.getRange("A2").values=[[`${data.period.start} to ${data.period.end} | Starting equity $20,000 | BTC:BNB:SOL allocation = 2:1:1`]];
summary.getRange("A4:H4").values=[["Scenario","BTC Max","BNB Max","SOL Max","Ending Equity","Return","Max DD","Capped Entries"]];
header(summary.getRange("A4:H4"));
const sumRows=names.map(n=>{const s=data.scenarios[n];return[n,s.symbolLimitsPct.BTCUSDT,s.symbolLimitsPct.BNBUSDT,s.symbolLimitsPct.SOLUSDT,s.endingEquity,s.returnPct,s.maxDrawdownPct,s.cappedEntries];});
summary.getRange("A5:H8").values=sumRows;
summary.getRange("B5:D8").format.numberFormat=percent;
summary.getRange("E5:E8").format.numberFormat=currency;
summary.getRange("F5:G8").format.numberFormat=percent;
body(summary.getRange("A5:H8"));
summary.getRange("A5:H5").format.fill=green;
summary.getRange("A8:H8").format.fill=orange;

title(yearly,"A1:I1","Yearly Ending Equity by Scenario");
yearly.getRange("A4:I4").values=[["Year",...names.flatMap(n=>[`${n} P&L`,`${n} End Equity`])]];
header(yearly.getRange("A4:I4"));
const years=data.scenarios[names[0]].yearly.map(y=>y.year);
const yearRows=years.map(y=>[Number(y),...names.flatMap(n=>{const r=data.scenarios[n].yearly.find(x=>x.year===y);return[r.pnl,r.endingEquity];})]);
yearly.getRange(`A5:I${years.length+4}`).values=yearRows;
yearly.getRange(`B5:I${years.length+4}`).format.numberFormat=currency;
body(yearly.getRange(`A5:I${years.length+4}`));

title(detail,"A1:Q1","Trade-by-Trade Scenario Comparison");
detail.getRange("A4:Q4").values=[["Seq","Symbol","Entry","Exit","Net R",...names.flatMap(n=>[`${n} Risk`,`${n} P&L`,`${n} Equity`])]];
header(detail.getRange("A4:Q4"));
const base=data.scenarios[names[0]].tradeDetail;
const rows=base.map((t,i)=>[t.exitSequence,t.symbol,t.entryTime,t.exitTime,t.netRAfterFunding,...names.flatMap(n=>{const x=data.scenarios[n].tradeDetail[i];return[x.allocatedRisk,x.pnl,x.equityAfterExit];})]);
detail.getRange(`A5:Q${rows.length+4}`).values=rows;
detail.getRange(`C5:D${rows.length+4}`).format.numberFormat="yyyy-mm-dd";
detail.getRange(`F5:Q${rows.length+4}`).format.numberFormat=currency;
body(detail.getRange(`A5:Q${rows.length+4}`));
detail.freezePanes.freezeRows(4);detail.freezePanes.freezeColumns(4);
detail.tables.add(`A4:Q${rows.length+4}`,true,"VariantTrades");

title(capped,"A1:I1","Entries Capped in Each Scenario");
capped.getRange("A4:I4").values=[["Scenario","Symbol","Entry","Exit","Requested Risk","Open Risk Before","Capacity","Allocated Risk","Allocated %"]];
header(capped.getRange("A4:I4"));
const capRows=names.flatMap(n=>data.scenarios[n].tradeDetail.filter(t=>t.wasCapped).map(t=>[n,t.symbol,t.entryTime,t.exitTime,t.requestedRisk,t.openRiskBefore,t.capacityBefore,t.allocatedRisk,t.allocatedRiskPct]));
capped.getRange(`A5:I${capRows.length+4}`).values=capRows;
capped.getRange(`C5:D${capRows.length+4}`).format.numberFormat="yyyy-mm-dd";
capped.getRange(`E5:H${capRows.length+4}`).format.numberFormat=currency;
capped.getRange(`I5:I${capRows.length+4}`).format.numberFormat=percent;
body(capped.getRange(`A5:I${capRows.length+4}`));

title(assumptions,"A1:D1","Assumptions");
assumptions.getRange("A4:D4").values=[["Item","Value","Unit","Notes"]];header(assumptions.getRange("A4:D4"));
assumptions.getRange("A5:D12").values=[
 ["Allocation ratio","2:1:1","BTC:BNB:SOL","BTC receives half of the total cap; BNB and SOL receive one quarter each"],
 ["Cap 3%","1.50 / 0.75 / 0.75","% equity","Current conservative baseline"],
 ["Cap 5%","2.50 / 1.25 / 1.25","% equity","Balanced-aggressive"],
 ["Cap 6%","3.00 / 1.50 / 1.50","% equity","Aggressive"],
 ["Cap 8%","4.00 / 2.00 / 2.00","% equity","Very aggressive"],
 ["Equity basis","Realized equity","","Risk locked at entry"],
 ["TP1 release","After TP1","","Same-day entries cannot reuse TP1 risk"],
 ["Drawdown","Closed-trade equity","","Does not include intratrade mark-to-market loss"],
];body(assumptions.getRange("A5:D12"));

title(checks,"A1:F1","Model Checks");
checks.getRange("A4:F4").values=[["Scenario","Trades","Capped","Skipped","Max Open Risk","Status"]];header(checks.getRange("A4:F4"));
checks.getRange("A5:F8").values=names.map(n=>{const s=data.scenarios[n];return[n,s.trades,s.cappedEntries,s.skippedEntries,s.maxOpenRiskPctAtEntry,Math.abs(s.maxOpenRiskPctAtEntry-s.portfolioCapPct)<1e-9?"OK":"FAIL"];});
checks.getRange("E5:E8").format.numberFormat=percent;body(checks.getRange("A5:F8"));
checks.getRange("F5:F8").conditionalFormats.add("containsText",{text:"OK",format:{fill:green,font:{bold:true,color:"#006100"}}});

chartData.getRange(`A1:E${base.length+1}`).values=[["Seq",...names],...base.map((t,i)=>[t.exitSequence,...names.map(n=>data.scenarios[n].tradeDetail[i].equityAfterExit)])];
header(chartData.getRange("A1:E1"));chartData.getRange(`B2:E${base.length+1}`).format.numberFormat=currency;
const chart=summary.charts.add("line",chartData.getRange(`A1:E${base.length+1}`));chart.title="Equity Curves";chart.hasLegend=true;chart.yAxis={numberFormatCode:"$#,##0"};chart.xAxis={axisType:"textAxis"};chart.setPosition("A10","J28");

summary.getRange("A:H").format.columnWidth=17;yearly.getRange("A:I").format.columnWidth=17;detail.getRange("A:Q").format.columnWidth=14;
capped.getRange("A:I").format.columnWidth=18;assumptions.getRange("A:A").format.columnWidth=22;assumptions.getRange("B:C").format.columnWidth=22;assumptions.getRange("D:D").format.columnWidth=60;checks.getRange("A:F").format.columnWidth=18;
await fs.mkdir(previewDir,{recursive:true});
for(const n of ["Summary","Yearly","Trade Comparison","Capped Entries","Assumptions","Checks"]){const img=await wb.render({sheetName:n,autoCrop:"all",scale:n==="Trade Comparison"?0.7:1,format:"png"});await fs.writeFile(path.join(previewDir,`${n.replaceAll(" ","_")}.png`),new Uint8Array(await img.arrayBuffer()));}
const x=await SpreadsheetFile.exportXlsx(wb);await x.save(output);
console.log(output);
console.log((await wb.inspect({kind:"table",range:"Summary!A4:H8",include:"values,formulas",tableMaxRows:10,tableMaxCols:10})).ndjson);
console.log((await wb.inspect({kind:"match",searchTerm:"#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",options:{useRegex:true,maxResults:100},summary:"formula errors"})).ndjson);
