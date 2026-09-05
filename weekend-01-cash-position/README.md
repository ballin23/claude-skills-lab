# Daily Cash Position Tracker

A single Python script that consolidates a folder of per-bank daily balance
files into one cash position, shows the day-over-day change per account, and
flags accounts that moved by more than a threshold percentage.

This mirrors a morning treasury routine: pull balances for every bank account,
check the total position, and investigate anything that swung materially since
the prior close.

## Requirements

- Python 3.11+
- Standard library only. No install step, no dependencies.

## Input

One CSV file per bank per day, all in the same folder. The bank and date come
from the filename, not from inside the file:

```
balances/
  chase_2026-09-03.csv
  bofa_2026-09-03.csv
  wells_2026-09-03.csv
  chase_2026-09-04.csv
  ...
```

- Filename: `<bank>_<YYYY-MM-DD>.csv`. The bank token is everything before the
  last underscore; the date is the last token before `.csv`. Files that don't
  match are skipped with a warning.
- File contents: an `account,balance` header, then one row per account.

```csv
account,balance
Operating,8420000.00
Payroll,1250000.00
Controlled Disbursement,0.00
```

Balances are plain decimals — no currency symbol, no thousands separators — and
may be negative. An account is identified by its `(bank, account)` pair, so two
banks can both have an `Operating` account.

## Usage

```
python cash_position.py balances/
python cash_position.py balances/ --threshold 5
python cash_position.py balances/ --date 2026-09-04
```

- `folder` — path to the folder of per-bank daily CSVs.
- `--threshold PCT` — percent day-over-day move that triggers a flag. Default `10`.
- `--date YYYY-MM-DD` — treat this date as "today" and compare it to the most
  recent earlier date. Defaults to the latest date found across all files.

The tool reads every matching CSV, then compares the two most recent dates
across all banks.

## Output

```
Cash Position - 2026-09-05 (prior: 2026-09-04)
Files read: 9 across 3 banks (bofa, chase, wells)

Bank    Account                   Prior          Current        Change          Change %
bofa    FX Settlement             -45,000.00     -45,000.00     +0.00           +0.0%
bofa    Investment Sweep          3,100,000.00   3,600,000.00   +500,000.00     +16.1%  ** FLAG
bofa    Money Market              5,650,000.00   5,655,000.00   +5,000.00       +0.1%
chase   Controlled Disbursement   0.00           0.00           +0.00           n/a
chase   Operating                 7,980,000.00   9,650,000.00   +1,670,000.00   +20.9%  ** FLAG
chase   Payroll                   1,180,000.00   1,175,000.00   -5,000.00       -0.4%
chase   Tax Reserve               n/a            900,000.00     n/a             n/a
wells   Debt Service Reserve      1,500,000.00   1,500,000.00   +0.00           +0.0%
wells   Operating                 2,340,000.00   2,300,000.00   -40,000.00      -1.7%

Total cash position:   24,735,000.00
Change from prior day: +3,030,000.00  (+14.0%)

2 accounts moved more than 10.0%.
```

- Rows are sorted by bank, then account.
- An account present on only one of the two dates shows `n/a` on the missing
  side and is not flagged. `Change %` is also `n/a` when the prior balance is
  zero.
- Results go to stdout; warnings and errors go to stderr.
- Exit code is `0` on a clean run and `1` on a usage or data error (folder
  missing or empty, no files match the naming pattern, an unparseable row, or
  fewer than two distinct dates).

## Sample data

The `balances/` folder holds three banks across three days
(2026-09-03 to 2026-09-05) for a quick demo, including a new account that
appears only on the last day, a zero-balance disbursement account, a negative
FX settlement balance, and two accounts that breach the default 10% threshold.
