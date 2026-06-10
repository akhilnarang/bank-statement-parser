"""Reconciliation invariant tests.

These guard the primary correctness signal: ``balance_delta`` /
``reconciled``. All values here are fully synthetic.
"""

from typing import Literal

from bank_statement_parser.models import BankTransaction
from bank_statement_parser.parsers.reconciliation import build_reconciliation


def _txn(amount: str, kind: Literal["debit", "credit"]) -> BankTransaction:
    return BankTransaction(
        date="02/04/2026",
        narration="SYNTHETIC ENTRY",
        amount=amount,
        transaction_type=kind,
    )


def test_empty_parse_does_not_report_clean_reconciliation() -> None:
    """A parse that extracted no transactions and no balances must not
    look like a perfect 0.00 reconciliation."""
    recon = build_reconciliation([], None, None)
    assert recon is not None
    assert recon.balance_delta is None
    assert recon.reconciled is False
    assert recon.transaction_count == 0


def test_missing_closing_balance_is_unreconciled() -> None:
    recon = build_reconciliation([_txn("100.00", "debit")], "1,000.00", None)
    assert recon is not None
    assert recon.balance_delta is None
    assert recon.reconciled is False


def test_balanced_synthetic_set_reconciles() -> None:
    """A genuinely balanced set still reports 0.00 and reconciled=True."""
    txns = [_txn("1,000.00", "debit"), _txn("500.00", "credit")]
    recon = build_reconciliation(txns, "10,000.00", "9,500.00")
    assert recon is not None
    assert recon.balance_delta == "0.00"
    assert recon.reconciled is True
    assert recon.transaction_count == 2


def test_zero_transactions_with_balances_is_not_reconciled() -> None:
    """Opening == closing with zero transactions is suspicious; report the
    delta but do not call it reconciled."""
    recon = build_reconciliation([], "10,000.00", "10,000.00")
    assert recon is not None
    assert recon.balance_delta == "0.00"
    assert recon.reconciled is False


def test_unbalanced_set_reports_real_delta() -> None:
    txns = [_txn("1,000.00", "debit"), _txn("500.00", "credit")]
    recon = build_reconciliation(txns, "10,000.00", "9,999.00")
    assert recon is not None
    assert recon.balance_delta == "499.00"
    assert recon.reconciled is False
