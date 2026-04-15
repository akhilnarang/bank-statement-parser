"""Parser interface for bank-specific account statement normalization."""

from abc import ABC, abstractmethod
from typing import Any

from bank_statement_parser.models import (
    BankReconciliation,
    BankTransaction,
    ParsedBankStatement,
)
from bank_statement_parser.parsers.reconciliation import (
    assign_transaction_ids,
    summarize_transactions,
)
from bank_statement_parser.parsers.utils import format_amount


class BankStatementParser(ABC):
    """Base contract for all bank account statement parser implementations."""

    bank: str = "generic"

    @abstractmethod
    def parse(self, raw_data: dict[str, Any]) -> ParsedBankStatement:
        """Convert raw extractor payload into normalized bank statement output.

        Args:
            raw_data: Raw extraction payload from extractor module.

        Returns:
            Normalized parser output as a ParsedBankStatement model.
        """
        raise NotImplementedError

    def _post_process(
        self,
        transactions: list[BankTransaction],
        raw_data: dict[str, Any],
    ) -> list[BankTransaction]:
        """Apply safe shared post-processing without altering parse semantics."""
        del raw_data
        assign_transaction_ids(transactions, self.bank)
        return transactions

    def _build_statement(
        self,
        *,
        file_name: str,
        transactions: list[BankTransaction],
        account_holder_name: str | None,
        account_number: str | None,
        statement_period_start: str | None,
        statement_period_end: str | None,
        opening_balance: str | None,
        closing_balance: str | None,
        reconciliation: BankReconciliation | None,
    ) -> ParsedBankStatement:
        """Build the output model with shared totals/counts formatting."""
        debit_total, credit_total, debit_count, credit_count = summarize_transactions(
            transactions
        )
        return ParsedBankStatement(
            file=file_name,
            bank=self.bank,
            account_holder_name=account_holder_name,
            account_number=account_number,
            statement_period_start=statement_period_start,
            statement_period_end=statement_period_end,
            opening_balance=opening_balance,
            closing_balance=closing_balance,
            debit_count=debit_count,
            credit_count=credit_count,
            debit_total=format_amount(debit_total),
            credit_total=format_amount(credit_total),
            transactions=transactions,
            reconciliation=reconciliation,
        )

    def build_debug(self, raw_data: dict[str, Any]) -> dict[str, Any]:
        """Return lightweight debug details; subclasses may extend."""
        return {"bank": self.bank, "page_count": raw_data.get("page_count", 0)}
