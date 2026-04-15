"""HDFC Bank account statement parser.

HDFC bank statements have a highly compressed table layout:
- Each page has a single 2-row "table": one header row and one data row
- The data row contains all transactions packed as newline-delimited values
  in each cell:
    - Col 0 (Txn Date):       DD/MM/YYYY\nDD/MM/YYYY\n...   (one per txn)
    - Col 1 (Narration):      multi-line per txn, each ends with
                              "Value Dt DD/MM/YYYY [Ref XXXXXXXXX]"
    - Col 2 (Withdrawals):    amount\namount\n...
    - Col 3 (Deposits):       amount\namount\n...
    - Col 4 (Closing Balance):amount\namount\n...
- 0.00 is used for the non-applicable side (debit or credit)
- Date format: DD/MM/YYYY (ISO-aligned)
- Account number, holder name, and statement period appear in page text
- Opening balance on each page in "Opening Balance : X,XX,XXX.XX"
- Summary row on last page: Opening Balance / Debit / Credit / Closing
"""

from __future__ import annotations

import re
from typing import Any

from bank_statement_parser.models import BankTransaction, ParsedBankStatement
from bank_statement_parser.parsers.generic import GenericBankStatementParser
from bank_statement_parser.parsers.reconciliation import build_reconciliation
from bank_statement_parser.parsers.utils import (
    detect_channel,
    extract_amount,
    extract_reference_number,
    parse_amount,
    parse_date_text,
)

# ---------------------------------------------------------------------------
# Metadata regexes
# ---------------------------------------------------------------------------

_ACCOUNT_RE = re.compile(r"Account\s+Number\s*:\s*(\d+)", re.IGNORECASE)
_NAME_RE = re.compile(r"^([A-Z][a-z].*?)(?:\s{2,}|\n)", re.MULTILINE)
_PERIOD_RE = re.compile(
    r"Statement\s+From\s*:\s*(\d{2}/\d{2}/\d{4})\s+To\s+(\d{2}/\d{2}/\d{4})",
    re.IGNORECASE,
)
_OPENING_BAL_RE = re.compile(r"Opening\s+Balance\s*:\s*([\d,]+\.\d{2})", re.IGNORECASE)
_CLOSING_BAL_RE = re.compile(
    r"Opening\s+Balance\s+Debit\s+Amount\s+Credit\s+Amount\s+Closing\s+Balance\s+"
    r"([\d,]+\.\d{2})\s+([\d,]+\.\d{2})\s+([\d,]+\.\d{2})\s+([\d,]+\.\d{2})",
    re.IGNORECASE,
)

# Each narration block ends with "Value Dt DD/MM/YYYY [Ref XXXXXXXXX]"
# We split the joined narration string on this pattern so each split
# captures (prefix_text, value_dt_block) pairs.
_VALUE_DT_RE = re.compile(r"(Value\s+Dt\s+\d{2}/\d{2}/\d{4}(?:\s+Ref\s+\S+)?)")

# Ref line in narration: "Ref XXXXXXXXXXXX"
_NARR_REF_RE = re.compile(r"\bRef\s+(\S+)")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _group_narrations(narration_str: str) -> list[str]:
    """Split merged narration cell into individual per-transaction narrations.

    Each HDFC narration block ends with a "Value Dt DD/MM/YYYY [Ref XXXX]"
    marker. We join all lines into one string then split on this marker,
    pairing prefix text with its Value Dt line.
    """
    joined = " ".join(narration_str.split("\n"))
    parts = _VALUE_DT_RE.split(joined)

    narrations: list[str] = []
    i = 0
    while i < len(parts):
        chunk = parts[i].strip()
        if i + 1 < len(parts) and _VALUE_DT_RE.fullmatch(parts[i + 1].strip()):
            # Combine prefix text with the Value Dt marker
            val_dt = parts[i + 1].strip()
            narration = f"{chunk} {val_dt}".strip() if chunk else val_dt
            narrations.append(narration)
            i += 2
        else:
            if chunk:
                narrations.append(chunk)
            i += 1

    return narrations


def _extract_value_date(narration: str) -> str | None:
    """Extract value date from narration's 'Value Dt DD/MM/YYYY' marker."""
    m = re.search(r"Value\s+Dt\s+(\d{2}/\d{2}/\d{4})", narration)
    if m:
        return parse_date_text(m.group(1))
    return None


def _clean_narration(narration: str) -> str:
    """Strip the trailing 'Value Dt ... Ref ...' suffix from narration text."""
    cleaned = re.sub(
        r"\s+Value\s+Dt\s+\d{2}/\d{2}/\d{4}(?:\s+Ref\s+\S+)?$", "", narration
    )
    return cleaned.strip()


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


class HdfcBankStatementParser(GenericBankStatementParser):
    """Parser for HDFC Bank savings/current account statements."""

    bank = "hdfc"

    def parse(self, raw_data: dict[str, Any]) -> ParsedBankStatement:
        pages = raw_data.get("pages", [])
        file_name = raw_data.get("file", "")

        full_text = "\n".join(
            str(page.get("text", "")) for page in pages if isinstance(page, dict)
        )

        # Metadata extraction
        account_number = self._extract_account_number(full_text)
        holder_name = self._extract_name(full_text)
        period_start, period_end = self._extract_period(full_text)
        opening_balance = self._extract_opening_balance(full_text)
        closing_balance = self._extract_closing_balance(full_text)

        # Transactions
        transactions = self._extract_hdfc_transactions(pages)
        transactions = self._post_process(transactions, raw_data)

        # Fallback: use last transaction's balance as closing balance
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
            account_holder_name=holder_name,
            account_number=account_number,
            statement_period_start=period_start,
            statement_period_end=period_end,
            opening_balance=opening_balance,
            closing_balance=closing_balance,
            reconciliation=reconciliation,
        )

    # ------------------------------------------------------------------
    # Metadata helpers
    # ------------------------------------------------------------------

    def _extract_account_number(self, text: str) -> str | None:
        m = _ACCOUNT_RE.search(text)
        return m.group(1).strip() if m else None

    def _extract_name(self, text: str) -> str | None:
        """Extract the account holder's name from the first line of text."""
        # The name appears as the first non-header line on page 1
        for line in text.splitlines():
            line = line.strip()
            # Name is typically "Firstname Lastname" — title-cased, no colon
            if line and ":" not in line and re.match(r"[A-Z][a-z]", line):
                # Skip page header lines like "Page 1 of 5"
                if re.match(r"Page\s+\d+", line, re.IGNORECASE):
                    continue
                # Likely the name if it looks like a proper name
                if re.match(r"[A-Z][a-z]+ [A-Z]", line):
                    return line
        return None

    def _extract_period(self, text: str) -> tuple[str | None, str | None]:
        m = _PERIOD_RE.search(text)
        if m:
            return parse_date_text(m.group(1)), parse_date_text(m.group(2))
        return None, None

    def _extract_opening_balance(self, text: str) -> str | None:
        m = _OPENING_BAL_RE.search(text)
        return m.group(1) if m else None

    def _extract_closing_balance(self, text: str) -> str | None:
        """Extract closing balance from the SUMMARY section on the last page."""
        m = _CLOSING_BAL_RE.search(text)
        if m:
            # SUMMARY row: Opening Balance | Debit Amount | Credit Amount | Closing Balance
            return m.group(4)
        return None

    # ------------------------------------------------------------------
    # Transaction extraction
    # ------------------------------------------------------------------

    def _extract_hdfc_transactions(
        self,
        pages: list[dict[str, Any]],
    ) -> list[BankTransaction]:
        """Parse all transactions from the HDFC compressed table format."""
        all_txns: list[BankTransaction] = []

        for page in pages:
            tables = page.get("tables", [])
            for table in tables:
                if not table or len(table) < 2:
                    continue

                # Check if this is the transaction table (has Txn Date / Narration header)
                header = table[0]
                header_text = " ".join(str(c or "") for c in header).upper()
                if "TXN DATE" not in header_text and "NARRATION" not in header_text:
                    continue

                # The data is in row 1 (the single merged data row)
                data_row = table[1]
                if not data_row or len(data_row) < 5:
                    continue

                txns = self._parse_hdfc_data_row(data_row)
                all_txns.extend(txns)

        return all_txns

    def _parse_hdfc_data_row(
        self,
        row: list[Any],
    ) -> list[BankTransaction]:
        """Parse a single merged data row into individual BankTransactions.

        The row has 5 cells, each containing newline-delimited values for all
        transactions on the page:
          [0] Dates        [1] Narrations   [2] Withdrawals
          [3] Deposits     [4] Closing Balances
        """
        txns: list[BankTransaction] = []

        dates_raw = str(row[0] or "").strip()
        narr_raw = str(row[1] or "").strip()
        wd_raw = str(row[2] or "").strip()
        dep_raw = str(row[3] or "").strip()
        bal_raw = str(row[4] or "").strip()

        # Split the simple columns by newline
        dates = [d.strip() for d in dates_raw.split("\n") if d.strip()]
        withdrawals = [w.strip() for w in wd_raw.split("\n") if w.strip()]
        deposits = [d.strip() for d in dep_raw.split("\n") if d.strip()]
        balances = [b.strip() for b in bal_raw.split("\n") if b.strip()]

        # Split narrations using Value Dt markers
        narrations = _group_narrations(narr_raw)

        # Guard: all lists must have the same length
        n = len(dates)
        if not (len(withdrawals) == len(deposits) == len(balances) == n):
            return txns
        if len(narrations) != n:
            return txns

        for i in range(n):
            date = parse_date_text(dates[i])
            if not date:
                continue

            narration_full = narrations[i]
            value_date = _extract_value_date(narration_full)
            narration = _clean_narration(narration_full)

            wd_amt = extract_amount(withdrawals[i])
            dep_amt = extract_amount(deposits[i])
            bal_amt = extract_amount(balances[i])

            # Classify: HDFC uses 0.00 for the non-applicable side
            if wd_amt and parse_amount(wd_amt) > 0:
                direction: str = "debit"
                amount = wd_amt
            elif dep_amt and parse_amount(dep_amt) > 0:
                direction = "credit"
                amount = dep_amt
            else:
                # Both zero — skip this row
                continue

            ref = _NARR_REF_RE.search(narration_full)
            reference_number = (
                ref.group(1) if ref else extract_reference_number(narration)
            )
            channel = detect_channel(narration)

            txns.append(
                BankTransaction(
                    date=date,
                    narration=narration,
                    amount=amount,
                    transaction_type=direction,
                    balance=bal_amt,
                    reference_number=reference_number,
                    channel=channel,
                    value_date=value_date,
                )
            )

        return txns
