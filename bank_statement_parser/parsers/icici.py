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
from typing import Any

from bank_statement_parser.models import BankTransaction, ParsedBankStatement
from bank_statement_parser.parsers.extractors import (
    ColumnThresholds,
    group_words_into_lines,
)
from bank_statement_parser.parsers.generic import GenericBankStatementParser
from bank_statement_parser.parsers.metadata import MetadataExtractor
from bank_statement_parser.parsers.reconciliation import build_reconciliation
from bank_statement_parser.parsers.utils import (
    AMOUNT_RE,
    detect_channel,
    extract_reference_number,
    parse_date_text,
)

_ACCOUNT_RE = re.compile(r"Savings\s+Account\s+([\dX]+)", re.IGNORECASE)
_PERIOD_RE = re.compile(
    r"period\s+([A-Z][a-z]+)\s+(\d{2}),\s+(\d{4})\s*-\s*([A-Z][a-z]+)\s+(\d{2}),\s+(\d{4})",
    re.IGNORECASE,
)
_NAME_RE = re.compile(r"ACCOUNT\s+HOLDERS?\s*:\s*(MR\.|MRS\.|MS\.)?(.+)", re.IGNORECASE)

_THRESHOLDS = ColumnThresholds(
    deposit_max=420.0,
    withdrawal_max=520.0,
)


class IciciMetadataExtractor(MetadataExtractor):
    account_number_pattern = _ACCOUNT_RE
    period_pattern = _PERIOD_RE
    name_pattern = _NAME_RE
    opening_balance_pattern = None
    closing_balance_pattern = None

    def extract_account_holder_name(self, full_text: str) -> str | None:
        match = self.name_pattern.search(full_text) if self.name_pattern else None
        if not match:
            return None
        name = match.group(2).strip()
        return name or None

    def extract_period(self, full_text: str) -> tuple[str | None, str | None]:
        match = self.period_pattern.search(full_text) if self.period_pattern else None
        if not match:
            return None, None
        return (
            parse_date_text(
                f"{match.group(1)} {match.group(2)}, {match.group(3)}",
                dayfirst=False,
                format_hints=["%B %d, %Y"],
            ),
            parse_date_text(
                f"{match.group(4)} {match.group(5)}, {match.group(6)}",
                dayfirst=False,
                format_hints=["%B %d, %Y"],
            ),
        )


class IciciBankStatementParser(GenericBankStatementParser):
    """Parser for ICICI Bank savings/current account statements."""

    bank = "icici"
    metadata_extractor = IciciMetadataExtractor()

    def parse(self, raw_data: dict[str, Any]) -> ParsedBankStatement:
        pages = raw_data.get("pages", [])
        file_name = raw_data.get("file", "")

        full_text = "\n".join(
            str(page.get("text", "")) for page in pages if isinstance(page, dict)
        )

        metadata = self.metadata_extractor.extract(full_text)

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

        transactions = self._post_process(transactions, raw_data)

        # Closing balance from last transaction
        closing_balance = transactions[-1].balance if transactions else None

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
            date = parse_date_text(tokens[0], format_hints=["%d-%m-%Y"])

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
                    if (
                        _THRESHOLDS.deposit_max is not None
                        and x < _THRESHOLDS.deposit_max
                    ):
                        deposit_amt = amt_str
                    elif (
                        _THRESHOLDS.withdrawal_max is not None
                        and x < _THRESHOLDS.withdrawal_max
                    ):
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
                if parse_date_text(next_tokens[0], format_hints=["%d-%m-%Y"]):
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
