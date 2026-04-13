"""Kotak Mahindra Bank account statement parser.

Kotak (811) statements have a clean 7-column table:
- # | Date | Description | Chq/Ref. No. | Withdrawal (Dr.) | Deposit (Cr.) | Balance
- Date format: DD Mon YYYY (e.g. "02 Mar 2026")
- First data row is an "Opening Balance" row with "-" placeholders in other columns
- Continuation tables on subsequent pages reuse the same header
- A separate "Account Summary" table on the final transactions page lists
  opening and closing balance amounts together

Metadata:
- Account number appears as "Account No. NNNN" on page 1 and as
  "Account No.NNNN" (no space) on continuation pages
- Statement period appears as "01 Mar 2026 - 31 Mar 2026"
- Holder name appears on its own line before "Account No."
- Chq/Ref. No. cells often contain the raw reference id (e.g. "UPI-...",
  "811BP-...", "ONBF-..."); use it as a fallback reference when narration
  does not contain a long numeric UTR.
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Any

from bank_statement_parser.models import BankTransaction, ParsedBankStatement
from bank_statement_parser.parsers.generic import (
    GenericBankStatementParser,
    MONTH_ABBREVS,
    _build_reconciliation,
    _extract_amount,
    detect_channel,
    extract_reference_number,
    format_amount,
    parse_amount,
)

_ACCOUNT_RE = re.compile(
    r"Account\s+No\.?\s*:?\s*(\d[\dX*]{5,})",
    re.IGNORECASE,
)
_PERIOD_RE = re.compile(
    r"(\d{2}\s+[A-Za-z]{3}\s+\d{4})\s*[-\u2013]\s*(\d{2}\s+[A-Za-z]{3}\s+\d{4})",
)
_NAME_RE = re.compile(
    r"^([A-Z][A-Za-z.'\- ]+?)\s+Account\s+No\.",
    re.MULTILINE,
)
_DATE_RE = re.compile(
    r"^(\d{2})\s+([A-Za-z]{3})\s+(\d{4})$",
)


def _parse_kotak_date(raw: str) -> str | None:
    """Parse ``DD Mon YYYY`` into ``DD/MM/YYYY``."""
    m = _DATE_RE.fullmatch(raw.strip())
    if not m:
        return None
    day = m.group(1)
    month = MONTH_ABBREVS.get(m.group(2).upper()[:3])
    year = m.group(3)
    if month is None:
        return None
    return f"{day}/{month}/{year}"


class KotakBankStatementParser(GenericBankStatementParser):
    """Parser for Kotak Mahindra Bank savings/current account statements."""

    bank = "kotak"

    def parse(self, raw_data: dict[str, Any]) -> ParsedBankStatement:
        pages = raw_data.get("pages", [])
        file_name = raw_data.get("file", "")

        full_text = "\n".join(
            str(page.get("text", "")) for page in pages if isinstance(page, dict)
        )

        account_number = self._extract_account_number(full_text)
        holder_name = self._extract_name(full_text)
        period_start, period_end = self._extract_period(full_text)

        transactions: list[BankTransaction] = []
        opening_balance: str | None = None
        closing_balance: str | None = None
        cols: dict[str, int] | None = None

        for page in pages:
            for table in page.get("tables", []):
                if not table:
                    continue

                # Account Summary table — opening & closing balances
                if self._is_account_summary(table):
                    ob, cb = self._parse_account_summary(table)
                    if ob is not None:
                        opening_balance = ob
                    if cb is not None:
                        closing_balance = cb
                    continue

                header_idx = self._find_header(table)
                if header_idx is not None:
                    cols = self._classify_columns(table[header_idx])
                    if cols is None:
                        continue
                    ob_from_table, txns = self._parse_rows(
                        table, header_idx + 1, cols
                    )
                    if ob_from_table is not None and opening_balance is None:
                        opening_balance = ob_from_table
                    transactions.extend(txns)
                elif cols is not None:
                    # Continuation table without a header row — reuse mapping
                    _, txns = self._parse_rows(table, 0, cols)
                    transactions.extend(txns)

        # Assign IDs
        for i, txn in enumerate(transactions):
            txn.transaction_id = f"kotak_txn_{i:04d}"

        if not closing_balance and transactions:
            closing_balance = transactions[-1].balance

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
            credit_count=sum(
                1 for t in transactions if t.transaction_type == "credit"
            ),
            debit_total=format_amount(debit_total),
            credit_total=format_amount(credit_total),
            transactions=transactions,
            reconciliation=reconciliation,
        )

    # ------------------------------------------------------------------
    # Metadata helpers
    # ------------------------------------------------------------------

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
        return _parse_kotak_date(m.group(1)), _parse_kotak_date(m.group(2))

    # ------------------------------------------------------------------
    # Table classification helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _find_header(table: list[list[str | None]]) -> int | None:
        """Find the transaction header row index.

        Kotak uses a header like:
        ``# Date Description Chq/Ref. No. Withdrawal (Dr.) Deposit (Cr.) Balance``
        """
        for i, row in enumerate(table):
            if not row:
                continue
            row_text = " ".join(str(c or "") for c in row).upper()
            if (
                "DATE" in row_text
                and "WITHDRAWAL" in row_text
                and "DEPOSIT" in row_text
                and "BALANCE" in row_text
            ):
                return i
        return None

    @staticmethod
    def _classify_columns(
        header_row: list[str | None],
    ) -> dict[str, int] | None:
        cols: dict[str, int] = {}
        for i, cell in enumerate(header_row):
            if cell is None:
                continue
            upper = str(cell).strip().upper()
            if not upper:
                continue
            if upper == "#":
                cols["sn"] = i
            elif upper == "DATE":
                cols["date"] = i
            elif upper in ("DESCRIPTION", "NARRATION", "PARTICULARS"):
                cols["narration"] = i
            elif "CHQ" in upper or "REF" in upper:
                cols["ref"] = i
            elif "WITHDRAWAL" in upper or upper.startswith("DR"):
                cols["debit"] = i
            elif "DEPOSIT" in upper or upper.startswith("CR"):
                cols["credit"] = i
            elif "BALANCE" in upper:
                cols["balance"] = i

        if "date" not in cols:
            return None
        return cols

    @staticmethod
    def _is_account_summary(table: list[list[str | None]]) -> bool:
        """Check if a table is the end-of-statement Account Summary table."""
        if not table:
            return False
        row_text = " ".join(
            str(c or "") for row in table for c in row
        ).upper()
        return (
            "ACCOUNT SUMMARY" in row_text
            and "OPENING BALANCE" in row_text
            and "CLOSING BALANCE" in row_text
        )

    @staticmethod
    def _parse_account_summary(
        table: list[list[str | None]],
    ) -> tuple[str | None, str | None]:
        """Extract opening and closing balance from the Account Summary table.

        The table has shape:
            [Account Summary, None, None]
            [Particulars, Opening Balance, Closing Balance]
            [Savings Account (SA):, <opening>, <closing>]
        """
        opening: str | None = None
        closing: str | None = None
        header_idx: int | None = None
        ob_col: int | None = None
        cb_col: int | None = None

        for i, row in enumerate(table):
            if not row:
                continue
            for j, cell in enumerate(row):
                if cell is None:
                    continue
                upper = str(cell).strip().upper()
                if upper == "OPENING BALANCE":
                    ob_col = j
                    header_idx = i
                elif upper == "CLOSING BALANCE":
                    cb_col = j
                    header_idx = i

        if header_idx is None:
            return None, None

        for row in table[header_idx + 1 :]:
            if not row:
                continue
            if ob_col is not None and ob_col < len(row):
                val = _extract_amount(str(row[ob_col] or ""))
                if val:
                    opening = val
            if cb_col is not None and cb_col < len(row):
                val = _extract_amount(str(row[cb_col] or ""))
                if val:
                    closing = val
            if opening is not None and closing is not None:
                break

        return opening, closing

    # ------------------------------------------------------------------
    # Transaction parsing
    # ------------------------------------------------------------------

    def _parse_rows(
        self,
        table: list[list[str | None]],
        start_idx: int,
        cols: dict[str, int],
    ) -> tuple[str | None, list[BankTransaction]]:
        """Parse data rows. Returns (opening_balance_from_row, transactions)."""
        opening_balance: str | None = None
        txns: list[BankTransaction] = []

        for row in table[start_idx:]:
            if not row:
                continue

            row_text = " ".join(str(c or "") for c in row).upper()

            # Opening balance row has "Opening Balance" in narration column
            if "OPENING BALANCE" in row_text:
                if "balance" in cols and cols["balance"] < len(row):
                    bal_cell = str(row[cols["balance"]] or "").strip()
                    amt = _extract_amount(bal_cell)
                    if amt:
                        opening_balance = amt
                continue

            # Closing balance summary row
            if "CLOSING BALANCE" in row_text:
                continue

            date_cell = ""
            if "date" in cols and cols["date"] < len(row):
                date_cell = str(row[cols["date"]] or "").strip()
            date = _parse_kotak_date(date_cell)
            if not date:
                continue

            narration = ""
            if "narration" in cols and cols["narration"] < len(row):
                narration = (
                    str(row[cols["narration"]] or "").strip().replace("\n", " ")
                )

            ref_cell = ""
            if "ref" in cols and cols["ref"] < len(row):
                ref_cell = (
                    str(row[cols["ref"]] or "").strip().replace("\n", "")
                )

            debit_str = ""
            if "debit" in cols and cols["debit"] < len(row):
                debit_str = str(row[cols["debit"]] or "").strip()
            credit_str = ""
            if "credit" in cols and cols["credit"] < len(row):
                credit_str = str(row[cols["credit"]] or "").strip()
            balance_str = ""
            if "balance" in cols and cols["balance"] < len(row):
                balance_str = str(row[cols["balance"]] or "").strip()

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

            balance = _extract_amount(balance_str) if balance_str else None
            channel = detect_channel(narration)
            ref = extract_reference_number(narration)
            if not ref and ref_cell:
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

        return opening_balance, txns
