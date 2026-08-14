# CSZN income ledger

Standalone tape of venue income. Not part of `run.py`. Does not place orders.

## File

`var/income_ledger.csv` (gitignored). Append-only.

Columns: `time_utc,time_ms,tran_id,trade_id,symbol,income_type,income,asset`

Kept types: `REALIZED_PNL`, `COMMISSION`, `FUNDING_FEE`.

## Run

```bash
cd cszn_trader
source .venv/bin/activate
python tools/sync_ledger.py
```

First run pulls about 30 days. Later runs fetch from the last CSV timestamp (one-minute overlap) and **skip fingerprints already in the file**. Rows already written are never edited or deleted.

Source is signed `GET /fapi/v1/income` on `FAPI_BASE` (demo). Totals printed are **sums of the CSV**, plus current `margin_balance` (that balance includes unrealized and is not equal to ledger net).
