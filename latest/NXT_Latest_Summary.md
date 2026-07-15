# NXT Latest Summary

## Promoted system

NXT v3.5 portfolio for BTCUSDT, BNBUSDT and SOLUSDT using Binance USD-M perpetual 1D candles (00:00 UTC), SSL14, Runner A, Early-BE 7%, anti-immediate-reversal after a runner SSL exit netting at least +0.50R, and LONG-only pullback continuation on an SSL bullish flip.

Promoted rule: block a `SHORT Primary` on the exit candle and the immediately following candle when the prior `LONG` did not reach TP1, exited on an SSL bearish flip, and netted below 0R.

## Backtest basis

- Period: 2020-05-17 to 2026-07-13
- Requested end: 2026-07-15
- Data: Binance USD-M perpetual 1D klines and USD-M historical funding
- Closed trades: 240
- Funding-adjusted total: 164.66R
- Funding-adjusted win rate: 47.50%
- Funding-adjusted profit factor: 2.93
- Funding-adjusted maximum drawdown: -7.23R
- Fixed $1,000/R ending equity: $184,662.87
- Portfolio cap 6% equal split ending equity: $337,653.95
- Open positions at last data date: SOLUSDT LONG entry 2026-06-30 @ 75.13, mark 2026-07-13 @ 74.96, open -0.03R

Note: rerun was requested to 2026-07-15, but Binance archive had closed daily candles available through 2026-07-13 at generation time.

## Published artifacts

- `NXT_Latest_NXT35_USDM_BlockShortAfterLosingLong_FundingAdjusted_20K.json`
- `NXT_Latest_NXT35_USDM_BlockShortAfterLosingLong_FundingAdjusted_20K.xlsx`
- `NXT_Latest_NXT35_USDM_BlockShortAfterLosingLong_System_And_Indicators.docx`
- `NXT_Latest_NXT35_USDM_BlockShortAfterLosingLong_SignalRegression.json`

Signal-level regression for the rule-change publish remains from 2026-07-14: 13 direct blocked SHORT signals mapped to 13 removed baseline SHORT trades; 234 shared trades had no financial mismatch. This 2026-07-15 update refreshes data only and does not change rules.
