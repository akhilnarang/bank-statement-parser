"""ICICI Bank savings account statement parser.

ICICI bank statements render transactions as positioned text, NOT as PDF
tables. pdfplumber finds no usable transaction tables — only single-row
header/footer tables. Parsing uses word-line reconstruction.

Layout:
- Narration text spans multiple lines above/below the date line. The date,
  mode and amount cells are vertically centred on the row, and the particulars
  lines fill the row top-down at a fixed pitch. So the particulars lines of a
  row are symmetric about its date: a row has as many lines below its date as
  above it. Since July 2026 the first particulars line of a UPI/IMPS/NEFT row
  is the counterparty name on its own line; it does not start with a channel
  prefix, so only this symmetry tells it apart from the previous row's tail.
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
    extract_counterparty,
    extract_reference_number,
    parse_date_text,
)

_ACCOUNT_RE = re.compile(r"Savings\s+Account\s+([\dX]+)", re.IGNORECASE)
_PERIOD_RE = re.compile(
    r"period\s+([A-Z][a-z]+)\s+(\d{2}),\s+(\d{4})\s*-\s*([A-Z][a-z]+)\s+(\d{2}),\s+(\d{4})",
    re.IGNORECASE,
)
_NAME_RE = re.compile(r"ACCOUNT\s+HOLDERS?\s*:\s*(MR\.|MRS\.|MS\.)?(.+)", re.IGNORECASE)

# Lines that end the transaction table. A page usually closes with "Total:", but
# the FINAL page of a statement need not carry one — there the table simply runs
# into the post-statement sections. Without a marker for those, the last
# transaction's narration absorbs the entire page tail: nominee table, card-
# blocking instructions, the transaction-code legend. That garbage then feeds
# channel/counterparty detection, so a transfer was read as an ATM withdrawal
# because the legend it swallowed contains "Cash Withdrawal at other Bank's ATM".
_TABLE_END_MARKERS = (
    "TOTAL:",
    "ACCOUNT RELATED OTHER INFORMATION",
    "NAME OF NOMINEE",
    "LEGENDS FOR TRANSACTIONS",
    "THIS IS A SYSTEM GENERATED",
    "CARD BLOCKING PROCEDURE",
    "ACCOUNT BLOCKING PROCEDURE",
    "SINCERELY",
)

# Backstop for a tail we have not seen before. Real ICICI narrations run to a
# handful of continuation lines; a page footer runs to dozens. Marker lists only
# catch the footers we already know, so bound the walk structurally too — an
# unrecognised footer then costs a few stray words, not the whole page.
_MAX_CONTINUATION_LINES = 5

# The particulars lines of a row are symmetric about its date baseline. A line
# below the date belongs to the row when its distance from the date does not
# exceed the distance of the row's first line above the date. The line pitch
# is 8.47 points and offsets are multiples of half a pitch, so a margin under
# half a pitch separates the last line of a row from the first line of the
# next one.
_MIRROR_TOLERANCE = 3.0

# Header, section and footer lines between transactions. Anchor the keywords
# to the start of the line, or match the full phrase, so a narration cannot
# match by accident. A substring match read "UPI/.../MandateExe/AXIS" as a
# header because "MandateExe" contains "DATE", and a bare whole-word match
# would still drop a narration that holds the word "Total" or "Page".
_HEADER_LINE_RE = re.compile(
    r"^(?:DATE\b|(?:SUB |GRAND )?TOTAL\b|PAGE \d+ OF\b|STATEMENT OF TRANSACTIONS\b"
    r"|ACCOUNT (?:DETAILS|HOLDERS|TYPE)\b|REGISTERED OFFICE\b"
    r"|PLEASE CALL FROM YOUR REGISTERED\b)"
    r"|\bNOMINATION\b|\bREGISTERED$"
)

# The vertical distance between two particulars lines of one row.
_LINE_PITCH = 8.47

# The PARTICULARS column starts at x = 136 (monthly) or 140 (yearly). The MODE
# column ends before x = 130.
_PARTICULARS_MIN_X = 130.0

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
            # The Linked Fixed Deposits section ends the savings statement. No
            # later page has savings rows after this section starts. Stop here.
            if "Statement of Linked Fixed Deposits" in str(page.get("text", "")):
                break

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
        # (text, doctop) of the particulars lines seen since the last date
        # row. The doctop gives the row's extent above its date baseline.
        pending_narration_above: list[tuple[str, float]] = []
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

            # ICICI adds the "Statement of Linked Fixed Deposits" section after
            # the savings transactions. Its date rows are for a different (FD)
            # account. Do not read them as savings rows. The FD balance would
            # then replace the savings closing balance and break the
            # reconciliation. Stop at this header. Match the full header text.
            # Do not match the page summary "Fixed Deposits Linked to Account",
            # because that summary is on the same line group as the B/F opening
            # row.
            if "STATEMENT OF LINKED FIXED DEPOSITS" in upper:
                break

            if _HEADER_LINE_RE.search(upper):
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
                    pending_narration_above.append(
                        (narr_text, float(line_words[0]["doctop"]))
                    )
                i += 1
                continue

            # Date line found — extract amounts by x-position
            deposit_amt = None
            withdrawal_amt = None
            balance_amt = None
            # MODE column text ("MOBILE BANKING") and the particulars text on
            # the date line. Keep them apart: the particulars text is the
            # middle of a narration that wraps around the date line, and the
            # mode text must not split it.
            mode_tokens: list[str] = []
            inline_tokens: list[str] = []

            for w in line_words[1:]:  # skip the date token
                # An amount token IS an amount — it does not merely contain
                # one. Narration fragments like "SENDER/707070/UBI/01.02.2099…"
                # embed amount-shaped substrings ("01.02") but live in the
                # PARTICULARS column; `fullmatch` keeps them as narration.
                amt_match = AMOUNT_RE.fullmatch(w["text"])
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
                elif float(w["x0"]) < _PARTICULARS_MIN_X:
                    mode_tokens.append(w["text"])
                else:
                    inline_tokens.append(w["text"])

            # Check for B/F (Brought Forward) — opening balance
            if "B/F" in " ".join(mode_tokens + inline_tokens):
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
            date_line_y = float(line_words[0]["doctop"])
            narration_parts = list(mode_tokens)
            narration_parts.extend(text for text, _ in pending_narration_above)
            narration_parts.extend(inline_tokens)
            # The row extends as far below its date as it does above it. Only
            # the lines that sit at the line pitch above the date count: a
            # stray line further up is not part of the row and must not widen
            # the window below the date.
            above_span = 0.0
            previous_y = date_line_y
            for _, y in sorted(pending_narration_above, key=lambda item: -item[1]):
                if previous_y - y > _LINE_PITCH + _MIRROR_TOLERANCE:
                    break
                above_span = date_line_y - y
                previous_y = y
            pending_narration_above = []

            # Collect continuation lines below (non-date, non-header lines)
            i += 1
            continuation_lines = 0
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
                # End of the transactions section: everything below is metadata
                # and must not be absorbed into the last transaction's narration.
                if any(marker in next_upper for marker in _TABLE_END_MARKERS):
                    break
                # A narration this long is not a narration. Stop before an
                # unrecognised footer swallows the page.
                if continuation_lines >= _MAX_CONTINUATION_LINES:
                    break
                if _HEADER_LINE_RE.search(next_upper):
                    i += 1
                    continue
                # A line further below the date than the row's first line is
                # above it belongs to the next row. Leave it for the outer
                # loop, which collects it as that row's leading narration.
                narration_y = float(lines[i][0]["doctop"])
                if narration_y - date_line_y > above_span + _MIRROR_TOLERANCE:
                    break
                # The line continues the narration of the current row.
                narration_parts.append(next_joined.strip())
                continuation_lines += 1
                i += 1

            narration = " ".join(narration_parts).strip()
            channel = detect_channel(narration)
            ref = extract_reference_number(narration, channel)
            counterparty = extract_counterparty(narration, channel)

            txns.append(
                BankTransaction(
                    date=date,
                    narration=narration,
                    amount=amount,
                    transaction_type=direction,
                    balance=balance_amt,
                    reference_number=ref,
                    channel=channel,
                    counterparty=counterparty,
                )
            )

        return txns, opening_balance
