"""Generic bank account statement parser.

Provides the default parsing implementation used as the base class for
bank-specific profiles. Strategy:

1. Try table extraction first (many bank statements render as PDF tables).
2. Fall back to word-line reconstruction for positioned-text layouts.
3. Extract metadata (account number, holder name, period, balances).
4. Build reconciliation (balance verification).
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any

from bank_statement_parser.models import (
    BankReconciliation,
    BankTransaction,
    ParsedBankStatement,
)
from bank_statement_parser.parsers.base import BankStatementParser

# ---------------------------------------------------------------------------
# Regex constants
# ---------------------------------------------------------------------------

DATE_RE = re.compile(r"^\d{2}/\d{2}/\d{4}$")
DATE_SHORT_RE = re.compile(r"^\d{2}/\d{2}/\d{2}$")
DATE_DASH_RE = re.compile(r"^\d{2}-\d{2}-\d{4}$")
DATE_DASH_SHORT_RE = re.compile(r"^\d{2}-\d{2}-\d{2}$")
AMOUNT_RE = re.compile(r"[-+]?\d[\d,]*\.\d{2}")
MONTH_ABBREVS = {
    "JAN": "01",
    "FEB": "02",
    "MAR": "03",
    "APR": "04",
    "MAY": "05",
    "JUN": "06",
    "JUL": "07",
    "AUG": "08",
    "SEP": "09",
    "OCT": "10",
    "NOV": "11",
    "DEC": "12",
}

# Channel detection patterns (order matters — first match wins)
_CHANNEL_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("upi", re.compile(r"\bUPI\b", re.IGNORECASE)),
    ("neft", re.compile(r"\bNEFT\b", re.IGNORECASE)),
    ("rtgs", re.compile(r"\bRTGS\b", re.IGNORECASE)),
    ("imps", re.compile(r"\bIMPS\b", re.IGNORECASE)),
    ("atm", re.compile(r"\bATM\b", re.IGNORECASE)),
    ("atm", re.compile(r"\bCASH\s*W/?D", re.IGNORECASE)),
    ("cash_deposit", re.compile(r"\bCASH\s*DEP", re.IGNORECASE)),
    ("cheque", re.compile(r"\bCHQ\b|\bCHEQUE\b", re.IGNORECASE)),
    ("interest", re.compile(r"\bINT\.?\s*PAID\b|\bINTEREST\b", re.IGNORECASE)),
    # ACH-C: NACH credit (dividends, salary, refunds, payouts)
    ("ach_credit", re.compile(r"\bACH[\s-]*C\b", re.IGNORECASE)),
    # ACH-D: NACH debit (SIPs, EMIs, standing instructions for investments)
    ("ach_debit", re.compile(r"\bACH[\s-]*D\b", re.IGNORECASE)),
    (
        "standing_instruction",
        re.compile(r"\bSI/|\bSTANDING\s*INSTRUCTION\b", re.IGNORECASE),
    ),
    ("emandate", re.compile(r"\bE-?MANDATE\b|\bENACH\b|\bNACH\b", re.IGNORECASE)),
    ("netbanking", re.compile(r"\bNET[\s-]*BANKING\b", re.IGNORECASE)),
    ("card", re.compile(r"\bPOS\b|\bCARD\b", re.IGNORECASE)),
]

# Reference number patterns
_REF_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\b(\d{12,22})\b"),  # UPI ref / UTR — 12-22 digit number
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def parse_amount(s: str) -> Decimal:
    """Convert an amount string to Decimal (0 on failure)."""
    cleaned = s.replace(",", "").replace("`", "").strip()
    # Strip trailing Cr/Dr markers
    cleaned = re.sub(r"\s*(Cr|Dr|CR|DR|C|D)\.?\s*$", "", cleaned)
    try:
        return Decimal(cleaned)
    except InvalidOperation, ValueError:
        return Decimal("0")


def format_amount(value: Decimal) -> str:
    """Format Decimal as comma-separated 2-decimal string."""
    return f"{value:,.2f}"


def detect_channel(narration: str) -> str | None:
    """Detect transaction channel from narration text."""
    for channel, pattern in _CHANNEL_PATTERNS:
        if pattern.search(narration):
            return channel
    return None


def extract_reference_number(narration: str) -> str | None:
    """Extract a reference/UTR number from narration text."""
    for pattern in _REF_PATTERNS:
        m = pattern.search(narration)
        if m:
            return m.group(1)
    return None


def normalize_date(token: str) -> str | None:
    """Parse a date token in various formats into DD/MM/YYYY."""
    token = token.strip()
    if DATE_RE.fullmatch(token):
        return token
    if DATE_SHORT_RE.fullmatch(token):
        d, m, y = token.split("/")
        return f"{d}/{m}/20{y}"
    if DATE_DASH_RE.fullmatch(token):
        return token.replace("-", "/")
    if DATE_DASH_SHORT_RE.fullmatch(token):
        d, m, y = token.split("-")
        return f"{d}/{m}/20{y}"
    return None


def parse_multi_token_date(tokens: list[str], start: int) -> tuple[str | None, int]:
    """Parse a ``DD Mon YY`` or ``DD Mon YYYY`` date spread across tokens."""
    if start + 2 >= len(tokens):
        return None, 0
    day = tokens[start].strip()
    month_tok = tokens[start + 1].strip()
    year_tok = tokens[start + 2].strip()

    if not re.fullmatch(r"\d{1,2}", day):
        return None, 0
    month = MONTH_ABBREVS.get(month_tok.upper()[:3])
    if month is None:
        return None, 0
    if not re.fullmatch(r"\d{2,4}", year_tok):
        return None, 0

    day_padded = day.zfill(2)
    year = year_tok if len(year_tok) == 4 else f"20{year_tok}"
    return f"{day_padded}/{month}/{year}", 3


def _extract_amount(token: str) -> str | None:
    """Extract a decimal amount string from a token."""
    token = token.replace("`", "").strip()
    m = AMOUNT_RE.search(token)
    return m.group(0) if m else None


def group_words_into_lines(
    words: list[dict[str, Any]],
    y_tolerance: float = 1.8,
) -> list[list[dict[str, Any]]]:
    """Group extracted PDF words into visual lines by y-position."""
    sorted_words = sorted(
        words,
        key=lambda item: (float(item["doctop"]), float(item["x0"])),
    )
    lines: list[list[dict[str, Any]]] = []
    current_line: list[dict[str, Any]] = []
    current_y: float | None = None

    for word in sorted_words:
        y_value = float(word["doctop"])
        if current_y is None or abs(y_value - current_y) <= y_tolerance:
            current_line.append(word)
            current_y = y_value if current_y is None else (current_y + y_value) / 2
        else:
            lines.append(sorted(current_line, key=lambda item: float(item["x0"])))
            current_line = [word]
            current_y = y_value

    if current_line:
        lines.append(sorted(current_line, key=lambda item: float(item["x0"])))

    return lines


# ---------------------------------------------------------------------------
# Table-based extraction
# ---------------------------------------------------------------------------


def _find_header_row(table: list[list[str | None]]) -> int | None:
    """Find the header row index by looking for Date/Narration/Debit/Credit keywords."""
    for i, row in enumerate(table):
        if not row:
            continue
        text = " ".join(str(c or "") for c in row).upper()
        has_date = "DATE" in text
        has_amount = (
            "DEBIT" in text
            or "WITHDRAWAL" in text
            or "CREDIT" in text
            or "DEPOSIT" in text
        )
        if has_date and has_amount:
            return i
    return None


def _classify_columns(
    header_row: list[str | None],
) -> dict[str, int] | None:
    """Map column indices from a header row.

    Returns dict with keys: date, narration, debit, credit, balance, ref, value_date
    (each optional except date).
    """
    cols: dict[str, int] = {}
    for i, cell in enumerate(header_row):
        if cell is None:
            continue
        upper = cell.strip().upper()
        if not upper:
            continue
        if "DATE" in upper and "VALUE" in upper:
            cols["value_date"] = i
        elif "DATE" in upper and "date" not in cols:
            cols["date"] = i
        elif upper in (
            "NARRATION",
            "PARTICULARS",
            "DESCRIPTION",
            "DETAILS",
            "TRANSACTION DETAILS",
            "TRANSACTION PARTICULARS",
        ):
            cols["narration"] = i
        elif "MODE" in upper and "narration" not in cols:
            cols["narration"] = i
        elif "BALANCE" in upper:
            # Check BALANCE before DR/CR to avoid "BALANCE (CR)" being
            # misclassified as a credit column by the "CR" substring match
            cols["balance"] = i
        elif any(kw in upper for kw in ("WITHDRAWAL", "DEBIT")) or (
            "DR" in upper.split() and "BALANCE" not in upper
        ):
            cols["debit"] = i
        elif any(kw in upper for kw in ("DEPOSIT", "CREDIT")) or (
            "CR" in upper.split() and "BALANCE" not in upper
        ):
            cols["credit"] = i
        elif any(kw in upper for kw in ("REF", "CHQ", "CHEQUE")):
            cols["ref"] = i

    if "date" not in cols:
        return None
    return cols


def _parse_table_transactions(
    table: list[list[str | None]],
    header_idx: int,
    cols: dict[str, int],
) -> list[BankTransaction]:
    """Parse transaction rows from a classified table."""
    txns: list[BankTransaction] = []
    for row in table[header_idx + 1 :]:
        if not row or len(row) <= max(cols.values()):
            continue

        date_cell = str(row[cols["date"]] or "").strip()
        date = normalize_date(date_cell)
        if not date:
            continue

        narration = ""
        if "narration" in cols:
            narration = str(row[cols["narration"]] or "").strip()

        debit_str = (
            str(row[cols.get("debit", -1)] or "").strip() if "debit" in cols else ""
        )
        credit_str = (
            str(row[cols.get("credit", -1)] or "").strip() if "credit" in cols else ""
        )
        balance_str = (
            str(row[cols.get("balance", -1)] or "").strip() if "balance" in cols else ""
        )
        ref_str = str(row[cols.get("ref", -1)] or "").strip() if "ref" in cols else ""
        value_date_str = ""
        if "value_date" in cols:
            value_date_str = str(row[cols["value_date"]] or "").strip()

        debit_amt = _extract_amount(debit_str)
        credit_amt = _extract_amount(credit_str)

        if debit_amt:
            direction = "debit"
            amount = debit_amt
        elif credit_amt:
            direction = "credit"
            amount = credit_amt
        else:
            continue

        balance = _extract_amount(balance_str) if balance_str else None
        value_date = normalize_date(value_date_str) if value_date_str else None
        ref = ref_str if ref_str else extract_reference_number(narration)
        channel = detect_channel(narration)

        txns.append(
            BankTransaction(
                date=date,
                narration=narration,
                amount=amount,
                transaction_type=direction,
                balance=balance,
                reference_number=ref,
                channel=channel,
                value_date=value_date,
            )
        )

    return txns


# ---------------------------------------------------------------------------
# Word-line-based extraction (fallback)
# ---------------------------------------------------------------------------


def _parse_lines_transactions(
    pages: list[dict[str, Any]],
) -> list[BankTransaction]:
    """Extract transactions from word-line reconstruction.

    Expects columnar layout: Date ... Narration ... Debit ... Credit ... Balance
    Identifies columns by x-position clustering.
    """
    txns: list[BankTransaction] = []
    prev_balance: Decimal | None = None

    for page in pages:
        words = page.get("words", [])
        if not words:
            continue
        lines = group_words_into_lines(words)

        for line_words in lines:
            tokens = [w["text"] for w in line_words]
            if not tokens:
                continue

            # Try to find a date at the start
            date = normalize_date(tokens[0])
            consumed = 1
            if not date and len(tokens) >= 3:
                date, consumed = parse_multi_token_date(tokens, 0)
            if not date:
                continue

            # Remaining tokens after the date
            rest = tokens[consumed:]
            if not rest:
                continue

            # Find amounts from the right side
            amounts: list[tuple[int, str]] = []
            for i, tok in enumerate(rest):
                amt = _extract_amount(tok)
                if amt:
                    amounts.append((i, amt))

            if not amounts:
                continue

            # Narration is everything before the first amount
            first_amt_idx = amounts[0][0]
            narration = " ".join(rest[:first_amt_idx]).strip()

            # Determine debit/credit/balance from amount positions
            # Common patterns: 2 amounts = (debit_or_credit, balance)
            #                  3 amounts = (debit, credit, balance)
            if len(amounts) >= 3:
                debit_str = amounts[0][1]
                credit_str = amounts[1][1]
                balance_str = amounts[2][1]
                if parse_amount(debit_str) > 0 and parse_amount(credit_str) == 0:
                    direction = "debit"
                    amount = debit_str
                elif parse_amount(credit_str) > 0 and parse_amount(debit_str) == 0:
                    direction = "credit"
                    amount = credit_str
                elif parse_amount(debit_str) > 0:
                    direction = "debit"
                    amount = debit_str
                else:
                    direction = "credit"
                    amount = credit_str
            elif len(amounts) == 2:
                # (amount, balance) — infer direction from balance delta
                amount = amounts[0][1]
                balance_str = amounts[1][1]
                this_bal = parse_amount(balance_str)
                if prev_balance is not None and this_bal < prev_balance:
                    direction = "debit"
                elif prev_balance is not None and this_bal > prev_balance:
                    direction = "credit"
                else:
                    # First row or unchanged balance — cannot infer; default debit
                    direction = "debit"
            else:
                amount = amounts[0][1]
                balance_str = None
                direction = "debit"

            balance = balance_str if (len(amounts) >= 2 and balance_str) else None
            ref = extract_reference_number(narration)
            channel = detect_channel(narration)

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
            if balance:
                prev_balance = parse_amount(balance)

    return txns


# ---------------------------------------------------------------------------
# Metadata extraction
# ---------------------------------------------------------------------------

_ACCOUNT_NUMBER_RE = re.compile(
    r"(?:A/?C|ACCOUNT)\s*(?:NO\.?|NUMBER|#)\s*:?\s*(\d[\dX*\s]{6,20}\d)",
    re.IGNORECASE,
)
_PERIOD_RE = re.compile(
    r"(?:STATEMENT\s+(?:OF|FOR)\s+(?:THE\s+)?(?:PERIOD|MONTH)?\s*"
    r"(?:FROM|:)?\s*)?"
    r"(\d{2}[/\-]\d{2}[/\-]\d{2,4})\s*(?:TO|[-–])\s*(\d{2}[/\-]\d{2}[/\-]\d{2,4})",
    re.IGNORECASE,
)
_OPENING_BAL_RE = re.compile(
    r"OPENING\s+BALANCE\s*:?\s*([\d,]+\.\d{2})",
    re.IGNORECASE,
)
_CLOSING_BAL_RE = re.compile(
    r"CLOSING\s+BALANCE\s*:?\s*([\d,]+\.\d{2})",
    re.IGNORECASE,
)
_NAME_RE = re.compile(
    r"(?:ACCOUNT\s+HOLDER|CUSTOMER\s+NAME|NAME)\s*:?\s*(.+)",
    re.IGNORECASE,
)


def _extract_metadata(full_text: str) -> dict[str, str | None]:
    """Extract account metadata from statement text."""
    meta: dict[str, str | None] = {
        "account_number": None,
        "account_holder_name": None,
        "period_start": None,
        "period_end": None,
        "opening_balance": None,
        "closing_balance": None,
    }

    m = _ACCOUNT_NUMBER_RE.search(full_text)
    if m:
        meta["account_number"] = re.sub(r"\s+", "", m.group(1))

    m = _PERIOD_RE.search(full_text)
    if m:
        meta["period_start"] = normalize_date(m.group(1))
        meta["period_end"] = normalize_date(m.group(2))

    m = _OPENING_BAL_RE.search(full_text)
    if m:
        meta["opening_balance"] = m.group(1)

    m = _CLOSING_BAL_RE.search(full_text)
    if m:
        meta["closing_balance"] = m.group(1)

    m = _NAME_RE.search(full_text)
    if m:
        name = m.group(1).strip()
        # Stop at common delimiters
        name = re.split(r"\s{2,}|\t|\n", name)[0].strip()
        if name:
            meta["account_holder_name"] = name

    return meta


# ---------------------------------------------------------------------------
# Reconciliation
# ---------------------------------------------------------------------------


def _build_reconciliation(
    transactions: list[BankTransaction],
    opening_balance: str | None,
    closing_balance: str | None,
) -> BankReconciliation | None:
    """Build balance verification reconciliation."""
    opening = parse_amount(opening_balance or "0")
    closing = parse_amount(closing_balance or "0")

    debit_total = Decimal("0")
    credit_total = Decimal("0")
    debit_count = 0
    credit_count = 0

    for txn in transactions:
        amt = parse_amount(txn.amount)
        if txn.transaction_type == "debit":
            debit_total += amt
            debit_count += 1
        else:
            credit_total += amt
            credit_count += 1

    computed_closing = opening + credit_total - debit_total
    balance_delta = closing - computed_closing

    return BankReconciliation(
        opening_balance=format_amount(opening),
        closing_balance=format_amount(closing),
        parsed_debit_total=format_amount(debit_total),
        parsed_credit_total=format_amount(credit_total),
        computed_closing_balance=format_amount(computed_closing),
        balance_delta=format_amount(balance_delta),
        transaction_count=len(transactions),
        debit_count=debit_count,
        credit_count=credit_count,
    )


# ---------------------------------------------------------------------------
# Transaction ID generation
# ---------------------------------------------------------------------------


def _assign_transaction_ids(
    transactions: list[BankTransaction],
    bank: str,
) -> None:
    """Assign deterministic transaction IDs based on position."""
    for i, txn in enumerate(transactions):
        txn.transaction_id = f"{bank}_txn_{i:04d}"


# ---------------------------------------------------------------------------
# Main parser
# ---------------------------------------------------------------------------


class GenericBankStatementParser(BankStatementParser):
    """Default bank account statement parser implementation."""

    bank = "generic"

    def parse(self, raw_data: dict[str, Any]) -> ParsedBankStatement:
        """Normalize raw extractor payload into bank statement output."""
        pages = raw_data.get("pages", [])
        file_name = raw_data.get("file", "")

        # Build full text for metadata extraction
        full_text = "\n".join(
            str(page.get("text", "")) for page in pages if isinstance(page, dict)
        )

        meta = _extract_metadata(full_text)

        # Extract transactions — try tables first, fall back to word-lines
        transactions = self._extract_transactions(pages)

        _assign_transaction_ids(transactions, self.bank)

        # Compute totals
        debit_total = Decimal("0")
        credit_total = Decimal("0")
        debit_count = 0
        credit_count = 0
        for txn in transactions:
            amt = parse_amount(txn.amount)
            if txn.transaction_type == "debit":
                debit_total += amt
                debit_count += 1
            else:
                credit_total += amt
                credit_count += 1

        # If we didn't find opening/closing from text, try from transactions
        opening_balance = meta["opening_balance"]
        closing_balance = meta["closing_balance"]
        if not closing_balance and transactions:
            last_bal = transactions[-1].balance
            if last_bal:
                closing_balance = last_bal

        # Infer period from transactions if not found in header
        period_start = meta["period_start"]
        period_end = meta["period_end"]
        if not period_start and transactions:
            period_start = transactions[0].date
        if not period_end and transactions:
            period_end = transactions[-1].date

        reconciliation = _build_reconciliation(
            transactions,
            opening_balance,
            closing_balance,
        )

        return ParsedBankStatement(
            file=file_name,
            bank=self.bank,
            account_holder_name=meta["account_holder_name"],
            account_number=meta["account_number"],
            statement_period_start=period_start,
            statement_period_end=period_end,
            opening_balance=opening_balance,
            closing_balance=closing_balance,
            debit_count=debit_count,
            credit_count=credit_count,
            debit_total=format_amount(debit_total),
            credit_total=format_amount(credit_total),
            transactions=transactions,
            reconciliation=reconciliation,
        )

    def _extract_transactions(
        self,
        pages: list[dict[str, Any]],
    ) -> list[BankTransaction]:
        """Extract transactions trying tables first, then word-lines."""
        # Try table extraction across all pages
        txns = self._extract_from_tables(pages)
        if txns:
            return txns

        # Fall back to word-line reconstruction
        return _parse_lines_transactions(pages)

    def _extract_from_tables(
        self,
        pages: list[dict[str, Any]],
    ) -> list[BankTransaction]:
        """Extract transactions from PDF tables across all pages."""
        all_txns: list[BankTransaction] = []
        cols: dict[str, int] | None = None

        for page in pages:
            tables = page.get("tables", [])
            for table in tables:
                if not table:
                    continue

                header_idx = _find_header_row(table)
                if header_idx is not None:
                    new_cols = _classify_columns(table[header_idx])
                    if new_cols is None:
                        continue
                    cols = new_cols
                    txns = _parse_table_transactions(table, header_idx, cols)
                elif cols is not None:
                    # Continuation table — reuse last seen column mapping
                    txns = _parse_table_transactions(table, -1, cols)
                else:
                    continue
                all_txns.extend(txns)

        return all_txns
