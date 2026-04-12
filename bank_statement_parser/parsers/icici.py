"""ICICI Bank savings account statement parser.

ICICI bank statements render transactions as positioned text, NOT as PDF
tables. pdfplumber finds no usable transaction tables — only single-row
header/footer tables. Parsing uses word-line reconstruction.

Layout:
- Narration text spans multiple lines above/below the date line
- Date lines start with DD-MM-YYYY and contain amounts positioned at:
  - x < 420: deposit
  - 420 < x < 520: withdrawal
  - x > 520: balance
- First date row with "B/F" is the opening balance (Brought Forward)
- Summary rows with "Total:" at end of each page
- Account number in "Savings Account XXXXXXXXNNNN"
- Statement period in "March 01, 2026 - March 31, 2026"
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Any

from bank_statement_parser.models import BankTransaction, ParsedBankStatement
from bank_statement_parser.parsers.generic import (
    AMOUNT_RE,
    GenericBankStatementParser,
    _build_reconciliation,
    detect_channel,
    extract_reference_number,
    format_amount,
    group_words_into_lines,
    parse_amount,
)

_DATE_RE = re.compile(r"^\d{2}-\d{2}-\d{4}$")
_ACCOUNT_RE = re.compile(r"Savings\s+Account\s+([\dX]+)", re.IGNORECASE)
_PERIOD_RE = re.compile(
    r"period\s+([A-Z][a-z]+)\s+(\d{2}),\s+(\d{4})\s*-\s*([A-Z][a-z]+)\s+(\d{2}),\s+(\d{4})",
    re.IGNORECASE,
)
_NAME_RE = re.compile(r"ACCOUNT\s+HOLDERS?\s*:\s*(MR\.|MRS\.|MS\.)?(.+)", re.IGNORECASE)

_MONTH_MAP = {
    "january": "01",
    "february": "02",
    "march": "03",
    "april": "04",
    "may": "05",
    "june": "06",
    "july": "07",
    "august": "08",
    "september": "09",
    "october": "10",
    "november": "11",
    "december": "12",
}

# x-position thresholds for classifying amounts (from header positions)
_DEPOSIT_X_MAX = 420.0
_WITHDRAWAL_X_MAX = 520.0


def _parse_icici_date(raw: str) -> str | None:
    """Parse DD-MM-YYYY into DD/MM/YYYY."""
    raw = raw.strip()
    if _DATE_RE.fullmatch(raw):
        return raw.replace("-", "/")
    return None


def _parse_period_date(month_name: str, day: str, year: str) -> str | None:
    """Parse 'March 01, 2026' components into DD/MM/YYYY."""
    m = _MONTH_MAP.get(month_name.lower())
    if m:
        return f"{day}/{m}/{year}"
    return None


class IciciBankStatementParser(GenericBankStatementParser):
    """Parser for ICICI Bank savings/current account statements."""

    bank = "icici"

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

        # Transactions from word-lines across all pages
        transactions: list[BankTransaction] = []
        opening_balance: str | None = None

        for page in pages:
            words = page.get("words", [])
            if not words:
                continue
            txns, ob = self._parse_icici_page(words)
            transactions.extend(txns)
            if ob is not None and opening_balance is None:
                opening_balance = ob

        # Assign IDs
        for i, txn in enumerate(transactions):
            txn.transaction_id = f"icici_txn_{i:04d}"

        # Closing balance from last transaction
        closing_balance = transactions[-1].balance if transactions else None

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
            name = m.group(2).strip()
            return name if name else None
        return None

    def _extract_period(self, text: str) -> tuple[str | None, str | None]:
        m = _PERIOD_RE.search(text)
        if not m:
            return None, None
        start = _parse_period_date(m.group(1), m.group(2), m.group(3))
        end = _parse_period_date(m.group(4), m.group(5), m.group(6))
        return start, end

    def _parse_icici_page(
        self,
        words: list[dict[str, Any]],
    ) -> tuple[list[BankTransaction], str | None]:
        """Parse a single page's words into transactions.

        Returns (transactions, opening_balance).
        """
        lines = group_words_into_lines(words)
        txns: list[BankTransaction] = []
        opening_balance: str | None = None

        # Collect transactions: each transaction spans a date line + surrounding
        # narration lines. We walk through lines, collecting narration text
        # between date lines.
        pending_narration_above: list[str] = []
        i = 0

        while i < len(lines):
            line_words = lines[i]
            tokens = [w["text"] for w in line_words]

            if not tokens:
                i += 1
                continue

            # Skip header/section/footer lines
            joined = " ".join(tokens)
            upper = joined.upper()
            if any(
                kw in upper
                for kw in (
                    "DATE",
                    "PARTICULARS",
                    "ACCOUNT DETAILS",
                    "ACCOUNT HOLDERS",
                    "STATEMENT OF TRANSACTIONS",
                    "ACCOUNT TYPE",
                    "TOTAL",
                    "NOMINATION",
                    "REGISTERED",
                    "PAGE",
                )
            ):
                pending_narration_above = []
                i += 1
                continue

            # Check if this line starts with a date
            date = _parse_icici_date(tokens[0])

            if not date:
                # Not a date line — accumulate as narration for the next transaction
                # Filter out pure continuation hash/ref fragments
                narr_text = joined.strip()
                if narr_text and not narr_text.startswith("Total"):
                    pending_narration_above.append(narr_text)
                i += 1
                continue

            # Date line found — extract amounts by x-position
            deposit_amt = None
            withdrawal_amt = None
            balance_amt = None
            mode_tokens: list[str] = []

            for w in line_words[1:]:  # skip the date token
                amt_match = AMOUNT_RE.search(w["text"])
                if amt_match:
                    x = float(w["x0"])
                    amt_str = amt_match.group(0)
                    if x < _DEPOSIT_X_MAX:
                        deposit_amt = amt_str
                    elif x < _WITHDRAWAL_X_MAX:
                        withdrawal_amt = amt_str
                    else:
                        balance_amt = amt_str
                else:
                    # Non-amount token on date line = mode or narration continuation
                    mode_tokens.append(w["text"])

            # Check for B/F (Brought Forward) — opening balance
            if "B/F" in " ".join(mode_tokens):
                opening_balance = balance_amt
                pending_narration_above = []
                i += 1
                continue

            # Determine direction
            if withdrawal_amt and not deposit_amt:
                direction = "debit"
                amount = withdrawal_amt
            elif deposit_amt and not withdrawal_amt:
                direction = "credit"
                amount = deposit_amt
            elif deposit_amt and withdrawal_amt:
                # Both present — unusual, treat deposit
                direction = "credit"
                amount = deposit_amt
            else:
                # No amount — skip
                pending_narration_above = []
                i += 1
                continue

            # Build narration: above-lines + mode tokens + below continuation lines
            narration_parts = list(pending_narration_above)
            if mode_tokens:
                narration_parts.append(" ".join(mode_tokens))

            # Collect continuation lines below (non-date, non-header lines)
            pending_narration_above = []
            i += 1
            while i < len(lines):
                next_tokens = [w["text"] for w in lines[i]]
                if not next_tokens:
                    i += 1
                    continue
                # Check if next line is a date or header
                if _parse_icici_date(next_tokens[0]):
                    break  # Next transaction starts
                next_joined = " ".join(next_tokens)
                next_upper = next_joined.upper()
                if any(kw in next_upper for kw in ("TOTAL:", "DATE", "PAGE")):
                    i += 1
                    continue
                # Check if this looks like narration for the NEXT transaction
                # (starts with UPI/, NEFT/, IMPS/, MMT/, etc.)
                if re.match(
                    r"^(UPI|NEFT|IMPS|MMT|RTGS|POS|ATM|ACH|NACH|SI/|FT/|VISA|BIL)",
                    next_joined,
                    re.IGNORECASE,
                ):
                    # This is the start of narration for the NEXT date line
                    pending_narration_above.append(next_joined.strip())
                    i += 1
                    break
                # Continuation of current narration
                narration_parts.append(next_joined.strip())
                i += 1

            narration = " ".join(narration_parts).strip()
            channel = detect_channel(narration)
            ref = extract_reference_number(narration)

            txns.append(
                BankTransaction(
                    date=date,
                    narration=narration,
                    amount=amount,
                    transaction_type=direction,
                    balance=balance_amt,
                    reference_number=ref,
                    channel=channel,
                )
            )

        return txns, opening_balance
