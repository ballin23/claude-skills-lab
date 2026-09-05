# Transaction Categorization Engine

A small Python command-line tool that reads a CSV of parsed BAI bank
transactions, runs each one through a configurable 6-tier rules cascade, and
reports totals per category, a categorized detail listing, and a separate list
of uncategorized transactions flagged for manual review.

This mirrors a real treasury workflow: every day the bank feed lands as parsed
BAI activity, and someone has to bucket each line into a cash-flow category
(A/P, A/R, payroll, fees, intercompany, investments, ...) so the day's activity
can be reported and forecast. The rules are fiddly and bank-specific, so they
live in an editable config rather than in code.

## Scope

Keep it simple. This is a weekend project.

- One Python script. No package, no framework, no external dependencies beyond
  the standard library (`csv`, `json`, `argparse`, `decimal`, `pathlib`,
  `sys`).
- A CSV in and a JSON rules file in, formatted text out to the terminal.
- No database, no config beyond the one rules file, no network calls.

## Layout

```
weekend-02-categorization/
  CLAUDE.md
  categorize.py        # the whole tool
  rules.json           # sample / working rules config
  transactions.csv     # sample input
  README.md            # short usage notes for a human
```

## Input format

A single CSV file of parsed BAI transactions. Header row plus one row per
transaction.

```csv
date,description,amount,bai_code,account,txnid
2026-09-04,LOCKBOX DEPOSIT 88213,125430.00,195,Operating,CH-000481
2026-09-04,ACH PAYMENT VENDOR PAYABLE INV 5567,-18200.00,455,Operating,CH-000482
2026-09-04,WIRE FEE,-15.00,555,Operating,CH-000483
```

- `date`: ISO date (`YYYY-MM-DD`).
- `description`: free text, upper- or mixed-case. Keyword matching against this
  field is case-insensitive substring matching.
- `amount`: decimal, no thousands separators, no currency symbol. Negative is a
  debit / outflow, positive is a credit / inflow. Parsed with
  `decimal.Decimal`.
- `bai_code`: BAI type code. Compared as a trimmed string (so `455` and `"455"`
  are the same; leading zeros are preserved).
- `account`: account label, e.g. `Operating`, `Payroll`. Compared as an exact,
  case-sensitive string.
- `txnid`: unique transaction id, carried through to the detail and review
  listings.

A row that is missing a column, has an unparseable `amount`, or an unparseable
`date` is a data error (see exit codes) — it is not silently skipped.

## Rules config

A single JSON file, default `rules.json`, overridable with `--rules`.

```json
{
  "rules": [
    { "tier": 1, "account": "Operating", "bai_code": "455",
      "keywords": ["Payment", "Payable"], "category": "A/P" },
    { "tier": 2, "account": "Operating", "bai_code": "195",
      "keywords": ["Lockbox"], "category": "A/R" },
    { "tier": 3, "account": "Payroll", "bai_code": "475",
      "category": "Payroll Disbursement" },
    { "tier": 4, "account": "Operating",
      "keywords": ["Wire Fee", "Service Charge", "Analysis Charge"],
      "category": "Bank Fees" },
    { "tier": 5, "account": "Investment Sweep", "category": "Investments" },
    { "tier": 6, "keywords": ["Interest"], "category": "Interest Income" }
  ]
}
```

Each rule has a `tier` (1-6), a `category`, and the match fields required by its
tier:

| Tier | Match fields | Keyword rule |
|------|--------------|--------------|
| 1 | `account` + `bai_code` + `keywords` (exactly 2) | **all** listed keywords must appear in `description` |
| 2 | `account` + `bai_code` + `keywords` (1 or more) | **any** listed keyword must appear |
| 3 | `account` + `bai_code` | — |
| 4 | `account` + `keywords` (1 or more) | **any** listed keyword must appear |
| 5 | `account` | — |
| 6 | `keywords` (1 or more) | **any** listed keyword must appear |

Tiers go from most specific (1) to last-resort catch-all (6). Tier 5 is for
accounts that always route to one bucket regardless of transaction type. Tier 6
is a description-only net before "Uncategorized".

A rule that is missing a field its tier requires, carries a field its tier does
not use, or has a `tier` outside 1-6 is a config error (exit `1`). A rules file
with an empty `rules` list is valid — everything falls through to
"Uncategorized".

## The cascade

For each transaction:

1. Consider rules in ascending tier order (all tier-1 rules, then all tier-2,
   ...). Within a tier, use file order.
2. The first rule whose every condition holds wins. Assign its `category` and
   stop — no later tier or rule is checked.
3. If no rule matches after tier 6, the category is `Uncategorized`.

First match wins. Keyword comparisons are case-insensitive substring tests
against `description`; `account` and `bai_code` are exact string matches.

## Usage

```
python categorize.py transactions.csv
python categorize.py transactions.csv --rules rules.json
```

- Positional arg: path to the transactions CSV.
- `--rules PATH`: path to the JSON rules file. Default `rules.json` in the
  current directory.

## Output

Plain text to stdout, in three sections.

```
Categorization Summary - transactions.csv
Transactions: 42   Rules: 11   Uncategorized: 3

Category                  Count   Total
A/P                          14   -412,300.00
A/R                          11   +865,120.00
Bank Fees                     6   -1,240.00
Payroll Disbursement          2   -96,400.00
Investments                   4   -250,000.00
Interest Income               2   +1,905.00
Uncategorized                 3   -8,415.00
                        -----------------------
TOTAL                        42   +98,670.00

Detail
Date         Account    BAI   Amount          Category               Txn ID
2026-09-04   Operating  195   +125,430.00     A/R                    CH-000481
2026-09-04   Operating  455   -18,200.00      A/P                    CH-000482
2026-09-04   Operating  555   -15.00          Bank Fees              CH-000483
...

Uncategorized - flagged for manual review (3)
Date         Account    BAI   Amount          Description                    Txn ID
2026-09-04   Operating  399   -8,400.00       MISC DEBIT ADJUSTMENT          CH-000501
...
```

- Summary rows sorted by descending absolute total, with `Uncategorized` last
  and a `TOTAL` line.
- Detail rows in input order.
- Currency formatted with thousands separators and two decimals, no symbol,
  explicit `+` / `-` sign.
- The uncategorized section is always printed, showing `(0)` and no rows when
  everything categorized.

## Exit codes

- `0` — clean run, including a run where some transactions are `Uncategorized`.
  Uncategorized transactions are a review signal, not an error.
- `1` — usage or data error: input file missing or unreadable, empty CSV,
  missing/extra columns, unparseable `amount` or `date`, rules file missing or
  not valid JSON, or a rule that violates its tier's field requirements.

## Conventions

- Target Python 3.11+.
- Use `argparse` for the CLI, `csv.DictReader` for the input, `json` for the
  rules file.
- Represent money with `decimal.Decimal`, not `float`.
- Keep functions small and pure where practical: rules loading + validation,
  matching one transaction against the cascade, aggregating totals per category,
  and formatting each output section should be separable so they can be tested
  without running the CLI.
- Keep the tier-to-required-fields rule in exactly one place.
- Write errors to stderr, results to stdout.
- Format with `black` defaults if formatting comes up.

## Testing

If tests are added, use `pytest` and cover:

- each tier matching on its own (a transaction that only a tier-N rule can
  catch lands in that category);
- first-match-wins: a transaction that satisfies both a tier-2 and a tier-3
  rule takes the tier-2 category; two rules in the same tier resolve by file
  order;
- tier 1 requires **both** keywords — a description with only one of the two
  falls through;
- tiers 2 / 4 / 6 match on **any** one keyword;
- keyword matching is case-insensitive substring (`"payable"` matches
  `"VENDOR PAYABLE"`);
- `bai_code` given as a JSON number and as a string both match a string BAI
  code in the CSV;
- the same `account` with two different `bai_code`s routes to two different
  categories via tier 3;
- tier 5 routes every transaction on an account to one bucket regardless of
  BAI code or description;
- a transaction that matches nothing becomes `Uncategorized` and the run still
  exits `0`;
- category totals math, including negative amounts and a category whose total
  nets to zero;
- error handling: missing CSV, CSV with a bad `amount`, missing rules file,
  malformed rules JSON, and a rule missing a field its tier requires.
