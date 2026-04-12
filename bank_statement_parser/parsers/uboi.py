"""Union Bank of India account statement parser.

UBOI bank statements have a clean 7-column table:
- SI | Date | Particulars | Chq Num | Withdrawal | Deposit | Balance
- Date format: DD-MM-YYYY
- Balance suffix: "Cr"
- Summary rows at bottom with Total Debits/Credits and Opening/Closing Balance
- Account number in details table as "Account Number : XXXXXXXXXNNNN"
- Statement period in header: "01-03-2026 TO 31-03-2026"
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Any

from bank_statement_parser.models import BankTransaction, ParsedBankStatement
from bank_statement_parser.parsers.generic import (
    GenericBankStatementParser,
    _build_reconciliation,
    _extract_amount,
    detect_channel,
    extract_reference_number,
    format_amount,
    parse_amount,
)

_ACCOUNT_RE = re.compile(
    r"Account\s+Number\s*:\s*([\dX]+)",
    re.IGNORECASE,
)
_PERIOD_RE = re.compile(
    r"PERIOD\s+FROM\s+(\d{2}-\d{2}-\d{4})\s+TO\s+(\d{2}-\d{2}-\d{4})",
    re.IGNORECASE,
)
_NAME_RE = re.compile(
    r"Name\s*&\s*Address\s*:.*?\n\s*([A-Z][A-Z ]+?)\s+(?:Account|Customer|IFSC)",
)


def _parse_uboi_date(raw: str) -> str | None:
    """Parse DD-MM-YYYY into DD/MM/YYYY."""
    raw = raw.strip()
    m = re.fullmatch(r"(\d{2})-(\d{2})-(\d{4})", raw)
    if m:
        return f"{m.group(1)}/{m.group(2)}/{m.group(3)}"
    return None


def _strip_cr(balance: str) -> str:
    """Remove ' Cr' / ' Dr' suffix from balance strings."""
    return re.sub(r"\s*(Cr|Dr|CR|DR)\s*$", "", balance.strip(), flags=re.IGNORECASE)


class UboiBankStatementParser(GenericBankStatementParser):
    """Parser for Union Bank of India savings/current account statements."""

    bank = "uboi"

    def parse(self, raw_data: dict[str, Any]) -> ParsedBankStatement:
        pages = raw_data.get("pages", [])
        file_name = raw_data.get("file", "")

        full_text = "\n".join(
            str(page.get("text", "")) for page in pages if isinstance(page, dict)
        )

        # Metadata
        account_number = self._extract_account_number(full_text)
        holder_name = self._extract_name(full_text)
        period_start, period_end = self._extract_period(full_text)

        # Transactions from tables
        transactions: list[BankTransaction] = []
        opening_balance: str | None = None
        closing_balance: str | None = None

        for page in pages:
            for table in page.get("tables", []):
                if not table:
                    continue
                txns, ob, cb = self._parse_uboi_table(table)
                transactions.extend(txns)
                if ob is not None:
                    opening_balance = ob
                if cb is not None:
                    closing_balance = cb

        # Assign IDs
        for i, txn in enumerate(transactions):
            txn.transaction_id = f"uboi_txn_{i:04d}"

        # If we didn't find closing from summary, try last transaction
        if not closing_balance and transactions:
            closing_balance = transactions[-1].balance

        # Compute totals
        debit_total = Decimal("0")
        credit_total = Decimal("0")
        for txn in transactions:
            amt = parse_amount(txn.amount)
            if txn.transaction_type == "debit":
                debit_total += amt
            else:
                credit_total += amt

        reconciliation = _build_reconciliation(
            transactions,
            opening_balance,
            closing_balance,
        )

        return ParsedBankStatement(
            file=file_name,
            bank=self.bank,
            account_holder_name=holder_name,
            account_number=account_number,
            statement_period_start=period_start,
            statement_period_end=period_end,
            opening_balance=opening_balance,
            closing_balance=closing_balance,
            debit_count=sum(1 for t in transactions if t.transaction_type == "debit"),
            credit_count=sum(1 for t in transactions if t.transaction_type == "credit"),
            debit_total=format_amount(debit_total),
            credit_total=format_amount(credit_total),
            transactions=transactions,
            reconciliation=reconciliation,
        )

    def _extract_account_number(self, text: str) -> str | None:
        m = _ACCOUNT_RE.search(text)
        return m.group(1) if m else None

    def _extract_name(self, text: str) -> str | None:
        m = _NAME_RE.search(text)
        if m:
            return m.group(1).strip()
        return None

    def _extract_period(self, text: str) -> tuple[str | None, str | None]:
        m = _PERIOD_RE.search(text)
        if not m:
            return None, None
        return _parse_uboi_date(m.group(1)), _parse_uboi_date(m.group(2))

    def _parse_uboi_table(
        self,
        table: list[list],
    ) -> tuple[list[BankTransaction], str | None, str | None]:
        """Parse a UBOI transaction table.

        Returns (transactions, opening_balance, closing_balance).
        """
        txns: list[BankTransaction] = []
        opening_balance: str | None = None
        closing_balance: str | None = None

        # Find header row
        header_idx = None
        for i, row in enumerate(table):
            if not row:
                continue
            row_text = " ".join(str(c or "") for c in row).upper()
            if (
                "WITHDRAWAL" in row_text
                and "DEPOSIT" in row_text
                and "DATE" in row_text
            ):
                header_idx = i
                break

        if header_idx is None:
            return txns, opening_balance, closing_balance

        # Classify columns
        header = table[header_idx]
        cols: dict[str, int] = {}
        for i, cell in enumerate(header):
            if cell is None:
                continue
            upper = str(cell).upper().strip()
            if upper == "SI":
                cols["si"] = i
            elif upper == "DATE":
                cols["date"] = i
            elif upper in ("PARTICULARS", "NARRATION", "DESCRIPTION"):
                cols["narration"] = i
            elif "CHQ" in upper or "REF" in upper or "CHEQUE" in upper:
                cols["ref"] = i
            elif "WITHDRAWAL" in upper:
                cols["debit"] = i
            elif "DEPOSIT" in upper:
                cols["credit"] = i
            elif "BALANCE" in upper:
                cols["balance"] = i

        if "date" not in cols or ("debit" not in cols and "credit" not in cols):
            return txns, opening_balance, closing_balance

        # Parse data rows
        for row in table[header_idx + 1 :]:
            if not row:
                continue

            row_text = " ".join(str(c or "") for c in row).upper()

            # Summary row: "Total Debits :" / "Total Credits :" / "Opening Balance :" / "Closing Balance :"
            if "OPENING BALANCE" in row_text:
                # Extract opening balance — scan cells right-to-left for first amount
                for cell in reversed(row):
                    cell_str = _strip_cr(str(cell or "").strip())
                    if amt := _extract_amount(cell_str):
                        opening_balance = amt
                        break
                continue

            if "CLOSING BALANCE" in row_text:
                last_cell = str(row[-1] or "").strip()
                if _extract_amount(_strip_cr(last_cell)):
                    closing_balance = _strip_cr(last_cell)
                continue

            if (
                "TOTAL DEBIT" in row_text
                or "TOTAL CREDIT" in row_text
                or "SUMMARY" in row_text
            ):
                # Check if this summary row also has opening/closing balance
                for ci, cell in enumerate(row):
                    cell_str = str(cell or "").strip()
                    if "Opening Balance" in cell_str and ci + 1 < len(row):
                        ob_str = str(row[ci + 1] or "").strip()
                        if _extract_amount(_strip_cr(ob_str)):
                            opening_balance = _strip_cr(ob_str)
                    if "Closing Balance" in cell_str and ci + 1 < len(row):
                        cb_str = str(row[ci + 1] or "").strip()
                        if _extract_amount(_strip_cr(cb_str)):
                            closing_balance = _strip_cr(cb_str)
                continue

            # Regular transaction row
            date_cell = (
                str(row[cols["date"]] or "").strip()
                if "date" in cols and cols["date"] < len(row)
                else ""
            )
            date = _parse_uboi_date(date_cell)
            if not date:
                continue

            narration = ""
            if "narration" in cols and cols["narration"] < len(row):
                narration = str(row[cols["narration"]] or "").strip().replace("\n", " ")

            debit_str = (
                str(row[cols["debit"]] or "").strip()
                if "debit" in cols and cols["debit"] < len(row)
                else ""
            )
            credit_str = (
                str(row[cols["credit"]] or "").strip()
                if "credit" in cols and cols["credit"] < len(row)
                else ""
            )
            balance_str = (
                str(row[cols["balance"]] or "").strip()
                if "balance" in cols and cols["balance"] < len(row)
                else ""
            )

            debit_amt = _extract_amount(debit_str) if debit_str else None
            credit_amt = _extract_amount(credit_str) if credit_str else None

            if debit_amt:
                direction = "debit"
                amount = debit_amt
            elif credit_amt:
                direction = "credit"
                amount = credit_amt
            else:
                continue

            balance = _extract_amount(_strip_cr(balance_str)) if balance_str else None
            channel = detect_channel(narration)
            ref = extract_reference_number(narration)

            # UBOI ref column
            if not ref and "ref" in cols and cols["ref"] < len(row):
                ref_cell = str(row[cols["ref"]] or "").strip()
                if ref_cell:
                    ref = ref_cell

            txns.append(
                BankTransaction(
                    date=date,
                    narration=narration,
                    amount=amount,
                    transaction_type=direction,
                    balance=balance,
                    reference_number=ref,
                    channel=channel,
                )
            )

        return txns, opening_balance, closing_balance
