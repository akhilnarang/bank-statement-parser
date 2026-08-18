"""State Bank of India account statement parser.

SBI e-statements put transactions in an 8-column table:
- Date | Transaction Reference | (merged) | (merged) | Ref.No./Chq.No. | Credit |
  Debit | Balance
- Date format: DD-MM-YY
- The empty side of a credit/debit uses "0"; the reference column uses "-".
- Opening/closing balances appear as summary rows ("... Balance on DD-MM-YY:
  <amt>") around the transactions. The PDF extractor sometimes character-
  interleaves the opening row's label, so it is matched on the "on DD-MM-YY:"
  fragment rather than the literal word "Opening".
"""

from __future__ import annotations

import re
from typing import Any

from bank_statement_parser.models import BankTransaction, ParsedBankStatement
from bank_statement_parser.parsers.generic import GenericBankStatementParser
from bank_statement_parser.parsers.metadata import MetadataExtractor
from bank_statement_parser.parsers.reconciliation import build_reconciliation
from bank_statement_parser.parsers.utils import (
    detect_channel,
    extract_amount,
    extract_reference_number,
    parse_date_text,
)
from bank_statement_parser.parsers.utils.sbi_counterparty import (
    extract_counterparty,
)

_ACCOUNT_RE = re.compile(r"(X{5,}\d{3,})\s+OPEN", re.IGNORECASE)
_NAME_RE = re.compile(r"My\s+Name\s+(.+?)\s+My\s+Address", re.IGNORECASE)
_MONEY_RE = re.compile(r"^\d[\d,]*\.\d{2}$")
_ON_DATE_RE = re.compile(r"on\s+(\d{2}-\d{2}-\d{2})", re.IGNORECASE)
_SBI_DATE_RE = re.compile(r"^(\d{2})-(\d{2})-(\d{2})$")


def _sbi_date(cell: str) -> str | None:
    """Parse an SBI `DD-MM-YY` date, forcing the 2-digit year to `20YY`.

    Statement dates are always in the 2000s, so the plain ``%y`` pivot (which
    would send ``69``-``99`` to the 1900s) must not be used.
    """
    match = _SBI_DATE_RE.match(cell.strip())
    if not match:
        return None
    day, month, year = match.groups()
    return parse_date_text(f"{day}-{month}-20{year}", format_hints=["%d-%m-%Y"])


class SbiMetadataExtractor(MetadataExtractor):
    account_number_pattern = _ACCOUNT_RE
    name_pattern = _NAME_RE
    period_pattern = None
    opening_balance_pattern = None
    closing_balance_pattern = None


def _first_money(row: list) -> str | None:
    """First cell that looks like a rupee amount (has a decimal), else None."""
    for cell in row:
        text = str(cell or "").strip()
        if _MONEY_RE.match(text.replace(" ", "")):
            return text.replace(" ", "")
    return None


def _on_date(text: str) -> str | None:
    match = _ON_DATE_RE.search(text)
    if not match:
        return None
    return _sbi_date(match.group(1))


class SbiBankStatementParser(GenericBankStatementParser):
    """Parser for State Bank of India savings account e-statements."""

    bank = "sbi"
    metadata_extractor = SbiMetadataExtractor()

    def parse(self, raw_data: dict[str, Any]) -> ParsedBankStatement:
        pages = raw_data.get("pages", [])
        file_name = raw_data.get("file", "")

        full_text = "\n".join(
            str(page.get("text", "")) for page in pages if isinstance(page, dict)
        )
        metadata = self.metadata_extractor.extract(full_text)

        transactions: list[BankTransaction] = []
        opening_balance: str | None = None
        closing_balance: str | None = None
        period_start: str | None = None
        period_end: str | None = None

        for page in pages:
            for table in page.get("tables", []):
                if not table:
                    continue
                result = self._parse_sbi_table(table)
                transactions.extend(result["transactions"])
                opening_balance = result["opening_balance"] or opening_balance
                closing_balance = result["closing_balance"] or closing_balance
                period_start = result["period_start"] or period_start
                period_end = result["period_end"] or period_end

        transactions = self._post_process(transactions, raw_data)

        if not closing_balance and transactions:
            closing_balance = transactions[-1].balance

        reconciliation = build_reconciliation(
            transactions,
            opening_balance,
            closing_balance,
        )

        return self._build_statement(
            file_name=file_name,
            transactions=transactions,
            account_holder_name=metadata["account_holder_name"],
            account_number=metadata["account_number"],
            statement_period_start=period_start or metadata["period_start"],
            statement_period_end=period_end or metadata["period_end"],
            opening_balance=opening_balance,
            closing_balance=closing_balance,
            reconciliation=reconciliation,
        )

    def _parse_sbi_table(self, table: list[list]) -> dict[str, Any]:
        empty: dict[str, Any] = {
            "transactions": [],
            "opening_balance": None,
            "closing_balance": None,
            "period_start": None,
            "period_end": None,
        }

        header_idx = None
        for i, row in enumerate(table):
            if not row:
                continue
            row_text = " ".join(str(c or "") for c in row).upper()
            if "CREDIT" in row_text and "DEBIT" in row_text and "BALANCE" in row_text:
                header_idx = i
                break
        if header_idx is None:
            return empty

        cols: dict[str, int] = {}
        for i, cell in enumerate(table[header_idx]):
            if cell is None:
                continue
            upper = str(cell).upper().strip()
            if upper == "DATE":
                cols["date"] = i
            elif "TRANSACTION" in upper:
                cols["narration"] = i
            elif "CHQ" in upper:
                cols["ref"] = i
            elif upper == "CREDIT":
                cols["credit"] = i
            elif upper == "DEBIT":
                cols["debit"] = i
            elif upper == "BALANCE":
                cols["balance"] = i

        if "date" not in cols or "credit" not in cols or "debit" not in cols:
            return empty

        txns: list[BankTransaction] = []
        result = dict(empty)
        result["transactions"] = txns

        for i, row in enumerate(table):
            if not row:
                continue

            date_cell = (
                str(row[cols["date"]] or "").strip() if cols["date"] < len(row) else ""
            )
            date = _sbi_date(date_cell)

            if not date:
                # Opening/closing balance summary row — matched anywhere in the
                # table, so a summary that sits before the header is not lost.
                joined = " ".join(str(c or "") for c in row)
                upper = joined.upper()
                if "CLOSING BALANCE" in upper:
                    result["closing_balance"] = _first_money(row)
                    result["period_end"] = _on_date(joined)
                elif "OPENING" in upper or _ON_DATE_RE.search(joined):
                    result["opening_balance"] = _first_money(row)
                    result["period_start"] = _on_date(joined)
                continue

            # A dated row at or before the header is not a transaction.
            if i <= header_idx:
                continue

            narration = ""
            if "narration" in cols and cols["narration"] < len(row):
                narration = str(row[cols["narration"]] or "").strip().replace("\n", " ")

            credit_str = (
                str(row[cols["credit"]] or "").strip()
                if cols["credit"] < len(row)
                else ""
            )
            debit_str = (
                str(row[cols["debit"]] or "").strip() if cols["debit"] < len(row) else ""
            )
            credit_amt = extract_amount(credit_str)
            debit_amt = extract_amount(debit_str)

            if credit_amt:
                direction, amount = "credit", credit_amt
            elif debit_amt:
                direction, amount = "debit", debit_amt
            else:
                continue

            balance_str = (
                str(row[cols["balance"]] or "").strip()
                if "balance" in cols and cols["balance"] < len(row)
                else ""
            )
            balance = extract_amount(balance_str) if balance_str else None

            channel = detect_channel(narration)
            ref = extract_reference_number(narration, channel)
            # Cheque / some references live only in the Ref.No./Chq.No. column;
            # its empty marker is "-".
            if not ref and "ref" in cols and cols["ref"] < len(row):
                ref_cell = str(row[cols["ref"]] or "").strip()
                if ref_cell and ref_cell != "-":
                    ref = ref_cell

            txns.append(
                BankTransaction(
                    date=date,
                    narration=narration,
                    counterparty=extract_counterparty(narration, channel),
                    amount=amount,
                    transaction_type=direction,
                    balance=balance,
                    reference_number=ref,
                    channel=channel,
                )
            )

        return result
