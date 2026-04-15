"""Generic bank account statement parser."""

from __future__ import annotations

from typing import Any

from bank_statement_parser.models import BankTransaction, ParsedBankStatement
from bank_statement_parser.parsers.base import BankStatementParser
from bank_statement_parser.parsers.extractors.tables import (
    extract_transactions_from_tables,
)
from bank_statement_parser.parsers.extractors.wordlines import parse_lines_transactions
from bank_statement_parser.parsers.metadata import MetadataExtractor, extract_metadata
from bank_statement_parser.parsers.reconciliation import build_reconciliation


class GenericBankStatementParser(BankStatementParser):
    """Default bank account statement parser implementation."""

    bank = "generic"
    metadata_extractor = MetadataExtractor()

    def parse(self, raw_data: dict[str, Any]) -> ParsedBankStatement:
        """Normalize raw extractor payload into bank statement output."""
        pages = raw_data.get("pages", [])
        file_name = raw_data.get("file", "")
        full_text = "\n".join(
            str(page.get("text", "")) for page in pages if isinstance(page, dict)
        )

        meta = extract_metadata(full_text, self.metadata_extractor)
        transactions = self._post_process(self._extract_transactions(pages), raw_data)

        opening_balance = meta["opening_balance"]
        closing_balance = meta["closing_balance"]
        if not closing_balance and transactions:
            last_balance = transactions[-1].balance
            if last_balance:
                closing_balance = last_balance

        period_start = meta["period_start"]
        period_end = meta["period_end"]
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
            account_holder_name=meta["account_holder_name"],
            account_number=meta["account_number"],
            statement_period_start=period_start,
            statement_period_end=period_end,
            opening_balance=opening_balance,
            closing_balance=closing_balance,
            reconciliation=reconciliation,
        )

    def _extract_transactions(
        self,
        pages: list[dict[str, Any]],
    ) -> list[BankTransaction]:
        """Extract transactions trying tables first, then word-lines."""
        transactions = self._extract_from_tables(pages)
        if transactions:
            return transactions
        return parse_lines_transactions(pages)

    def _extract_from_tables(
        self,
        pages: list[dict[str, Any]],
    ) -> list[BankTransaction]:
        """Extract transactions from PDF tables across all pages."""
        return extract_transactions_from_tables(pages)


__all__ = ["GenericBankStatementParser"]
