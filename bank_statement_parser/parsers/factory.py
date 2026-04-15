"""Parser selection utilities.

The bank name is always passed explicitly by the caller (the fetcher knows
the bank from the FetchRule). Auto-detection is deliberately not supported
because bank statement narrations routinely mention other banks (UPI via
HDFC, NEFT from ICICI, etc.) making heuristic detection unreliable.
"""

from bank_statement_parser.parsers.base import BankStatementParser
from bank_statement_parser.parsers.registry import create_parser


def get_parser(bank: str) -> BankStatementParser:
    """Return parser instance for the given bank.

    Args:
        bank: Bank slug. Must be explicit — no auto-detection.
    """
    return create_parser(bank)
