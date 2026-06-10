"""Pydantic models for bank account statement parser output."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class BankTransaction(BaseModel):
    """A single bank account transaction (debit or credit)."""

    date: str
    narration: str
    amount: str
    transaction_type: Literal["debit", "credit"]
    balance: str | None = None
    reference_number: str | None = None
    channel: str | None = None
    counterparty: str | None = None
    value_date: str | None = None
    transaction_id: str = ""


class BankReconciliation(BaseModel):
    """Balance verification metrics for a bank account statement.

    ``balance_delta`` is the primary correctness signal: ``"0.00"`` means the
    parsed transactions reconcile opening to closing balance. It is ``None``
    when reconciliation could not be performed because the opening and/or
    closing balance was not extracted from the statement — in that case a
    delta of ``"0.00"`` would be a false positive for a failed parse.

    ``reconciled`` is ``True`` only when both balances were present, at least
    one transaction was extracted, and the computed closing matches the
    stated closing (``balance_delta == "0.00"``). Consumers should check
    ``reconciled`` rather than comparing ``balance_delta`` to ``"0.00"``.
    """

    opening_balance: str
    closing_balance: str
    parsed_debit_total: str
    parsed_credit_total: str
    computed_closing_balance: str
    balance_delta: str | None
    transaction_count: int
    debit_count: int
    credit_count: int
    reconciled: bool = False


class ParsedBankStatement(BaseModel):
    """Root output of bank account statement parsers."""

    file: str
    bank: str
    account_holder_name: str | None = None
    account_number: str | None = None
    statement_period_start: str | None = None
    statement_period_end: str | None = None
    opening_balance: str | None = None
    closing_balance: str | None = None
    debit_count: int = 0
    credit_count: int = 0
    debit_total: str = "0.00"
    credit_total: str = "0.00"
    transactions: list[BankTransaction] = Field(default_factory=list)
    reconciliation: BankReconciliation | None = None


__all__ = [
    "BankReconciliation",
    "BankTransaction",
    "ParsedBankStatement",
]
