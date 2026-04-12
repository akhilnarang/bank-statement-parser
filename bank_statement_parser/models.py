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
    value_date: str | None = None
    transaction_id: str = ""


class BankReconciliation(BaseModel):
    """Balance verification metrics for a bank account statement."""

    opening_balance: str
    closing_balance: str
    parsed_debit_total: str
    parsed_credit_total: str
    computed_closing_balance: str
    balance_delta: str
    transaction_count: int
    debit_count: int
    credit_count: int


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
