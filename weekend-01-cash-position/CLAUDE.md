# Daily Cash Position Tracker

A small Python command-line tool that reads a folder of per-bank daily balance
files, reports the total cash position, shows the day-over-day change per
account, and flags accounts that moved by more than a threshold percentage.

This mirrors a real treasury workflow: each morning you pull balances for every
bank account, check the consolidated position, and investigate any account that
swung materially since the prior close.

## Scope

Keep it simple. This is a weekend project.

- One Python script. No package, no framework, no external dependencies beyond
  the standard library (`csv`, `argparse`, `datetime`, `pathlib`, `sys`).
- A folder of CSVs in, formatted text out to the terminal.
- No database, no config files, no network calls.

## Layout

```
weekend-01-cash-position/
  CLAUDE.md
  cash_position.py     # the whole tool
  balances/            # sample / working input folder (per-bank daily files)
    chase_2026-09-04.csv
    bofa_2026-09-04.csv
    chase_2026-09-05.csv
    bofa_2026-09-05.csv
  README.md            # short usage notes for a human
```

## Input format

One CSV file per bank per day, all sitting in the same folder. The bank and the
date come from the filename, not from inside the file.

- Filename pattern: `<bank>_<YYYY-MM-DD>.csv`, e.g. `chase_2026-09-04.csv`,
  `bofa_2026-09-05.csv`. The bank token is everything before the last
  underscore; the date is the last underscore-delimited token before `.csv` and
  must parse as an ISO date. Files in the folder that don't match are skipped
  with a warning to stderr.
- File contents: a header row plus one row per account for that bank on that
  day.

```csv
account,balance
Operating,1250000.00
Payroll,480000.00
```

- `account`: free-text label. The unique key is the `(bank, account)` pair, so
  two banks may both have an `Operating` account.
- `balance`: decimal, no thousands separators, no currency symbol. May be
  negative (overdraft).

The tool reads every matching CSV in the folder, groups rows by date, and
compares the two most recent dates found across all banks. An account present on
only one of those two dates is still listed, with the missing side shown as
`n/a` and no percentage change. A bank that is missing entirely on one of the
two dates just means all of its accounts show `n/a` on that side.

## Usage

```
python cash_position.py balances/
python cash_position.py balances/ --threshold 5
python cash_position.py balances/ --date 2026-09-05
```

- Positional arg: path to the folder of per-bank daily CSVs.
- `--threshold PCT`: percent move that triggers a flag. Default `10`.
- `--date YYYY-MM-DD`: treat this date as "today" and compare it to the most
  recent prior date. Defaults to the latest date found across all files.

## Output

Plain text table to stdout, followed by a summary:

```
Cash Position - 2026-09-05 (prior: 2026-09-04)
Files read: 4 across 2 banks (chase, bofa)

Bank    Account         Prior          Current        Change         Change %
chase   Operating       1,250,000.00   1,180,000.00   -70,000.00     -5.6%
chase   Payroll         480,000.00     475,000.00     -5,000.00      -1.0%
bofa    Money Market    3,100,000.00   3,550,000.00   +450,000.00    +14.5%  ** FLAG

Total cash position:   5,205,000.00
Change from prior day: +375,000.00  (+7.8%)

1 account moved more than 10.0%.
```

- Rows sorted by bank, then account.
- Currency formatted with thousands separators and two decimals; no symbol.
- Changes carry an explicit `+` / `-` sign.
- Flagged rows are marked with a trailing `** FLAG` and counted in the summary.
- Exit code `0` on a clean run, `1` on a usage or data error (folder missing or
  empty, no files match the `<bank>_<date>.csv` pattern, unparseable row, fewer
  than two distinct dates across all files).

## Conventions

- Target Python 3.11+.
- Use `argparse` for the CLI, `pathlib` to enumerate the folder, and
  `csv.DictReader` for parsing file contents.
- Parse the bank and date from the filename in one small helper; keep the
  `<bank>_<date>.csv` rule in exactly one place.
- Represent money with `decimal.Decimal`, not `float`.
- Keep functions small and pure where practical: filename parsing, row parsing,
  the position calculation, and formatting should be separable so they can be
  tested without running the CLI.
- Write errors to stderr, results to stdout.
- Format with `black` defaults if formatting comes up.

## Testing

If tests are added, use `pytest` and cover:

- filename parsing: valid `<bank>_<date>.csv`, a name with extra underscores in
  the bank token, and a non-matching name that should be skipped;
- total position and per-account change math, including negative balances;
- threshold flagging exactly at, just under, and just over the boundary;
- an account present on only one of the two compared dates, and a bank missing
  entirely on one date;
- the same account name (`Operating`) at two different banks stays separate;
- error handling for a missing/empty folder and for a folder with only one date.
