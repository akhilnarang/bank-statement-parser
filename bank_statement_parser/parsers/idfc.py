"""IDFC FIRST Bank account statement parser.

IDFC bank statements have:
- Date format: DD Mon YY (e.g., "01 Mar 26") with time on next line
- 7-column tables: Date and Time | Value Date | Transaction Details |
  Ref/Cheque No. | Withdrawals (INR) | Deposits (INR) | Balance (INR)
- Balance always has "CR" suffix
- Account number in "SAVINGS ACCOUNT DETAILS FOR A/C : XXXXXXXXXXX"
- Opening/closing balance in summary table row
- Statement period: DD-MON-YYYY to DD-MON-YYYY
- Page 1 table extraction is often malformed; page 2+ tables are clean
"""

from __future__ import annotations

import re
from typing import Any

from bank_statement_parser.models import BankTransaction, ParsedBankStatement
from bank_statement_parser.parsers.extractors import group_words_into_lines
from bank_statement_parser.parsers.generic import GenericBankStatementParser
from bank_statement_parser.parsers.metadata import MetadataExtractor
from bank_statement_parser.parsers.reconciliation import build_reconciliation
from bank_statement_parser.parsers.utils import (
    detect_channel,
    extract_amount,
    extract_reference_number,
    parse_date_text,
)

_ACCOUNT_RE = re.compile(
    r"SAVINGS ACCOUNT DETAILS FOR A/C\s*:\s*(\d+)",
    re.IGNORECASE,
)
_PERIOD_RE = re.compile(
    r"STATEMENT\s+PERIOD\s*:\s*(\d{2}-[A-Z]{3}-\d{4})\s+to\s+(\d{2}-[A-Z]{3}-\d{4})",
    re.IGNORECASE,
)
_NAME_RE = re.compile(r"^(Mr\.|Mrs\.|Ms\.|Dr\.)\s+(.+)", re.MULTILINE)
_OPENING_ROW_RE = re.compile(
    r"([\d,]+\.\d{2})\s+CR\s+\d+\s+\d+\s+([\d,]+\.\d{2})\s+([\d,]+\.\d{2})\s+([\d,]+\.\d{2})\s+CR",
)
_IDFC_DATE_HINTS = ["%d-%b-%Y", "%d %b %y"]


def _strip_cr(balance: str) -> str:
    """Remove ' CR' suffix from balance strings."""
    return re.sub(r"\s*CR\s*$", "", balance.strip(), flags=re.IGNORECASE)


def _is_cr_suffix(token: str) -> bool:
    """Check if a token is just a CR/DR balance suffix."""
    return token.strip().upper() in ("CR", "DR")


class IdfcMetadataExtractor(MetadataExtractor):
    account_number_pattern = _ACCOUNT_RE
    period_pattern = _PERIOD_RE
    name_pattern = _NAME_RE
    opening_balance_pattern = None
    closing_balance_pattern = None

    def extract_account_holder_name(self, full_text: str) -> str | None:
        match = self.name_pattern.search(full_text) if self.name_pattern else None
        return match.group(2).strip() if match else None

    def extract_period(self, full_text: str) -> tuple[str | None, str | None]:
        match = self.period_pattern.search(full_text) if self.period_pattern else None
        if not match:
            return None, None
        return (
            parse_date_text(match.group(1), format_hints=["%d-%b-%Y"]),
            parse_date_text(match.group(2), format_hints=["%d-%b-%Y"]),
        )


class IdfcBankStatementParser(GenericBankStatementParser):
    """Parser for IDFC FIRST Bank savings/current account statements."""

    bank = "idfc"
    metadata_extractor = IdfcMetadataExtractor()

    def parse(self, raw_data: dict[str, Any]) -> ParsedBankStatement:
        pages = raw_data.get("pages", [])
        file_name = raw_data.get("file", "")

        full_text = "\n".join(
            str(page.get("text", "")) for page in pages if isinstance(page, dict)
        )

        metadata = self.metadata_extractor.extract(full_text)
        opening_balance, closing_balance = self._extract_balances(full_text)

        # Transactions — from tables across all pages
        transactions = self._extract_idfc_transactions(pages)
        transactions = self._post_process(transactions, raw_data)

        # If we didn't find opening/closing from text, try from transactions
        if not closing_balance and transactions:
            last_bal = transactions[-1].balance
            if last_bal:
                closing_balance = last_bal

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
            statement_period_start=metadata["period_start"],
            statement_period_end=metadata["period_end"],
            opening_balance=opening_balance,
            closing_balance=closing_balance,
            reconciliation=reconciliation,
        )

    def _extract_balances(self, text: str) -> tuple[str | None, str | None]:
        """Extract opening and closing balance from the summary table row."""
        m = _OPENING_ROW_RE.search(text)
        if m:
            opening = _strip_cr(m.group(1))
            closing = _strip_cr(m.group(4))
            return opening, closing
        return None, None

    def _extract_idfc_transactions(
        self,
        pages: list[dict[str, Any]],
    ) -> list[BankTransaction]:
        """Extract transactions from IDFC statement tables.

        Page 1's table is often malformed (merged Date/Value Date/Details
        columns). We try table extraction first; if a page yields a malformed
        5-col table (no clean date column), we fall back to parsing word-lines
        for that page. Page 2+ typically has clean 7-column tables.
        """
        all_txns: list[BankTransaction] = []

        for page in pages:
            tables = page.get("tables", [])
            page_txns: list[BankTransaction] = []

            for table in tables:
                if not table:
                    continue
                txns = self._parse_idfc_table(table)
                page_txns.extend(txns)

            # If table extraction found nothing for this page but there's
            # a transaction table in the text, try parsing the merged table
            # with dates extracted from word positions
            if not page_txns:
                page_text = str(page.get("text", "")).upper()
                if "WITHDRAWAL" in page_text and "DEPOSIT" in page_text:
                    for table in tables:
                        if not table:
                            continue
                        row_text = " ".join(
                            str(c or "") for c in (table[0] or [])
                        ).upper()
                        # Skip the summary table (has "NUMBER OF" in header)
                        if "NUMBER OF" in row_text:
                            continue
                        # Check if it's the transaction table (has balance column)
                        if "BALANCE" in row_text or (
                            "WITHDRAWAL" in row_text and "DATE" in row_text
                        ):
                            page_txns = self._parse_idfc_merged_table(table, page)
                            if page_txns:
                                break

            all_txns.extend(page_txns)

        return all_txns

    def _parse_idfc_merged_table(
        self,
        table: list[list],
        page: dict[str, Any],
    ) -> list[BankTransaction]:
        """Parse page 1's malformed 5-col table where date columns are merged.

        Column 0 contains narration (with date fragments mixed in).
        Columns 2/3/4 are Withdrawals/Deposits/Balance (clean).

        Dates are extracted from the page's word positions.
        """
        txns: list[BankTransaction] = []

        # Extract dates from page words
        words = page.get("words", [])
        lines = group_words_into_lines(words) if words else []

        # Build list of (date, time) from word lines with DD Mon YY pattern
        date_entries: list[tuple[str, str | None]] = []
        for line_words in lines:
            tokens = [w["text"] for w in line_words]
            if len(tokens) >= 3:
                date = parse_date_text(
                    f"{tokens[0]} {tokens[1]} {tokens[2]}",
                    format_hints=["%d %b %y"],
                )
                if date:
                    time_str = None
                    if len(tokens) > 3 and re.fullmatch(r"\d{2}:\d{2}", tokens[3]):
                        time_str = tokens[3]
                    date_entries.append((date, time_str))

        # Dates come in pairs: (date+time, value_date). Keep only the first of each pair.
        txn_dates: list[tuple[str, str | None]] = []
        i = 0
        while i < len(date_entries):
            txn_dates.append(date_entries[i])
            # Skip the value date (same date, typically no time)
            if i + 1 < len(date_entries) and date_entries[i + 1][1] is None:
                i += 2
            else:
                i += 1

        # Collect data rows from the table (skip header and opening balance)
        data_rows = []
        for row in table:
            if not row:
                continue
            # Skip header row — check first cell only (not full row, since
            # narrations can contain "WITHDRAWAL" or "BALANCE" legitimately)
            first_cell = str(row[0] or "").upper()
            if (
                "WITHDRAWAL" in first_cell
                or "BALANCE" in first_cell
                or "DATE" in first_cell
            ):
                continue
            cell0 = str(row[0] or "").strip().lower()
            if "opening balance" in cell0:
                continue
            # Must have an amount in withdrawal or deposit column
            has_amount = False
            for col_idx in [2, 3]:
                if col_idx < len(row):
                    cell = str(row[col_idx] or "").strip()
                    if extract_amount(cell):
                        has_amount = True
                        break
            if has_amount:
                data_rows.append(row)

        # Match dates to rows 1:1
        for row_idx, row in enumerate(data_rows):
            if row_idx >= len(txn_dates):
                break

            date, _ = txn_dates[row_idx]

            # Clean narration from column 0
            narr_raw = str(row[0] or "").replace("\n", " ").strip()
            # Remove "Mon YY" date fragments
            narr_raw = re.sub(r"\b[A-Z][a-z]{2}\s+\d{2}\b", "", narr_raw).strip()
            narr_raw = re.sub(r"\s{2,}", " ", narr_raw)

            debit_str = str(row[2] or "").strip() if len(row) > 2 else ""
            credit_str = str(row[3] or "").strip() if len(row) > 3 else ""
            balance_str = str(row[4] or "").strip() if len(row) > 4 else ""

            debit_amt = extract_amount(debit_str) if debit_str else None
            credit_amt = extract_amount(credit_str) if credit_str else None

            if debit_amt:
                direction = "debit"
                amount = debit_amt
            elif credit_amt:
                direction = "credit"
                amount = credit_amt
            else:
                continue

            balance = extract_amount(_strip_cr(balance_str)) if balance_str else None
            channel = detect_channel(narr_raw)
            ref = extract_reference_number(narr_raw)

            txns.append(
                BankTransaction(
                    date=date,
                    narration=narr_raw,
                    amount=amount,
                    transaction_type=direction,
                    balance=balance,
                    reference_number=ref,
                    channel=channel,
                )
            )

        return txns

    def _parse_idfc_table(self, table: list[list]) -> list[BankTransaction]:
        """Parse a single IDFC table into transactions."""
        txns: list[BankTransaction] = []

        # Find the transaction table by looking for the header row
        header_idx = None
        for i, row in enumerate(table):
            if not row:
                continue
            row_text = " ".join(str(c or "") for c in row).upper()
            if "WITHDRAWAL" in row_text and (
                "DEPOSIT" in row_text or "BALANCE" in row_text
            ):
                header_idx = i
                break

        if header_idx is None:
            return txns

        # Determine column mapping from header
        header = table[header_idx]
        cols = self._classify_idfc_columns(header)
        if cols is None:
            return txns

        # Parse data rows after header
        for row in table[header_idx + 1 :]:
            txn = self._parse_idfc_row(row, cols)
            if txn:
                txns.append(txn)

        return txns

    def _classify_idfc_columns(self, header: list) -> dict[str, int] | None:
        """Map column indices for IDFC table headers.

        Expected columns (7-col layout):
        Date and Time | Value Date | Transaction Details | Ref/Cheque No. |
        Withdrawals (INR) | Deposits (INR) | Balance (INR)

        Or (5-col layout from page 1, merged):
        ue Date Transaction Details | Ref/Cheque No. | Withdrawals (INR) |
        Deposits (INR) | Balance (INR)
        """
        cols: dict[str, int] = {}
        for i, cell in enumerate(header):
            if cell is None:
                continue
            upper = str(cell).upper().replace("\n", " ")
            if "DATE AND TIME" in upper:
                cols["date"] = i
            elif "VALUE DATE" in upper and "date" in cols:
                cols["value_date"] = i
            elif "TRANSACTION" in upper or "DETAILS" in upper:
                cols["narration"] = i
            elif "REF" in upper or "CHEQUE" in upper:
                cols["ref"] = i
            elif "WITHDRAWAL" in upper:
                cols["debit"] = i
            elif "DEPOSIT" in upper and "BALANCE" not in upper:
                cols["credit"] = i
            elif "BALANCE" in upper:
                cols["balance"] = i

        # For the 5-col merged layout (page 1), the first column contains
        # the merged value_date + narration. Try to work with it.
        if "date" not in cols and "debit" in cols:
            # Merged layout — no clean date column
            cols["merged"] = 0
            if "narration" not in cols:
                cols["narration"] = 0

        if "debit" not in cols and "credit" not in cols:
            return None

        return cols

    def _parse_idfc_row(
        self,
        row: list,
        cols: dict[str, int],
    ) -> BankTransaction | None:
        """Parse a single data row into a BankTransaction."""
        if not row:
            return None

        # Get date from "Date and Time" column
        date_str = None

        if "date" in cols:
            date_cell = str(row[cols["date"]] or "").strip()
            if not date_cell:
                return None
            # Date cell format: "01 Mar 26\n22:38"
            parts = date_cell.split("\n")
            date_str = parse_date_text(parts[0].strip(), format_hints=_IDFC_DATE_HINTS)
            # Time is in the second line (e.g., "22:38") but not used in output
        elif "merged" in cols:
            # Merged layout — try to find date in the cell text
            merged_cell = str(row[cols["merged"]] or "").strip()
            if not merged_cell:
                return None
            # Look for "DD Mon YY" pattern in the text
            m = re.search(r"(\d{2}\s+[A-Za-z]{3}\s+\d{2})", merged_cell)
            if not m:
                return None
            date_str = parse_date_text(m.group(1), format_hints=_IDFC_DATE_HINTS)

        if not date_str:
            # Check for special rows like "opening balance"
            narr_col = cols.get("narration", cols.get("merged", 0))
            narr_text = (
                str(row[narr_col] or "").strip().lower() if narr_col < len(row) else ""
            )
            if "opening balance" in narr_text:
                return None  # Skip opening balance row
            return None

        # Narration
        narration = ""
        if "narration" in cols and cols["narration"] < len(row):
            narration = str(row[cols["narration"]] or "").strip()
            narration = narration.replace("\n", " ")

        # Value date
        value_date = None
        if "value_date" in cols and cols["value_date"] < len(row):
            vd = str(row[cols["value_date"]] or "").strip()
            value_date = parse_date_text(vd, format_hints=_IDFC_DATE_HINTS)

        # Amounts
        debit_str = ""
        credit_str = ""
        balance_str = ""

        if "debit" in cols and cols["debit"] < len(row):
            debit_str = str(row[cols["debit"]] or "").strip()
        if "credit" in cols and cols["credit"] < len(row):
            credit_str = str(row[cols["credit"]] or "").strip()
        if "balance" in cols and cols["balance"] < len(row):
            balance_str = str(row[cols["balance"]] or "").strip()

        debit_amt = extract_amount(debit_str) if debit_str else None
        credit_amt = extract_amount(credit_str) if credit_str else None

        if debit_amt:
            direction = "debit"
            amount = debit_amt
        elif credit_amt:
            direction = "credit"
            amount = credit_amt
        else:
            return None

        balance = extract_amount(_strip_cr(balance_str)) if balance_str else None
        channel = detect_channel(narration)
        ref = extract_reference_number(narration)

        return BankTransaction(
            date=date_str,
            narration=narration,
            amount=amount,
            transaction_type=direction,
            balance=balance,
            reference_number=ref,
            channel=channel,
            value_date=value_date,
        )
