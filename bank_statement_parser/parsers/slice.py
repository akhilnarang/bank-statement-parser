"""Slice Small Finance Bank account statement parser.

Slice bank statements have:
- No PDF tables — transactions are rendered as positioned word text
- Date format: DD Mon 'YY (e.g. "01 Mar '26") — 3 tokens at x < 90
- Column layout (approximate x positions):
    Date:      x ~32–58
    Narration: x ~92 (continuation lines have no date)
    Ref No:    x ~284
    Amount:    x ~420–450 (₹ or -₹ prefix)
    Balance:   x ~515–535 (₹ prefix)
- Amounts with '-₹' prefix are debits; '₹' prefix (no minus) are credits
- Opening/closing balances from the summary line on page 1
- Account number from "A/C number XXXXXXX" line
- Statement period from "DD Mon 'YY - DD Mon 'YY" header
- Account holder name from first non-header text line
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
from bank_statement_parser.parsers.reconciliation import build_reconciliation
from bank_statement_parser.parsers.utils import (
    detect_channel,
    extract_amount,
    extract_reference_number,
    parse_date_text,
)

# Regex patterns for metadata extraction
_ACCOUNT_RE = re.compile(r"A/C\s+number\s+(\d+)", re.IGNORECASE)
_PERIOD_RE = re.compile(
    r"(\d{1,2})\s+([A-Za-z]{3})\s+'(\d{2})\s*-\s*(\d{1,2})\s+([A-Za-z]{3})\s+'(\d{2})"
)
_NAME_RE = re.compile(r"^([A-Z][A-Z\s]+)$", re.MULTILINE)
# Opening balance summary: ₹7,52,230.91 (first ₹ amount in summary row)
_SUMMARY_AMOUNTS_RE = re.compile(
    r"₹([\d,]+\.\d{2})\s+₹([\d,]+\.\d{2})\s+₹([\d,]+\.\d{2})\s+₹([\d,]+\.\d{2})\s+₹([\d,]+\.\d{2})"
)

_THRESHOLDS = ColumnThresholds(
    date_max=40.0,
    ref_min=270.0,
    amount_min=410.0,
    balance_min=505.0,
)


def _strip_rupee(token: str) -> tuple[str | None, bool]:
    """Strip ₹ or -₹ prefix and return (amount_str, is_debit).

    Returns (None, False) if the token is not an amount.
    """
    token = token.strip()
    if token.startswith("-₹"):
        amt = extract_amount(token[2:])
        return amt, True
    if token.startswith("₹"):
        amt = extract_amount(token[1:])
        return amt, False
    return None, False


class SliceBankStatementParser(GenericBankStatementParser):
    """Parser for Slice Small Finance Bank savings account statements."""

    bank = "slice"

    def parse(self, raw_data: dict[str, Any]) -> ParsedBankStatement:
        pages = raw_data.get("pages", [])
        file_name = raw_data.get("file", "")

        full_text = "\n".join(
            str(page.get("text", "")) for page in pages if isinstance(page, dict)
        )

        account_number = self._extract_account_number(full_text)
        holder_name = self._extract_name(full_text)
        period_start, period_end = self._extract_period(full_text)
        opening_balance, closing_balance = self._extract_balances(full_text)

        transactions = self._extract_slice_transactions(pages)
        transactions = self._post_process(transactions, raw_data)

        if not closing_balance and transactions:
            last_bal = transactions[-1].balance
            if last_bal:
                closing_balance = last_bal

        if not period_start and transactions:
            period_start = transactions[0].date
        if not period_end and transactions:
            period_end = transactions[-1].date

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
    # Metadata extraction
    # ------------------------------------------------------------------

    def _extract_account_number(self, text: str) -> str | None:
        m = _ACCOUNT_RE.search(text)
        return m.group(1) if m else None

    def _extract_name(self, text: str) -> str | None:
        """Extract account holder name — first ALL-CAPS multi-word line."""
        for line in text.splitlines():
            line = line.strip()
            if re.fullmatch(r"[A-Z][A-Z\s]{4,}", line):
                return line
        return None

    def _extract_period(self, text: str) -> tuple[str | None, str | None]:
        """Parse period from 'DD Mon 'YY - DD Mon 'YY' header."""
        m = _PERIOD_RE.search(text)
        if not m:
            return None, None
        start = parse_date_text(
            f"{m.group(1)} {m.group(2)} {m.group(3)}",
            format_hints=["%d %b %y"],
        )
        end = parse_date_text(
            f"{m.group(4)} {m.group(5)} {m.group(6)}",
            format_hints=["%d %b %y"],
        )
        return start, end

    def _extract_balances(self, text: str) -> tuple[str | None, str | None]:
        """Extract opening and closing balance from summary row on page 1.

        Row format: ₹OPENINGbal ₹CREDITS ₹INTEREST ₹DEBITS ₹CLOSING
        The first amount is opening balance, the last is closing balance.
        """
        m = _SUMMARY_AMOUNTS_RE.search(text)
        if m:
            opening = m.group(1)
            closing = m.group(5)
            return opening, closing
        return None, None

    # ------------------------------------------------------------------
    # Transaction extraction
    # ------------------------------------------------------------------

    def _extract_slice_transactions(
        self,
        pages: list[dict[str, Any]],
    ) -> list[BankTransaction]:
        """Parse transactions from all pages using word-position analysis."""
        all_txns: list[BankTransaction] = []

        for page in pages:
            words = page.get("words", [])
            if not words:
                continue
            lines = group_words_into_lines(words)
            page_txns = self._parse_page_lines(lines)
            all_txns.extend(page_txns)

        return all_txns

    def _parse_page_lines(
        self,
        lines: list[list[dict[str, Any]]],
    ) -> list[BankTransaction]:
        """Parse word-position lines from a single page into transactions.

        Each transaction may span multiple lines due to long narrations.
        A new transaction starts whenever we see a valid 3-token date at
        low x-position. Continuation lines (narration overflow) have no
        date and start with text at x~92.
        """
        txns: list[BankTransaction] = []

        # Current pending transaction parts
        pending_date: str | None = None
        pending_narr_parts: list[str] = []
        pending_ref: str | None = None
        pending_amount: str | None = None
        pending_is_debit: bool = True
        pending_balance: str | None = None

        def flush() -> None:
            """Flush pending transaction to txns list."""
            nonlocal pending_date, pending_narr_parts, pending_ref
            nonlocal pending_amount, pending_is_debit, pending_balance

            if pending_date is None or pending_amount is None:
                pending_date = None
                pending_narr_parts = []
                pending_ref = None
                pending_amount = None
                pending_balance = None
                return

            narration = " ".join(pending_narr_parts).strip()
            channel = detect_channel(narration)
            if not channel and narration.lower() == "bill payment":
                channel = "upi"
            ref = pending_ref or extract_reference_number(narration, channel)
            direction: str = "debit" if pending_is_debit else "credit"

            txns.append(
                BankTransaction(
                    date=pending_date,
                    narration=narration,
                    amount=pending_amount,
                    transaction_type=direction,  # type: ignore[arg-type]
                    balance=pending_balance,
                    reference_number=ref,
                    channel=channel,
                )
            )
            pending_date = None
            pending_narr_parts = []
            pending_ref = None
            pending_amount = None
            pending_balance = None

        for line in lines:
            if not line:
                continue

            # Check if this line starts with a date (first 3 tokens at low x)
            toks = line  # list of word dicts
            first_x = float(toks[0]["x0"])

            # Date lines: first token is a 1-2 digit day number at x < 40
            is_date_line = (
                _THRESHOLDS.date_max is not None
                and first_x < _THRESHOLDS.date_max
                and re.fullmatch(r"\d{1,2}", toks[0]["text"])
                and len(toks) >= 3
                and re.fullmatch(r"[A-Za-z]{3}", toks[1]["text"])
                and re.fullmatch(r"'\d{2}", toks[2]["text"])
            )

            if is_date_line:
                # Flush previous pending transaction
                flush()

                date_str = parse_date_text(
                    f"{toks[0]['text']} {toks[1]['text']} {toks[2]['text']}",
                    format_hints=["%d %b %y"],
                )
                if not date_str:
                    continue

                pending_date = date_str

                # Remaining tokens after the 3 date tokens
                rest = toks[3:]

                # Split rest by column position:
                # narration words, ref column, amount column, balance column
                narr_words: list[str] = []
                ref_words: list[str] = []
                amount_str: str | None = None
                is_debit: bool = True
                balance_str: str | None = None

                for w in rest:
                    x = float(w["x0"])
                    text = w["text"]

                    if (
                        _THRESHOLDS.balance_min is not None
                        and x >= _THRESHOLDS.balance_min
                    ):
                        # Balance column
                        amt, _ = _strip_rupee(text)
                        if amt:
                            balance_str = amt
                        # else might be continuation of balance text (rare)
                    elif (
                        _THRESHOLDS.amount_min is not None
                        and x >= _THRESHOLDS.amount_min
                    ):
                        # Amount column
                        amt, debit_flag = _strip_rupee(text)
                        if amt:
                            amount_str = amt
                            is_debit = debit_flag
                    elif _THRESHOLDS.ref_min is not None and x >= _THRESHOLDS.ref_min:
                        # Ref number column
                        ref_words.append(text)
                    else:
                        # Narration column
                        narr_words.append(text)

                pending_narr_parts = narr_words
                pending_ref = " ".join(ref_words) if ref_words else None
                pending_amount = amount_str
                pending_is_debit = is_debit
                pending_balance = balance_str

            else:
                # Continuation line — check if it's a narration overflow or noise
                # Footer lines ("Need help?", "slice small finance bank", page header)
                # and page numbers should be skipped.
                line_text = " ".join(w["text"] for w in toks)

                # Skip page headers (e.g. "01 Mar '26 - 31 Mar '26", "1/7")
                if re.fullmatch(r"\d+/\d+", line_text.strip()):
                    continue
                if _PERIOD_RE.search(line_text):
                    continue
                # Skip footer
                if (
                    "help@slice.bank.in" in line_text
                    or "slice small finance bank" in line_text
                ):
                    continue
                # Skip "Generated on DD Mon 'YY"
                if line_text.strip().startswith("Generated"):
                    continue

                # Narration continuation — only if we have a pending transaction
                # and the line starts at narration x position
                if (
                    pending_date is not None
                    and _THRESHOLDS.ref_min is not None
                    and first_x < _THRESHOLDS.ref_min
                ):
                    pending_narr_parts.append(line_text.strip())

        # Flush the last pending transaction
        flush()

        return txns
