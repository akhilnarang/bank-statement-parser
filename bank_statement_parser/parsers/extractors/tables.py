"""Table-based transaction extraction helpers."""

from __future__ import annotations

from typing import Any

from bank_statement_parser.models import BankTransaction
from bank_statement_parser.parsers.utils import (
    detect_channel,
    extract_amount,
    extract_reference_number,
    parse_date_text,
)


def find_header_row(table: list[list[str | None]]) -> int | None:
    """Find the header row index by looking for Date/Narration/Debit/Credit keywords."""
    for index, row in enumerate(table):
        if not row:
            continue
        text = " ".join(str(cell or "") for cell in row).upper()
        has_date = "DATE" in text
        has_amount = (
            "DEBIT" in text
            or "WITHDRAWAL" in text
            or "CREDIT" in text
            or "DEPOSIT" in text
        )
        if has_date and has_amount:
            return index
    return None


def classify_columns(
    header_row: list[str | None],
) -> dict[str, int] | None:
    """Map common transaction table columns from a header row."""
    cols: dict[str, int] = {}
    for index, cell in enumerate(header_row):
        if cell is None:
            continue
        upper = cell.strip().upper()
        if not upper:
            continue
        if "DATE" in upper and "VALUE" in upper:
            cols["value_date"] = index
        elif "DATE" in upper and "date" not in cols:
            cols["date"] = index
        elif upper in (
            "NARRATION",
            "PARTICULARS",
            "DESCRIPTION",
            "DETAILS",
            "TRANSACTION DETAILS",
            "TRANSACTION PARTICULARS",
        ):
            cols["narration"] = index
        elif "MODE" in upper and "narration" not in cols:
            cols["narration"] = index
        elif "BALANCE" in upper:
            cols["balance"] = index
        elif any(keyword in upper for keyword in ("WITHDRAWAL", "DEBIT")) or (
            "DR" in upper.split() and "BALANCE" not in upper
        ):
            cols["debit"] = index
        elif any(keyword in upper for keyword in ("DEPOSIT", "CREDIT")) or (
            "CR" in upper.split() and "BALANCE" not in upper
        ):
            cols["credit"] = index
        elif any(keyword in upper for keyword in ("REF", "CHQ", "CHEQUE")):
            cols["ref"] = index

    if "date" not in cols:
        return None
    return cols


def parse_table_transactions(
    table: list[list[str | None]],
    header_idx: int,
    cols: dict[str, int],
) -> list[BankTransaction]:
    """Parse transaction rows from a classified table."""
    txns: list[BankTransaction] = []
    for row in table[header_idx + 1 :]:
        if not row or len(row) <= max(cols.values()):
            continue

        date_cell = str(row[cols["date"]] or "").strip()
        date = parse_date_text(date_cell)
        if not date:
            continue

        narration = (
            str(row[cols["narration"]] or "").strip() if "narration" in cols else ""
        )
        debit_str = str(row[cols["debit"]] or "").strip() if "debit" in cols else ""
        credit_str = str(row[cols["credit"]] or "").strip() if "credit" in cols else ""
        balance_str = (
            str(row[cols["balance"]] or "").strip() if "balance" in cols else ""
        )
        ref_str = str(row[cols["ref"]] or "").strip() if "ref" in cols else ""
        value_date_str = (
            str(row[cols["value_date"]] or "").strip() if "value_date" in cols else ""
        )

        debit_amt = extract_amount(debit_str)
        credit_amt = extract_amount(credit_str)
        if debit_amt:
            direction = "debit"
            amount = debit_amt
        elif credit_amt:
            direction = "credit"
            amount = credit_amt
        else:
            continue

        channel = detect_channel(narration)

        txns.append(
            BankTransaction(
                date=date,
                narration=narration,
                amount=amount,
                transaction_type=direction,
                balance=extract_amount(balance_str) if balance_str else None,
                reference_number=ref_str or extract_reference_number(narration, channel),
                channel=channel,
                value_date=parse_date_text(value_date_str) if value_date_str else None,
            )
        )

    return txns


def extract_transactions_from_tables(
    pages: list[dict[str, Any]],
) -> list[BankTransaction]:
    """Extract transactions from PDF tables across all pages."""
    all_txns: list[BankTransaction] = []
    cols: dict[str, int] | None = None

    for page in pages:
        for table in page.get("tables", []):
            if not table:
                continue

            header_idx = find_header_row(table)
            if header_idx is not None:
                new_cols = classify_columns(table[header_idx])
                if new_cols is None:
                    continue
                cols = new_cols
                txns = parse_table_transactions(table, header_idx, cols)
            elif cols is not None:
                txns = parse_table_transactions(table, -1, cols)
            else:
                continue

            all_txns.extend(txns)

    return all_txns


__all__ = [
    "classify_columns",
    "extract_transactions_from_tables",
    "find_header_row",
    "parse_table_transactions",
]
