"""Word-line based extraction helpers."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from bank_statement_parser.models import BankTransaction
from bank_statement_parser.parsers.utils import (
    detect_channel,
    extract_amount,
    extract_reference_number,
    parse_amount,
    parse_date_text,
    parse_multi_token_date,
)


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


def parse_lines_transactions(
    pages: list[dict[str, Any]],
) -> list[BankTransaction]:
    """Extract transactions from word-line reconstruction."""
    txns: list[BankTransaction] = []
    prev_balance: Decimal | None = None

    for page in pages:
        words = page.get("words", [])
        if not words:
            continue

        for line_words in group_words_into_lines(words):
            tokens = [word["text"] for word in line_words]
            if not tokens:
                continue

            date = parse_date_text(tokens[0])
            consumed = 1
            if not date and len(tokens) >= 3:
                date, consumed = parse_multi_token_date(tokens, 0)
            if not date:
                continue

            rest = tokens[consumed:]
            if not rest:
                continue

            amounts: list[tuple[int, str]] = []
            for index, token in enumerate(rest):
                amount = extract_amount(token)
                if amount:
                    amounts.append((index, amount))

            if not amounts:
                continue

            first_amount_index = amounts[0][0]
            narration = " ".join(rest[:first_amount_index]).strip()

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
                amount = amounts[0][1]
                balance_str = amounts[1][1]
                this_balance = parse_amount(balance_str)
                if prev_balance is not None and this_balance < prev_balance:
                    direction = "debit"
                elif prev_balance is not None and this_balance > prev_balance:
                    direction = "credit"
                else:
                    direction = "debit"
            else:
                amount = amounts[0][1]
                balance_str = None
                direction = "debit"

            balance = balance_str if (len(amounts) >= 2 and balance_str) else None
            txns.append(
                BankTransaction(
                    date=date,
                    narration=narration,
                    amount=amount,
                    transaction_type=direction,
                    balance=balance,
                    reference_number=extract_reference_number(narration),
                    channel=detect_channel(narration),
                )
            )
            if balance:
                prev_balance = parse_amount(balance)

    return txns


__all__ = [
    "group_words_into_lines",
    "parse_lines_transactions",
]
