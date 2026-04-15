"""Parser registry and supported bank slug helpers."""

from __future__ import annotations

from bank_statement_parser.parsers.base import BankStatementParser
from bank_statement_parser.parsers.hdfc import HdfcBankStatementParser
from bank_statement_parser.parsers.icici import IciciBankStatementParser
from bank_statement_parser.parsers.idfc import IdfcBankStatementParser
from bank_statement_parser.parsers.indusind import IndusindBankStatementParser
from bank_statement_parser.parsers.kotak import KotakBankStatementParser
from bank_statement_parser.parsers.slice import SliceBankStatementParser
from bank_statement_parser.parsers.uboi import UboiBankStatementParser

PARSER_REGISTRY: dict[str, type[BankStatementParser]] = {
    "hdfc": HdfcBankStatementParser,
    "icici": IciciBankStatementParser,
    "idfc": IdfcBankStatementParser,
    "indusind": IndusindBankStatementParser,
    "kotak": KotakBankStatementParser,
    "slice": SliceBankStatementParser,
    "uboi": UboiBankStatementParser,
}


def get_supported_bank_slugs() -> tuple[str, ...]:
    """Return registered bank slugs in CLI/display order."""
    return tuple(PARSER_REGISTRY.keys())


def create_parser(bank: str) -> BankStatementParser:
    """Instantiate a parser from the registry."""
    try:
        parser_class = PARSER_REGISTRY[bank]
    except KeyError as error:
        raise ValueError(f"Unsupported bank: {bank}") from error
    return parser_class()


__all__ = [
    "PARSER_REGISTRY",
    "create_parser",
    "get_supported_bank_slugs",
]
