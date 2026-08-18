"""Table-parsing tests for the SBI bank-statement parser.

All data here is synthetic (JANE/JOHN DOE, example VPAs, fake refs) — this
repo is public, so no real statement values.
"""

from __future__ import annotations

from bank_statement_parser.parsers.sbi import SbiBankStatementParser

_HEADER = [
    "Date",
    "Transaction Reference",
    None,
    None,
    "Ref.No./Chq.No.",
    "Credit",
    "Debit",
    "Balance",
]


def _parse(table):
    return SbiBankStatementParser()._parse_sbi_table(table)


def test_sbi_table_extracts_txns_balances_and_period():
    table = [
        _HEADER,
        # Opening summary row with a garbled label (no literal "Opening"),
        # matched on the "on DD-MM-YY:" fragment; balance sits in its own cell.
        [
            "Yourn Oupllening",
            "nBualllance on 01-07-26:",
            None,
            "0.00",
            None,
            None,
            None,
            None,
        ],
        [
            "28-07-26",
            "UPI/CR/900000000001/JANE DOE/EXBK/jane@examplebank/Payme",
            None,
            None,
            "-",
            "10000.00",
            "0",
            "10000.00",
        ],
        [
            "31-07-26",
            "UPI/DR/900000000002/JOHN DOE/EXBK/john@examplebank/Paid",
            None,
            None,
            "-",
            "0",
            "5000.00",
            "5000.00",
        ],
        [
            "Your Closing Balance on 31-07-26:",
            None,
            "5000.00",
            None,
            None,
            None,
            None,
            None,
        ],
    ]
    result = _parse(table)
    txns = result["transactions"]

    assert len(txns) == 2
    # 2-digit year is forced to 20YY, not the %y 1900s pivot.
    assert txns[0].date == "28/07/2026"
    assert txns[0].transaction_type == "credit"
    assert txns[0].amount == "10000.00"
    assert txns[0].counterparty == "JANE DOE"
    assert txns[1].transaction_type == "debit"
    assert txns[1].amount == "5000.00"
    assert txns[1].counterparty == "JOHN DOE"
    assert result["opening_balance"] == "0.00"
    assert result["closing_balance"] == "5000.00"
    assert result["period_start"] == "01/07/2026"
    assert result["period_end"] == "31/07/2026"


def test_sbi_table_short_dated_row_does_not_crash():
    # A dated row shorter than the credit/debit columns must not IndexError.
    table = [_HEADER, ["28-07-26", "UPI/CR/900000000001/JANE DOE/EXBK/x/P"]]
    assert _parse(table)["transactions"] == []


def test_sbi_table_without_header_is_ignored():
    assert _parse([["Account", "Summary"], ["foo", "bar"]])["transactions"] == []
