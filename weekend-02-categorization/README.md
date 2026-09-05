# Transaction Categorization Engine

Reads a CSV of parsed BAI bank transactions, runs each one through a
configurable 6-tier rules cascade, and prints:

1. totals per category,
2. a detail listing of every transaction with its assigned category,
3. a separate list of uncategorized transactions flagged for manual review.

Python 3.11+, standard library only. No install step.

## Usage

```
python categorize.py transactions.csv
python categorize.py transactions.csv --rules rules.json
```

- `transactions.csv` — path to the transactions CSV (positional, required).
- `--rules PATH` — path to the JSON rules file. Defaults to `rules.json` in the
  current directory.

Exit code is `0` on a clean run — **including** when some transactions come out
`Uncategorized`; those are a review signal, not an error. Exit code is `1` on a
usage or data error: input or rules file missing, empty CSV, wrong columns, an
unparseable amount or date, invalid rules JSON, or a rule that breaks its tier's
field requirements. Errors go to stderr, results to stdout.

## Input CSV

One row per transaction, with this exact header:

```csv
date,description,amount,bai_code,account,txnid
2026-09-04,ACH PAYMENT TO VENDOR ACCOUNTS PAYABLE INV 88213,-18250.00,455,Operating,OP-1001
2026-09-06,INCOMING WIRE CUSTOMER SETTLEMENT ACME CORP,175000.00,195,Operating,OP-1008
```

- `date` — ISO `YYYY-MM-DD`.
- `description` — free text. Keyword matching against it is case-insensitive
  substring matching.
- `amount` — decimal, no thousands separators, no currency symbol. Negative is
  an outflow, positive an inflow.
- `bai_code` — BAI type code, compared as a string.
- `account` — account label, compared as an exact, case-sensitive string.
- `txnid` — unique id, carried through to the output.

`transactions.csv` in this folder is a worked sample with at least one
transaction for every tier plus three that land in `Uncategorized`.

## Rules file

A JSON object with a `rules` array. Each rule has a `tier` (1-6), a `category`,
and the match fields that tier uses:

| Tier | Matches on | Keywords |
|------|------------|----------|
| 1 | account + bai_code + keywords (exactly 2) | **all** must appear in the description |
| 2 | account + bai_code + keywords (1+) | **any** must appear |
| 3 | account + bai_code | — |
| 4 | account + keywords (1+) | **any** must appear |
| 5 | account | — |
| 6 | keywords (1+) | **any** must appear |

Each transaction is tested against tier 1 rules first, then tier 2, and so on;
within a tier, rules are tried in file order. **The first rule that matches
wins** and evaluation stops. A transaction that matches nothing after tier 6 is
`Uncategorized`.

Tier 1 is the most specific (e.g. "on the Operating account, a BAI 455 ACH debit
whose description contains both *Payment* and *Payable* is A/P"). Tier 5 is for
accounts that always route to one bucket regardless of transaction type. Tier 6
is a description-only catch-all before `Uncategorized`.

A rule that is missing a field its tier needs, carries a field its tier does not
use, has a tier outside 1-6, or (for tier 1) does not have exactly two keywords
is rejected with exit `1`. An empty `rules` array is valid — everything falls
through to `Uncategorized`.

See `rules.json` for a realistic set covering all six tiers (A/P, Credit Card,
Taxes, Real Estate, Payroll, Wire Transfer, Debt Service, and a few more).

## Example output

```
Categorization Summary - transactions.csv
Transactions: 19   Rules: 16   Uncategorized: 3

Category                  Count              Total
Investments                   1        -500,000.00
Real Estate                   2        -372,000.00
Wire Transfer                 2        +166,000.00
...
Uncategorized                 3          -1,765.00
                                  ----------------
TOTAL                        19        -821,955.13

Detail
Date        Account         BAI   Amount          Category              Txn ID
2026-09-04  Operating       455   -18,250.00      A/P                   OP-1001
...

Uncategorized - flagged for manual review (3)
Date        Account         BAI   Amount          Description                       Txn ID
2026-09-08  Operating       399   -815.00         MISC DEBIT ADJUSTMENT REF 90021   OP-1013
...
```

Summary rows are sorted by descending absolute total with `Uncategorized` last;
detail rows stay in input order. Currency is formatted with thousands
separators and two decimals, no symbol, and an explicit `+`/`-` sign.

## Files

```
weekend-02-categorization/
  categorize.py      # the whole tool
  rules.json         # sample rules, all 6 tiers
  transactions.csv   # sample input, 19 transactions
  CLAUDE.md          # project spec
  README.md          # this file
```
