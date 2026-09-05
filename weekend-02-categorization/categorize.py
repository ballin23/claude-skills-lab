#!/usr/bin/env python3
"""Transaction Categorization Engine.

Reads a CSV of parsed BAI transactions, runs each one through a configurable
6-tier rules cascade (first match wins), and prints totals per category, a
categorized detail listing, and a list of uncategorized transactions flagged
for manual review.

Standard library only. See CLAUDE.md for the full spec.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

EXPECTED_COLUMNS = ["date", "description", "amount", "bai_code", "account", "txnid"]

UNCATEGORIZED = "Uncategorized"

# The match fields each tier uses, in the order they are tested. This is the one
# place the tier -> fields rule lives; validation and matching both read it.
TIER_FIELDS = {
    1: ("account", "bai_code", "keywords"),
    2: ("account", "bai_code", "keywords"),
    3: ("account", "bai_code"),
    4: ("account", "keywords"),
    5: ("account",),
    6: ("keywords",),
}


class UserError(Exception):
    """A usage or data error that should exit 1 with a message on stderr."""


# --------------------------------------------------------------------------- #
# Rules loading + validation
# --------------------------------------------------------------------------- #


def validate_rule(rule: object, index: int) -> None:
    """Raise UserError if ``rule`` is not a well-formed rule for its tier."""
    where = f"rule {index}"
    if not isinstance(rule, dict):
        raise UserError(f"{where}: expected a JSON object")

    tier = rule.get("tier")
    if tier not in TIER_FIELDS:
        raise UserError(f"{where}: tier must be an integer 1-6, got {tier!r}")

    category = rule.get("category")
    if not isinstance(category, str) or not category.strip():
        raise UserError(f"{where}: missing non-empty 'category'")

    allowed = {"tier", "category", *TIER_FIELDS[tier]}
    present = set(rule)
    missing = allowed - present
    if missing:
        raise UserError(
            f"{where} (tier {tier}): missing field(s) {sorted(missing)}"
        )
    extra = present - allowed
    if extra:
        raise UserError(
            f"{where} (tier {tier}): unexpected field(s) {sorted(extra)} "
            f"- tier {tier} uses {sorted(allowed)}"
        )

    if "account" in TIER_FIELDS[tier]:
        if not isinstance(rule["account"], str) or not rule["account"].strip():
            raise UserError(f"{where}: 'account' must be a non-empty string")

    if "bai_code" in TIER_FIELDS[tier]:
        if not isinstance(rule["bai_code"], (str, int)) or isinstance(
            rule["bai_code"], bool
        ):
            raise UserError(f"{where}: 'bai_code' must be a string or integer")

    if "keywords" in TIER_FIELDS[tier]:
        kws = rule["keywords"]
        if not isinstance(kws, list) or not all(
            isinstance(k, str) and k.strip() for k in kws
        ):
            raise UserError(
                f"{where}: 'keywords' must be a list of non-empty strings"
            )
        if tier == 1 and len(kws) != 2:
            raise UserError(
                f"{where}: tier 1 requires exactly 2 keywords, got {len(kws)}"
            )
        if tier != 1 and len(kws) < 1:
            raise UserError(f"{where}: tier {tier} requires at least 1 keyword")


def load_rules(path: str) -> list[dict]:
    """Load, validate, and tier-order the rules file.

    Returns the rules sorted by ascending tier; the sort is stable, so file
    order is preserved within a tier.
    """
    p = Path(path)
    if not p.is_file():
        raise UserError(f"rules file not found: {path}")
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise UserError(f"rules file is not valid JSON: {exc}")

    if not isinstance(data, dict) or not isinstance(data.get("rules"), list):
        raise UserError('rules file must be a JSON object with a "rules" array')

    rules = data["rules"]
    for i, rule in enumerate(rules):
        validate_rule(rule, i)

    return sorted(rules, key=lambda r: r["tier"])


# --------------------------------------------------------------------------- #
# Transaction loading
# --------------------------------------------------------------------------- #


def parse_amount(raw: str, lineno: int) -> Decimal:
    try:
        return Decimal(raw.strip())
    except (InvalidOperation, AttributeError):
        raise UserError(f"row {lineno}: unparseable amount {raw!r}")


def parse_date(raw: str, lineno: int) -> date:
    try:
        return datetime.strptime(raw.strip(), "%Y-%m-%d").date()
    except (ValueError, AttributeError):
        raise UserError(f"row {lineno}: unparseable date {raw!r} (want YYYY-MM-DD)")


def read_transactions(path: str) -> list[dict]:
    p = Path(path)
    if not p.is_file():
        raise UserError(f"input file not found: {path}")

    with p.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames is None:
            raise UserError("input file is empty")
        header = [c.strip() for c in reader.fieldnames]
        if header != EXPECTED_COLUMNS:
            raise UserError(
                f"expected columns {EXPECTED_COLUMNS}, got {reader.fieldnames}"
            )

        txns: list[dict] = []
        for lineno, row in enumerate(reader, start=2):
            if None in row:  # extra values beyond the header
                raise UserError(f"row {lineno}: more values than columns")
            if any(row.get(c) is None for c in EXPECTED_COLUMNS):
                raise UserError(f"row {lineno}: fewer values than columns")

            txns.append(
                {
                    "date": parse_date(row["date"], lineno),
                    "description": row["description"],
                    "amount": parse_amount(row["amount"], lineno),
                    "bai_code": row["bai_code"].strip(),
                    "account": row["account"].strip(),
                    "txnid": row["txnid"].strip(),
                }
            )

    if not txns:
        raise UserError("input file has no transactions")
    return txns


# --------------------------------------------------------------------------- #
# The cascade
# --------------------------------------------------------------------------- #


def rule_matches(rule: dict, txn: dict) -> bool:
    """True if every condition of ``rule`` holds for ``txn``."""
    tier = rule["tier"]
    fields = TIER_FIELDS[tier]

    if "account" in fields and txn["account"] != rule["account"]:
        return False
    if "bai_code" in fields and txn["bai_code"] != str(rule["bai_code"]).strip():
        return False
    if "keywords" in fields:
        haystack = txn["description"].lower()
        needles = [k.lower() for k in rule["keywords"]]
        if tier == 1:
            if not all(n in haystack for n in needles):
                return False
        elif not any(n in haystack for n in needles):
            return False
    return True


def categorize(txn: dict, rules: list[dict]) -> str:
    """Return the category for ``txn``: first matching rule wins, else Uncategorized."""
    for rule in rules:
        if rule_matches(rule, txn):
            return rule["category"]
    return UNCATEGORIZED


# --------------------------------------------------------------------------- #
# Aggregation + formatting
# --------------------------------------------------------------------------- #


def aggregate(results: list[tuple[dict, str]]) -> dict[str, dict]:
    """category -> {"count": int, "total": Decimal}."""
    totals: dict[str, dict] = {}
    for txn, category in results:
        bucket = totals.setdefault(category, {"count": 0, "total": Decimal("0")})
        bucket["count"] += 1
        bucket["total"] += txn["amount"]
    return totals


def money(value: Decimal) -> str:
    q = value.quantize(Decimal("0.01"))
    sign = "-" if q < 0 else "+"
    return f"{sign}{abs(q):,.2f}"


def _clip(text: str, width: int) -> str:
    return text if len(text) <= width else text[: width - 1] + "…"


def format_summary(
    source: str,
    n_txns: int,
    n_rules: int,
    totals: dict[str, dict],
) -> str:
    n_uncat = totals.get(UNCATEGORIZED, {}).get("count", 0)
    lines = [
        f"Categorization Summary - {source}",
        f"Transactions: {n_txns}   Rules: {n_rules}   Uncategorized: {n_uncat}",
        "",
        f"{'Category':<24}{'Count':>7}   {'Total':>16}",
    ]

    def sort_key(item: tuple[str, dict]) -> tuple[int, Decimal]:
        name, bucket = item
        return (1 if name == UNCATEGORIZED else 0, -abs(bucket["total"]))

    grand = Decimal("0")
    for name, bucket in sorted(totals.items(), key=sort_key):
        grand += bucket["total"]
        lines.append(
            f"{_clip(name, 24):<24}{bucket['count']:>7}   {money(bucket['total']):>16}"
        )

    lines.append(f"{'':<24}{'':>7}   {'-' * 16}")
    lines.append(f"{'TOTAL':<24}{n_txns:>7}   {money(grand):>16}")
    return "\n".join(lines)


def format_detail(results: list[tuple[dict, str]]) -> str:
    lines = [
        "Detail",
        f"{'Date':<12}{'Account':<16}{'BAI':<6}{'Amount':<16}"
        f"{'Category':<22}{'Txn ID'}",
    ]
    for txn, category in results:
        lines.append(
            f"{txn['date'].isoformat():<12}"
            f"{_clip(txn['account'], 15):<16}"
            f"{txn['bai_code']:<6}"
            f"{money(txn['amount']):<16}"
            f"{_clip(category, 21):<22}"
            f"{txn['txnid']}"
        )
    return "\n".join(lines)


def format_uncategorized(results: list[tuple[dict, str]]) -> str:
    rows = [txn for txn, category in results if category == UNCATEGORIZED]
    lines = [
        f"Uncategorized - flagged for manual review ({len(rows)})",
    ]
    if rows:
        lines.append(
            f"{'Date':<12}{'Account':<16}{'BAI':<6}{'Amount':<16}"
            f"{'Description':<34}{'Txn ID'}"
        )
        for txn in rows:
            lines.append(
                f"{txn['date'].isoformat():<12}"
                f"{_clip(txn['account'], 15):<16}"
                f"{txn['bai_code']:<6}"
                f"{money(txn['amount']):<16}"
                f"{_clip(txn['description'], 33):<34}"
                f"{txn['txnid']}"
            )
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Categorize parsed BAI transactions with a 6-tier rules cascade."
    )
    parser.add_argument("transactions", help="path to the transactions CSV")
    parser.add_argument(
        "--rules",
        default="rules.json",
        help="path to the JSON rules file (default: rules.json)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        rules = load_rules(args.rules)
        txns = read_transactions(args.transactions)
    except UserError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    results = [(txn, categorize(txn, rules)) for txn in txns]
    totals = aggregate(results)

    source = Path(args.transactions).name
    print(format_summary(source, len(txns), len(rules), totals))
    print()
    print(format_detail(results))
    print()
    print(format_uncategorized(results))
    return 0


if __name__ == "__main__":
    sys.exit(main())
