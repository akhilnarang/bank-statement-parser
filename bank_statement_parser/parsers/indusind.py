"""IndusInd Bank account statement parser.

IndusInd Bank PDF statements have the following structure:
- Page 1: Customer info, notices, relationship summary (no transactions)
- Pages 2-3: Transaction history tables
- Pages 4+: Interest certificate, ads, insurance details

Table layout:
  Date | Particulars | Chq No/Ref No | Withdrawal | Deposit | Balance

Date format: DD-Mon-YYYY (e.g., "01-Jan-2026")
Special rows: "Brought Forward" (opening balance), "Carried Forward" (closing balance)
Multi-line narrations: pdfplumber joins with newlines inside cells.

Metadata:
- Account number found in the account info table on page 2
- Account holder name in same table
- Period: "Statement Period : DD-Mon-YYYY TO DD-Mon-YYYY"
"""

from __future__ import annotations

import re
from typing import Any

from bank_statement_parser.models import (
    BankTransaction,
    ParsedBankStatement,
)
from bank_statement_parser.parsers.generic import GenericBankStatementParser
from bank_statement_parser.parsers.metadata import MetadataExtractor
from bank_statement_parser.parsers.reconciliation import build_reconciliation
from bank_statement_parser.parsers.utils import (
    detect_channel,
    extract_amount,
    extract_reference_number,
    parse_date_text,
)

# Metadata patterns
_PERIOD_RE = re.compile(
    r"Statement\s+Period\s*:\s*(\d{2}-[A-Za-z]{3}-\d{4})\s+TO\s+(\d{2}-[A-Za-z]{3}-\d{4})",
    re.IGNORECASE,
)
_ACCOUNT_NUMBER_RE = re.compile(
    r"\b(\d{2}X{5,}\d{3})\b",
)
# Matches: "<account_number> <ACCOUNT HOLDER NAME> Primary Holder <customer_id>"
_NAME_RE = re.compile(
    r"\d{2}X{5,}\d{3}\s+([A-Z][A-Z ]+?)\s+(?:Primary|Single|Joint)\s+Holder",
)

# Skip patterns for non-transaction rows
_SKIP_KEYWORDS = {
    "brought forward",
    "carried forward",
    "opening balance",
    "closing balance",
    "total",
}


class IndusindMetadataExtractor(MetadataExtractor):
    account_number_pattern = _ACCOUNT_NUMBER_RE
    period_pattern = _PERIOD_RE
    name_pattern = _NAME_RE
    opening_balance_pattern = None
    closing_balance_pattern = None

    def extract_period(self, full_text: str) -> tuple[str | None, str | None]:
        match = self.period_pattern.search(full_text) if self.period_pattern else None
        if not match:
            return None, None
        return (
            parse_date_text(match.group(1), format_hints=["%d-%b-%Y"]),
            parse_date_text(match.group(2), format_hints=["%d-%b-%Y"]),
        )


class IndusindBankStatementParser(GenericBankStatementParser):
    """Parser for IndusInd Bank savings/current account statements."""

    bank = "indusind"
    metadata_extractor = IndusindMetadataExtractor()

    def parse(self, raw_data: dict[str, Any]) -> ParsedBankStatement:
        """Parse IndusInd Bank statement PDF."""
        pages = raw_data.get("pages", [])
        file_name = raw_data.get("file", "")

        # Build full text for metadata extraction
        full_text = "\n".join(
            str(page.get("text", "")) for page in pages if isinstance(page, dict)
        )

        meta = self.metadata_extractor.extract(full_text)

        # Extract opening/closing balance from Brought Forward / Carried Forward rows
        opening_balance, closing_balance = self._extract_indusind_opening_closing(pages)

        # Override with text-based metadata if found
        if meta["opening_balance"]:
            opening_balance = meta["opening_balance"]
        if meta["closing_balance"]:
            closing_balance = meta["closing_balance"]

        # Extract transactions from tables
        transactions = self._extract_indusind_transactions(pages)
        transactions = self._post_process(transactions, raw_data)

        reconciliation = build_reconciliation(
            transactions,
            opening_balance,
            closing_balance,
        )

        return self._build_statement(
            file_name=file_name,
            transactions=transactions,
            account_holder_name=meta["account_holder_name"],
            account_number=meta["account_number"],
            statement_period_start=meta["period_start"],
            statement_period_end=meta["period_end"],
            opening_balance=opening_balance,
            closing_balance=closing_balance,
            reconciliation=reconciliation,
        )

    # ------------------------------------------------------------------
    # Opening / Closing balance from table rows
    # ------------------------------------------------------------------

    def _extract_indusind_opening_closing(
        self,
        pages: list[dict[str, Any]],
    ) -> tuple[str | None, str | None]:
        """Extract opening/closing balance from Brought Forward/Carried Forward rows."""
        opening: str | None = None
        closing: str | None = None

        for page in pages:
            tables = page.get("tables", [])
            for table in tables:
                if not table:
                    continue
                for row in table:
                    if not row:
                        continue
                    row_text = " ".join(str(c or "") for c in row).lower()
                    if "brought forward" in row_text:
                        # Balance is in the last non-empty column
                        for cell in reversed(row):
                            amt = extract_amount(str(cell or ""))
                            if amt:
                                opening = amt
                                break
                    elif "carried forward" in row_text:
                        for cell in reversed(row):
                            amt = extract_amount(str(cell or ""))
                            if amt:
                                closing = amt
                                break

        return opening, closing

    # ------------------------------------------------------------------
    # Transaction extraction
    # ------------------------------------------------------------------

    def _extract_indusind_transactions(
        self,
        pages: list[dict[str, Any]],
    ) -> list[BankTransaction]:
        """Extract transactions from IndusInd statement tables."""
        all_txns: list[BankTransaction] = []
        cols: dict[str, int] | None = None

        for page in pages:
            tables = page.get("tables", [])
            for table in tables:
                if not table:
                    continue

                # Find header row
                header_idx = self._find_indusind_header(table)
                if header_idx is not None:
                    new_cols = self._classify_indusind_columns(table[header_idx])
                    if new_cols is not None:
                        cols = new_cols
                        txns = self._parse_indusind_table(table, header_idx, cols)
                        all_txns.extend(txns)
                elif cols is not None:
                    # Continuation table without header — reuse column mapping
                    txns = self._parse_indusind_table(table, -1, cols)
                    all_txns.extend(txns)

        return all_txns

    def _find_indusind_header(self, table: list[list[str | None]]) -> int | None:
        """Find the transaction header row in an IndusInd table."""
        for i, row in enumerate(table):
            if not row:
                continue
            text = " ".join(str(c or "") for c in row).upper()
            has_date = "DATE" in text
            has_particulars = "PARTICULARS" in text or "NARRATION" in text
            has_amount = "WITHDRAWAL" in text or "DEPOSIT" in text
            if has_date and has_particulars and has_amount:
                return i
        return None

    def _classify_indusind_columns(
        self,
        header_row: list[str | None],
    ) -> dict[str, int] | None:
        """Map column indices for IndusInd table headers."""
        cols: dict[str, int] = {}
        for i, cell in enumerate(header_row):
            if cell is None:
                continue
            upper = cell.strip().upper()
            if not upper:
                continue
            if "DATE" in upper and "date" not in cols:
                cols["date"] = i
            elif upper in ("PARTICULARS", "NARRATION", "DESCRIPTION"):
                cols["narration"] = i
            elif "CHQ" in upper or "REF" in upper:
                cols["ref"] = i
            elif "WITHDRAWAL" in upper:
                cols["debit"] = i
            elif "DEPOSIT" in upper:
                cols["credit"] = i
            elif "BALANCE" in upper:
                cols["balance"] = i

        if "date" not in cols:
            return None
        return cols

    def _parse_indusind_table(
        self,
        table: list[list[str | None]],
        header_idx: int,
        cols: dict[str, int],
    ) -> list[BankTransaction]:
        """Parse transaction rows from an IndusInd table."""
        txns: list[BankTransaction] = []

        for row in table[header_idx + 1 :]:
            if not row:
                continue
            # Ensure row has enough columns
            max_col = max(cols.values())
            if len(row) <= max_col:
                continue

            date_cell = str(row[cols["date"]] or "").strip()
            narration = ""
            if "narration" in cols:
                narration = str(row[cols["narration"]] or "").strip()

            # Check for special non-transaction rows
            narration_lower = narration.lower()
            is_special = any(kw in narration_lower for kw in _SKIP_KEYWORDS)
            if is_special:
                continue

            # Parse date — IndusInd uses DD-Mon-YYYY
            date = parse_date_text(date_cell, format_hints=["%d-%b-%Y"])
            if not date:
                continue

            # Clean narration: replace newlines with spaces, collapse whitespace
            narration = narration.replace("\n", " ").replace("\r", " ")
            narration = re.sub(r"\s{2,}", " ", narration).strip()

            debit_str = (
                str(row[cols.get("debit", -1)] or "").strip() if "debit" in cols else ""
            )
            credit_str = (
                str(row[cols.get("credit", -1)] or "").strip()
                if "credit" in cols
                else ""
            )
            balance_str = (
                str(row[cols.get("balance", -1)] or "").strip()
                if "balance" in cols
                else ""
            )
            ref_str = (
                str(row[cols.get("ref", -1)] or "").strip() if "ref" in cols else ""
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

            # Extract balance, preserving negative sign for overdraft
            balance: str | None = None
            if balance_str:
                cleaned_bal = balance_str.strip()
                is_negative = cleaned_bal.startswith("-")
                bal_val = extract_amount(
                    cleaned_bal.lstrip("-") if is_negative else cleaned_bal
                )
                if bal_val:
                    balance = f"-{bal_val}" if is_negative else bal_val

            channel = detect_channel(narration)
            ref = ref_str if ref_str else extract_reference_number(narration, channel)

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

        return txns
