"""Parser selection utilities.

The bank name is always passed explicitly by the caller (the fetcher knows
the bank from the FetchRule). Auto-detection is deliberately not supported
because bank statement narrations routinely mention other banks (UPI via
HDFC, NEFT from ICICI, etc.) making heuristic detection unreliable.
"""

from typing import Literal

from bank_statement_parser.parsers.base import BankStatementParser
from bank_statement_parser.parsers.hdfc import HdfcBankStatementParser
from bank_statement_parser.parsers.icici import IciciBankStatementParser
from bank_statement_parser.parsers.idfc import IdfcBankStatementParser
from bank_statement_parser.parsers.indusind import IndusindBankStatementParser
from bank_statement_parser.parsers.slice import SliceBankStatementParser
from bank_statement_parser.parsers.uboi import UboiBankStatementParser

type BankChoice = Literal[
    "hdfc",
    "icici",
    "idfc",
    "indusind",
    "slice",
    "uboi",
]


def get_parser(bank: BankChoice) -> BankStatementParser:
    """Return parser instance for the given bank.

    Args:
        bank: Bank slug. Must be explicit — no auto-detection.
    """
    match bank:
        case "hdfc":
            return HdfcBankStatementParser()
        case "icici":
            return IciciBankStatementParser()
        case "idfc":
            return IdfcBankStatementParser()
        case "slice":
            return SliceBankStatementParser()
        case "uboi":
            return UboiBankStatementParser()
        case "indusind":
            return IndusindBankStatementParser()
        case _:
            raise ValueError(f"Unsupported bank: {bank}")
