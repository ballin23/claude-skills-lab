#!/usr/bin/env python3
"""Daily Cash Position Tracker.

Reads a folder of per-bank daily balance CSVs named ``<bank>_<YYYY-MM-DD>.csv``,
reports the consolidated cash position, shows the day-over-day change per
account, and flags accounts that moved by more than a threshold percentage.

Standard library only. See CLAUDE.md for the full spec.
"""

from __future__ import annotations

import argparse
import csv
import sys
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path


class DataError(Exception):
    """A problem with the input folder, a filename, or a file's contents."""


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class Balance:
    """One account's balance at one bank on one day."""

    bank: str
    account: str
    day: date
    amount: Decimal


def parse_filename(path: Path) -> tuple[str, date]:
    """Return ``(bank, day)`` parsed from a ``<bank>_<YYYY-MM-DD>.csv`` name.

    The bank token is everything before the last underscore; the date is the
    final underscore-delimited token before the extension. Raises ``ValueError``
    if the name does not match, so the caller can skip and warn.
    """
    bank, sep, datestr = path.stem.rpartition("_")
    if not sep or not bank:
        raise ValueError("expected <bank>_<date>.csv")
    try:
        day = date.fromisoformat(datestr)
    except ValueError:
        raise ValueError(f"bad date {datestr!r} in filename") from None
    return bank, day


def parse_rows(path: Path, bank: str, day: date) -> list[Balance]:
    """Read one balance file. Raises ``DataError`` on a malformed header or row."""
    balances: list[Balance] = []
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fields = reader.fieldnames or []
        if "account" not in fields or "balance" not in fields:
            raise DataError(
                f"{path.name}: expected an 'account,balance' header, got {fields!r}"
            )
        for lineno, row in enumerate(reader, start=2):
            account = (row.get("account") or "").strip()
            raw = (row.get("balance") or "").strip()
            if not account and not raw:
                continue  # blank line
            if not account:
                raise DataError(f"{path.name} line {lineno}: missing account name")
            try:
                amount = Decimal(raw.replace(",", ""))
            except InvalidOperation:
                raise DataError(
                    f"{path.name} line {lineno}: cannot parse balance {raw!r}"
                ) from None
            balances.append(Balance(bank=bank, account=account, day=day, amount=amount))
    return balances


@dataclass
class Folder:
    """Everything read from the input folder."""

    balances: list[Balance]
    file_count: int
    banks: list[str]


def load_folder(folder: Path) -> Folder:
    """Read every ``<bank>_<date>.csv`` in ``folder``. Raises ``DataError``."""
    if not folder.exists():
        raise DataError(f"folder not found: {folder}")
    if not folder.is_dir():
        raise DataError(f"not a folder: {folder}")

    csv_files = sorted(
        p for p in folder.iterdir() if p.is_file() and p.suffix.lower() == ".csv"
    )
    if not csv_files:
        raise DataError(f"no .csv files in {folder}")

    balances: list[Balance] = []
    file_count = 0
    for path in csv_files:
        try:
            bank, day = parse_filename(path)
        except ValueError as exc:
            print(f"warning: skipping {path.name}: {exc}", file=sys.stderr)
            continue
        balances.extend(parse_rows(path, bank, day))
        file_count += 1

    if file_count == 0:
        raise DataError(f"no files in {folder} match <bank>_<date>.csv")
    if not balances:
        raise DataError(f"no balance rows found in any file in {folder}")

    banks = sorted({b.bank for b in balances})
    return Folder(balances=balances, file_count=file_count, banks=banks)


# --------------------------------------------------------------------------- #
# Position calculation
# --------------------------------------------------------------------------- #

@dataclass
class Line:
    """One account across the two compared days."""

    bank: str
    account: str
    prior: Decimal | None
    current: Decimal | None

    @property
    def change(self) -> Decimal | None:
        if self.prior is None or self.current is None:
            return None
        return self.current - self.prior

    @property
    def pct(self) -> Decimal | None:
        if self.prior is None or self.current is None or self.prior == 0:
            return None
        return (self.current - self.prior) / self.prior * 100


def pick_dates(balances: list[Balance], as_of: date | None) -> tuple[date, date]:
    """Choose the (prior, current) days to compare."""
    dates = sorted({b.day for b in balances})
    if as_of is not None:
        if as_of not in dates:
            raise DataError(f"no files for date {as_of.isoformat()}")
        earlier = [d for d in dates if d < as_of]
        if not earlier:
            raise DataError(
                f"no earlier date than {as_of.isoformat()} to compare against"
            )
        return earlier[-1], as_of
    if len(dates) < 2:
        found = ", ".join(d.isoformat() for d in dates) or "none"
        raise DataError(f"need at least two distinct dates to compare; found {found}")
    return dates[-2], dates[-1]


def build_lines(
    balances: list[Balance], prior_day: date, current_day: date
) -> list[Line]:
    prior = {
        (b.bank, b.account): b.amount for b in balances if b.day == prior_day
    }
    current = {
        (b.bank, b.account): b.amount for b in balances if b.day == current_day
    }
    keys = sorted(set(prior) | set(current))
    return [
        Line(bank, account, prior.get((bank, account)), current.get((bank, account)))
        for bank, account in keys
    ]


# --------------------------------------------------------------------------- #
# Formatting
# --------------------------------------------------------------------------- #

def _denormalize_zero(value: Decimal) -> Decimal:
    """Collapse ``-0`` (and ``-0.00...``) to a plain zero for display."""
    return Decimal("0") if value == 0 else value


def fmt_money(value: Decimal | None) -> str:
    return "n/a" if value is None else f"{_denormalize_zero(value):,.2f}"


def fmt_signed(value: Decimal | None) -> str:
    return "n/a" if value is None else f"{_denormalize_zero(value):+,.2f}"


def fmt_pct(value: Decimal | None) -> str:
    return "n/a" if value is None else f"{_denormalize_zero(value):+.1f}%"


def render(
    lines: list[Line],
    prior_day: date,
    current_day: date,
    threshold: Decimal,
    file_count: int,
    banks: list[str],
) -> str:
    out: list[str] = []
    out.append(
        f"Cash Position - {current_day.isoformat()} "
        f"(prior: {prior_day.isoformat()})"
    )
    bank_word = "bank" if len(banks) == 1 else "banks"
    out.append(
        f"Files read: {file_count} across {len(banks)} {bank_word} "
        f"({', '.join(banks)})"
    )
    out.append("")

    headers = ["Bank", "Account", "Prior", "Current", "Change", "Change %"]
    rows: list[list[str]] = []
    flagged = 0
    for line in lines:
        pct = line.pct
        is_flag = pct is not None and abs(pct) > threshold
        if is_flag:
            flagged += 1
        rows.append(
            [
                line.bank,
                line.account,
                fmt_money(line.prior),
                fmt_money(line.current),
                fmt_signed(line.change),
                fmt_pct(pct) + ("  ** FLAG" if is_flag else ""),
            ]
        )

    widths = [
        max(len(headers[i]), *(len(r[i]) for r in rows)) if rows else len(headers[i])
        for i in range(len(headers))
    ]

    def fmt_row(cells: list[str]) -> str:
        last = len(cells) - 1
        return "   ".join(
            cell.ljust(widths[i]) if i < last else cell
            for i, cell in enumerate(cells)
        ).rstrip()

    out.append(fmt_row(headers))
    out.extend(fmt_row(r) for r in rows)
    out.append("")

    total_current = sum(
        (line.current for line in lines if line.current is not None), Decimal("0")
    )
    total_prior = sum(
        (line.prior for line in lines if line.prior is not None), Decimal("0")
    )
    total_change = total_current - total_prior
    total_pct = (total_change / total_prior * 100) if total_prior else None

    out.append(f"Total cash position:   {fmt_money(total_current)}")
    pct_suffix = f"  ({fmt_pct(total_pct)})" if total_pct is not None else ""
    out.append(f"Change from prior day: {fmt_signed(total_change)}{pct_suffix}")
    out.append("")

    noun = "account" if flagged == 1 else "accounts"
    out.append(f"{flagged} {noun} moved more than {threshold:.1f}%.")
    return "\n".join(out)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def _isodate(text: str) -> date:
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not an ISO date (YYYY-MM-DD): {text!r}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="cash_position.py",
        description=(
            "Consolidated daily cash position from a folder of per-bank "
            "balance CSVs named <bank>_<YYYY-MM-DD>.csv."
        ),
    )
    parser.add_argument(
        "folder", type=Path, help="folder of <bank>_<YYYY-MM-DD>.csv files"
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=10.0,
        metavar="PCT",
        help="percent day-over-day move that triggers a flag (default: 10)",
    )
    parser.add_argument(
        "--date",
        dest="as_of",
        type=_isodate,
        default=None,
        metavar="YYYY-MM-DD",
        help="treat this date as 'today' (default: latest date found)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        folder = load_folder(args.folder)
        prior_day, current_day = pick_dates(folder.balances, args.as_of)
        lines = build_lines(folder.balances, prior_day, current_day)
        threshold = Decimal(str(args.threshold))
        print(
            render(
                lines,
                prior_day,
                current_day,
                threshold,
                folder.file_count,
                folder.banks,
            )
        )
    except DataError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
