# Crypto trading

Workspace for crypto trading strategy documents, backtest scripts, and generated result workbooks.

## Contents

- `scripts/`: backtest, optimization, and workbook verification scripts.
- `*.docx`: strategy documents used as source rules.
- `*.xlsx`: small source/reference workbooks kept in the repository.
- `outputs/`: generated backtest results. This folder is ignored by Git because it can be regenerated and may become large.

## Setup on another computer

1. Clone the repository.
2. Install Node.js.
3. Restore any dependencies needed by the scripts.
4. Run the relevant script from `scripts/`.

Example:

```powershell
node scripts/backtest_htf_pullback.mjs
```
