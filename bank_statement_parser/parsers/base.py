"""Parser interface for bank-specific account statement normalization."""

from abc import ABC, abstractmethod
from typing import Any

from bank_statement_parser.models import ParsedBankStatement


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

    def build_debug(self, raw_data: dict[str, Any]) -> dict[str, Any]:
        """Return lightweight debug details; subclasses may extend."""
        return {"bank": self.bank, "page_count": raw_data.get("page_count", 0)}
