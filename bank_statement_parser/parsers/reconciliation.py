"""Shared reconciliation and transaction summarization helpers."""

from __future__ import annotations

from decimal import Decimal

from bank_statement_parser.models import BankReconciliation, BankTransaction
from bank_statement_parser.parsers.utils import format_amount, parse_amount


def assign_transaction_ids(
    transactions: list[BankTransaction],
    bank: str,
) -> None:
    """Assign deterministic transaction IDs based on position."""
    for index, transaction in enumerate(transactions):
        transaction.transaction_id = f"{bank}_txn_{index:04d}"


def summarize_transactions(
    transactions: list[BankTransaction],
) -> tuple[Decimal, Decimal, int, int]:
    """Return debit total, credit total, debit count, credit count."""
    debit_total = Decimal(0)
    credit_total = Decimal(0)
    debit_count = 0
    credit_count = 0

    for transaction in transactions:
        amount = parse_amount(transaction.amount)
        if transaction.transaction_type == "debit":
            debit_total += amount
            debit_count += 1
        else:
            credit_total += amount
            credit_count += 1

    return debit_total, credit_total, debit_count, credit_count


def build_reconciliation(
    transactions: list[BankTransaction],
    opening_balance: str | None,
    closing_balance: str | None,
) -> BankReconciliation | None:
    """Build balance verification reconciliation.

    When opening and/or closing balance is missing (None/empty), the balance
    delta cannot be computed meaningfully: defaulting the missing balance to
    zero would yield a spurious ``balance_delta == "0.00"`` for a statement
    where nothing was extracted. In that case ``balance_delta`` is set to
    ``None`` and ``reconciled`` is ``False``, so a consumer can tell a genuine
    reconciliation apart from a failed/empty parse.

    A statement is only considered ``reconciled`` when both balances are
    present, at least one transaction was extracted, and the stated closing
    matches the computed closing (delta of exactly ``"0.00"``).
    """
    has_balances = bool(opening_balance) and bool(closing_balance)
    opening = parse_amount(opening_balance or "0")
    closing = parse_amount(closing_balance or "0")
    debit_total, credit_total, debit_count, credit_count = summarize_transactions(
        transactions
    )
    computed_closing = opening + credit_total - debit_total

    transaction_count = len(transactions)
    if has_balances:
        balance_delta = format_amount(closing - computed_closing)
        reconciled = balance_delta == "0.00" and transaction_count > 0
    else:
        balance_delta = None
        reconciled = False

    return BankReconciliation(
        opening_balance=format_amount(opening),
        closing_balance=format_amount(closing),
        parsed_debit_total=format_amount(debit_total),
        parsed_credit_total=format_amount(credit_total),
        computed_closing_balance=format_amount(computed_closing),
        balance_delta=balance_delta,
        transaction_count=transaction_count,
        debit_count=debit_count,
        credit_count=credit_count,
        reconciled=reconciled,
    )


__all__ = [
    "assign_transaction_ids",
    "build_reconciliation",
    "summarize_transactions",
]
